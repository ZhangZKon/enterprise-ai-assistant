"""
Personnel DSL：LLM 生成结构化 QueryDSL → 校验 → 执行。

所有白名单来自 personnel_semantic.yaml，不再硬编码。
"""
from __future__ import annotations

import json
import logging
import re
import asyncio
import os
from dataclasses import dataclass, field
from typing import Literal

import httpx
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from config.config import APP_CONFIG
from config.semantic_config import (
    get_config, get_valid_operations, get_valid_fields,
    get_sensitive_fields, get_public_fields, get_distinct_fields,
    get_limits, get_defaults,
    get_operation_constraints,
    build_semantic_prompt_block,
    build_dsl_schema,
)

logger = logging.getLogger(__name__)

# ── 正则（强实体快速路径） ──
_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_RAG_PATTERNS = re.compile(
    r"流程|制度|申请|材料|怎么|如何|政策|规定|方法|步骤|条件|标准|要求|指引|办理|操作|说明"
)

# ── 加载yaml.语义配置 ──
_SEMANTIC_CONFIG = get_config()
VALID_OPERATIONS = get_valid_operations(_SEMANTIC_CONFIG)
VALID_FIELDS = get_valid_fields(_SEMANTIC_CONFIG)
VALID_DISTINCT_FIELDS = get_distinct_fields(_SEMANTIC_CONFIG)
SENSITIVE_FIELDS = get_sensitive_fields(_SEMANTIC_CONFIG)
PUBLIC_FIELDS = get_public_fields(_SEMANTIC_CONFIG)
# 默认 select_fields 从 YAML defaults 读取（list/detail 默认输出列由 YAML 单一来源驱动）
_SEMANTIC_DEFAULTS = get_defaults(_SEMANTIC_CONFIG)
LIST_DEFAULT_FIELDS = _SEMANTIC_DEFAULTS.get("list_select_fields", ["nickname"])

# ── 字段标签 / 敏感展示字段 ──
FIELD_LABELS = {
    "phone": "电话",
    "email": "邮箱",
    "employee_id": "工号",
    "department": "部门",
    "title": "职位",
    "supervisor": "直属领导",
    "hire_date": "入职日期",
}
SENSITIVE_DISPLAY_FIELDS = ("phone", "email", "supervisor", "hire_date")

# ── Prompt 语义块 / DSL 输出结构（均从 YAML 动态生成） ──
_SEMANTIC_BLOCK = build_semantic_prompt_block(_SEMANTIC_CONFIG)
_DSL_SCHEMA = build_dsl_schema(_SEMANTIC_CONFIG)
_DSL_TIMEOUT_S = float(os.getenv("LLM_DSL_TIMEOUT", "25"))


# ═══════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════

@dataclass
class PersonnelFilters:
    name: str | None = None
    username: str | None = None
    employee_id: str | None = None
    department: str | None = None
    title: str | None = None
    phone: str | None = None
    email: str | None = None
    supervisor: str | None = None
    hire_date: str | None = None


@dataclass
class PersonnelQueryDSL:
    domain: str = "personnel"
    operation: Literal["detail", "list", "count", "distinct", "rag", "clarify"] = "clarify"
    filters: PersonnelFilters = field(default_factory=PersonnelFilters)
    distinct_field: str | None = None
    select_fields: list[str] = field(default_factory=list)
    limit: int = 20
    offset: int = 0
    confidence: float = 0.0
    reason: str = ""


# ═══════════════════════════════════════════════════════════════
# LLM → DSL
# ═══════════════════════════════════════════════════════════════

_DSL_PROMPT = ChatPromptTemplate.from_template("""
你是 Query Planner，严格根据语义配置 (semantic.yaml) 把用户问题转换成 QueryDSL。
只输出 JSON，不输出解释，不生成 SQL。

语义配置：
{semantic_block}

输出 JSON 必须严格按下述结构（filters 中所有字段都必须包含，不需要就填 null；
operation 只能从可选值中选择一个；select_fields 从可用字段中选择，未明确指定就留空数组；confidence自由判断）：
{dsl_schema}

用户问题：{query}

只输出 JSON：""")


