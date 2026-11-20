# api/__init__.py
from .health import router as health_router
from .retrieve import router as retrieve_router
from .chat import router as chat_router

# 统一导出，便于 main.py 导入
router = health_router
__all__ = ["health", "retrieve", "chat"]
