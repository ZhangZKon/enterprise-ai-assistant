"""写出 evidence 和 report 为 Markdown 文件。"""

from pathlib import Path
from datetime import datetime
import os
import re


OUTPUT_DIR = Path(os.getenv("WEB_REPORT_OUTPUT_DIR", Path(__file__).parent.parent / "outputs"))


def create_run_output_dir(topic: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify(topic)
    output_dir = OUTPUT_DIR / f"{timestamp}_{slug}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def write_evidence_list(evidence_list: list[dict], output_dir: Path | None = None) -> str:
    """写出 evidence_list.md。
    Returns:
        输出文件路径。
    """
    output_dir = output_dir or create_run_output_dir("report")

    lines = [
        "# 证据列表",
        f"\n生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"共 {len(evidence_list)} 条来源\n",
    ]

    for e in evidence_list:
        lines.append(f"## [{e['id']}] {e['title']}")
        lines.append(f"- **URL**: {e['url']}")
        lines.append(f"- **域名**: {e['domain']}")
        if e.get("published_date"):
            lines.append(f"- **发布日期**: {e['published_date']}")
        lines.append(f"- **相关度**: {e['relevance_score']}")
        if e.get("summary"):
            lines.append(f"\n**摘要**:\n\n{e['summary']}")
        if e.get("key_points"):
            lines.append("\n**关键点**:")
            for kp in e["key_points"]:
                lines.append(f"- {kp}")
        if e.get("content_excerpt"):
            lines.append(f"\n**正文节选**:\n\n```\n{e['content_excerpt']}\n```")
        lines.append("\n---\n")

    content = "\n".join(lines)
    output_path = output_dir / "evidence_list.md"
    output_path.write_text(content, encoding="utf-8")
    return str(output_path)


def write_report(report_markdown: str, output_dir: Path | None = None) -> str:
    """写出 report.md。
    Returns:
        输出文件路径。
    """
    output_dir = output_dir or create_run_output_dir("report")

    header = (
        f"<!-- 报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} -->\n\n"
    )
    output_path = output_dir / "report.md"
    output_path.write_text(header + report_markdown, encoding="utf-8")
    return str(output_path)


def _slugify(text: str, max_len: int = 40) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip())
    value = re.sub(r"_+", "_", value).strip("_")
    return (value or "report")[:max_len]
