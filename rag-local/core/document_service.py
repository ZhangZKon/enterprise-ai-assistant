import os
import asyncio
from typing import List
import re
from langchain_community.document_loaders import DirectoryLoader, UnstructuredMarkdownLoader, PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from minio import S3Error

from config.config import APP_CONFIG
from core.minio_service import MinioClient, s3_client
import logging
logger = logging.getLogger(__name__)

class DocumentLoader:
    def __init__(self):
        self.chunk_size = APP_CONFIG.chunk_size
        self.chunk_overlap = APP_CONFIG.chunk_overlap
        self.s3_client = MinioClient()
        self.document_path = APP_CONFIG.document_path

        # 初始化递归字符文本分割器
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            add_start_index=True,
        )

    async def load_and_split_documents(self, file_name: str = "*") -> List[Document]:
        """
        加载指定目录下的所有 Markdown 和 PDF 文件，或单个指定文件，并将其分割成文本块。
        支持递归加载子目录中的文件。

        Args:
            file_name (str): 要加载的特定文件名。如果为 "*"，则加载目录下所有支持的文件。

        Returns:
            List[Document]: 分割后的文本块列表，每个文本块是一个 Langchain Document 对象。
                            如果未找到任何文档，则返回空列表。
        Raises:
            FileNotFoundError: 如果指定了单个文件但未找到。
            ValueError: 如果指定了不支持的文件类型。
        """
        documents = []

        if file_name == "*":
            logger.info(f"开始从目录 '{self.document_path}' 加载所有文档...")

            # Load documents concurrently
            loaders = [
                (DirectoryLoader(
                    self.document_path,
                    glob="**/*.md",
                    loader_cls=UnstructuredMarkdownLoader,
                    show_progress=True
                ), "Markdown"),
                (DirectoryLoader(
                    self.document_path,
                    glob="**/*.pdf",
                    loader_cls=PyPDFLoader,
                    show_progress=True
                ), "PDF")
            ]

            async def load_documents(loader, doc_type):
                docs = await asyncio.to_thread(loader.load)
                logger.info(f"已加载 {len(docs)} 个 {doc_type} 文件。")
                return docs

            results = await asyncio.gather(*(load_documents(loader, doc_type) for loader, doc_type in loaders))
            for docs in results:
                documents.extend(docs)

        else:
            file_path = os.path.join(self.document_path, file_name)
            logger.info(f"开始加载指定文件 '{file_path}'...")
            try:
                file_content = self.get_file_from_minio(file_name, bucket_name=APP_CONFIG.minio.bucket_name)
                if file_content:
                    document = Document(page_content=file_content, metadata={"source": file_name})
                    documents.append(document)
                    logger.info(f"已从 MinIO 加载文件: {file_name}")
                else:
                    logger.warning(f"无法从 MinIO 加载文件: {file_name}")
            except Exception as e:
                logger.error(f"从 MinIO 加载文件失败: {file_name}, 错误: {e}")

        if not documents:
            logger.warning(f"在目录 '{self.document_path}' 中未找到任何文档或指定文件。")
            return []

        logger.info(f"总共加载了 {len(documents)} 个文档。开始分割文本...")
        split_documents = await asyncio.to_thread(self.text_splitter.split_documents, documents)
        logger.info(f"文档分割完成，共生成 {len(split_documents)} 个文本块。")

        #TODO  增加清洗文本逻辑
        # 清洗文本：过滤空值、非法字符、超长内容
        cleaned_docs = []
        max_length = 2000  # 智谱embedding-2最大支持8192 token，留余量
        for idx, doc in enumerate(split_documents):
            # 1. 移除空白字符和不可见字符
            content = doc.page_content.strip()
            if not content:
                logger.warning(f"跳过空文本块 {idx}")
                continue

            # 2. 移除特殊字符（保留中文、英文、数字、常用标点）
            content = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s，。！？；：""''()（）【】《》、·]', '', content)
            content = re.sub(r'\s+', ' ', content)  # 多个空格合并为一个

            # 3. 截断超长文本
            if len(content) > max_length:
                logger.warning(f"文本块 {idx} 过长（{len(content)}字符），截断到{max_length}字符")
                content = content[:max_length]

            # 4. 补全 Milvus schema 要求的元数据字段（缺省为空字符串）
            for key in ("producer", "creator", "creationdate", "author", "title",
                        "total_pages", "page", "page_label"):
                if key not in doc.metadata:
                    doc.metadata[key] = "" if key != "total_pages" and key != "page" else 0

            # 5. 重新赋值并添加到清洗列表
            doc.page_content = content
            cleaned_docs.append(doc)

        logger.info(f"清洗后剩余 {len(cleaned_docs)} 个有效文本块")
        # 返回原始为清洗的分割文本
        # return split_documents
        #返回清洗后的文本
        return cleaned_docs

    def get_file_from_minio(self, file_name: str, bucket_name: str = None) -> bytes:
        """
        从MinIO下载文件并返回文件字节内容
        :param file_name: MinIO中存储的文件名（含路径，如docs/test.pdf）
        :param bucket_name: 存储文档的MinIO桶名，需提前创建
        :return: 文件的字节内容
        """
        if bucket_name is None:
            bucket_name = APP_CONFIG.minio.bucket_name
        try:
            # 下载文件到内存字节流
            response = self.s3_client.get_object(bucket_name, file_name)
            file_content = response.read()
            return file_content
        except S3Error as e:
            # 异常处理：文件不存在、权限错误等
            raise Exception(f"从MinIO获取文件失败: {e}")
        finally:
            if 'response' in locals():
                response.close()
                response.release_conn()
