# RAG 知识库 API

## 项目简介

本项目是一个基于 FastAPI、Milvus 和 OpenAI 构建的 RAG（Retrieval Augmented Generation）知识库 API。它旨在提供一个高效、可扩展的解决方案，用于从非结构化文档中检索信息，并结合大型语言模型（LLM）生成准确、相关的答案。

**核心功能包括：**

*   **文档摄取 (Ingestion)**：从指定目录加载 Markdown 和 PDF 文档，进行文本分割、嵌入，并存储到 Milvus 向量数据库。
*   **知识库查询 (Query)**：接收用户查询，从 Milvus 检索最相关的文档片段，通过重排模型优化结果，然后将检索到的上下文提供给 LLM 以生成最终答案。
*   **知识库管理 (Management)**：支持删除 Milvus 中的特定知识库集合。

## 技术选型

*   **后端框架**：[FastAPI](https://fastapi.tiangolo.com/) - 现代、快速（高性能）的 Web 框架，用于构建 API。
*   **异步 HTTP 客户端**：[Httpx](https://www.python-httpx.org/) - 用于执行异步 HTTP 请求，提高并发性能。
*   **向量数据库**：[Milvus](https://milvus.io/) - 开源的向量数据库，专为海量向量数据存储、索引和查询而设计。
*   **嵌入模型/重排模型**：兼容 OpenAI API 的模型（例如，本地部署的 BGE 模型）。
*   **大型语言模型 (LLM)**：兼容 OpenAI API 的模型。
*   **RAG 框架**：[LangChain](https://www.langchain.com/) - 用于开发由语言模型驱动的应用程序的框架，简化了 RAG 流程的构建。
*   **数据验证**：[Pydantic](https://pydantic-docs.helpmanual.io/) - 用于数据解析和验证，确保 API 请求和响应的数据结构正确性。
*   **环境变量管理**：[python-dotenv](https://pypi.org/project/python-dotenv/) - 从 `.env` 文件加载环境变量。
*   **文档加载与分割**：`langchain-community` 和 `langchain.text_splitter`。

## 目录架构

```
rag/
├── main.py                 # FastAPI 应用程序入口点
├── api/
│   ├── __init__.py
│   └── endpoints.py        # API 路由定义（控制器层）
├── core/
│   ├── __init__.py
│   ├── config.py           # 应用程序配置，包括模型和数据库设置
│   ├── document_service.py # 文档加载和分割服务
│   ├── embedding_service.py# 嵌入模型和重排模型服务
│   ├── retriever_service.py# 知识库检索服务（结合向量搜索和重排）
│   └── vector_db_service.py# Milvus 向量数据库交互服务
├── models/
│   ├── __init__.py
│   └── schemas.py          # Pydantic 请求和响应数据模型
├── knowledge_base_documents/   # 存放知识库文档的目录（Markdown, PDF 等）
│   └── ...
├── .env                        # 环境变量配置文件（敏感信息）
└── requirements.txt            # Python 依赖列表
```

## 功能说明

### 1. 文档摄取 (`/ingest_documents`)

*   **功能**：将位于 `knowledge_base_documents/` 目录下的 Markdown 和 PDF 文件加载到 Milvus 向量数据库中。
*   **流程**：
    1.  使用 `DocumentLoader` 加载并分割文档。
    2.  通过 `VectorDB` 将分割后的文本块进行嵌入，并插入到指定的 Milvus 集合。
    3.  如果集合已存在，会先尝试删除旧集合以确保数据新鲜度。
*   **HTTP 方法**：`POST`
*   **参数**：
    *   `collection_name` (str, 可选)：目标 Milvus 集合的名称，默认为 `APP_CONFIG.milvus.collection_name`。
*   **响应**：`IngestResponse` (message, documents\_ingested, collection\_name)

### 2. 知识库查询 (`/query`)

*   **功能**：接收用户查询，从知识库中检索相关信息，并利用 LLM 生成答案。
*   **流程**：
    1.  `QueryRequest` 对输入参数进行严格校验。
    2.  `KnowledgeBaseRetriever` 执行混合搜索（密集向量 + 稀疏向量）从 Milvus 检索初步文档。
    3.  `RerankModel` 对初步检索到的文档进行重排，以提高相关性。
    4.  将重排后的相关文档作为上下文，结合用户查询，发送给 LLM 生成最终答案。
*   **HTTP 方法**：`POST`
*   **请求体**：`QueryRequest`
    *   `query` (str, 必填)：用户查询文本。
    *   `collection_name` (str, 可选)：Milvus 集合名称。
    *   `k` (int, 可选)：初步检索的文档数量 (>=1)。
    *   `rerank_top_n` (int, 可选)：重排后返回的最终文档数量 (>=1)。
    *   `hybrid_alpha` (float, 可选)：混合搜索权重 (0.0-1.0)。
*   **响应**：`QueryResponse` (query, answer, source\_documents)

### 3. 删除知识库集合 (`/knowledge_base/{collection_name}`)

*   **功能**：删除 Milvus 中指定的知识库集合及其所有数据。
*   **HTTP 方法**：`DELETE`
*   **路径参数**：
    *   `collection_name` (str, 必填)：要删除的 Milvus 集合的名称。
*   **响应**：`dict` (message)

### 4. 健康检查 (`/health`)

*   **功能**：简单的健康检查接口，用于判断服务是否正常运行。
*   **HTTP 方法**：`GET`
*   **响应**：`dict` (status: "ok")

## 部署注意事项和优化建议

### 1. 环境变量配置

在生产环境中，务必配置以下环境变量：

*   `MILVUS_HOST`：Milvus 服务的主机地址。
*   `MILVUS_PORT`：Milvus 服务的端口。
*   `EMBEDDING_BASE_URL`：嵌入模型服务的 URL。
*   `RERANK_BASE_URL`：重排模型服务的 URL。
*   `RERANK_API_KEY`：重排模型服务的 API 密钥。
*   `OPENAI_API_KEY`：LLM 和 Embedding 模型使用的 API 密钥。
*   `LOG_LEVEL`：日志级别（例如 `INFO`, `WARNING`, `ERROR`）。

建议使用 Docker 或 Kubernetes 进行部署，并通过配置管理工具（如 Kubernetes Secrets）安全地管理这些环境变量。

### 2. 高并发场景优化

*   **异步编程**：FastAPI 结合 `async/await` 语法，确保 I/O 密集型操作（如文档加载、HTTP 请求到模型服务、Milvus 交互）不会阻塞主事件循环，从而提高并发处理能力。本项目已将核心服务中的阻塞操作转换为异步模式。
*   **模型服务独立部署**：嵌入模型和重排模型应作为独立服务部署，并通过高性能的 API 网关进行访问，以实现负载均衡和弹性伸缩。
*   **Milvus 性能调优**：
    *   **索引优化**：根据数据量和查询模式，调整 Milvus 的索引参数（例如 `IVF_FLAT` 的 `nlist`，`HNSW` 的 `M` 和 `efConstruction`）。
    *   **硬件资源**：为 Milvus 分配足够的 CPU、内存和存储资源。
    *   **分片和副本**：在生产环境中，考虑 Milvus 的分片（sharding）和副本（replica）机制，以提高吞吐量和可用性。
*   **批量处理**：文档摄取已采用批量处理机制，减少了与 Milvus 的交互次数，提高了效率。
*   **连接池**：Milvus 客户端和 `httpx` 内部通常会管理连接池，确保高效的连接复用。

### 3. 健壮性和错误处理

*   **Pydantic 验证**：所有 API 请求参数都通过 Pydantic 模型进行严格的数据类型和值验证，确保输入数据的合法性。
*   **细粒度异常处理**：在核心服务和 API 路由中，已将通用的 `Exception` 捕获替换为更具体的异常类型（如 `FileNotFoundError`, `httpx.HTTPStatusError`），并向客户端返回通用错误消息，同时在日志中记录详细的错误堆栈，防止敏感信息泄露。
*   **日志记录**：使用 `logging` 模块进行详细的日志记录，包括请求信息、处理状态和错误详情。建议将日志输出到标准输出，并通过日志收集系统（如 ELK Stack, Grafana Loki）进行集中管理和监控。
*   **健康检查**：提供 `/health` 接口，便于容器编排系统（如 Kubernetes）进行健康探测和自动恢复。

### 4. 安全性

*   **API 密钥管理**：所有敏感的 API 密钥都通过环境变量加载，并建议使用安全的密钥管理服务。在代码中避免硬编码敏感信息。
*   **HTTPS**：在生产环境中，务必为 FastAPI 应用程序配置 HTTPS，以加密客户端和服务器之间的通信。
*   **访问控制**：根据需求，可以考虑在 API 网关层或 FastAPI 应用程序内部添加认证和授权机制（例如 OAuth2, JWT），以限制对敏感接口的访问。

### 5. 未来优化（第一阶段不考虑）

*   **缓存机制**：引入缓存层（如 Redis）来存储频繁查询的结果或中间计算结果，减少对 Milvus 和 LLM 的重复请求，进一步提高响应速度和降低成本。
*   **监控和告警**：集成 Prometheus/Grafana 等监控工具，收集应用程序性能指标，并设置告警规则，及时发现和解决生产问题。
*   **链路追踪**：引入 OpenTelemetry 等链路追踪工具，方便在分布式系统中追踪请求的完整生命周期，定位性能瓶颈和错误。
*   **LLM 异步调用**：如果 LLM 客户端支持异步调用，可以进一步优化 `rag_chain` 的执行，使其完全非阻塞。

## 如何运行

1.  **克隆项目**：
    ```bash
    git clone <项目仓库地址>
    cd rag
    ```
2.  **创建并激活虚拟环境**：
    ```bash
    python -m venv venv
    source venv/bin/activate # macOS/Linux
    # venv\Scripts\activate # Windows
    ```
3.  **安装依赖**：
    ```bash
    pip install -r requirements.txt
    ```
4.  **配置环境变量**：
    在项目根目录创建 `.env` 文件，并填入必要的配置（例如 Milvus 地址、模型 API 密钥等）。
    ```dotenv
    MILVUS_HOST=localhost
    MILVUS_PORT=19530
    EMBEDDING_BASE_URL=http://localhost:8000/v1
    RERANK_BASE_URL=http://localhost:8001/v1
    RERANK_API_KEY=your_rerank_api_key
    OPENAI_API_KEY=your_openai_api_key
    LOG_LEVEL=INFO
    ```
    请根据实际部署的模型服务地址和 API 密钥进行修改。

5.  **准备知识库文档**：
    将您的 Markdown (`.md`) 和 PDF (`.pdf`) 文档放入 `knowledge_base_documents/` 目录。

6.  **启动 Milvus 服务**：
    确保您的 Milvus 向量数据库服务正在运行。您可以使用 Docker 启动一个 Milvus 实例：
    ```bash
    docker run -d --name milvus_standalone -e MILVUS_PORT=19530 -p 19530:19530 -p 9091:9091 milvusdb/milvus:v2.3.0
    ```
    （请根据 Milvus 官方文档获取最新和推荐的部署方式）

7.  **启动模型服务**：
    确保您的嵌入模型和重排模型服务正在运行，并且可以通过 `EMBEDDING_BASE_URL` 和 `RERANK_BASE_URL` 访问。例如，如果您使用 BGE 模型，可能需要启动相应的推理服务。

8.  **运行 FastAPI 应用程序**：
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ```
    `--reload` 选项在开发时很有用，生产环境部署时应移除。

9.  **访问 API 文档**：
    服务启动后，您可以通过浏览器访问：`http://localhost:8000/docs` 查看 OpenAPI (Swagger UI) 文档，并测试 API 接口。
