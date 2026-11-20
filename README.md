# Enterprise AI Assistant

An internship project portfolio that combines agent orchestration, retrieval-augmented generation, web research, streaming APIs, and backend service integration.

This repository is a sanitized portfolio version. Internal documents, production data, credentials, and deployment-specific secrets are intentionally excluded.

## Highlights

- **Agent orchestration**: plan tool calls, execute them, evaluate intermediate results, and produce a final answer.
- **Private knowledge retrieval**: ingest local documents, retrieve relevant passages with Milvus, optionally rerank results, and generate answers with an OpenAI-compatible LLM.
- **Web research**: search and extract public web sources with Tavily, filter and deduplicate sources, build an evidence list, and generate a Markdown report.
- **Streaming interaction**: expose Server-Sent Events (SSE) for incremental responses.
- **Service integration**: connect a Spring Boot API, Python services, Redis, Milvus, MinIO, and external LLM APIs.
- **Observability and safeguards**: record structured execution events, support cache layers, validate tool arguments, and fail clearly when a tool or model call is unavailable.

## Architecture

```text
Spring Boot API
    |
    +--> Agent service ----------------------+
             |                                |
             +--> RAG service ---------------+--> LLM / Redis / Milvus / MinIO
             |
             +--> Web report skill -----------> Tavily Search / Extract
```

## Repository layout

| Directory | Responsibility |
|---|---|
| `agent-service` | Agent planning, tool execution, evaluation, caching, and event logging |
| `big-model` | Spring Boot API, authentication-related endpoints, personnel queries, and SSE forwarding |
| `rag-local` | FastAPI RAG service with document ingestion, retrieval, reranking, and generation |
| `web-report-skill` | CLI workflow for web search, evidence construction, and report generation |

## Technology stack

- Python, FastAPI, OpenAI-compatible APIs
- LangChain, Milvus, MinIO, Redis
- Java 17, Spring Boot, MySQL
- Docker Compose

## Local setup

### 1. Start infrastructure

```bash
docker compose up -d
```

The compose file provides local development services such as Milvus, MinIO, MySQL, and Redis. Change all local passwords before using this setup outside a local machine.

### 2. Configure environment variables

Copy the example files and fill in your own credentials:

```bash
cp agent-service/.env.example agent-service/.env
cp rag-local/.env.example rag-local/.env
cp web-report-skill/.env.example web-report-skill/.env
```

Never commit `.env` files or real API keys.

### 3. Start the services

Start `rag-local`, `web-report-skill`, and `agent-service` with their module-level commands. Then start the Java API:

```bash
cd big-model
./mvnw spring-boot:run
```

The exact ports and service URLs are configurable through environment variables.

## Data and security

- No internal company documents or employee records are included.
- No API keys, passwords, or production endpoints are included.
- Bring your own documents and model credentials for local experiments.
- The default configuration is for local development and should be reviewed before deployment.

## Scope and limitations

This repository focuses on system design and implementation patterns. It does not provide a hosted demo, production credentials, or a complete public dataset. Some integrations require external services and API keys.

## Author

[ZhangZKon](https://github.com/ZhangZKon)
