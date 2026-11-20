from __future__ import annotations

from typing import Any, Callable

from src.tools import internal_rag_tool, web_report_tool


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "internal_rag_query",
            "description": "Query internal enterprise RAG, SQL, personnel, and document knowledge.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The user's original internal knowledge question.",
                    },
                    "role": {
                        "type": "string",
                        "enum": ["user", "admin"],
                        "description": "User role used by internal permission logic.",
                    },
                    "collection_name": {
                        "type": "string",
                        "description": "RAG collection name. Defaults to rag.",
                    },
                    "bypass_cache": {
                        "type": "boolean",
                        "description": "Whether to bypass RAG cache.",
                    },
                    "conversation_id": {
                        "type": "string",
                        "description": "Optional conversation id for multi-turn RAG.",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_report",
            "description": "Generate a web research report using Tavily search/extract and LLM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Report topic.",
                    },
                    "report_type": {
                        "type": "string",
                        "description": "Report type, for example 综述报告, 数据调研, 竞品分析.",
                    },
                    "time_range": {
                        "type": "string",
                        "description": "Search time range, for example past_week, past_month, past_year.",
                    },
                    "keywords": {
                        "type": "string",
                        "description": "Optional comma-separated search keywords.",
                    },
                },
                "required": ["topic"],
            },
        },
    },
]


TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "internal_rag_query": internal_rag_tool.run,
    "web_report": web_report_tool.run,
}


# ── 执行管线钩子 ──────────────────────────────────────────────
# 借鉴 dsh tools 管线（pre-execute → execute → post-execute）的思路，
# 用最轻量的钩子列表实现：
#   PRE_HOOKS  执行前按序运行，可修改 arguments（补参、校验、脱敏前处理）；
#   POST_HOOKS 执行后按序运行，可改写 result（记录、包装）。
# 钩子返回新值表示"已修改"，返回 None 表示不修改。
# 新增横切能力（权限、脱敏、日志、超时……）时只需往列表里加一个
# 普通函数，不需要改 call_tool 本身。


def _normalize_string_arguments(
    name: str,
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """pre-execute 钩子：归一化工具参数的类型（LLM 自由 JSON 的格式漂移防御）。

    planner/evaluator 输出的 arguments 不经过 schema 校验，字符串参数可能被
    写成数组（如 keywords: ["华为","招聘"]）或 null。这里统一转回字符串：
    list/tuple → 逗号连接；None → 移除；其他 → str。
    """
    string_keys = ("question", "topic", "report_type", "time_range", "keywords",
                   "collection_name", "role")
    changed = False
    for key in string_keys:
        if key not in arguments:
            continue
        value = arguments[key]
        if isinstance(value, str):
            continue
        if value is None:
            del arguments[key]
        elif isinstance(value, (list, tuple)):
            arguments[key] = ",".join(str(item) for item in value)
        else:
            arguments[key] = str(value)
        changed = True
    return arguments if changed else None


def _inject_context_arguments(
    name: str,
    arguments: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """pre-execute 钩子：补齐调用方运行时上下文参数。

    原 agent.py / orchestrator.py 里重复的 internal_rag_query 参数补充
    逻辑收口到这里，两个调用路径行为保持一致。
    """
    if name != "internal_rag_query" or not context:
        return None
    changed = False
    if context.get("question") and "question" not in arguments:
        arguments["question"] = context["question"]
        changed = True
    if context.get("role") and "role" not in arguments:
        arguments["role"] = context["role"]
        changed = True
    if context.get("bypass_cache") is not None:
        arguments["bypass_cache"] = context["bypass_cache"]
        changed = True
    if context.get("conversation_id"):
        arguments["conversation_id"] = context["conversation_id"]
        changed = True
    return arguments if changed else None


PRE_HOOKS: list[Callable[[str, dict[str, Any], dict[str, Any] | None], dict[str, Any] | None]] = [
    _normalize_string_arguments,
    _inject_context_arguments,
]

POST_HOOKS: list[Callable[[str, dict[str, Any], dict[str, Any] | None, dict[str, Any]], dict[str, Any] | None]] = [
    # 示例：def _log_result(name, arguments, context, result): ...
]


def sanitize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """返回脱敏展示副本（key/token/password 字段替换为 ***）。

    用于日志与前端展示，不修改执行参数本身。
    """
    safe = dict(arguments)
    for key in list(safe):
        if "key" in key.lower() or "token" in key.lower() or "password" in key.lower():
            safe[key] = "***"
    return safe


def call_tool(
    name: str,
    arguments: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行一次工具调用，走 pre → handler → post 钩子管线。

    :param name: 工具名（须在 TOOL_HANDLERS 中）。
    :param arguments: 工具参数（pre 钩子可能就地补齐）。
    :param context: 调用方运行时上下文（question/role/bypass_cache/
        conversation_id 等），供 pre 钩子补齐参数使用；可选。
    """

    # 预处理阶段，顺序执行pre_hooks内部的所有函数
    for hook in PRE_HOOKS:
        updated = hook(name, arguments, context)
        if updated is not None:
            arguments = updated

    # 调用工具，执行业务
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        result: dict[str, Any] = {
            "success": False,
            "answer": "",
            "data": {},
            "error": f"Unknown tool: {name}",
        }
    else:
        result = handler(**arguments)

    # 后处理阶段，按顺序执行 post_hooks 内的函数，目前待开发
    for hook in POST_HOOKS:
        updated = hook(name, arguments, context, result)
        if updated is not None:
            result = updated
    return result
