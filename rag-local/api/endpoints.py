import logging
from typing import List, Optional
import io
from fastapi import APIRouter, status, UploadFile, File, HTTPException, Form
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.documents import Document

from core.document_service import DocumentLoader
from core.vector_db_service import VectorDB
from core.retriever_service import KnowledgeBaseRetriever
from config.config import APP_CONFIG
from core.minio_service import s3_client

from models.schemas import QueryRequest, IngestRequest, IngestResponse, QueryResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# 初始化核心组件实例
# 文档加载器：负责加载和分割知识库文档
document_loader = DocumentLoader()
# 向量数据库管理器：懒加载，避免 API Key 缺失时阻止服务启动
_vector_db = None

def _get_vector_db() -> VectorDB:
    global _vector_db
    if _vector_db is None:
        _vector_db = VectorDB()
    return _vector_db

# LLM（大型语言模型）：用于生成答案
if not APP_CONFIG.llm.api_key:
    logger.error("LLM_API_KEY 环境变量未设置. LLM 功能将不可用.")
    # 生产环境中可以考虑直接退出或抛出更严重的错误
    llm = None # 或者使用一个模拟的LLM
else:
    llm = ChatOpenAI(
        base_url=APP_CONFIG.llm.base_url,
        model=APP_CONFIG.llm.model_id,
        api_key=APP_CONFIG.llm.api_key,
        temperature=0.1,  # 控制生成答案的随机性，较低的值表示更确定
    )


router = APIRouter()  # 核心：创建APIRouter实例  可以用多个接口

@router.get("/health", summary="健康检查接口")
async def health_check():
    """健康检查接口，用于判断服务是否正常运行。"""
    logger.info("健康检查请求收到.")
    return {"status": "ok"}


