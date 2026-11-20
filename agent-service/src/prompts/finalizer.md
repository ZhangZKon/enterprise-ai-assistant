---
name: finalizer
order: 50
description: 基于单个工具结果直接回答用户
---
请基于工具返回结果直接回答用户。
如果 web_report 返回了 report_preview，请先概括报告的核心内容，再在末尾给出 report_path/evidence_path。
不要只返回文件路径。
原始问题：{{original_message}}
