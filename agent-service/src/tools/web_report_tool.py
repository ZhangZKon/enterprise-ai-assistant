from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from src import config
from src.schemas import ToolResult


# ── Redis 结果缓存 ──────────────────────────────────────────────
# 报告按（归一化主题 + 报告类型 + 时间范围 + 关键词）缓存到 Redis（与 rag-local 共用
# rag-redis 实例）。归一化去掉语气词/虚词，让"劳动法关于请假制度的规定"和
# "劳动法请假制度规定"这类近似主题命中同一份缓存，缓解 LLM 输出不一致导致的低命中。
_TOPIC_NOISE = re.compile(
    r"[\s，。！？、；：""''（）()\[\]【】·…—\-]"
    r"|的|了|吗|呢|吧|请问|关于|相关|情况|内容|目前|现在"
    r"|什么|如何|怎样|怎么|哪些|有没有|是否|一些|这个|那个|介绍|和|及|与"
)


def _normalize_topic(text: str) -> str:
    """归一化主题：去标点/语气词/虚词，保留实词。"""
    return _TOPIC_NOISE.sub("", text or "")


def _cache_key(topic: str, report_type: str, time_range: str, keywords: str) -> str:
    """对缓存key进行统一的归一化处理"""
    raw = "|".join([
        _normalize_topic(topic),
        _normalize_topic(report_type),
        _normalize_topic(time_range),
        _normalize_topic(keywords),
    ])
    return "web_report:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _redis_client():
    try:
        import redis
        return redis.Redis.from_url(config.REDIS_URL, decode_responses=True)
    except Exception:
        return None


def _cache_get(key: str) -> dict | None:
    """读缓存；Redis 不可用时静默降级为 None（不影响功能）。"""
    try:
        client = _redis_client()
        if client is None:
            return None
        value = client.get(key)
        return json.loads(value) if value else None
    except Exception:
        return None


def _cache_set(key: str, data: dict) -> None:
    """写缓存（带 TTL）；Redis 不可用时静默跳过。"""
    try:
        client = _redis_client()
        if client is None:
            return
        client.set(key, json.dumps(data, ensure_ascii=False), ex=config.WEB_REPORT_CACHE_TTL)
    except Exception:
        pass


def _answer_from_preview(report_preview: str) -> str:
    """answer 字段摘要：取报告正文前 300 字符（去 HTML 注释头）。"""
    preview_text = re.sub(r"<!--.*?-->", "", report_preview, flags=re.S).strip()
    if not preview_text:
        return "网络调研报告已生成"
    return (preview_text[:300].strip() + "…" if len(preview_text) > 300 else preview_text)


def run(
    topic: str,
    report_type: str = "综述报告",
    time_range: str = "past_month",
    keywords: str = "",
) -> dict:
    cache_key = _cache_key(topic, report_type, time_range, keywords)
    cached = _cache_get(cache_key)
    if cached:
        preview = cached.get("report_preview", "")
        return ToolResult(
            success=True,
            answer=_answer_from_preview(preview),
            data={
                "tool": "web_report",
                "topic": topic,
                "report_type": report_type,
                "time_range": time_range,
                "keywords": keywords,
                "cache_hit": True,
                **cached,
            },
        ).to_dict()

    project_dir = config.WEB_REPORT_PROJECT_DIR
    outputs_dir = config.WEB_REPORT_OUTPUT_DIR
    before = _latest_output_dir(outputs_dir)

    command = [
        str(config.WEB_REPORT_PYTHON),
        str(project_dir / "main.py"),
        "--topic",
        topic,
        "--report-type",
        report_type,
    ]
    if time_range:
        command.extend(["--time-range", time_range])
    if keywords:
        command.extend(["--keywords", keywords])

    try:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = str(project_dir)
        env["WEB_REPORT_OUTPUT_DIR"] = str(config.WEB_REPORT_OUTPUT_DIR)
        for proxy_key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            env.pop(proxy_key, None)
        # 剥离本服务的 LLM 环境变量：web-report-skill 有独立的 .env 配置，
        # 否则 load_dotenv 不会覆盖继承过来的变量，会出现"智谱端点 + qwen 模型名"的 400。
        for llm_key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
            env.pop(llm_key, None)
        completed = subprocess.run(
            command,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=config.WEB_REPORT_TIMEOUT,
        )
        if completed.returncode != 0:
            # 附带 stderr 尾段，便于定位失败根因（如内部 LLM 429）
            stderr_tail = (completed.stderr or "")[-300:].strip()
            return ToolResult(
                success=False,
                answer="网络报告生成失败",
                data={"stdout": completed.stdout[-2000:], "stderr": completed.stderr[-2000:]},
                error=f"web-report-skill exited with code {completed.returncode}: {stderr_tail}",
            ).to_dict()

        output_dir = _latest_output_dir(outputs_dir)
        if output_dir is None or output_dir == before:
            # 子进程声称成功但没有生成新的报告目录：绝不 fallback 到旧报告
            # （那会把上一次的无关内容当成本次结果，比失败更危险——fail-closed）。
            return ToolResult(
                success=False,
                answer="",
                data={"stdout": completed.stdout[-2000:], "stderr": completed.stderr[-2000:]},
                error="web-report-skill 未生成新的报告输出目录",
            ).to_dict()

        report_path = output_dir / "report.md"
        if not report_path.exists():
            return ToolResult(
                success=False,
                answer="",
                data={"stdout": completed.stdout[-2000:], "stderr": completed.stderr[-2000:]},
                error="web-report-skill 报告文件缺失",
            ).to_dict()
        evidence_path = output_dir / "evidence_list.md"
        report_preview = _read_text_preview(report_path, max_chars=5000)

        cache_payload = {
            "output_dir": str(output_dir) if output_dir else "",
            "report_path": str(report_path) if report_path and report_path.exists() else "",
            "evidence_path": str(evidence_path) if evidence_path and evidence_path.exists() else "",
            "report_preview": report_preview,
        }
        _cache_set(cache_key, cache_payload)

        return ToolResult(
            success=True,
            answer=_answer_from_preview(report_preview),
            data={
                "tool": "web_report",
                "topic": topic,
                "report_type": report_type,
                "time_range": time_range,
                "keywords": keywords,
                "cache_hit": False,
                **cache_payload,
            },
        ).to_dict()
    except Exception as exc:
        return ToolResult(False, "", error=f"web_report call failed: {exc}").to_dict()


def _latest_output_dir(outputs_dir: Path) -> Path | None:
    if not outputs_dir.exists():
        return None
    dirs = [p for p in outputs_dir.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def _read_text_preview(path: Path | None, max_chars: int = 5000) -> str:
    if not path or not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception:
        return ""
