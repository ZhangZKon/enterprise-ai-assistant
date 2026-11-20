"""
人员查询服务：通过 HTTP 调用 Java /personnel/search 接口。

本模块不调用 LLM，只做 HTTP 调用和答案格式化。
"""
import json
import logging
import httpx


logger = logging.getLogger(__name__)

# Java 人员查询接口
PERSONNEL_SEARCH_URL = "http://localhost:8081/api/personnel/search"


def _mask_phone(phone: str | None) -> str:
    """手机号脱敏：只保留前3后4，如 138****1027"""
    if not phone:
        return "N/A"
    if len(phone) >= 7:
        return phone[:3] + "****" + phone[-4:]
    return "***"


async def search_personnel(
    *,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    role: str = "user",
    requested_fields: list[str] | None = None,
) -> dict:
    """调用 Java 人员查询接口，返回已按角色脱敏的结果。

    传递 requested_fields 让 Java 做字段白名单过滤。
    """
    payload = {
        "name": name,
        "phone": phone,
        "email": email,
        "role": role,
        "requested_fields": requested_fields or [],
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            PERSONNEL_SEARCH_URL,
            json=payload,
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # 日志脱敏：不记录手机号/邮箱明文
        query_type = "name" if name else "phone" if phone else "email" if email else "unknown"
        logger.info(
            "Personnel search: role=%s type=%s → hits=%d",
            role, query_type, len(data.get("data", [])),
        )
        return data


def format_personnel_answer(
    results: list[dict],
    role: str,
    requested_fields: list[str] | None = None,
) -> str:
    """将 Java 返回的结果格式化为确定性文本回答（不调 LLM）。

    admin: 展示完整信息
    user:  仅展示公开信息，电话/邮箱显示"无权限查看"
    """
    if not results:
        return "未找到匹配的人员信息，请确认姓名、手机号或邮箱是否正确。"

    lines: list[str] = []
    for person in results:
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
            # 仅展示 Java 实际返回的字段（受 requested_fields 白名单控制）
            if "phone" in person:
                lines.append(f"电话：{person['phone'] or '未登记'}")
            if "email" in person:
                lines.append(f"邮箱：{person['email'] or '未登记'}")
        else:
            lines.append("联系方式：无权限查看")

        lines.append("")  # 多结果之间空行

    return "\n".join(lines).strip()
