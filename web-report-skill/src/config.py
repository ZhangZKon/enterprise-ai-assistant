"""集中读取配置，优先从 .env 文件，其次从环境变量。"""

import os
from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


TAVILY_API_KEY = _env("TAVILY_API_KEY")
LLM_API_KEY = _env("LLM_API_KEY")
LLM_BASE_URL = _env("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = _env("LLM_MODEL", "gpt-4o")
# 候选来源数量
SEARCH_MAX_RESULTS = int(_env("SEARCH_MAX_RESULTS", "5"))
# 深度阅读来源数量
EXTRACT_MAX_SOURCES = int(_env("EXTRACT_MAX_SOURCES", "4"))
SEARCH_DEPTH = _env("SEARCH_DEPTH", "advanced")
EXTRACT_DEPTH = _env("EXTRACT_DEPTH", "advanced")
# 每个网页里最多提取的相关片段个数
EXTRACT_CHUNKS_PER_SOURCE = int(_env("EXTRACT_CHUNKS_PER_SOURCE", "3"))
EVIDENCE_EXCERPT_CHARS = int(_env("EVIDENCE_EXCERPT_CHARS", "3000"))
# 每个域名最多保留的条数
MAX_PER_DOMAIN = int(_env("MAX_PER_DOMAIN", "2"))
# 最终保留的最小/最大来源数
MIN_SOURCES = int(_env("MIN_SOURCES", "5"))
MAX_SOURCES = int(_env("MAX_SOURCES", "8"))


def validate():
    """校验必要配置是否存在。"""
    missing = []
    if not TAVILY_API_KEY:
        missing.append("TAVILY_API_KEY")
    if not LLM_API_KEY:
        missing.append("LLM_API_KEY")
    if missing:
        raise RuntimeError(
            f"缺少必要配置: {', '.join(missing)}。"
            f"请在 .env 文件中设置这些变量。"
        )
