"""调用 LLM 生成报告。"""

from pathlib import Path
from openai import OpenAI
from src import config


def generate_report(
    topic: str,
    report_type: str,
    time_range: str,
    evidence_list: list[dict],
) -> str:
    """调用 LLM 生成 Markdown 报告。
    Args:
        topic: 调研主题
        report_type: 报告类型
        time_range: 时间范围
        evidence_list: evidence dict 列表
    Returns:
        Markdown 格式的报告文本。
    """
    config.validate()

    client = OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
    )

    system_prompt = _load_prompt()

    # 把 evidence_list 格式化成 LLM 可读的文本
    evidence_text = _format_evidence(evidence_list)

    user_message = f"""主题：{topic}
报告类型：{report_type}
时间范围：{time_range}

以下是供参考的证据列表：

{evidence_text}

请基于以上证据生成报告。"""

    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,
    )

    return resp.choices[0].message.content or ""


def _load_prompt() -> str:
    """加载提示词模板。"""
    prompt_path = Path(__file__).parent.parent / "prompts" / "report_prompt.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    # 兜底 prompt
    return """你是企业研究助理。请基于给定证据生成中文 Markdown 报告。
只使用给定的来源信息，关键结论标注 [来源编号]，不要编造信息。"""


def _format_evidence(evidence_list: list[dict]) -> str:
    """把 evidence 列表格式化为便于 LLM 阅读的文本。"""
    lines = []
    for e in evidence_list:
        lines.append(f"[来源 {e['id']}] {e['title']}")
        lines.append(f"  URL: {e['url']}")
        lines.append(f"  域名: {e['domain']}")
        if e.get("published_date"):
            lines.append(f"  发布日期: {e['published_date']}")
        if e.get("summary"):
            lines.append(f"  摘要: {e['summary']}")
        if e.get("key_points"):
            for kp in e["key_points"]:
                lines.append(f"  - {kp}")
        if e.get("content_excerpt"):
            lines.append(f"  正文节选: {e['content_excerpt']}")
        lines.append("")
    return "\n".join(lines)
