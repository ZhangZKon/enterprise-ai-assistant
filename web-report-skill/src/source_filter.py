"""Filter Tavily sources with minimal, explainable rules."""

from src import config
from src.tavily_client import ExtractResult, SearchResult


def filter_sources(
    search_results: list[SearchResult],
    extract_results: list[ExtractResult],
    max_per_domain: int = None,
    min_sources: int = None,
    max_sources: int = None,
) -> list[dict]:
    """Merge search/extract results and rank only by Tavily score."""
    if max_per_domain is None:
        max_per_domain = config.MAX_PER_DOMAIN
    if min_sources is None:
        min_sources = config.MIN_SOURCES
    if max_sources is None:
        max_sources = config.MAX_SOURCES

    extract_map = {e.url: e.raw_content for e in extract_results}

    merged = []
    seen_urls = set()

    for sr in search_results:
        url = (sr.url or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        raw_content = extract_map.get(url) or sr.raw_content or sr.content

        merged.append(
            {
                "title": sr.title,
                "url": url,
                "domain": _extract_domain(url),
                "content": sr.content,
                "raw_content": raw_content,
                "score": sr.score,
                "published_date": sr.published_date,
            }
        )

    # Keep Tavily as the source of relevance ranking. Avoid untested custom weights.
    merged.sort(key=lambda x: x["score"], reverse=True)

    domain_count: dict[str, int] = {}
    filtered = []
    for item in merged:
        domain = item["domain"]
        current = domain_count.get(domain, 0)
        if current >= max_per_domain:
            continue
        domain_count[domain] = current + 1
        filtered.append(item)

    result = filtered[:max_sources]

    if len(result) < min_sources:
        remaining = [item for item in merged if item not in result]
        result.extend(remaining[: min_sources - len(result)])

    return result


def _extract_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return urlparse(url).netloc
    except Exception:
        return url
