"""极简 prompt 注册中心：扫描 src/prompts/*.md，frontmatter 声明元数据，
渲染时严格插值 {{变量}}。

借鉴 dsh system-prompt（packages/core/system-prompt）的分段注册 + 严格变量语义，
只保留本项目需要的 20%：
  - 分段：每个角色一个 .md 文件，frontmatter 声明 name / order / description
  - 组装：assemble() 按 order 升序拼接多个段（当前单段渲染为主，预留复用）
  - 严格插值：{{变量}} 必须已提供，否则抛错（fail loud，不留空引用）
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# 变量名白名单：小写字母开头，字母/数字/下划线（模仿 dsh 的 VARIABLE_NAME）
_VARIABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
# 完整 {{name}} 引用组
_GROUP_AT = re.compile(r"\{\{([^{}]*)\}\}")


class PromptError(RuntimeError):
    """prompt 配置或渲染错误（fail loud）。"""


@dataclass(frozen=True)
class PromptSection:
    name: str
    order: int
    description: str
    text: str


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """解析 YAML 风格的 frontmatter（--- 包裹的 key: value 块），返回 (元数据, 正文)。"""
    if not raw.startswith("---"):
        return {}, raw
    lines = raw.splitlines()
    end: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, raw
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[end + 1:])


def _interpolate(text: str, variables: dict[str, str], owner: str) -> str:
    """严格插值 {{变量}}；未知、未提供或非法变量名全部抛错。"""
    parts: list[str] = []
    last = 0
    for match in _GROUP_AT.finditer(text):
        name = match.group(1)
        if not _VARIABLE_NAME.match(name):
            raise PromptError(f'malformed prompt variable "{{{{{name}}}}}" in "{owner}"')
        if name not in variables:
            raise PromptError(
                f'unknown prompt variable "{{{{{name}}}}}" in "{owner}"; '
                f"provided: {sorted(variables) or '(none)'}"
            )
        parts.append(text[last:match.start()])
        parts.append(variables[name])
        last = match.end()
    parts.append(text[last:])
    return "".join(parts)


class PromptRegistry:
    """扫描目录下的 *.md，构建 {name: PromptSection} 并提供渲染/组装。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.sections: dict[str, PromptSection] = {}
        self._load()

    def _load(self) -> None:
        if not self.root.is_dir():
            raise PromptError(f"prompt root does not exist: {self.root}")
        for path in sorted(self.root.glob("*.md")):
            meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            name = meta.get("name") or path.stem
            if name in self.sections:
                raise PromptError(f'duplicate prompt section "{name}" in {path}')
            try:
                order = int(meta["order"])
            except (KeyError, ValueError):
                raise PromptError(f'prompt "{name}" ({path}) needs a numeric "order" frontmatter') from None
            self.sections[name] = PromptSection(
                name=name,
                order=order,
                description=meta.get("description", ""),
                text=body.strip(),
            )

    def names(self) -> list[str]:
        return sorted(self.sections)

    def render(self, name: str, **variables: str) -> str:
        """渲染单个段；未知段名或未提供变量抛 PromptError。"""
        section = self.sections.get(name)
        if section is None:
            raise PromptError(
                f'unknown prompt section "{name}" (available: {self.names()})'
            )
        return _interpolate(section.text, variables, name)

    def assemble(self, *names: str, **variables: str) -> str:
        """按 order 升序拼接多个段（模仿 dsh renderPrompt 的排序拼接）。"""
        missing = [name for name in names if name not in self.sections]
        if missing:
            raise PromptError(
                f'unknown prompt section(s): {missing} (available: {self.names()})'
            )
        ordered = sorted(
            (self.sections[name] for name in names),
            key=lambda section: section.order,
        )
        return "\n\n".join(
            _interpolate(section.text, variables, section.name)
            for section in ordered
        )


# 全局单例：注册表根目录固定为 src/prompts/
registry = PromptRegistry(Path(__file__).resolve().parent / "prompts")
