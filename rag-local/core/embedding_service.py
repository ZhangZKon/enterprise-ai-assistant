from langchain_openai import OpenAIEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document
import logging
import httpx
import os
import re
import numpy as np
import sys
from sklearn.metrics.pairwise import cosine_similarity
from config.config import APP_CONFIG
from typing import Optional, List, Tuple  # 确保这行存在且正确

logger = logging.getLogger(__name__)
# 先添加项目根路径，确保导入正常
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)



class EmbeddingModel:
    def __init__(self):
        self.config = APP_CONFIG.embedding
        # 强制检查 API Key
        if not self.config.api_key or self.config.api_key == "":
            raise ValueError("请在 .env 中配置有效的 ZHIPU_API_KEY！")
        self._model: Optional[Embeddings] = None # 存储 Embedding 模型实例

    def get_embedding_model(self) -> Embeddings:
        """
        获取配置好的 Embedding 模型实例。
        使用单例模式避免重复初始化，确保每次调用都返回同一个模型实例。

        Returns:
            Embeddings: 配置好的 Embedding 模型实例。

        Raises:
            Exception: 如果 Embedding 模型初始化失败。
        """
        if self._model is None:
            try:
                logger.info(f"正在初始化 Embedding 模型: {self.config.model_id} (Base URL: {self.config.base_url})")
                if not self.config.api_key:
                    logger.error("EMBEDDING_API_KEY 环境变量未设置。Embedding 模型功能将不可用。")
                    raise ValueError("EMBEDDING_API_KEY must be set in environment variables.")
                # 初始化 OpenAI 兼容的 Embedding 模型（支持智谱/OpenAI/千帆等）
                self._model = OpenAIEmbeddings(
                    base_url=self.config.base_url,
                    model=self.config.model_id,
                    api_key=self.config.api_key,
                    chunk_size=16 # 强制 LangChain 每批只发 16 条
                    # client_kwargs={"timeout": 30.0}# 增加超时配置，避免卡住
                    # model_kwargs={"timeout": 30.0} #新版 langchain-openai 用 model_kwargs 替代 client_kwargs

                )
                logger.info("Embedding 模型初始化成功。")
            except Exception as e:
                logger.error(f"Embedding 模型初始化失败: {e}", exc_info=True)
                raise
        return self._model

