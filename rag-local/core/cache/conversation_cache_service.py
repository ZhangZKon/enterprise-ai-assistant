import json
import re
from typing import Any

from core.cache.qa_cache_service import CACHE_TTL_SECONDS, qa_cache_service
from core.llm_service import llm_service

# 保留最近2轮QA原文
MAX_RECENT_TURNS = 2
_CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class ConversationCacheService:
    def __init__(self):
        self.client = qa_cache_service.client

    @staticmethod
    def build_key(conversation_id: str) -> str:
        if not _CONVERSATION_ID_RE.fullmatch(conversation_id):
            raise ValueError("Invalid conversation_id")
        return f"conversation:{conversation_id}"

    async def get_state(self, conversation_id: str) -> dict[str, Any]:
        """ 查询历史对话总结和最近的QA内容 """
        raw = await self.client.get(self.build_key(conversation_id))
        if raw is None:
            return {
                "summary": "",
                "recent_turns": [],
                "turn_count": 0,
            }

        payload = json.loads(raw)
        return {
            "summary": payload.get("summary", ""),
            "recent_turns": payload.get("recent_turns", []),
            "turn_count": payload.get("turn_count", 0),
        }

    async def has_history(self, conversation_id: str) -> bool:
        """ 判断是否有历史记录 """
        state = await self.get_state(conversation_id)
        return bool(state["summary"] or state["recent_turns"])

    async def append_turn(
            self,
            conversation_id: str,
            user: str,
            assistant: str ) -> dict[str, Any]:
        """ 保留最近两轮原文和压缩摘要 """
        state = await self.get_state(conversation_id)

        all_recent = [
            *state["recent_turns"],
            {"user": user, "assistant": assistant},
        ]
        summary = state["summary"]

        # 溢出的较早轮次压缩到长期摘要，只留下最后两轮原文。
        if len(all_recent) > MAX_RECENT_TURNS:
            turns_to_summarize = all_recent[:-MAX_RECENT_TURNS]
            summary = await llm_service.summarize_turns(
                existing_summary=summary,
                turns=turns_to_summarize,
            )
            all_recent = all_recent[-MAX_RECENT_TURNS:]

        new_state = {
            "summary": summary,
            "recent_turns": all_recent,
            "turn_count": state["turn_count"] + 1,
        }

        await self.client.set(
            self.build_key(conversation_id),
            json.dumps(new_state, ensure_ascii=False),
            ex=CACHE_TTL_SECONDS,
        )
        return new_state


conversation_cache_service = ConversationCacheService()
