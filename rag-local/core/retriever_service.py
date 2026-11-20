from typing import List, Optional
from langchain_core.documents import Document
import logging
import math
import re
import time
import jieba
from pymilvus import Collection
from config.config import APP_CONFIG
# 确保导入路径正确
from core.vector_db_service import VectorDB
from core.embedding_service import RerankModel
logger = logging.getLogger(__name__)

_COLLECTION_DOC_CACHE = {}
_BM25_INDEX_CACHE = {}


def _bm25_tokens(text: str) -> List[str]:
    """ 使用jieba分词 """
    tokens: List[str] = []
    for token in jieba.lcut((text or "").lower()):
        token = token.strip()
        if not token or re.fullmatch(r"[\W_]+", token):
            continue
        tokens.append(token)
    return tokens


class SimpleBM25Index:
    def __init__(self, documents: List[Document], k1: float = 1.5, b: float = 0.75):
        self.documents = documents
        self.k1 = k1
        self.b = b
        self.doc_tokens = [_bm25_tokens(document.page_content) for document in documents]
        self.doc_lens = [len(tokens) for tokens in self.doc_tokens]
        self.avgdl = (sum(self.doc_lens) / len(self.doc_lens)) if self.doc_lens else 0.0
        self.doc_freq = {}
        for tokens in self.doc_tokens:
            for token in set(tokens):
                self.doc_freq[token] = self.doc_freq.get(token, 0) + 1

    def _idf(self, token: str) -> float:
        n_docs = len(self.documents)
        df = self.doc_freq.get(token, 0)
        return math.log(1 + (n_docs - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int) -> List[Document]:
        """
        BM25初检，返回检索、打分后的排序
        """
        # 对 query 进行 jieba 分词和去重
        query_tokens = _bm25_tokens(query)
        if not query_tokens or not self.documents:
            return []
        query_terms = set(query_tokens)
        scored = []
        # 计算匹配词频
        for document, tokens, doc_len in zip(self.documents, self.doc_tokens, self.doc_lens):
            term_freq = {}
            for token in tokens:
                if token in query_terms:
                    term_freq[token] = term_freq.get(token, 0) + 1
            score = 0.0
            for token in query_terms:
                freq = term_freq.get(token, 0)
                if freq <= 0:
                    continue
                # 使用 BM25 核心公式计算得分
                denom = freq + self.k1 * (1 - self.b + self.b * doc_len / (self.avgdl or 1.0))
                score += self._idf(token) * (freq * (self.k1 + 1)) / denom
            # 过滤、排序与 Top-K 截断
            if score > 0:
                scored.append((score, document))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [document for _, document in scored[:k]]


def _dedupe_documents(documents: List[Document]) -> List[Document]:
    deduped = []
    seen = set()
    for document in documents:
        metadata = document.metadata or {}
        key = (
            metadata.get("source", ""),
            metadata.get("page", ""),
            metadata.get("chunk_index", ""),
            metadata.get("pk") or metadata.get("id") or metadata.get("chunk_id"),
            document.page_content,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(document)
    return deduped


def _non_vector_field_names(collection: Collection) -> List[str]:
    return [field.name for field in collection.schema.fields if "VECTOR" not in str(field.dtype).upper()]


def _guess_text_field(collection: Collection) -> str:
    field_names = [field.name for field in collection.schema.fields]
    for candidate in ("text", "page_content", "content"):
        if candidate in field_names:
            return candidate
    for field in collection.schema.fields:
        if "VARCHAR" in str(field.dtype).upper():
            return field.name
    raise RuntimeError(f"Could not find text field in collection schema: {field_names}")

class KnowledgeBaseRetriever:
    def __init__(
        self,
        collection_name: str,
        k: int = 20, # 从向量数据库初步检索的文档数量
        rerank_top_n: int = 3, # 经过重排后返回的最终文档数量
        hybrid_alpha: float = 0.7 # 混合搜索权重 (0-1)
    ):
        """
        初始化知识库检索器。

        Args:
            collection_name (str): Milvus 集合名称。
            k (int): 从向量数据库初步检索的文档数量。
            rerank_top_n (int): 经过重排后返回的最终文档数量。
            hybrid_alpha (float): 混合搜索权重 (0-1)，1 表示完全使用密集向量，0 表示完全使用稀疏向量。
        """
        self.config = APP_CONFIG
        self.collection_name = collection_name
        self.k = k
        self.rerank_top_n = rerank_top_n
        self.hybrid_alpha = hybrid_alpha
        
        # 初始化向量数据库实例
        self.vector_db = VectorDB()
        
        # 初始化重排模型实例
        self.reranker = RerankModel()
        
        # 缓存重排结果 (当前未使用，但保留以备未来扩展)
        self._rerank_cache = {}

    def _load_collection_documents(self) -> List[Document]:
        if self.collection_name in _COLLECTION_DOC_CACHE:
            return _COLLECTION_DOC_CACHE[self.collection_name]

        collection = Collection(self.collection_name)
        collection.load()
        text_field = _guess_text_field(collection)
        rows = collection.query(
            expr=f'{text_field} != ""',
            output_fields=_non_vector_field_names(collection),
            limit=16384,
        )

        documents: List[Document] = []
        for row in rows:
            content = str(row.get(text_field) or "")
            if not content.strip():
                continue
            metadata = {key: value for key, value in row.items() if key != text_field}
            documents.append(Document(page_content=content, metadata=metadata))

        _COLLECTION_DOC_CACHE[self.collection_name] = documents
        logger.info(
            "Loaded %s docs for BM25 collection=%s",
            len(documents),
            self.collection_name,
        )
        return documents

    def _bm25_search(self, query: str, k: int) -> List[Document]:
        try:
            if self.collection_name not in _BM25_INDEX_CACHE:
                _BM25_INDEX_CACHE[self.collection_name] = SimpleBM25Index(
                    self._load_collection_documents()
                )
                logger.info("Built BM25 index for collection=%s", self.collection_name)
            return _BM25_INDEX_CACHE[self.collection_name].search(query, k)
        except Exception as e:
            logger.warning("BM25 search failed, fallback to dense only: %s", e, exc_info=True)
            return []

    async def _rerank_documents(
        self,
        query: str,
        documents: List[Document]
    ) -> List[tuple[float, Document]]:
        """
        对文档列表进行重排。
        调用 RerankModel 对初步检索到的文档进行相关性排序。
        
        Args:
            query (str): 查询文本。
            documents (List[Document]): 待重排的文档列表。
            
        Returns:
            List[tuple[float, Document]]: 包含 (分数, 文档) 元组的列表，按分数降序排列。
        """
        try:
            # 使用专门的 reranker 进行重排
            reranked_docs = await self.reranker.rerank(query, documents)
            
            return reranked_docs
        except Exception as e:
            logger.error(f"文档重排失败: {e}。返回原始文档列表。")
            # 如果重排失败，返回原始文档，分数设为 0.0
            return [(0.0, doc) for doc in documents]

    async def retrieve(
        self,
        query: str,
        timings: Optional[dict] = None,
    ) -> List[Document]:
        """
        根据查询检索相关文档，并进行重排。
        这是检索器的核心方法，执行以下步骤：
        1. 从向量数据库执行混合搜索，获取初步文档。
        2. 对初步文档进行重排，以提高相关性。
        3. 返回重排后的前 N 个文档。

        Args:
            query (str): 用户查询。
            timings (Optional[dict]): 若传入，则把各阶段耗时（秒）写入该字典，
                键为 'retrieve_s' / 'rerank_s'。不传则行为完全不变（仅用于基线埋点）。

        Returns:
            List[Document]: 经过重排后的相关文档列表。

        Raises:
            Exception: 如果检索过程发生错误。
        """
        logger.info(f"开始检索文档，查询: '{query}'。")

        try:
            # 基线埋点：计时起点（timings 传入时才有意义）
            if timings is not None:
                _t0 = time.perf_counter()
            # 1. 执行混合搜索，从 Milvus 获取初步相关文档
            # 假设 self.vector_db.hybrid_search 已经是异步方法
            dense_docs = await self.vector_db.hybrid_search(
                query=query,
                collection_name=self.collection_name,
                k=self.k, # 初步检索数量
                alpha=self.hybrid_alpha, # 混合搜索权重
            )
            bm25_docs = self._bm25_search(query, self.k)
            initial_docs = _dedupe_documents([*dense_docs, *bm25_docs])
            if timings is not None:
                timings["retrieve_s"] = time.perf_counter() - _t0

            if not initial_docs:
                logger.warning("未检索到任何文档。")
                if timings is not None:
                    timings.setdefault("rerank_s", 0.0)
                return []

            logger.info(
                "Initial retrieval merged dense=%s bm25=%s merged=%s",
                len(dense_docs),
                len(bm25_docs),
                len(initial_docs),
            )

            # 2. 对初步检索到的文档进行重排
            all_scores = await self._rerank_documents(query, initial_docs)
            
            # 3. 根据重排分数降序排序，并取前 rerank_top_n 个文档
            all_scores.sort(key=lambda x: x[0], reverse=True) # 按分数降序排序
            
            # 提取最终的文档列表
            final_docs = [doc for score, doc in all_scores[:self.rerank_top_n]]
            
            logger.info(f"重排完成，返回 {len(final_docs)} 个文档。")
            return final_docs
            
        except Exception as e:
            logger.error(f"检索过程发生错误: {e}", exc_info=True)
            raise

# 模块测试部分
# 模块测试部分
if __name__ == "__main__":
    import asyncio  # 新增：导入异步库

    logging.basicConfig(level=logging.INFO)
    logger.info("--- 开始测试知识库检索器 ---")


    # 定义异步测试主函数
    async def main_test():
        # 实例化检索器
        test_collection_name = "test_collection_retriever_opt"
        retriever = KnowledgeBaseRetriever(
            collection_name=test_collection_name,
            k=5,
            rerank_top_n=2,
            hybrid_alpha=0.7
        )

        # 初始化 VectorDB
        temp_vector_db = VectorDB()

        # 模拟插入文档（异步调用，加 await）
        test_docs_for_retriever = [
            Document(page_content="Milvus是一个开源的向量数据库，专为AI应用设计。", metadata={"source": "doc_milvus.md"}),
            Document(page_content="RAG（Retrieval-Augmented Generation）结合了检索和生成模型，提高了LLM的准确性。",
                     metadata={"source": "doc_rag.md"}),
            Document(page_content="Langchain是一个用于开发LLM应用的框架，提供了许多工具和组件。",
                     metadata={"source": "doc_langchain.md"}),
            Document(page_content="向量数据库在处理非结构化数据方面表现出色，例如文本、图像和音频。",
                     metadata={"source": "doc_vector.md"}),
            Document(page_content="重排模型可以提高检索结果的相关性，通过重新排序初始检索到的文档。",
                     metadata={"source": "doc_rerank.md"}),
            Document(page_content="Python是一种广泛使用的高级编程语言，以其简洁和可读性而闻名。",
                     metadata={"source": "doc_python.md"}),
            Document(page_content="人工智能（AI）是计算机科学的一个分支，旨在创建智能机器。",
                     metadata={"source": "doc_ai.md"}),
        ]
        logger.info(f"为测试检索器，正在向集合 '{test_collection_name}' 插入模拟文档...")
        try:
            await temp_vector_db.insert_documents(test_docs_for_retriever, test_collection_name)  # 加 await
            logger.info("模拟文档插入成功。")
        except Exception as e:
            logger.error(f"模拟文档插入失败，无法进行检索器测试: {e}")
            return

        # 执行异步查询（加 await）
        test_query = "Langchain是做什么的？"
        logger.info(f"执行查询: '{test_query}'")
        try:
            retrieved_documents = await retriever.retrieve(test_query)  # 加 await

            if retrieved_documents:
                logger.info(f"\n查询 '{test_query}' 的最终检索结果:")
                for i, doc in enumerate(retrieved_documents):
                    logger.info(f"  文档 {i + 1}:")
                    logger.info(f"    内容: {doc.page_content[:200]}...")
                    logger.info(f"    元数据: {doc.metadata}")
                    logger.info("-" * 20)
            else:
                logger.info(f"未找到与查询 '{test_query}' 相关的文档。")

        except Exception as e:
            logger.error(f"检索器测试失败: {e}", exc_info=True)
        finally:
            # 清理测试集合（异步调用，加 await）
            logger.info(f"测试结束：清理集合 '{test_collection_name}'...")
            try:
                await temp_vector_db.delete_collection(test_collection_name)  # 加 await
                logger.info(f"集合 '{test_collection_name}' 已成功清理。")
            except Exception as e:
                logger.error(f"最终清理集合 '{test_collection_name}' 失败: {e}")

    # 运行异步测试函数
    asyncio.run(main_test())
