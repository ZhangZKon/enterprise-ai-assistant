from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import OpenAI

from src import config
from src.prompt_registry import registry
from src.tool_registry import TOOL_SCHEMAS


logger = logging.getLogger(__name__)


def _client() -> OpenAI:
    config.validate_llm_config()
    # max_retries 调高：429 限流是间歇性的，多退避重试几次能扛过短时窗口
    return OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
        max_retries=4,
    )


def load_system_prompt() -> str:
    return registry.render("system")


def _repair_json_text(text: str) -> str:
    """修复 LLM 输出 JSON 的高频笔误（仅做保守的模式替换）。

    1. 数组元素前多余的引号：`},"{` → `},{`、`},"[` → `},[`
       （模型常在对象/数组元素之间多写一个引号，如 `}},"{"tool"...`）
    2. 尾逗号：`{...,}` / `[...,]` → 去掉逗号
    修复失败仍由调用方走 fail-closed 降级。
    """
    repaired = text.replace('},"{', '},{').replace('},"[', '},[')
    return re.sub(r",\s*([}\]])", r"\1", repaired)


def _json_from_response(content: str, fallback: dict[str, Any], owner: str = "llm") -> dict[str, Any]:
    """解析 LLM 输出为 JSON dict；先直接解析，失败后尝试轻量修复，仍失败
    记录警告并返回 fallback（fail-closed 由各 fallback 保证）。

    :param owner: 调用方标识（planner/evaluator/rewriter），用于日志归因。
    """
    text = (content or "").strip()
    if not text:
        logger.warning("llm_client.json_empty owner=%s fallback=%r", owner, fallback)
        return fallback
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        repaired = _repair_json_text(text)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            logger.warning("llm_client.json_parse_failed owner=%s text=%r", owner, text[:300])
            return fallback
        logger.warning("llm_client.json_repaired owner=%s text=%r", owner, text[:300])
    if not isinstance(data, dict):
        logger.warning("llm_client.json_not_object owner=%s text=%r", owner, text[:300])
        return fallback
    return data


def plan_agent_steps(message: str, role: str = "user") -> dict[str, Any]:
    # fail-closed：规划输出解析失败时不默认直接回答（那会跳过工具调用），
    # 而是进入澄清分支，请用户补充信息。
    fallback = {
        "intent": "clarification",
        "needs_clarification": True,
        "clarification_question": "我暂时无法理解你的问题，请补充你想查询的主题、范围或对象。",
        "steps": [],
        "reason": "planner output parse failed",
    }
    response = _client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": registry.render("planner"),
            },
            {"role": "user", "content": f"用户角色：{role}\n用户问题：{message}"},
        ],
        temperature=0.1,
    )
    return _json_from_response(response.choices[0].message.content or "", fallback, owner="planner")


def evaluate_agent_progress(
    original_message: str,
    tool_results: list[dict[str, Any]],
    iteration: int,
    max_iterations: int,
) -> dict[str, Any]:
    # fail-closed：评估输出解析失败时绝不默认"答案足够"放行，
    # 而是进入 clarify 分支请用户确认/补充。
    fallback = {
        "sufficient": False,
        "needs_clarification": True,
        "next_action": "clarify",
        "next_tool": "",
        "next_arguments": {},
        "final_answer": "",
        "reason": "评估结果解析失败，暂时无法确认是否已回答，请补充或换一种问法。",
    }
    response = _client().chat.completions.create(
        model=config.EVALUATOR_MODEL,
        messages=[
            {
                "role": "system",
                "content": registry.render("evaluator"),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "original_message": original_message,
                        "iteration": iteration,
                        "max_iterations": max_iterations,
                        "tool_results": tool_results,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        temperature=0.1,
    )
    return _json_from_response(response.choices[0].message.content or "", fallback, owner="evaluator")


def synthesize_agent_answer(
    original_message: str,
    plan: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
) -> str:
    response = _client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": registry.render("synthesizer"),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "original_message": original_message,
                        "plan": plan,
                        "tool_calls": tool_calls,
                        "tool_results": tool_results,
                        "evaluations": evaluations,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


def request_tool_call(message: str, role: str = "user") -> tuple[dict[str, Any] | None, list[dict[str, Any]], Any]:
    """
    根据query判断调用哪个工具，以及根据schemas返回 tool call 参数
    :param message:
    :param role:
    :return:
    """


    messages = [
        {"role": "system", "content": load_system_prompt()},
        {"role": "user", "content": f"用户角色：{role}\n用户问题：{message}"},
    ]

    # 输入用户query和工具列表 TOOL_SCHEMAS，让LLM自己选择是否调用工具
    response = _client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        tools=TOOL_SCHEMAS,
        tool_choice="auto", # 可以自行选择是否调用tool
        temperature=0.1,
    )

    # 如果LLM判断调用工具，则读取模型返回的标准 tool_calls 字段
    assistant_message = response.choices[0].message
    tool_calls = assistant_message.tool_calls or []
    if not tool_calls:
        return None, messages, assistant_message

    first_call = tool_calls[0]
    try:
        arguments = json.loads(first_call.function.arguments or "{}")
    except json.JSONDecodeError:
        arguments = {}

    return (
        {
            "id": first_call.id,
            "name": first_call.function.name,   # 返回工具名
            "arguments": arguments,             # 返回工具参数
        },
        messages,
        assistant_message,
    )


def summarize_tool_result(
    original_message: str,
    messages: list[dict[str, Any]],
    assistant_message: Any,
    tool_call: dict[str, Any],
    tool_result: dict[str, Any],
) -> str:
    """ 调用LLM来汇总tools返回的结果，生成最终的回答 """

    final_messages = list(messages)
    final_messages.append(assistant_message)
    final_messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "name": tool_call["name"],
            "content": json.dumps(tool_result, ensure_ascii=False),
        }
    )
    final_messages.append(
        {
            "role": "user",
            "content": registry.render("finalizer", original_message=original_message),
        }
    )

    response = _client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=final_messages,
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


def direct_answer(message: str, role: str = "user") -> str:
    response = _client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": registry.render("direct")},
            {"role": "user", "content": f"用户角色：{role}\n用户问题：{message}"},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""
