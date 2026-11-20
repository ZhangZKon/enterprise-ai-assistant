from __future__ import annotations

import os
import tempfile
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


def _load_env_file() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


RAG_BASE_URL = env("RAG_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
RAG_CHAT_PATH = env("RAG_CHAT_PATH", "/chat/")
RAG_STREAM_PATH = env("RAG_STREAM_PATH", "/chat/stream")
RAG_COLLECTION_NAME = env("RAG_COLLECTION_NAME", "rag")

LLM_API_KEY = env("LLM_API_KEY")
LLM_BASE_URL = env("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
LLM_MODEL = env("LLM_MODEL", "glm-4-flash")
# evaluator 用便宜模型做质量判断（不需要最强模型）；planner 保持 LLM_MODEL
EVALUATOR_MODEL = env("EVALUATOR_MODEL", "glm-4.5-flash")

WEB_REPORT_PROJECT_DIR = Path(env("WEB_REPORT_PROJECT_DIR", "../web-report-skill"))
WEB_REPORT_PYTHON = Path(
    env("WEB_REPORT_PYTHON", str(WEB_REPORT_PROJECT_DIR / ".venv" / "Scripts" / "python.exe"))
)
WEB_REPORT_OUTPUT_DIR = Path(
    env("WEB_REPORT_OUTPUT_DIR", str(Path(tempfile.gettempdir()) / "web-report-skill" / "outputs"))
)
WEB_REPORT_TIMEOUT = int(env("WEB_REPORT_TIMEOUT", "300"))

# 每次请求的执行轨迹 JSONL 落盘目录（默认 agent-service/logs，可经 .env 调整）
EVENT_LOG_DIR = Path(env("EVENT_LOG_DIR", str(BASE_DIR / "logs")))

# Redis（web_report 结果缓存；与 rag-local 共用 docker 里的 rag-redis 实例）
REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379")
# web_report 缓存有效期（秒），报告会过时，默认 1 小时
WEB_REPORT_CACHE_TTL = int(env("WEB_REPORT_CACHE_TTL", "3600"))


def validate_llm_config() -> None:
    if not LLM_API_KEY:
        raise RuntimeError("Missing LLM_API_KEY. Set it in agent-service/.env.")
