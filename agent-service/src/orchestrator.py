from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any

from src import config
from src.llm_client import (
    direct_answer,
    evaluate_agent_progress,
    plan_agent_steps,
    synthesize_agent_answer,
)
from src.schemas import AgentRunState
from src.tool_registry import call_tool, sanitize_arguments


logger = logging.getLogger(__name__)


def run_orchestrated_agent(
    message: str,
    role: str = "user",
    bypass_cache: bool = False,
    conversation_id: str | None = None,
    max_iterations: int = 2,
) -> dict[str, Any]:
    state = AgentRunState(
        original_message=message,
        role=role,
        bypass_cache=bypass_cache,
        conversation_id=conversation_id,
        max_iterations=max_iterations,
    )

    try:
        # 根据query制定完整计划，包换step，tool的名词等
        plan = plan_agent_steps(message, role=role)
        state.intent = str(plan.get("intent") or "")
        # 数据清洗与标准化
        state.plan = _normalize_plan_steps(plan)
        _log(state, "plan", intent=state.intent, steps=state.plan)
        logger.info("orchestrator.plan intent=%s steps=%d", state.intent, len(state.plan))

        if plan.get("needs_clarification") or state.intent == "clarification":
            answer = str(plan.get("clarification_question") or "请补充你想查询的主题、范围或对象。")
            state.final_answer = answer
            _log(state, "clarify", answer_chars=len(answer))
            return _response_from_state(state, tool="")
        if state.intent == "direct_answer" or not state.plan:
            answer = direct_answer(message, role=role)
            state.final_answer = answer
            _log(state, "final", answer_chars=len(answer))
            return _response_from_state(state, tool="")

        # 执行完所有的plans
        _execute_plan_steps(state, state.plan)
        # 防空转：记住上一次实际执行的调用指纹（plan 的最后一步），
        # 若重写后的调用与它相同，说明重写无进展，直接停止迭代。
        last_fingerprint = _step_fingerprint(state.plan[-1]) if state.plan else None

        # 对第一轮执行的结果进行评估和重写
        # iteration 语义 = 已执行的评估次数（plan 初始执行不计数）
        while state.iteration < state.max_iterations:
            # 评估agent
            evaluation = evaluate_agent_progress(
                original_message=state.original_message,
                tool_results=state.tool_results,
                iteration=state.iteration,
                max_iterations=state.max_iterations,
            )
            state.iteration += 1
            state.evaluations.append(evaluation)
            _log(
                state,
                "evaluate",
                iteration=state.iteration,
                sufficient=bool(evaluation.get("sufficient")),
                next_action=str(evaluation.get("next_action") or ""),
                reason=str(evaluation.get("reason") or "")[:300],
            )
            logger.info(
                "orchestrator.evaluation sufficient=%s next_action=%s next_tool=%s",
                evaluation.get("sufficient"),
                evaluation.get("next_action"),
                evaluation.get("next_tool"),
            )

            if evaluation.get("needs_clarification") or evaluation.get("next_action") == "clarify":
                state.final_answer = str(
                    evaluation.get("reason") or "当前问题还缺少必要信息，请补充后我再继续查询。"
                )
                _log(state, "clarify", answer_chars=len(state.final_answer))
                return _response_from_state(state, tool=_tool_label(state))

            if evaluation.get("sufficient") or evaluation.get("next_action") == "final":
                # 评估-回答一体：evaluator 直接给出最终回答（为空时由循环外兜底合成）
                state.final_answer = str(evaluation.get("final_answer") or "").strip()
                break

            if evaluation.get("next_action") != "rewrite_and_call_tool":
                break

            # 决策一体：重写参数由 evaluator 直接给出，不再单独调用 rewriter
            step = _normalize_step(
                {
                    "tool": str(evaluation.get("next_tool") or ""),
                    "arguments": dict(evaluation.get("next_arguments") or {}),
                }
            )
            if not step:
                break
            _log(
                state,
                "rewrite",
                tool=step["tool"],
                arguments=sanitize_arguments(dict(step.get("arguments") or {})),
                reason=str(evaluation.get("reason") or "")[:300],
            )
            fingerprint = _step_fingerprint(step)
            if last_fingerprint is not None and fingerprint == last_fingerprint:
                logger.info(
                    "orchestrator.no_progress duplicate_call tool=%s arguments=%s stopping",
                    step["tool"],
                    fingerprint[1][:200],
                )
                _log(state, "no_progress", tool=step["tool"], reason="rewrite produced the same call as the last executed step")
                break
            last_fingerprint = fingerprint
            _execute_plan_steps(state, [step])

        # 汇总（仅当评估未直接产出最终回答时兜底合成）
        if not state.final_answer:
            state.final_answer = synthesize_agent_answer(
                original_message=state.original_message,
                plan=plan,
                tool_calls=state.tool_calls,
                tool_results=state.tool_results,
                evaluations=state.evaluations,
            )
        _log(state, "final", answer_chars=len(state.final_answer))
        return _response_from_state(state, tool=_tool_label(state))
    except Exception as exc:
        # LLM 调用失败（限流 429 / 超时等）：不抛 500，降级为可用结果或友好提示。
        # 附带 API 响应体（429 时智谱会返回具体限流/额度信息），便于定位根因。
        api_detail = ""
        response = getattr(exc, "response", None)
        if response is not None:
            api_detail = str(getattr(response, "text", "") or "")[:300]
        logger.error(
            "orchestrator.llm_or_tool_failed error=%r api_detail=%s",
            exc, api_detail, exc_info=True,
        )
        state.final_answer = _degraded_answer(state)
        _log(state, "degraded", reason=f"{str(exc)[:120]} {api_detail[:120]}")
        return _response_from_state(state, tool=_tool_label(state))
    finally:
        # 无论哪个分支返回，都把执行轨迹落盘为 JSONL（人机 QA 复盘用）
        log_path = _write_event_log(state)
        if log_path is not None:
            logger.info("orchestrator.event_log path=%s events=%d", log_path, len(state.events))


