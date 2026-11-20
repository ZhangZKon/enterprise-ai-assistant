"""
语义层配置：读取 personnel_semantic.yaml（entity-based 结构），
提供白名单、约束规则、prompt 语义块。

Codex / Snowflake 思路：
  - 实体 (entity) → 字段 (field) → 操作 (operation) 全部定义在 YAML
  - prompt 只做 "Query Planner根据YAML生成DSL"，不硬编码判断规则
  - sanitize 层的校验规则也从 YAML 读取
"""
from __future__ import annotations

import os
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "personnel_semantic.yaml"


# ═══════════════════════════════════════════════════════════════
# YAML 加载
# ═══════════════════════════════════════════════════════════════

def load_personnel_semantic(path: str | Path | None = None) -> dict:
    """加载 personnel_semantic.yaml 并返回 dict。"""
    target = Path(path) if path else _CONFIG_PATH
    try:
        with open(target, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            logger.warning("semantic YAML 格式异常，返回空配置")
            return {}
        return config
    except FileNotFoundError:
        logger.warning("semantic YAML 未找到：%s", target)
        return {}
    except yaml.YAMLError as e:
        logger.warning("semantic YAML 解析失败：%s", e)
        return {}


# ═══════════════════════════════════════════════════════════════
# Entity 提取
# ═══════════════════════════════════════════════════════════════

def _get_entity_config(config: dict, entity_name: str | None = None) -> dict:
    """提取指定 entity 的子配置，默认返回第一个 entity。"""
    entities = config.get("entities", {})
    if not entities:
        return {}
    if entity_name:
        return entities.get(entity_name, {})
    return next(iter(entities.values()), {})


def get_entity_names(config: dict) -> list[str]:
    """返回所有 entity 名称列表。"""
    return list(config.get("entities", {}).keys())


# ═══════════════════════════════════════════════════════════════
# Field 白名单 / 元数据（基于 entity）
# ═══════════════════════════════════════════════════════════════

def get_valid_fields(config: dict, entity_name: str | None = None) -> set[str]:
    """返回 entity 下所有字段名。"""
    entity = _get_entity_config(config, entity_name)
    fields = entity.get("fields", {})
    if not isinstance(fields, dict):
        return set()
    return set(fields.keys())


def get_sensitive_fields(config: dict, entity_name: str | None = None) -> set[str]:
    """返回标记 sensitive: true 的字段名。"""
    entity = _get_entity_config(config, entity_name)
    fields = entity.get("fields", {})
    if not isinstance(fields, dict):
        return set()
    return {
        name for name, meta in fields.items()
        if isinstance(meta, dict) and meta.get("sensitive") is True
    }


def get_public_fields(config: dict, entity_name: str | None = None) -> set[str]:
    """返回非敏感字段名。"""
    return get_valid_fields(config, entity_name) - get_sensitive_fields(config, entity_name)


def get_field_column_map(config: dict, entity_name: str | None = None) -> dict[str, str]:
    """返回 {field_name: db_column} 映射。"""
    entity = _get_entity_config(config, entity_name)
    fields = entity.get("fields", {})
    if not isinstance(fields, dict):
        return {}
    return {
        name: meta["column"]
        for name, meta in fields.items()
        if isinstance(meta, dict) and "column" in meta
    }


def get_distinct_fields(config: dict, entity_name: str | None = None) -> set[str]:
    """返回允许 distinct 的字段。"""
    entity = _get_entity_config(config, entity_name)
    dfs = entity.get("distinct_fields", [])
    if isinstance(dfs, list):
        return set(dfs)
    return set()


def get_limits(config: dict, entity_name: str | None = None) -> dict:
    """返回 {default: int, max: int} 分页限制。"""
    entity = _get_entity_config(config, entity_name)
    limits = entity.get("limits", {})
    if isinstance(limits, dict):
        return {"default": limits.get("default", 20), "max": limits.get("max", 50)}
    return {"default": 20, "max": 50}


def get_dsl_fields(config: dict, entity_name: str | None = None) -> dict:
    """返回 DSL 输出结构各字段的语义说明（select_fields/confidence/reason）。

    从 YAML 的 select_field / confidence / reason 配置块收集 description，
    注入 LLM prompt 帮助 Query Planner 正确填值，全部由 YAML 单一来源驱动。
    """
    entity = _get_entity_config(config, entity_name)
    result: dict[str, str] = {}
    for field_name, block in {
        "select_fields": "select_field",
        "confidence": "confidence",
        "reason": "reason",
    }.items():
        blk = entity.get(block, {})
        if not isinstance(blk, dict):
            continue
        parts = []
        if blk.get("description"):
            parts.append(blk["description"])
        avail = blk.get("available")
        if isinstance(avail, list) and avail:
            parts.append("可选: " + " / ".join(avail))
        if parts:
            result[field_name] = "；".join(parts)
    return result


def get_defaults(config: dict, entity_name: str | None = None) -> dict:
    """返回 entity 的 defaults 配置（如 list_select_fields / detail_select_fields）。

    供默认 select_fields 等场景使用，保证默认输出列也由 YAML 单一来源驱动。
    """
    entity = _get_entity_config(config, entity_name)
    defaults = entity.get("defaults", {})
    if isinstance(defaults, dict):
        return defaults
    return {}


# ═══════════════════════════════════════════════════════════════
# Operation 白名单 / 约束规则（基于 entity）
# ═══════════════════════════════════════════════════════════════

def get_valid_operations(config: dict, entity_name: str | None = None) -> set[str]:
    """返回 entity 下所有 operation 名称。"""
    entity = _get_entity_config(config, entity_name)
    ops = entity.get("operations", {})
    if not isinstance(ops, dict):
        return set()
    return set(ops.keys())


def get_operation_constraints(
    config: dict, operation: str, entity_name: str | None = None,
) -> dict:
    """返回某个 operation 的约束配置。

    返回 dict 可能包含：
      - description: str          操作描述
      - no_filters: bool          不允许带 filter（rag/clarify）
      - require_any_filter: list  至少需要一个的 filter 字段
      - require_distinct_field: bool  必须指定 distinct_field
    """
    entity = _get_entity_config(config, entity_name)
    ops = entity.get("operations", {})
    if not isinstance(ops, dict):
        return {}
    return ops.get(operation, {})


# ═══════════════════════════════════════════════════════════════
# Prompt 语义块生成（注入 LLM DSL prompt）
# ═══════════════════════════════════════════════════════════════

def build_semantic_prompt_block(config: dict, entity_name: str | None = None) -> str:
    """从 YAML 动态生成 prompt 中使用的语义块。

    输出格式：
      ## 实体: employee — 企业员工信息

      ### 字段
      - name: 姓名, 同义词=…, 敏感=否
      - phone: 电话, 同义词=…, 敏感(仅admin可见)

      ### Operation
      - detail: 查询个人信息, 约束=需要 name/phone/email 至少一个
      - list: 列出人员, 约束=需要 department/title/name 至少一个
      - rag: 查询制度流程文档, 约束=不需要 filter
      ...
    """
    entity = _get_entity_config(config, entity_name)
    if not entity:
        return "（无可用实体配置）"

    # 优先用传入的 entity_name，否则取第一个
    if entity_name:
        display_name = entity_name
    else:
        names = get_entity_names(config)
        display_name = names[0] if names else "unknown"

    description = entity.get("description", "")
    lines: list[str] = []

    # 实体头部
    lines.append(f"## 实体: {display_name}")
    if description:
        lines.append(f"描述: {description}")

    # ── 字段 ──
    lines.append("")
    lines.append("### 字段")
    fields = entity.get("fields", {})
    if isinstance(fields, dict):
        for fname, fmeta in fields.items():
            if not isinstance(fmeta, dict):
                continue
            label = fmeta.get("label", fname)
            synonyms = fmeta.get("synonyms", [])
            sensitive = fmeta.get("sensitive", False)
            allowed_roles = fmeta.get("permission", {}).get("role", [])

            syn_str = "、".join(synonyms) if synonyms else "无"
            line = f"- **{fname}** ({label}): 同义词={syn_str}"
            if sensitive:
                roles_str = "/".join(allowed_roles)
                line += f", [敏感字段, 仅 {roles_str} 可查]"
            lines.append(line)

    # ── Operation ──
    lines.append("")
    lines.append("### Operation（只能选择以下之一作为 operation 值）")
    ops = entity.get("operations", {})
    if isinstance(ops, dict):
        for op_name, op_meta in ops.items():
            if not isinstance(op_meta, dict):
                op_meta = {}
            desc = op_meta.get("description", "")
            constraints: list[str] = []

            if op_meta.get("no_filters"):
                constraints.append("filters 必须全部为 null")
            if op_meta.get("require_any_filter"):
                req = op_meta["require_any_filter"]
                constraints.append(f"必须提供 {'/'.join(req)} 至少一个作为 filter")
            if op_meta.get("require_distinct_field"):
                dfs = entity.get("distinct_fields", [])
                dfs_str = "/".join(dfs) if dfs else "distinct_field"
                constraints.append(f"必须指定 distinct_field（可选: {dfs_str}）")

            line = f"- **{op_name}**: {desc}"
            if constraints:
                line += f"  [约束: {'; '.join(constraints)}]"
            lines.append(line)

    # ── select_fields（用户本次明确想查看的字段） ──
    sel = entity.get("select_field", {})
    if isinstance(sel, dict) and (sel.get("description") or sel.get("available")):
        lines.append("")
        lines.append("### select_fields（用户本次明确想查看的字段）")
        if sel.get("description"):
            lines.append(sel["description"])
        if isinstance(sel.get("available"), list) and sel["available"]:
            lines.append("可选字段: " + " / ".join(sel["available"]))

    # ── distinct 允许的字段 ──
    dfs = entity.get("distinct_fields", [])
    if isinstance(dfs, list) and dfs:
        lines.append("")
        lines.append(f"### distinct_field 可选值: {' / '.join(dfs)}")

    # ── Limit ──
    limits = entity.get("limits", {})
    if isinstance(limits, dict):
        dflt = limits.get("default", 20)
        maxv = limits.get("max", 50)
        lines.append("")
        lines.append(f"### 分页: 默认 limit={dflt}, 最大 limit={maxv}")

    return "\n".join(lines)


def build_dsl_schema(config: dict, entity_name: str | None = None) -> str:
    """从 YAML 生成 DSL 输出 JSON 格式模板（供 LLM prompt 使用）。

    输出结构随 YAML 的 fields / operations / distinct_fields / limits
    自动变化，新增字段后无需再手动修改 prompt 模板。

    例如：
    {
      "domain": "employee",
      "operation": "detail|list|count|distinct|rag|clarify",
      "filters": {
        "name": null,
        "phone": null,
        ...
      },
      "distinct_field": null,
      "select_fields": [],
      "limit": 20,
      "offset": 0,
      "confidence": 0.0,
      "reason": "简短理由"
    }
    """
    names = get_entity_names(config)
    if entity_name is None:
        entity_name = names[0] if names else "entity"

    ops = sorted(get_valid_operations(config, entity_name))
    fields = sorted(get_valid_fields(config, entity_name))

    if not ops:
        ops = ["rag"]

    filters_lines = ",\n".join(f'    "{f}": null' for f in fields)
    schema = "\n".join([
        "{",
        f'  "domain": "{entity_name}",',
        f'  "operation": "{"|".join(ops)}",',
        '  "filters": {',
        filters_lines,
        "  },",
        '  "distinct_field": null,',
        '  "select_fields": [],',
        '  "limit": 20,',
        '  "offset": 0,',
        '  "confidence": 0.0,',
        '  "reason": "简短理由"',
        "}",
    ])

    # 追加各 DSL 字段的语义说明（从 YAML dsl_fields 生成），避免 LLM 照抄示例值
    dsl_notes = get_dsl_fields(config, entity_name)
    if dsl_notes:
        note_lines = ["", "DSL 字段说明："]
        note_lines += [f"- {k}: {v}" for k, v in dsl_notes.items()]
        schema += "\n" + "\n".join(note_lines)

    return schema


# ═══════════════════════════════════════════════════════════════
# 全局单例（首次导入时加载）
# ═══════════════════════════════════════════════════════════════

_SEMANTIC_CONFIG: dict | None = None


def get_config() -> dict:
    """获取全局语义配置（懒加载单例）。"""
    global _SEMANTIC_CONFIG
    if _SEMANTIC_CONFIG is None:
        _SEMANTIC_CONFIG = load_personnel_semantic()
    return _SEMANTIC_CONFIG