@router.post("/ingest_documents",response_model=IngestResponse, summary="摄取文档到知识库")
async def ingest_documents(request: IngestRequest):
    """从配置的文档路径加载文档，进行分割、嵌入，并存储到 Milvus 向量数据库中.

    Args:
        request (IngestRequest): 包含集合名称和文件路径列表的请求.

    Returns:
        IngestResponse: 包含摄取结果的消息、文档数量和集合名称.

    Raises:
        HTTPException: 如果未找到文档、文件类型不支持或摄取失败.
    """
    logger.info(f"开始为集合 '{request.collection_name}' 摄取文档. 文件: '{request.file_paths}'.")
    all_documents = []
    try:
        if request.file_paths == ["*"]:
            # 加载并分割文档，传入 file_name 参数
            documents = await document_loader.load_and_split_documents()
            if not documents:
                logger.warning(f"未找到任何文档.")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"未找到任何文档. 请检查路径是否存在."
                )
            all_documents.extend(documents)
        else:
            for file_path in request.file_paths:
                # 从 MinIO 加载文件
                file_content = document_loader.get_file_from_minio(file_path, bucket_name=APP_CONFIG.minio.bucket_name)
                if file_content:
                    document = Document(page_content=file_content, metadata={"source": file_path})
                    all_documents.append(document)
                    logger.info(f"已从 MinIO 加载文件: {file_path}")
                else:
                    logger.warning(f"无法从 MinIO 加载文件: {file_path}")

        if not all_documents:
            logger.warning(f"未找到任何文档或指定文件 '{request.file_paths}'.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到任何文档或指定文件 '{request.file_paths}'."
            )

        # 将文档插入到向量数据库
        await _get_vector_db().insert_documents(all_documents, request.collection_name)
        logger.info(f"成功将 {len(all_documents)} 个文档摄取到集合 '{request.collection_name}'.")
        return IngestResponse(
            message="文档摄取成功",
            documents_ingested=len(all_documents),
            collection_name=request.collection_name
        )
    except FileNotFoundError as e:
        logger.error(f"文档摄取失败 - 文件未找到: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"文档摄取失败：指定的文档路径或文件未找到: {e}.")
    except ValueError as e:
        logger.error(f"文档摄取失败 - 文件类型不支持: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文档摄取失败：文件类型不支持: {e}.")
    except Exception as e:
        logger.error(f"文档摄取失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="文档摄取失败：服务器内部错误."
        )


@router.post("/query", response_model=QueryResponse, summary="查询知识库")
async def query_knowledge_base_api(request: QueryRequest):
    """接收用户查询，从 Milvus 检索相关文档，进行重排，并使用 LLM 生成答案.

    Args:
        request (QueryRequest): 包含查询文本、集合名称、检索参数的请求体.

    Returns:
        QueryResponse: 包含原始查询、LLM 生成的答案和来源文档列表.

    Raises:
        HTTPException: 如果查询处理失败.
    """
    logger.info(f"收到查询请求: '{request.query}'，集合: '{request.collection_name}'.")
    try:
        # 初始化知识库检索器
        retriever = KnowledgeBaseRetriever(
            collection_name=request.collection_name,
            k=request.k,
            rerank_top_n=request.rerank_top_n,
            hybrid_alpha=request.hybrid_alpha
        )

        # 检索相关文档
        retrieved_docs = await retriever.retrieve(request.query)

        if not retrieved_docs:
            logger.warning(f"未找到与查询 '{request.query}' 相关的文档.")
            return QueryResponse(
                query=request.query,
                answer="抱歉，知识库中未找到与您问题相关的信息.",
                source_documents=[]
            )

        # 为 LLM 准备上下文
        context = "\\n\\n".join([doc.page_content for doc in retrieved_docs])

        # 构建 LLM 链
        template = """根据以下上下文回答问题:
        {context}

        问题: {question}
        """
        prompt = ChatPromptTemplate.from_template(template)

        # RAG 链的定义
        rag_chain = (
            {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
            | prompt
            | llm
            | StrOutputParser()
        )

        if llm is None:
            logger.error("LLM 未初始化，无法处理查询请求.")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LLM 服务不可用，请检查配置."
            )

        # 执行 RAG 链以获取答案
        answer = rag_chain.invoke({"context": context, "question": request.query})

        # 格式化来源文档输出
        source_documents_output = [
            {"page_content": doc.page_content, "metadata": doc.metadata}
            for doc in retrieved_docs
        ]

        logger.info(f"成功回答查询: '{request.query}'.")
        return QueryResponse(
            query=request.query,
            answer=answer,
            source_documents=source_documents_output
        )
    except Exception as e:
        logger.error(f"查询处理失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="查询处理失败：服务器内部错误."
        )


@router.delete("/knowledge_base/{collection_name}", summary="删除 Milvus 知识库集合")
async def delete_knowledge_base(collection_name: str):
    """删除指定的 Milvus 集合.

    Args:
        collection_name (str): 要删除的 Milvus 集合的名称.

    Returns:
        dict: 包含删除结果的消息.

    Raises:
        HTTPException: 如果删除失败.
    """
    logger.info(f"尝试删除集合: '{collection_name}'.")
    try:
        await _get_vector_db().delete_collection(collection_name)
        logger.info(f"集合 '{collection_name}' 已成功删除.")
        return {"message": f"集合 '{collection_name}' 已成功删除."}
    except Exception as e:
        logger.error(f"删除集合 '{collection_name}' 失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除集合失败：服务器内部错误."
        )


@router.post("/upload_file", summary="上传文件")
async def upload_file(files: List[UploadFile] = File(...), bucket_name: str = Form(...), object_name: Optional[str] = Form(None)):
    results = []
    for file in files:
        try:
            file_content = await file.read()
            object_path = f"{object_name}/{file.filename}" if object_name else file.filename
            s3_client.put_object(bucket_name, object_path, io.BytesIO(file_content))
            results.append({"filename": file.filename, "status": "success", "message": "File uploaded successfully"})
            logger.info(f"File '{file.filename}' uploaded to '{bucket_name}/{object_path}' successfully.")
        except Exception as e:
            logger.exception(f"File upload failed for '{file.filename}': {e}")
            results.append({"filename": file.filename, "status": "error", "message": f"File upload failed: {e}"})

    return {"uploaded_files": results}