_DSL_LLM = ChatOpenAI(
    base_url=APP_CONFIG.llm.base_url,
    model=APP_CONFIG.llm.model_id,
    api_key=APP_CONFIG.llm.api_key,
    temperature=0,
    max_tokens=256,
    timeout=_DSL_TIMEOUT_S,
)
_DSL_CHAIN = _DSL_PROMPT | _DSL_LLM | StrOutputParser()


async def _call_llm_dsl(query: str, timeout_s: float = _DSL_TIMEOUT_S) -> dict | None:
    """调用 LLM 生成 QueryDSL JSON。"""
    try:
        raw = await asyncio.wait_for(
            _DSL_CHAIN.ainvoke({
                "query": query,
                "semantic_block": _SEMANTIC_BLOCK,
                "dsl_schema": _DSL_SCHEMA,
            }),
            timeout=timeout_s,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("LLM DSL JSON 解析失败: %s", e)
        return None
    except asyncio.TimeoutError:
        logger.warning("LLM DSL 超时")
        return None
    except Exception:
        logger.exception("LLM DSL 生成异常")
        return None


# ═══════════════════════════════════════════════════════════════
# Sanitize
# ═══════════════════════════════════════════════════════════════

def _extract_phone(query: str) -> str | None:
    m = _PHONE_RE.search(query)
    return m.group(0) if m else None


def _extract_email(query: str) -> str | None:
    m = _EMAIL_RE.search(query)
    return m.group(0) if m else None


def _sanitize_dsl(raw: dict, query: str = "") -> PersonnelQueryDSL:
    """校验 + 清洗 LLM 生成的 DSL，基于 semantic config 白名单。

    业务规则修正（codex Step 5）：
    - rag/clarify → 清空 filters、distinct_field、select_fields
    - detail 无 name/phone/email → clarify
    - list 无 department/title/name → clarify
    - distinct 缺少 distinct_field → clarify
    """
    # operation 白名单校验
    op = raw.get("operation", "clarify")
    if op not in VALID_OPERATIONS:
        op = "clarify"

    # filters 白名单校验
    raw_filters = raw.get("filters", {})
    if not isinstance(raw_filters, dict):
        raw_filters = {}

    filters = PersonnelFilters()
    for key in sorted(VALID_FIELDS):
        val = raw_filters.get(key)
        if val is not None:
            val = str(val).strip()
            if val:
                setattr(filters, key, val)

    # distinct_field 白名单校验
    distinct_field = raw.get("distinct_field")
    if distinct_field is not None:
        distinct_field = str(distinct_field)
        if distinct_field not in VALID_DISTINCT_FIELDS:
            distinct_field = None

    # select_fields 白名单校验
    select_fields = raw.get("select_fields", [])
    if not isinstance(select_fields, list):
        select_fields = []
    select_fields = [f for f in select_fields if f in VALID_FIELDS]

    # limit 范围校验
    try:
        limit = int(raw.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    max_limit = get_limits(_SEMANTIC_CONFIG)["max"]
    limit = max(1, min(limit, max_limit))

    # offset
    try:
        offset = max(0, int(raw.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0

    # confidence
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.0

    reason = str(raw.get("reason", ""))[:200]

    # ── 业务规则修正：从 YAML operation 约束读取（Codex/Snowflake 思路） ──
    op_original = op
    op_config = get_operation_constraints(_SEMANTIC_CONFIG, op)
    raw_reason = reason

    # no_filters → 清空 filters、distinct_field、select_fields
    if op_config.get("no_filters"):
        filters = PersonnelFilters()
        distinct_field = None
        select_fields = []

    # require_any_filter → 至少需要指定的 filter 字段之一有值
    require_any = op_config.get("require_any_filter", [])
    if require_any:
        has_any = any(
            getattr(filters, f) for f in require_any
            if hasattr(filters, f)
        )
        if not has_any:
            op = "clarify"
            filters = PersonnelFilters()
            distinct_field = None
            select_fields = []
            if not reason or reason == raw_reason:
                reason = f"{op_original} 缺少可定位条件（需要 {'/'.join(require_any)} 至少一个）"

    # require_distinct_field → 必须指定 distinct_field
    if op_config.get("require_distinct_field") and distinct_field is None:
        op = "clarify"
        if not reason or reason == raw_reason:
            reason = f"distinct 缺少 distinct_field（可选: {'/'.join(get_distinct_fields(_SEMANTIC_CONFIG))}）"

    return PersonnelQueryDSL(
        domain="personnel",
        operation=op,
        filters=filters,
        distinct_field=distinct_field,
        select_fields=select_fields,
        limit=limit,
        offset=offset,
        confidence=confidence,
        reason=reason,
    )


# ═══════════════════════════════════════════════════════════════
# Main Entry: generate_dsl
# ═══════════════════════════════════════════════════════════════

async def generate_dsl(query: str) -> PersonnelQueryDSL:
    """主入口：正则快速路径 → LLM 生成 DSL → sanitize。

    1. 手机号/邮箱强实体 → 直接返回 detail DSL
    2. LLM 生成 QueryDSL → 白名单校验 + 业务规则修正
    """
    query = query.strip()
    if not query:
        return PersonnelQueryDSL(
            operation="rag",
            confidence=0.0,
            reason="empty query",
        )

    # 1. 强实体快速路径：手机号/邮箱 → detail
    phone = _extract_phone(query)
    email = _extract_email(query)
    if phone or email:
        return PersonnelQueryDSL(
            operation="detail",
            filters=PersonnelFilters(phone=phone, email=email),
            confidence=1.0,
            reason="强实体命中：手机号/邮箱",
        )

    # 2. LLM 路径
    llm_result = await _call_llm_dsl(query)
    if llm_result is None:
        logger.info("LLM DSL 生成失败，返回 clarify")
        return PersonnelQueryDSL(
            operation="clarify",
            confidence=0.0,
            reason="LLM 不可用",
        )

    dsl = _sanitize_dsl(llm_result, query)

    logger.info(
        "DSL: query=%r → op=%s filters=(name=%s dept=%s title=%s) "
        "distinct=%s confidence=%.2f reason=%r",
        query, dsl.operation,
        dsl.filters.name, dsl.filters.department, dsl.filters.title,
        dsl.distinct_field, dsl.confidence, dsl.reason,
    )

    return dsl


# ═══════════════════════════════════════════════════════════════
# Execute DSL
# ═══════════════════════════════════════════════════════════════

PERSONNEL_QUERY_URL = "http://localhost:8081/api/personnel/query"


async def execute_personnel_dsl(dsl: PersonnelQueryDSL, role: str = "user") -> dict:
    """执行 QueryDSL，调用 Java /personnel/query 接口。

    Java 负责 Validator 校验 + MyBatis-Plus 安全构造 SQL，
    detail/list/count/distinct 四种 operation 均由 Java 原生执行。
    """
    op = dsl.operation

    if op in ("rag", "clarify"):
        return {"success": True, "data": [], "operation": op}

    # 构造完整的 DSL payload，由 Java Validator 二次校验
    select_fields = dsl.select_fields
    if not select_fields and dsl.operation == "list":
        select_fields = LIST_DEFAULT_FIELDS

    payload = {
        "operation": dsl.operation,
        "filters": {
            key: getattr(dsl.filters, key) for key in sorted(VALID_FIELDS)
        },
        "distinct_field": dsl.distinct_field,
        "select_fields": select_fields,
        "limit": dsl.limit,
        "offset": dsl.offset,
        "role": role,
    }

    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.post(
                PERSONNEL_QUERY_URL,
                json=payload,
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json()

    except Exception as e:
        logger.exception("Personnel DSL 执行失败")
        return {"success": False, "data": [], "message": str(e)}


def format_personnel_dsl_answer(
    dsl: PersonnelQueryDSL,
    result: dict,
    role: str = "user",
) -> str:
    """将 DSL 执行结果格式化为用户可读文本。

    不同 operation 有不同的回答模板：
    - detail/list: 完整人员信息卡片
    - count: 数量
    - distinct: 枚举值
    - rag/clarify: 空字符串（由上游路由处理）
    """
    op = result.get("operation", dsl.operation)
    data = result.get("data", [])

    if op in ("rag", "clarify"):
        return ""

    if op == "count":
        n = result.get("count", 0)
        dept = dsl.filters.department or ""
        title = dsl.filters.title or ""
        if dept:
            return f"{dept}共有 {n} 人。"
        if title:
            return f"{title}岗位共有 {n} 人。"
        return f"共找到 {n} 名员工。"

    if op == "distinct":
        if data:
            # Java 返回 [{"department": "研发部"}, {"department": "市场部"}, ...]
            values = [list(d.values())[0] for d in data if d]
            field_label = {"department": "部门", "title": "职位"}.get(
                dsl.distinct_field or "", dsl.distinct_field or "字段"
            )
            return f"公司有以下{field_label}：{'、'.join(values)}。"
        return "未找到相关信息。"

    if op == "list":
        if not data:
            return "未找到匹配的人员信息，请确认姓名、手机号或邮箱是否正确。"

        lines: list[str] = []
        for person in data:
            parts = [f"姓名：{person.get('nickname', '')}"]
            if person.get("department"):
                parts.append(f"部门：{person.get('department', '')}")
            if person.get("title"):
                parts.append(f"职位：{person.get('title', '')}")
            lines.append("，".join(parts))

        return "\n".join(lines).strip()

    if op == "detail":
        if not data:
            return "未找到匹配的人员信息，请确认姓名、手机号或邮箱是否正确。"

        lines: list[str] = []
        for person in data:
            lines.append(f"姓名：{person.get('nickname', '')}")
            if person.get("username"):
                lines.append(f"账号：{person.get('username', '')}")
            if person.get("department"):
                lines.append(f"部门：{person.get('department', '')}")
            if person.get("title"):
                lines.append(f"职位：{person.get('title', '')}")
            if person.get("employee_id"):
                lines.append(f"工号：{person.get('employee_id', '')}")

            if role == "admin":
                for field in SENSITIVE_DISPLAY_FIELDS:
                    if field in person:
                        lines.append(f"{FIELD_LABELS[field]}：{person[field] or '未登记'}")
            else:
                denied = [
                    FIELD_LABELS[f] for f in SENSITIVE_DISPLAY_FIELDS
                    if f in dsl.select_fields
                ]
                if denied:
                    lines.append(f"你当前无权限查看{'、'.join(denied)}")

            lines.append("")  # 多结果之间空行

        return "\n".join(lines).strip()

    return ""


# ═══════════════════════════════════════════════════════════════
# DB 姓名校验（从 query_router 搬入）
# ═══════════════════════════════════════════════════════════════

def _looks_like_policy(query: str) -> bool:
    return bool(_RAG_PATTERNS.search(query))


async def validate_name_and_fallback(
    name: str, query: str, role: str = "user",
) -> Literal["personnel", "rag", "clarify"]:
    """调用 Java 服务校验 name 是否真实存在。

    返回 personnel / rag / clarify。
    """
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.post(
                "http://localhost:8081/api/personnel/search",
                json={"name": name, "phone": None, "email": None,
                       "role": role, "requested_fields": []},
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()
            found = data.get("data") and len(data["data"]) > 0

            if found:
                return "personnel"

            if _looks_like_policy(query):
                logger.info("DB 校验: name=%r 不存在，query 像流程制度 → 回退 RAG", name)
                return "rag"

            logger.info("DB 校验: name=%r 不存在，query 不像流程制度 → clarify", name)
            return "clarify"
    except Exception as e:
        logger.warning("DB 校验失败: %s，信任 LLM 结果", e)
        return "personnel"
