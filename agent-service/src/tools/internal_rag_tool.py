from __future__ import annotations

import json
import urllib.error
import urllib.request

from src import config
from src.schemas import ToolResult


def run(
    question: str,
    role: str = "user",
    collection_name: str | None = None,
    bypass_cache: bool = False,
    conversation_id: str | None = None,
) -> dict:
    payload = {
        "query": question,
        "collection_name": collection_name or config.RAG_COLLECTION_NAME,
        "bypass_cache": bypass_cache,
        "role": role if role in ("admin", "user") else "user",
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id

    url = f"{config.RAG_BASE_URL}{config.RAG_STREAM_PATH}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
        data = _parse_sse_response(raw)
        return ToolResult(
            success=not bool(data.get("error")),
            answer=data.get("answer", ""),
            data={
                "sources": data.get("sources", []),
                "metrics": data.get("metrics", {}),
                "tool": "internal_rag_query",
            },
            error=data.get("error", ""),
        ).to_dict()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return ToolResult(False, "", error=f"RAG HTTP {exc.code}: {detail}").to_dict()
    except Exception as exc:
        return ToolResult(False, "", error=f"RAG call failed: {exc}").to_dict()


def _parse_sse_response(raw: str) -> dict:
    answer_parts: list[str] = []
    sources = []
    metrics = {}
    error = ""

    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue

        payload_text = line[len("data:"):].strip()
        if not payload_text:
            continue

        try:
            event = json.loads(payload_text)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")
        data = event.get("data")

        if event_type == "token" and data:
            answer_parts.append(str(data))
        elif event_type == "sources":
            sources = data or []
        elif event_type == "done":
            metrics = (data or {}).get("metrics", {})
        elif event_type == "error":
            error = str(data or "RAG stream error")

    return {
        "answer": "".join(answer_parts),
        "sources": sources,
        "metrics": metrics,
        "error": error,
    }
