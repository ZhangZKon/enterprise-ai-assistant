# Agent Service

企业问答 Agent 编排服务：识别意图 → 规划工具调用 → 执行工具 → 评估回答质量（不足则重写重查）→ 输出最终回答。

## 系统位置

```text
前端(Vue) → agent-service（本服务）
              ├→ rag-local          内部知识/人员/制度问答（HTTP）
              └→ web-report-skill   联网检索与报告生成（子进程）
```

## 快速启动

1. `copy .env.example .env`，填写 `LLM_API_KEY`（其余按需调整）
2. 安装依赖：`pip install -r requirements.txt`
3. 启动前置依赖：rag-local（默认 `http://127.0.0.1:8000`）、web-report-skill（配置 `WEB_REPORT_PROJECT_DIR` / `WEB_REPORT_PYTHON`）
4. 启动服务：`python main.py`（默认端口 8010）
5. 冒烟测试：`python -c "from src.tool_registry import TOOL_SCHEMAS; print([t['function']['name'] for t in TOOL_SCHEMAS])"`

## 工作流程

```text
planner（识别意图 + 生成步骤）→ 执行工具 → evaluator（评估 + 决策 + 回答）
   └─ 评估不足 → 按 evaluator 给出的新参数重查（最多 max_iterations 轮，防空转）
```

- 意图：`internal_only` / `web_only` / `hybrid_compare` / `direct_answer` / `clarification`
- 工具：`internal_rag_query`（内部 RAG）、`web_report`（联网报告）

## 工程要点

- **提示词**：`src/prompts/*.md` 分段文件，改提示词不用改代码（`src/prompt_registry.py` 注册中心，严格变量校验）
- **工具管线**：`src/tool_registry.py` 的 PRE/POST 钩子（参数归一化、上下文补充等横切逻辑）
- **执行轨迹**：每次请求落 `logs/*.jsonl` 事件日志（`EVENT_LOG_DIR` 可配），用于人机 QA 复盘
- **容错**：LLM 输出解析失败走 fail-closed 降级（绝不默认"回答足够"）；限流/超时降级返回已获取内容

## 目录

```text
src/
  agent.py            入口（run_agent）
  orchestrator.py     主循环（规划→执行→评估→回答）
  llm_client.py       LLM 调用（planner / evaluator / direct）
  tool_registry.py    工具注册 + pre/post 钩子
  prompt_registry.py  提示词注册中心
  prompts/            分段提示词（.md）
  tools/              工具实现（internal_rag / web_report）
main.py               FastAPI 服务（POST /agent/chat）
docs/                 开发记录（任务计划 / ADR）
```
