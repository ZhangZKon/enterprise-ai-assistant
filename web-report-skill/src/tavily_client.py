"""封装 Tavily API：搜索 + 内容抽取。"""

from dataclasses import dataclass, field
from tavily import TavilyClient
from src import config


@dataclass
class SearchResult:
    title: str = ""
    url: str = ""
    content: str = ""
    raw_content: str = ""
    score: float = 0.0
    published_date: str = ""


@dataclass
class ExtractResult:
    url: str = ""
    raw_content: str = ""
    images: list = field(default_factory=list)


_client: TavilyClient | None = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        config.validate()
        _client = TavilyClient(api_key=config.TAVILY_API_KEY)
    return _client


def search(
    query: str,
    time_range: str = "",
    max_results: int = 10,
) -> list[SearchResult]:
    """调用 Tavily Search API。
    Args:
        query: 搜索 query
        time_range: 时间过滤，如 "day", "week", "month", "year"（可选）
        max_results: 最大返回条数
    Returns:
        SearchResult 列表。
    """
    client = _get_client()
    kwargs = {
        "query": query,
        "max_results": max_results,
        "search_depth": config.SEARCH_DEPTH,
        "chunks_per_source": 3,
        "include_raw_content": "markdown",
    }
    parsed_time_range = _parse_time_range(time_range)
    if parsed_time_range:
        kwargs["time_range"] = parsed_time_range

    resp = client.search(**kwargs)

    results = []
    for r in resp.get("results", []):
        results.append(SearchResult(
            title=r.get("title", ""),
            url=r.get("url", ""),
            content=r.get("content", ""),
            raw_content=r.get("raw_content", ""),
            score=r.get("score", 0.0),
            published_date=r.get("published_date", ""),
        ))
    return results


def extract(urls: list[str], query: str = "") -> list[ExtractResult]:
    """调用 Tavily Extract API 获取网页正文。
    Args:
        urls: 要抽取的 URL 列表
    Returns:
        ExtractResult 列表。
    """
    if not urls:
        return []

    client = _get_client()
    kwargs = {
        "urls": urls[:config.EXTRACT_MAX_SOURCES],
        "extract_depth": config.EXTRACT_DEPTH,
        "format": "markdown",
    }
    if query:
        kwargs["query"] = query
        kwargs["chunks_per_source"] = config.EXTRACT_CHUNKS_PER_SOURCE

    resp = client.extract(**kwargs)

    results = []
    # Tavily extract 返回的可能是列表或字典
    if isinstance(resp, dict):
        resp_list = resp.get("results", resp.get("extracted_content", [])) or []
    else:
        resp_list = resp if isinstance(resp, list) else []

    for r in resp_list:
        url = r.get("url", "") if isinstance(r, dict) else getattr(r, "url", "")
        raw = r.get("raw_content", "") if isinstance(r, dict) else getattr(r, "raw_content", "")
        results.append(ExtractResult(
            url=url,
            raw_content=raw,
        ))
    return results


def _parse_time_range(time_range: str) -> str:
    """Normalize user-friendly time range values for Tavily Search."""
    value = (time_range or "").strip().lower()
    aliases = {
        "day": "day",
        "past_day": "day",
        "today": "day",
        "week": "week",
        "past_week": "week",
        "month": "month",
        "past_month": "month",
        "this_month": "month",
        "year": "year",
        "past_year": "year",
        "this_year": "year",
    }
    return aliases.get(value, "")
