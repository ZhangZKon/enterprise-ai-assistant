# api/retrieve.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict

from core.retriever_service import KnowledgeBaseRetriever

router = APIRouter()


# 定义请求/响应模型
class RetrieveRequest(BaseModel):
    query: str
    collection_name: Optional[str] = "default_collection"


class DocumentResponse(BaseModel):
    content: str
    metadata: Dict


class RetrieveResponse(BaseModel):
    success: bool
    message: str
    documents: List[DocumentResponse]


# 初始化检索器——懒加载，避免 API Key 缺失时阻止服务启动
_retriever = None

def _get_retriever() -> KnowledgeBaseRetriever:
    global _retriever
    if _retriever is None:
        _retriever = KnowledgeBaseRetriever(
            collection_name="default_collection",
            k=5,
            rerank_top_n=3,
            hybrid_alpha=0.7
        )
    return _retriever


@router.post("/", response_model=RetrieveResponse)
async def retrieve_documents(request: RetrieveRequest):
    """文档检索接口：返回重排后的相关文档"""
    try:
        retriever = _get_retriever()
        original_collection = retriever.collection_name
        if request.collection_name:
            retriever.collection_name = request.collection_name

        # 调用检索逻辑
        retrieved_docs = await retriever.retrieve(request.query)

        # 恢复原始集合名
        retriever.collection_name = original_collection

        # 构造响应
        doc_responses = [
            DocumentResponse(content=doc.page_content, metadata=doc.metadata)
            for doc in retrieved_docs
        ]

        return RetrieveResponse(
            success=True,
            message=f"检索到 {len(doc_responses)} 个文档",
            documents=doc_responses
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检索失败：{str(e)}")
