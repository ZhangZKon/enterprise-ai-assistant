from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    success: bool
    answer: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "answer": self.answer,
            "data": self.data,
            "error": self.error,
        }


@dataclass
class AgentRunState:
    original_message: str
    role: str = "user"
    bypass_cache: bool = False
    conversation_id: str | None = None
    intent: str = ""
    plan: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    iteration: int = 0
    max_iterations: int = 2
    # 有序执行轨迹（plan / tool/call / tool/result / evaluate / rewrite / final），
    # 供人机 QA 复盘与前端展示；请求结束落盘为 JSONL。
    events: list[dict[str, Any]] = field(default_factory=list)
