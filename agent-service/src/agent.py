from __future__ import annotations

import logging

from src.llm_client import direct_answer, request_tool_call, summarize_tool_result
from src.orchestrator import run_orchestrated_agent
from src.tool_registry import call_tool


logger = logging.getLogger(__name__)


def run_agent(
    message: str,
    role: str = "user",
    bypass_cache: bool = False,
    conversation_id: str | None = None,
) -> dict:
    # 改为使用orchestrat多轮agent
    return run_orchestrated_agent(
        message,
        role=role,
        bypass_cache=bypass_cache,
        conversation_id=conversation_id,
    )

# 废弃方案，暂时没有调用
def run_single_step_agent(
    message: str,
    role: str = "user",
    bypass_cache: bool = False,
    conversation_id: str | None = None,
) -> dict:

    # 根据query判断调用哪个工具，以及根据schemas返回 tool call 参数
    tool_call, messages, assistant_message = request_tool_call(message, role=role)

    # 如果判断不需要调用工具，则返回LLM原始回答
    if tool_call is None:
        logger.info("agent.no_tool content_chars=%d", len(assistant_message.content or ""))
        answer = assistant_message.content or direct_answer(message, role=role)
        return {
            "answer": answer,
            "tool": "",
            "tool_call": None,
            "tool_result": None,
        }

    arguments = dict(tool_call["arguments"])

    # 调用工具（question/role/bypass_cache/conversation_id 等上下文参数
    # 调用相关工具
    tool_result = call_tool(
        tool_call["name"],
        arguments,
        context={
            "question": message,
            "role": role,
            "bypass_cache": bypass_cache,
            "conversation_id": conversation_id,
        },
    )
    logger.info(
        "agent.tool_result name=%s success=%s answer_chars=%d error=%r",
        tool_call["name"],
        tool_result.get("success"),
        len(tool_result.get("answer") or ""),
        (tool_result.get("error") or "")[:200],
    )

    # 再次调用LLM进行汇总结果
    answer = summarize_tool_result(
        original_message=message,
        messages=messages,
        assistant_message=assistant_message,
        tool_call=tool_call,
        tool_result=tool_result,
    )
    logger.info("agent.final_answer tool=%s chars=%d", tool_call["name"], len(answer))

    return {
        "answer": answer,
        "tool": tool_call["name"],
        "tool_call": {
            "name": tool_call["name"],
            "arguments": arguments,
        },
        "tool_result": tool_result,
    }
