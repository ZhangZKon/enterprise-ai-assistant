from langchain_core.documents import Document
from langchain_milvus import Milvus
import logging
from functools import lru_cache
from typing import List, Dict, Any

from pymilvus import connections, utility
import asyncio
from config.config import APP_CONFIG
from core.embedding_service import EmbeddingModel
from async_lru import alru_cache
logger = logging.getLogger(__name__)

class VectorDB:
    def __init__(self):
        self.config = APP_CONFIG.milvus
        self.embedding_model = EmbeddingModel().get_embedding_model() # 获取嵌入模型实例
        self.connection_args = {
            "uri": self.config.url, # Milvus 连接 URI
        }
        self.vector_store = None # Milvus 向量存储实例
    
    async def _get_vector_store(self, collection_name: str) -> Milvus:
        """
        获取或创建 Milvus 向量存储实例。
        如果实例尚未创建，则根据配置进行初始化。

        Args:
            collection_name (str): 目标 Milvus 集合的名称。

        Returns:
            Milvus: Milvus 向量存储实例。

        Raises:
            Exception: 如果创建/连接 Milvus 集合失败。
        """
        # 确保 Milvus 连接已建立
        await asyncio.to_thread(connections.connect, uri=self.config.url)

        # 检查集合是否存在
        collection_exists = await asyncio.to_thread(utility.has_collection, collection_name)

        if collection_exists:
            logger.info(f"集合 '{collection_name}' 已存在，正在复用现有集合。")
            # 如果集合存在，直接加载它
            self.vector_store = await asyncio.to_thread(
                Milvus,
                embedding_function=self.embedding_model,
                # 注释掉稀疏向量相关 ↓
                #builtin_function=BM25BuiltInFunction(),
                collection_name=collection_name,
                connection_args=self.connection_args,
                # 仅用密集向量，删除 sparse ↓
                # vector_field=["dense", "sparse"],
                vector_field="dense",
                consistency_level="Strong",
                auto_id=True,
                # 如果集合已存在，不需要 drop_old
            )
        else:
            logger.info(f"集合 '{collection_name}' 不存在，正在创建新集合。")
            # 如果集合不存在，则创建新集合
            dense_index = {
                "metric_type": "IP",
                #"index_type": "HNSW",
                # 改用 FLAT 索引，删除 HNSW ↓
                "index_type": "FLAT",
                # FLAT 索引无参数，删除多余配置 ↓
                # "params": {}
            }
            # 注释掉稀疏索引 ↓
            # sparse_index = {
            #     "metric_type": "BM25",
            #     "index_type": "AUTOINDEX",
            # }
            self.vector_store = await asyncio.to_thread(
                Milvus,
                embedding_function=self.embedding_model,
                # 注释掉稀疏向量相关
                # builtin_function=BM25BuiltInFunction(),
                collection_name=collection_name,
                connection_args=self.connection_args,
                # 仅传密集索引，删除 sparse_index ↓
                # index_params=[dense_index, sparse_index],
                index_params=dense_index,
                # 仅用密集向量，删除 sparse ↓
                # vector_field=["dense", "sparse"],
                vector_field="dense",
                consistency_level="Strong",
                auto_id=True,
                # drop_old=True # 首次创建时不需要，因为已经检查了不存在
            )
            logger.info(f"成功创建 Milvus 集合: {collection_name}")
        
        return self.vector_store

    def _batch_documents(self, documents: List[Document], batch_size: int) -> List[List[Document]]:
        """
        将文档列表分批处理。

        Args:
            documents (List[Document]): 待分批的文档列表。
            batch_size (int): 每个批次的最大文档数量。

        Returns:
            List[List[Document]]: 分批后的文档列表。
        """
        return [documents[i:i + batch_size] for i in range(0, len(documents), batch_size)]

    async def insert_documents(self, documents: List[Document], collection_name: str) -> None:
        """
        批量插入文档到 Milvus 集合。
        在插入前会尝试删除同名集合，并支持并行插入。

        Args:
            documents (List[Document]): 待插入的文档列表。
            collection_name (str): 目标 Milvus 集合的名称。

        Raises:
            Exception: 如果文档插入失败。
        """
        if not documents:
            logger.warning("没有文档可供插入。")
            return

        try:
            logger.info(f"正在将 {len(documents)} 个文档插入到 Milvus 集合 '{collection_name}' 中...")
            
            # 获取或创建向量存储实例，这里会处理集合的复用逻辑
            vector_store = await self._get_vector_store(collection_name)
            
            # 将文档分批
            batches = self._batch_documents(documents, self.config.batch_size)
            logger.info(f"文档已分为 {len(batches)} 个批次进行处理。")
            
            async def process_batch(batch: List[Document]) -> None:
                """内部函数：处理单个文档批次"""
                try:
                    logger.info(f"处理批次，包含 {len(batch)} 个文档。")
                    # 使用 add_documents 方法插入文档
                    await asyncio.to_thread(vector_store.add_documents, batch)
                    logger.info(f"批次处理完成。")
                except Exception as e:
                    logger.error(f"处理批次时发生错误: {e}", exc_info=True)
                    raise

            # 并行处理所有批次
            logger.info("开始并行处理文档批次...")
            await asyncio.gather(*[process_batch(batch) for batch in batches])
            
            logger.info("所有文档插入完成。")
            
        except Exception as e:
            logger.error(f"文档插入失败: {e}", exc_info=True)
            raise

    async def create_indexes(self, collection_name: str) -> None:
        """
        为 Milvus 集合创建索引。
        包括密集向量索引和稀疏向量索引，并加载集合到内存。

        Args:
            collection_name (str): 目标 Milvus 集合的名称。

        Raises:
            Exception: 如果创建索引失败。
        """
        try:
            vector_store = await self._get_vector_store(collection_name)
            
            # 创建 dense 向量字段的索引
            dense_index_params = self.config.index_params
            await asyncio.to_thread(
                vector_store.col.create_index,
                field_name="dense",
                index_params=dense_index_params
            )
            logger.info(f"已为 'dense' 字段创建索引: {dense_index_params}")
            
            # 创建 sparse 向量字段的索引
            # sparse_index_params = self.config.sparse_index_params
            # await asyncio.to_thread(
            #     vector_store.col.create_index,
            #     field_name="sparse",
            #     index_params=sparse_index_params
            # )
            # logger.info(f"已为 'sparse' 字段创建索引: {sparse_index_params}")
            
            # 加载集合到内存，以便进行查询
            await asyncio.to_thread(vector_store.col.load)
            logger.info(f"集合 '{collection_name}' 已加载到内存。")
            
        except Exception as e:
            logger.error(f"创建索引失败: {e}", exc_info=True)
            raise

    # @lru_cache(maxsize=100)
    @alru_cache
    async def get_vector_store(self, collection_name: str) -> Milvus:
        """
        获取向量存储实例（带缓存）。
        使用 LRU 缓存，避免频繁创建 Milvus 实例。

        Args:
            collection_name (str): 目标 Milvus 集合的名称。

        Returns:
            Milvus: Milvus 向量存储实例。
        """
        return await self._get_vector_store(collection_name)

    async def delete_collection(self, collection_name: str) -> None:
        """
        删除 Milvus 集合。

        Args:
            collection_name (str): 要删除的 Milvus 集合的名称。

        Raises:
            Exception: 如果删除集合失败。
        """
        try:
            vector_store = await self._get_vector_store(collection_name)
            if vector_store and vector_store.col:
                await asyncio.to_thread(vector_store.col.drop) # 删除集合
                self.vector_store = None # 清除内部存储的实例
                logger.info(f"集合 '{collection_name}' 已成功删除。")
            else:
                logger.warning(f"集合 '{collection_name}' 不存在或无法访问，无需删除。")
        except Exception as e:
            logger.error(f"删除集合失败: {e}", exc_info=True)
            raise

    async def hybrid_search(
        self,
        query: str,
        collection_name: str,
        k: int = 10,
        alpha: float = 0.5, # 混合权重，默认为 0.5
    ) -> List[Document]:
        """
        执行混合搜索（密集向量 + 稀疏向量）。

        Args:
            query (str): 查询文本。
            collection_name (str): 集合名称。
            k (int): 返回的文档数量。默认为 10。
            alpha (float): 混合权重 (0-1)，1 表示完全使用密集向量，0 表示完全使用稀疏向量。

        Returns:
            List[Document]: 检索到的文档列表。

        Raises:
            Exception: 如果混合搜索失败。
        """
        try:
            vector_store = await self.get_vector_store(collection_name)
        
            # 原 执行混合搜索，使用加权排名
            # 纯密集向量相似度搜索，删除混合搜索参数 ↓
            results = await asyncio.to_thread(
                vector_store.similarity_search,
                query,
                k=k,
                # 删除混合搜索相关参数 ↓
                # ranker_type="weighted", # 使用加权排名器
                # ranker_params={"weights": [alpha, 1 - alpha]}, # 设置密集和稀疏向量的权重
            )
            # 过滤空内容文档
            valid_results = []
            for doc in results:
                if doc.page_content.strip():
                    valid_results.append(doc)
                else:
                    logger.warning("检索到空文档，已过滤")
            logger.info(f"混合搜索完成，返回 {len(results)} 个文档。")
            
            return valid_results
        except Exception as e:
            logger.error(f"混合搜索失败: {e}", exc_info=True)
            raise

    async def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """
        获取 Milvus 集合的统计信息。

        Args:
            collection_name (str): 集合名称。

        Returns:
            Dict[str, Any]: 包含集合统计信息的字典。

        Raises:
            Exception: 如果获取统计信息失败。
        """
        try:
            vector_store = await self.get_vector_store(collection_name)
            if vector_store and vector_store.col:
                # stats = await asyncio.to_thread(vector_store.col.get_stats) # 获取集合统计信息
                #新版本的 pymilvus 中 Collection 对象已移除 get_stats() 方法，改用 num_entities 属性获取行数
                stats= await asyncio.to_thread(lambda :vector_store.col.num_entities)
                logger.info(f"集合 '{collection_name}' 统计信息: {stats}")
                return stats
            else:
                logger.warning(f"集合 '{collection_name}' 不存在或无法访问，无法获取统计信息。")
                return {}
        except Exception as e:
            logger.error(f"获取集合统计信息失败: {e}", exc_info=True)
            raise

