# api/chat.py
import logging
import time
import asyncio
import json

import numpy as np

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict

from core.retriever_service import KnowledgeBaseRetriever
from core.llm_service import llm_service
from core.cache.qa_cache_service import qa_cache_service
from core.cache.conversation_cache_service import conversation_cache_service
from core.personnel_dsl import generate_dsl, execute_personnel_dsl, format_personnel_dsl_answer, validate_name_and_fallback
logger = logging.getLogger(__name__)


router = APIRouter()
ENABLE_QUERY_REWRITE = False


# 复用检索请求模型
class ChatRequest(BaseModel):
    query: str
    collection_name: Optional[str]="rag"
    # 是否跳过缓存
    bypass_cache: Optional[bool] = False
    conversation_id: Optional[str] = None
    role: str = "user"  # "admin" | "user"，演示级角色参数


class ChatResponse(BaseModel):
    success: bool
    answer: str
    sources: List[Dict]
    message: str


def _preview(text: str, limit: int = 180) -> str:
    """截取文本前 limit 个字符作为预览，去除多余空白。"""
    return " ".join(text.split())[:limit]


# 初始化检索器——懒加载，避免 API Key 缺失时阻止服务启动
_sync_retriever = None

def _get_sync_retriever() -> KnowledgeBaseRetriever:
    global _sync_retriever
    if _sync_retriever is None:
        _sync_retriever = KnowledgeBaseRetriever(
            collection_name="rag",
            k=5,
            rerank_top_n=3,
            hybrid_alpha=0.7
        )
    return _sync_retriever


@router.post("/", response_model=ChatResponse)
async def chat_with_rag(request: ChatRequest):
    """智能问答接口：检索+LLM 生成回答"""
    try:
        # 基线埋点：记录各阶段耗时（秒），不影响任何业务逻辑与返回结构
        timings: Dict[str, float] = {}
        _t_start = time.perf_counter()

        # Step 1: 检索重排后的文档
        sync_retriever = _get_sync_retriever()
        original_collection = sync_retriever.collection_name
        if request.collection_name:
            sync_retriever.collection_name = request.collection_name
        retrieved_docs = await sync_retriever.retrieve(request.query, timings=timings)
        sync_retriever.collection_name = original_collection

        # Step 2: 调用 LLM 生成回答（复用 llm_service）
        usage: Dict[str, int] = {}
        _t_llm = time.perf_counter()
        answer = await llm_service.generate_answer(request.query, retrieved_docs, usage=usage)
        timings["llm_s"] = time.perf_counter() - _t_llm

        # Step 3: 构造溯源信息
        sources = [
            {"content": doc.page_content, "metadata": doc.metadata}
            for doc in retrieved_docs
        ]

        # 端到端总耗时（含组装 overhead，非三段简单相加）
        timings["total_s"] = time.perf_counter() - _t_start
        # 生成速度（tokens/s）：归一化 LLM 快慢，排除"答得短所以快"的干扰
        _completion = usage.get("completion_tokens", 0)
        _tps = _completion / timings["llm_s"] if timings["llm_s"] > 0 else 0.0
        logger.info(
            f"[PERF] retrieve={timings.get('retrieve_s', 0):.3f}s "
            f"rerank={timings.get('rerank_s', 0):.3f}s "
            f"llm={timings.get('llm_s', 0):.3f}s "
            f"total={timings['total_s']:.3f}s "
            f"docs={len(retrieved_docs)} answer_chars={len(answer)} "
            f"tokens(in/out)={usage.get('prompt_tokens', 0)}/{_completion} "
            f"gen_speed={_tps:.1f}tok/s"
        )

        logger.info(f"source is [{sources}]")


        return ChatResponse(
            success=True,
            answer=answer,
            sources=sources,
            message="回答生成成功"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"问答失败：{str(e)}")

def _json_default(obj):
    """
    json.dumps 兜底处理器：把 numpy 标量/数组转成 Python 原生 JSON 类型，
    防止向量检索分数（如 metadata['score'] 为 np.float32）导致 SSE 序列化失败。
    """
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def sse_event(event_type: str, data=None) -> str:
    """
    返回内容包装成 SSE 协议规定的格式，
    即 data: {"type": event_type, "data": data}
    """
    payload = {"type": event_type}
    if data is not None:
        payload["data"] = data

    return f"data: {json.dumps(payload, ensure_ascii=False, default=_json_default)}\n\n"

