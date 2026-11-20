# api/health.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def root():
    """根路由：服务状态查询"""
    return {
        "status": "success",
        "message": "RAG 服务已启动",
        "docs_url": "/docs",
        "redoc_url": "/redoc"
    }

@router.get("/health")
async def health_check():
    """健康检查路由"""
    return {
        "status": "healthy",
        "service": "rag-retriever",
        "version": "1.0.0"
    }