# 模块测试部分
if __name__ == "__main__":
    import asyncio  # 新增：导入异步库
    logging.basicConfig(level=logging.INFO)
    logger.info("--- 开始测试 Milvus 向量数据库 ---")

    #定义异步测试主函数
    async def main_test():
        vector_db_manager = VectorDB()
        test_collection = "test_collection_rag_opt" # 使用一个独特的测试集合名称



        # 1. 清理旧集合（如果存在）
        logger.info(f"测试开始：清理集合 '{test_collection}'...")
        try:
            await vector_db_manager.delete_collection(test_collection)
        except Exception as e:
            logger.warning(f"清理集合 '{test_collection}' 失败（可能不存在）：{e}")

        # 2. 准备测试文档
        test_docs = [
            Document(page_content="Milvus是一个开源的向量数据库，专为AI应用设计。", metadata={"source": "doc1.md", "title": "Milvus介绍"}),
            Document(page_content="RAG（Retrieval-Augmented Generation）结合了检索和生成模型，提高了LLM的准确性。", metadata={"source": "doc2.md", "title": "RAG原理"}),
            Document(page_content="Langchain是一个用于开发LLM应用的框架，提供了许多工具和组件。", metadata={"source": "doc3.md", "title": "Langchain应用"}),
            Document(page_content="向量数据库在处理非结构化数据方面表现出色，例如文本、图像和音频。", metadata={"source": "doc1.md", "title": "向量数据库优势"}),
            Document(page_content="重排模型可以提高检索结果的相关性，通过重新排序初始检索到的文档。", metadata={"source": "doc2.md", "title": "重排模型作用"}),
        ]
        logger.info(f"准备了 {len(test_docs)} 个测试文档。")

        # 3. 插入文档
        logger.info(f"开始插入文档到集合 '{test_collection}'...")
        try:
            await vector_db_manager.insert_documents(test_docs, test_collection)
            logger.info("文档插入成功。")
        except Exception as e:
            logger.error(f"文档插入失败: {e}")
            exit(1) # 插入失败则退出测试

        # 4. 获取集合统计信息
        logger.info(f"获取集合 '{test_collection}' 的统计信息...")
        stats = await vector_db_manager.get_collection_stats(test_collection)
        logger.info(f"集合统计信息: {stats}")

        # 5. 测试混合搜索 (优化为密集索引)
        test_query = "什么是向量数据库？"
        logger.info(f"开始测试密集搜索，查询: '{test_query}'")
        try:
            # 测试不同的 alpha 值，观察混合搜索效果
            for alpha in [0.3, 0.5, 0.7]:
                results = await vector_db_manager.hybrid_search(
                    query=test_query,
                    collection_name=test_collection,
                    k=3, # 返回前3个文档
                    alpha=alpha
                )

                logger.info(f"\n查询: '{test_query}' (alpha={alpha})，检索到 {len(results)} 个文档:")
                for i, doc in enumerate(results):
                    logger.info(f"  文档 {i+1}:")
                    logger.info(f"    内容: {doc.page_content[:100]}...") # 打印前100个字符
                    logger.info(f"    元数据: {doc.metadata}")
                    logger.info("-" * 10)
        except Exception as e:
            logger.error(f"混合搜索测试失败: {e}")

        # 6. 再次清理集合
        logger.info(f"测试结束：清理集合 '{test_collection}'...")
        try:
            await vector_db_manager.delete_collection(test_collection)
            logger.info(f"集合 '{test_collection}' 已成功清理。")
        except Exception as e:
            logger.error(f"最终清理集合 '{test_collection}' 失败: {e}")


    asyncio.run(main_test())