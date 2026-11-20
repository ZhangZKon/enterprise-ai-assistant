"""证据构建：把搜索+抽取结果整理成统一的 evidence 结构。"""

from src import config


def build_evidence_list(
    filtered_sources: list[dict],
) -> list[dict]:
    """把过滤后的来源整理成 evidence 列表。
    Args:
        filtered_sources: source_filter 过滤后的列表
    Returns:
        evidence dict 列表，按 relevance_score 降序排列。
    """
    evidence_list = []

    for i, src in enumerate(filtered_sources):
        evidence = {
            "id": i + 1,
            "title": src.get("title", ""),
            "url": src.get("url", ""),
            "domain": src.get("domain", ""),
            "published_date": src.get("published_date", ""),
            "summary": _generate_summary(src.get("content", ""), max_chars=200),
            "key_points": _extract_key_points(src.get("raw_content", "")),
            "content_excerpt": _truncate(
                src.get("raw_content", ""),
                max_chars=config.EVIDENCE_EXCERPT_CHARS,
            ),
            "relevance_score": round(src.get("score", 0.0), 2),
        }
        evidence_list.append(evidence)

    # 按 relevance_score 降序排列
    evidence_list.sort(key=lambda e: e["relevance_score"], reverse=True)
    # 重新编号
    for i, e in enumerate(evidence_list):
        e["id"] = i + 1

    return evidence_list


def _generate_summary(content: str, max_chars: int = 300) -> str:
    """从 Tavily 返回的摘要中生成简短摘要。"""
    if not content:
        return ""
    return _truncate(content.strip(), max_chars)


def _extract_key_points(raw_content: str) -> list[str]:
    """从正文中提取关键点。
    第一版简单实现：取每个自然段的首句作为 key point。
    """
    if not raw_content:
        return []

    points = []
    lines = raw_content.split("\n")
    for line in lines:
        line = line.strip()
        # 跳过过短的空行
        if not line or len(line) < 20:
            continue
        # 取第一个句号之前的内容
        first_sentence = line.split("。")[0].split(".")[0].strip()
        if 10 < len(first_sentence) < 150:
            points.append(first_sentence)
        if len(points) >= 5:
            break

    return points


def _truncate(text: str, max_chars: int) -> str:
    """截断文本到指定字符数。"""
    if not text or len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."
