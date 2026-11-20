# main.py
import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 导入路由模块（新增）
from api import health, retrieve, chat,endpoints

# 配置日志
# force=True 确保覆盖 uvicorn 自身的日志配置，使自定义格式和级别生效
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True
)
logger = logging.getLogger(__name__)

# 初始化 FastAPI 应用
app = FastAPI(
    title="RAG 智能问答服务",
    description="基于 Milvus + 智谱 LLM 的检索增强生成服务",
    version="1.0.0"
)

# 跨域配置（可选，前端调用需要）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境替换为具体前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由（核心：将拆分的路由挂载到主应用）
app.include_router(health.router, tags=["基础服务"])
app.include_router(retrieve.router, prefix="/retrieve", tags=["文档检索"])
app.include_router(chat.router, prefix="/chat", tags=["智能问答"])
app.include_router(endpoints.router,prefix="/api",tags=["文档处理"])

# 服务启动
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