class RerankModel:
    """
    Rerank 模型管理器，用于获取重排模型实例。
    直接使用 OpenAI API 进行重排。
    """
    def __init__(self):
        """
        初始化 Rerank 模型管理器。
        从 APP_CONFIG 中加载重排模型配置。
        """
        self.config = APP_CONFIG.rerank
        self.embedding_model = EmbeddingModel().get_embedding_model()
        # 读取重排模式（local/remote）
        self.rerank_mode = getattr(self.config, "mode", "local").lower()

        # 在线模式校验
        self.remote_enabled = False
        if self.rerank_mode == "remote":
            if all([self.config.api_key, self.config.base_url, self.config.model_id]):
                if self.config.base_url.startswith(("http://", "https://")):
                    # 移除 base_url 末尾的 /，避免拼接后路径重复
                    self.config.base_url = self.config.base_url.rstrip('/')
                    self.remote_enabled = True
                    logger.info(f"Rerank 模式：在线调用（地址: {self.config.base_url}）")
                else:
                    logger.error("Rerank 地址格式错误（需带http/https），自动降级为本地重排")
            else:
                logger.error("Rerank 配置不完整，自动降级为本地重排")
        else:
            logger.info("Rerank 模式：本地余弦相似度重排（无网络请求）")

    async def _remote_rerank(self, query: str, documents: List[Document]) -> List[tuple[float, Document]]:
        """
        使用 BGE Reranker API 对文档进行重排。
        通过 HTTP 请求调用外部重排服务。

        Args:
            query (str): 查询文本。
            documents (List[Document]): 待重排的文档列表。

        Returns:
            List[tuple[float, Document]]: 包含 (分数, 文档) 元组的重排后的文档列表，按分数降序排列。

        Raises:
            httpx.HTTPStatusError: 如果重排请求返回非 2xx 状态码。
            httpx.RequestError: 如果重排请求发生网络错误。
            ValueError: 如果 API 密钥未设置。
        """
        if not self.config.api_key:
            logger.error("Rerank API 密钥未设置。无法执行重排。")
            raise ValueError("Rerank API 密钥未设置。")
        # 第一步 ：严格过滤空文档
        valid_documents = []
        valid_doc_contents = []
        for doc in documents:
            # 过滤空内容、仅空格文档
            content = doc.page_content.strip()
            if content:
                valid_documents.append(doc)
                valid_doc_contents.append(content)

        if not valid_documents:
            logger.warning("无有效文档可供重排序。")
            return []
        
        api_url = f"{self.config.base_url}/rerank"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }
        
        documents_data = [doc.page_content for doc in documents]
        # 校验文本长度，避免超长导致400
        documents_data = [text[:5000] if len(text) > 5000 else text for text in documents_data]

        payload = {
            "model": self.config.model_id,
            "query": query.strip(),   ## 去除首尾空格，避免空查询
            "documents":documents_data,
            "texts": documents_data,   ## 核心修正：智谱用 texts 而非 documents
            "top_n": min(len(documents),20)   # 智谱限制 top_n 最大20
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:  # 缩短超时时间
                response = await client.post(api_url, headers=headers, json=payload, timeout=30.0) # 增加超时设置
                logger.info(f"Rerank 响应状态码: {response.status_code}, 响应内容: {response.text}")
                response.raise_for_status()
            
            result = response.json()
            # 解析重排结果
            # 3. 修正解析逻辑：智谱返回的是 data 字段，而非 results   （兼容智谱两种返回格式）
            reranked_results = result.get("results",result.get("data",[]))
            if not reranked_results:
                logger.warning("在线Rerank 返回空结果，降级到本地")
                return self._local_rerank(query, documents)

            scored_documents = []
            for item in reranked_results:
                original_index = item.get("index")
                score = item.get("score", item.get("relevance_score",0.0))  #  智谱用 score 而非 relevance_score
                if original_index is not None and 0 <= original_index < len(documents):
                    scored_documents.append((score, documents[original_index]))
            #按分数降序排列
            scored_documents.sort(key=lambda x: x[0], reverse=True)
            return scored_documents[:self.config.top_n]  # 截取top n

            # 兜底：如果重排结果为空，返回原文档
        except Exception as e:
            logger.error(f"在线 Rerank 失败: {e}", exc_info=True)
            return []  # 失败返回空，触发降级

    def _local_rerank(self, query: str, documents: List[Document]) -> List[Tuple[float, Document]]:
        """本地余弦相似度重排，引入词面匹配的混合打分逻辑，增强对精确问题的识别"""
        if not documents or not query.strip():
            return [(1.0, doc) for doc in documents[:self.config.top_n]]

        # 生成向量
        query_emb = self.embedding_model.embed_query(query)
        doc_embs = self.embedding_model.embed_documents([d.page_content for d in documents])

        # 计算相似度
        query_emb = np.array(query_emb).reshape(1, -1)
        doc_embs = np.array(doc_embs)
        similarities = cosine_similarity(query_emb, doc_embs)[0]

        # 语义分保护泛化匹配，词面分保护制度术语、数字、时间等精确信息。
        query_terms = self._lexical_terms(query)
        scored_docs = []
        for semantic_score, document in zip(similarities, documents):
            document_terms = self._lexical_terms(document.page_content)
            lexical_score = (
                len(query_terms & document_terms) / len(query_terms)
                if query_terms
                else 0.0
            )
            # 使用混合打分逻辑，增强词面信息的分数
            combined_score = 0.65 * float(semantic_score) + 0.35 * lexical_score
            document.metadata["semantic_rerank_score"] = float(semantic_score)
            document.metadata["lexical_rerank_score"] = float(lexical_score)
            document.metadata["rerank_score"] = float(combined_score)
            scored_docs.append((combined_score, document))
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return scored_docs[:self.config.top_n]

    @staticmethod
    def _lexical_terms(text: str) -> set[str]:
        """
        N-gram切分法, 把用户问题切成一组“词面特征”, 用于rerank 阶段的 lexical_score
        """
        terms: set[str] = set()
        for segment in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", (text or "").lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", segment):
                for width in (2, 3):
                    terms.update(
                        segment[index:index + width]
                        for index in range(max(0, len(segment) - width + 1))
                    )
            else:
                terms.add(segment)
        return terms

    async def rerank(self, query: str, documents: List[Document]) -> List[Tuple[float, Document]]:
        """统一重排入口（自动降级）"""
        if not documents:
            return []

        # 优先在线调用，失败则降级到本地
        if self.rerank_mode == "remote" and self.remote_enabled:
            remote_result = await self._remote_rerank(query, documents)
            if remote_result:
                return remote_result

        # 降级到本地重排
        logger.info("使用本地余弦相似度重排")
        return self._local_rerank(query, documents)


