# Web Report Skill

基于 Tavily 检索/抽取能力和 LLM 的网络调研报告生成流程。

## 作为 agent-service 的工具被调用

本模块可被 `agent-service` 作为子进程工具（`web_report`）调用。调用时通过环境变量 `WEB_REPORT_OUTPUT_DIR` 指定报告输出目录；agent-service 会剥离自身的 LLM 环境变量，因此本模块使用自己的 `.env` 配置（LLM 供应商可与 agent-service 不同）。

## 功能概括

本项目实现第一阶段的 Web Report 流程：

```text
用户输入主题/报告类型/时间范围/关键词
  -> 构造 Tavily search query
  -> Tavily Search 获取相关网页
  -> Tavily Extract 抽取网页正文或相关片段
  -> 来源过滤和去重
  -> 生成 evidence list
  -> 调用 LLM 生成 Markdown 报告
  -> 按时间目录保存 evidence 和 report
```

核心目标是把“网络检索 -> 证据整理 -> 报告生成”做成一个可解释、可扩展的报告生成模块。

## 项目结构

```text
web-report-skill/
  main.py
  README.md
  .env.example
  requirements.txt

  src/
    config.py            # 读取环境变量和运行参数
    query_builder.py     # 根据 topic/report_type/keywords 构造搜索 query
    tavily_client.py     # 封装 Tavily Search 和 Extract
    source_filter.py     # 来源去重、质量排序、域名限制
    evidence_builder.py  # 生成统一 evidence list
    report_generator.py  # 调用 LLM 生成 Markdown 报告
    markdown_writer.py   # 保存 evidence_list.md 和 report.md

  prompts/
    report_prompt.md     # 报告生成 prompt

  outputs/
    YYYYMMDD_HHMMSS_topic/
      evidence_list.md
      report.md
```

## 环境配置

复制 `.env.example` 为 `.env`，并填入真实 API Key：

```powershell
copy .env.example .env
```

主要配置项：

```text
TAVILY_API_KEY              Tavily API Key
LLM_API_KEY                 LLM API Key
LLM_BASE_URL                OpenAI-compatible LLM API 地址
LLM_MODEL                   LLM 模型名
SEARCH_MAX_RESULTS          Tavily Search 返回结果数
EXTRACT_MAX_SOURCES         Tavily Extract 最多抽取来源数
SEARCH_DEPTH                Tavily 搜索深度，建议 advanced
EXTRACT_DEPTH               Tavily 抽取深度，建议 advanced
EXTRACT_CHUNKS_PER_SOURCE   每个来源最多抽取的相关片段数
EVIDENCE_EXCERPT_CHARS      evidence 中保留的正文片段长度
MAX_PER_DOMAIN              每个域名最多保留多少条来源
MIN_SOURCES                 最少保留来源数
MAX_SOURCES                 最多保留来源数
```

`.env.example` 只能放占位符；`.env` 放真实密钥，并且不应提交到 git。

## 安装

```powershell
cd web-report-skill
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 使用方式

```powershell
.\.venv\Scripts\python.exe main.py --topic "新能源车目前的市场如何" --time-range past_month --report-type "综述报告"
```

带关键词：

```powershell
.\.venv\Scripts\python.exe main.py --topic "电影痴迷的票房排名" --report-type "数据调研" --keywords "电影痴迷,票房,排名"
```

每次运行会生成独立输出目录，避免覆盖历史结果：

```text
outputs/20260810_153012_新能源车目前的市场如何/
  evidence_list.md
  report.md
```

## Tavily 主要接口及功能

### 1. Search

Search 用于搜索网页。给一个 query，返回相关网页列表。

常见返回内容：

```text
title             标题
url               网页地址
content           搜索结果摘要或相关片段
raw_content       网页正文或正文片段
score             Tavily 给出的相关性分数
published_date    网页发布日期，部分来源可能为空
```

常用参数：

```text
query                搜索问题或关键词
max_results          返回结果数量
search_depth         搜索深度，basic/advanced/fast/ultra-fast
time_range           时间范围，day/week/month/year
include_raw_content  是否返回正文内容
include_domains      只包含指定域名
exclude_domains      排除指定域名
include_answer       是否让 Tavily 生成简短答案
auto_parameters      是否让 Tavily 自动优化部分搜索参数
```

在本项目中，Search 是第一步，用于获取候选网页。

### 2. Extract

Extract 用于抽取网页正文。给它一个或多个 URL，它会返回网页正文或与 query 相关的片段。

常用参数：

```text
urls                 需要抽取的 URL 列表
extract_depth        抽取深度，basic/advanced
format               返回格式，markdown/text
query                可选，只抽和 query 更相关的内容
chunks_per_source    每个来源返回的相关片段数量
```

在本项目中，Extract 用于把 Search 找到的 URL 转成可供 LLM 使用的正文材料。

### 3. Crawl

Crawl 用于从一个网站入口开始爬取整个网站或部分网站。

适合场景：

```text
爬官网
爬文档站
爬企业知识库
爬政策网站专题页
爬行业协会网站
```

Search 是“全网找相关网页”，Crawl 是“从指定网站入口往下爬”。

### 4. Map

Map 用于生成网站地图，只发现 URL，不抽正文。

可以理解为：

```text
Map = 找出一个网站有哪些页面
Crawl = 找页面 + 抽正文
Extract = 已知 URL 后抽正文
Search = 不知道 URL 时先全网搜索
```

Map 适合先了解一个网站结构，再决定哪些页面需要 Extract 或 Crawl。

### 5. Research

Research 是 Tavily 更高层的研究型接口，倾向于直接围绕主题做更完整的调研。

本项目第一阶段未使用 Research，当前流程为：

```text
Search -> Extract -> Filter -> Evidence -> LLM Report
```

Research 可作为后续对照方案。

## 当前相关性策略

本项目的相关性主要来自两层：

```text
第一层：Tavily Search 返回的排序和 score
第二层：source_filter.py 做 URL 去重、域名限制、正文完整性加分、发布时间加分
```

当前不是强 rerank 系统。后续如果需要更高质量，可以扩展：

```text
1. 多 query 检索
2. LLM 或 embedding rerank
3. 权威域名白名单/低质量域名黑名单
4. 按报告类型使用不同过滤规则
5. 对 Search 和 Extract 结果分别保存 raw JSON 便于调试
```

## 后续扩展

```text
阶段 1：普通 CLI 工具
阶段 2：补 SKILL.md，让 Agent 知道什么时候调用
阶段 3：封装成 web_report(topic, report_type, time_range, keywords) 工具函数
阶段 4：接入统一 Agent，让 Agent 在 internal RAG skill 和 web report skill 之间选择
阶段 5：如有需要，再封装成 MCP server
```