def _execute_plan_steps(state: AgentRunState, steps: list[dict[str, Any]]) -> None:

    for step in steps:
        tool_name = str(step.get("tool") or "")
        arguments = dict(step.get("arguments") or {})
        if tool_name not in ("internal_rag_query", "web_report"):
            continue

        tool_call = {"name": tool_name, "arguments": arguments, "iteration": state.iteration}
        state.tool_calls.append(tool_call)
        _log(state, "tool/call", tool=tool_name, arguments=sanitize_arguments(arguments))
        # question/role/bypass_cache/conversation_id 等上下文参数由
        # tool_registry 的 pre 钩子统一补齐
        tool_result = call_tool(
            tool_name,
            arguments,
            context={
                "question": state.original_message,
                "role": state.role,
                "bypass_cache": state.bypass_cache,
                "conversation_id": state.conversation_id,
            },
        )
        _log(
            state,
            "tool/result",
            tool=tool_name,
            success=bool(tool_result.get("success")),
            answer_chars=len(tool_result.get("answer") or ""),
            error=(tool_result.get("error") or "")[:200],
        )
        # 收集tool返回的结果
        state.tool_results.append(
            {
                "tool": tool_name,
                "arguments": arguments,
                "result": tool_result,
                "iteration": state.iteration,
            }
        )
        logger.info(
            "orchestrator.tool_result name=%s success=%s answer_chars=%d error=%r",
            tool_name,
            tool_result.get("success"),
            len(tool_result.get("answer") or ""),
            (tool_result.get("error") or "")[:200],
        )


def _log(state: AgentRunState, event_type: str, **payload: Any) -> None:
    """追加一条有序执行轨迹事件（模仿 dsh session 的 append-only 事件日志）。"""
    state.events.append({"type": event_type, **payload})


def _canonicalize(value: Any) -> Any:
    """深度 key 排序，使键顺序不影响指纹（模仿 dsh repeat-tool-reminder 的 canonicalize）。"""
    if isinstance(value, dict):
        return {k: _canonicalize(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canonicalize(v) for v in value]
    return value


def _step_fingerprint(step: dict[str, Any]) -> tuple[str, str]:
    """一次工具调用的判同指纹：(工具名, 深度排序后的参数 JSON)。"""
    tool_name = str(step.get("tool") or "")
    arguments = _canonicalize(dict(step.get("arguments") or {}))
    return (tool_name, json.dumps(arguments, ensure_ascii=False, sort_keys=True))


def _write_event_log(state: AgentRunState) -> str | None:
    """把执行轨迹落盘为 JSONL；目录可经 .env 的 EVENT_LOG_DIR 配置。"""
    if not state.events:
        return None
    log_dir = config.EVENT_LOG_DIR
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        logger.warning("orchestrator.event_log mkdir failed dir=%s error=%r", log_dir, error)
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = re.sub(r"[^0-9A-Za-z_-]", "_", state.conversation_id or "")[:40]
    if not suffix:
        suffix = hashlib.md5(state.original_message.encode("utf-8")).hexdigest()[:8]
    path = log_dir / f"agent-{timestamp}-{suffix}.jsonl"
    try:
        with path.open("w", encoding="utf-8") as handle:
            for event in state.events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as error:
        logger.warning("orchestrator.event_log write failed path=%s error=%r", path, error)
        return None
    return str(path)


def _normalize_plan_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = plan.get("steps") or []
    if not isinstance(raw_steps, list):
        return []
    steps = []
    for raw_step in raw_steps:
        step = _normalize_step(raw_step)
        if step:
            steps.append(step)
    return steps


def _normalize_step(raw_step: Any) -> dict[str, Any] | None:
    if not isinstance(raw_step, dict):
        return None
    tool_name = str(raw_step.get("tool") or "")
    if tool_name not in ("internal_rag_query", "web_report"):
        return None
    arguments = raw_step.get("arguments") or {}
    if not isinstance(arguments, dict):
        arguments = {}
    return {"tool": tool_name, "arguments": arguments}


def _tool_label(state: AgentRunState) -> str:
    names = []
    for tool_call in state.tool_calls:
        name = tool_call.get("name")
        if name and name not in names:
            names.append(name)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return "multi"


def _degraded_answer(state: AgentRunState) -> str:
    """LLM 调用失败（限流/超时）时的降级回答：有工具结果就尽力呈现，否则提示重试。"""
    parts = []
    for item in state.tool_results:
        answer = str((item.get("result") or {}).get("answer") or "").strip()
        if answer:
            parts.append(answer)
    if parts:
        return "\n\n".join(parts) + "\n\n（注：本次回答在生成总结时遇到服务繁忙，以上为直接返回的工具结果，请稍后重试完整版。）"
    return "抱歉，服务暂时繁忙（模型调用失败），请稍后重试。"


def _response_from_state(state: AgentRunState, tool: str) -> dict[str, Any]:
    last_call = state.tool_calls[-1] if state.tool_calls else None
    last_result = state.tool_results[-1]["result"] if state.tool_results else None
    if len(state.tool_results) > 1:
        last_result = {
            "success": all(item["result"].get("success") for item in state.tool_results),
            "answer": state.final_answer,
            "data": {
                "tool_results": state.tool_results,
                "evaluations": state.evaluations,
                "intent": state.intent,
                "events": state.events,
            },
            "error": "",
        }
    return {
        "answer": state.final_answer,
        "tool": tool,
        "tool_call": last_call,
        "tool_result": last_result,
    }
