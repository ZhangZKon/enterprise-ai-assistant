from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.agent import run_agent


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentChatRequest(BaseModel):
    message: str
    role: str = "user"
    bypass_cache: bool = False
    conversation_id: str | None = None


class AgentChatResponse(BaseModel):
    answer: str
    tool: str = ""
    tool_call: dict | None = None
    tool_result: dict | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/agent/chat", response_model=AgentChatResponse)
def agent_chat(request: AgentChatRequest) -> dict:
    logger.info(
        "POST /agent/chat role=%s message_chars=%d message=%r",
        request.role,
        len(request.message),
        request.message[:120],
    )
    return run_agent(
        request.message,
        role=request.role,
        bypass_cache=request.bypass_cache,
        conversation_id=request.conversation_id,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