if __name__ == "__main__":
    import asyncio
    #定义异步测试主函数
    # 配置日志格式
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger.info("--- 开始测试 Embedding 和 Rerank 模型 ---")


    async def main_test():
        # 将项目根目录添加到 Python 路径，以便在独立运行时也能找到 core 模块
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)



        logging.basicConfig(level=logging.INFO)
        logger.info("--- 开始测试 Embedding 模型 ---")

        # 测试 Embedding 模型功能
        embed_model_manager = EmbeddingModel()
        try:
            embedding_model = embed_model_manager.get_embedding_model()

            # 测试单句嵌入
            test_text = "这是一个测试文本，用于生成嵌入向量。"
            embedding = embedding_model.embed_query(test_text)
            logger.info(f"测试文本的嵌入向量长度: {len(embedding)}")
            logger.info(f"嵌入向量前5个元素: {embedding[:5]}...")
        except Exception as e:
            logger.error(f"Embedding 模型测试失败: {e}")

        try:   # 测试批量文档嵌入
            test_docs = [
                Document(page_content="向量数据库用于存储嵌入向量"),
                Document(page_content="RAG 是检索增强生成的缩写")
            ]
            doc_embeddings = embedding_model.embed_documents([doc.page_content for doc in test_docs])
            logger.info(f"批量文档嵌入完成，返回 {len(doc_embeddings)} 个向量，每个长度: {len(doc_embeddings[0])}")
        except Exception as e:
            logger.error(f"Embedding 模型测试失败: {e}", exc_info=True)


        logger.info("\n--- 开始测试 Rerank 模型 ---")

        # 测试 Rerank 模型功能
        rerank_model_manager = RerankModel()
        try:
            dummy_query = "什么是大型语言模型"
            dummy_documents = [
                Document(page_content="大型语言模型（LLM）是基于大量文本数据训练的深度学习模型，能够理解、生成和处理人类语言。"),
                Document(page_content="Python 是一种流行的编程语言。"),
                Document(page_content="自然语言处理（NLP）是人工智能领域的一个分支，专注于计算机与人类语言之间的交互。"),
                Document(page_content="向量数据库是一种专门用于存储、管理和检索向量嵌入的数据库，这些向量通常代表文本、图像或其他数据。"),
                Document(page_content="重排序（Reranking）是信息检索中的一个步骤，用于优化初始检索结果的顺序，以提高相关性。"),
            ]
            # RerankModel 的 rerank 方法是异步的，需要在一个异步上下文中调用          # 关键：异步函数直接 await 调用，无嵌套 asyncio.run
            reranked_docs = await rerank_model_manager.rerank(dummy_query, dummy_documents)
            logger.info("\n--- BGE Reranker 重排序后的文档 ---")
            for i, (score, doc) in enumerate(reranked_docs):
                logger.info(f"重排序结果 {i+1} (分数: {score:.4f}): {doc.page_content[:100]}...")
        except Exception as e:
            logger.error(f"Rerank 模型测试失败: {e}")

    asyncio.run(main_test())