@router.post("/stream")
async def chat_with_rag_stream(request: ChatRequest, http_request: Request):

    async def event_generator():
        """异步生成器"""
        try:
            yield sse_event("status", {"stage": "routing"})

            _t_start = time.perf_counter()
            timings: Dict[str, float] = {}

            state = {
                "summary": "",
                "recent_turns": [],
                "turn_count": 0,
            }

            # 获取历史对话记录
            if request.conversation_id:
                try:
                    state = await conversation_cache_service.get_state(
                        request.conversation_id
                    )
                except Exception:
                    logger.warning("Failed to read conversation state", exc_info=True)

            # 判断有没有历史记录
            has_history = (
                await conversation_cache_service.has_history(request.conversation_id)
                if request.conversation_id else False
            )

            # ---- 路由：DSL 生成 → DB 校验 → 执行 ----
            role = request.role if request.role in ("admin", "user") else "user"

            dsl = await generate_dsl(request.query)

            # DB 校验（detail/list 有 name 时）
            if dsl.operation in ("detail", "list") and dsl.filters.name:
                validated = await validate_name_and_fallback(
                    dsl.filters.name, request.query, role,
                )
                if validated == "rag":
                    logger.info(
                        "[DSL] DB 校验: name=%r 不存在，回退 RAG", dsl.filters.name,
                    )
                    dsl.operation = "rag"
                elif validated == "clarify":
                    logger.info(
                        "[DSL] DB 校验: name=%r 不存在 → clarify", dsl.filters.name,
                    )
                    dsl.operation = "clarify"

            # 低置信度 → clarify
            if dsl.operation not in ("rag", "clarify") and dsl.confidence < 0.5:
                logger.info(
                    "[DSL] confidence %.2f < 0.5 → clarify", dsl.confidence,
                )
                dsl.operation = "clarify"

            logger.info(
                "[DSL] final: query=%r op=%s filters=(name=%s dept=%s title=%s) "
                "confidence=%.2f reason=%r",
                request.query, dsl.operation,
                dsl.filters.name, dsl.filters.department, dsl.filters.title,
                dsl.confidence, dsl.reason,
            )

            # ── clarify ──
            if dsl.operation == "clarify":
                yield sse_event("token", "抱歉，我无法理解您的问题，请换一种方式描述。例如：'张三的电话是多少'、'研发部有哪些人'。")
                yield sse_event("sources", [])
                yield sse_event("done", {"metrics": {"route": "clarify"}})
                return

            # ── personnel ──
            if dsl.operation in ("detail", "list", "count", "distinct"):
                yield sse_event("status", {"stage": "personnel_search"})
                try:
                    result = await execute_personnel_dsl(dsl, role)
                except Exception:
                    logger.exception("Personnel search failed")
                    yield sse_event("error", "人员查询服务暂时不可用，请稍后重试")
                    return

                if not result.get("success"):
                    yield sse_event("error", result.get("message", "查询失败"))
                    return

                answer = format_personnel_dsl_answer(dsl, result, role)

                yield sse_event("token", answer)
                yield sse_event("sources", [])

                metrics = {
                    "route": "personnel",
                    "operation": dsl.operation,
                    "personnel_found": (
                        result.get("operation") == "count"
                        or len(result.get("data", [])) > 0
                    ),
                    "role": role,
                    "result_count": (
                        result.get("count")
                        if result.get("operation") == "count"
                        else len(result.get("data", []))
                    ),
                }
                yield sse_event("done", {"metrics": metrics})
                return

            # 仅没有历史的首轮可读取全局答案缓存。
            if not has_history and not request.bypass_cache:
                try:
                    cached = await qa_cache_service.get(request.query)
                except Exception:
                    # Redis may be restarting; continue through the RAG path.
                    logger.warning("Failed to read QA cache", exc_info=True)
                    cached = None
                if cached:
                    answer = cached["answer"]
                    for index in range(0, len(answer), 30):
                        yield sse_event("token", answer[index:index + 30])

                    yield sse_event("sources", cached["sources"])

                    # 即使答案来自全局缓存，也必须记录为该会话的第一轮。
                    if request.conversation_id:
                        try:
                            await conversation_cache_service.append_turn(
                                request.conversation_id, request.query, answer
                            )
                        except Exception:
                            logger.warning("Failed to save cached conversation turn", exc_info=True)

                    yield sse_event("done", {
                        "metrics": {
                            "cache_layer": "redis",
                            "cache_hit": True
                        }
                    })
                    return

            # Step0: 查询重写（第一轮原样检索；有历史才改写。）
            retrieval_query = request.query
            rewrite_ms = 0
            if ENABLE_QUERY_REWRITE and has_history:
                _t_rewrite = time.perf_counter()
                retrieval_query = await llm_service.rewrite_query(
                    summary=state["summary"],
                    recent_turns=state["recent_turns"],
                    query=request.query,
                )
                rewrite_ms = round((time.perf_counter() - _t_rewrite) * 1000, 1)

            # ---- RAG 诊断日志 1：查询重写后的检索上下文 ----
            logger.info(
                "[RAG_TRACE] conversation=%s has_history=%s raw_query=%r retrieval_query=%r "
                "summary_chars=%d recent_turns=%d rewrite_ms=%.1f",
                request.conversation_id,
                has_history,
                request.query,
                retrieval_query,
                len(state["summary"]),
                len(state["recent_turns"]),
                rewrite_ms,
            )

            # Step 1: 检索重排后的文档
            # 每个请求独享检索器，避免并发修改全局 collection_name。
            request_retriever = KnowledgeBaseRetriever(
                collection_name=request.collection_name or "rag",
                k=20,
                rerank_top_n=10,
                hybrid_alpha=0.7
            )
            retrieved_docs = await request_retriever.retrieve(retrieval_query, timings=timings)

            # ---- RAG 诊断日志 2：检索到的 Top 3 文档 ----
            logger.info(
                "[RAG_TRACE] conversation=%s retrieved_docs=%s",
                request.conversation_id,
                [
                    {
                        "rank": index + 1,
                        "source": doc.metadata.get("source", "unknown"),
                        "score": doc.metadata.get("score"),
                        "rerank_score": doc.metadata.get("rerank_score"),
                        "preview": _preview(doc.page_content),
                    }
                    for index, doc in enumerate(retrieved_docs)
                ],
            )

            # Step 2: 调用 LLM 生成回答（流式）
            _t_llm_start = time.perf_counter()
            ttft_s = None

            chunks = []
            async for chunk in llm_service.generate_answer_stream(
                    query=request.query,
                    documents=retrieved_docs,
                    summary=state["summary"],
                    recent_turns=state["recent_turns"],
            ):
                if ttft_s is None:
                    ttft_s = time.perf_counter() - _t_start
                if await http_request.is_disconnected():
                    logger.info("客户端已断开流式请求")
                    return

                # 向前端发送chunk内容
                chunks.append(chunk)
                yield sse_event("token", chunk)

            _t_llm_end = time.perf_counter()
            llm_s = _t_llm_end - _t_llm_start
            ttlt_s = _t_llm_end - _t_start

            # Step 3: 构造溯源信息
            sources = [
                {"content": doc.page_content, "metadata": doc.metadata}
                for doc in retrieved_docs
            ]

            # 向前端发送溯源内容
            yield sse_event("sources", sources)

            # 将结果存入缓存
            if not request.bypass_cache and not has_history:
                try:
                    await qa_cache_service.set(request.query, "".join(chunks), sources)
                except Exception:
                    logger.warning("Failed to write QA cache", exc_info=True)

            # 新的一轮历史问答存入Redis
            summary_updated = False
            if request.conversation_id:
                old_summary = state["summary"]
                try:
                    new_state = await conversation_cache_service.append_turn(
                        request.conversation_id,
                        request.query,
                        "".join(chunks),
                    )
                    summary_updated = bool(
                        new_state.get("summary") and new_state["summary"] != old_summary
                    )
                except Exception:
                    logger.warning("Failed to save conversation state", exc_info=True)

            # ---- RAG 诊断日志 3：最终回答统计 ----
            answer_text = "".join(chunks)
            logger.info(
                "[RAG_TRACE] conversation=%s answer_chars=%d source_chars=%d",
                request.conversation_id,
                len(answer_text),
                sum(len(doc.page_content) for doc in retrieved_docs),
            )

            # ---- 零成本泄漏检测 ----
            FORBIDDEN_MARKERS = (
                "文档1", "文档2", "文档3",
                "参考文档", "检索结果", "根据资料",
            )
            if any(marker in answer_text for marker in FORBIDDEN_MARKERS):
                logger.warning(
                    "[RAG_TRACE] Answer leaked internal retrieval wording for conversation=%s",
                    request.conversation_id,
                )

            # Step 4: done + 性能指标
            metrics = {
                "route": "rag",
                "server_ttft_ms": round((ttft_s * 1000) if ttft_s is not None else 0, 1),
                "llm_complete_ms": round(ttlt_s * 1000, 1),
                "retrieve_ms": round(timings.get("retrieve_s", 0) * 1000, 1),
                "rerank_ms": round(timings.get("rerank_s", 0) * 1000, 1),
                "llm_ms": round(llm_s * 1000, 1),
                "rewrite_ms": rewrite_ms,
                "cache_layer": "none",
                "cache_hit": False,
                "has_history": has_history,
                "query_rewritten": has_history,
                "retrieval_query": retrieval_query,
                "recent_turn_count": len(state["recent_turns"]),
                "summary_updated": summary_updated,
            }
            yield sse_event("done", {"metrics": metrics})

        except asyncio.CancelledError:
            logger.info("流式请求已取消")
            raise
        except Exception as exc:
            logger.exception("流式问答失败")
            yield sse_event("error", str(exc))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



