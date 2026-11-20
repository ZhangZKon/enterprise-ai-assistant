import hashlib
import json
import os

import redis.asyncio as redis

CACHE_TTL_SECONDS = 24 * 60 * 60

class QACacheService:
    def __init__(self):
        redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
        self.client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_keepalive=True,
            retry_on_timeout=True,
            retry_on_error=[ConnectionError],
            health_check_interval=30,
        )

    @staticmethod
    def normalize_question(question: str) -> str:
        return " ".join(question.strip().lower().split())

    # 标准化Question作为检索Key
    def build_key(self, question: str) -> str:
        normalized = self.normalize_question(question)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"qa:{digest}"

    # 在Redis中查询问题，并返回
    async def get(self, question: str) -> dict | None:
        raw  = await self.client.get(self.build_key(question))
        if raw is None:
            return None
        else:
            return json.loads(raw)

    # 把内容存进Redis
    async def set(self, question: str, answer: str, sources: list) -> None:
        payload = {
            "question": self.normalize_question(question),
            "answer": answer,
            "sources": sources,
        }
        await self.client.set(
            self.build_key(question),
            json.dumps(payload, ensure_ascii=False),
            ex=CACHE_TTL_SECONDS
        )

qa_cache_service = QACacheService()
