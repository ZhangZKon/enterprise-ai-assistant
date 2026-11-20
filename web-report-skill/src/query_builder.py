"""构造 Tavily 搜索 query。"""


def build_query(
    topic: str,
    report_type: str = "",
    keywords: str = "",
) -> str:
    """把用户输入拼接成一个搜索 query。
    Args:
        topic: 调研主题
        report_type: 报告类型（可选）
        keywords: 附加关键词，逗号分隔（可选）
    Returns:
        拼接后的搜索 query 字符串。
    """
    parts = [topic]

    if keywords:
        kw_list = [kw.strip() for kw in keywords.split(",") if kw.strip()]
        parts.extend(kw_list)

    return " ".join(parts)
