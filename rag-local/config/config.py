from typing import Dict, Any
from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

# 从 .env 文件加载环境变量
load_dotenv()

@dataclass
class EmbeddingConfig:
    """
    嵌入模型配置。
    Attributes:
        base_url (str): 嵌入模型 API 的基础 URL。
        model_id (str): 嵌入模型的 ID。
        dimension (int): 嵌入向量的维度。默认为 1024。
        batch_size (int): 批量处理文档时的大小。默认为 32。
    """
    base_url: str
    model_id: str
    dimension: int
    batch_size: int
    api_key: str = os.getenv("EMBEDDING_API_KEY")


@dataclass
class LLMConfig:
    """
    LLM 模型配置。
    Attributes:
        base_url (str): LLM 模型 API 的基础 URL。
        model_id (str): LLM 模型的 ID。
        api_key (str): LLM 模型 API 的密钥。
    """
    base_url: str
    model_id: str
    api_key: str


@dataclass
class RerankConfig:
    """
    重排模型配置。
    Attributes:
        base_url (str): 重排模型 API 的基础 URL。
        model_id (str): 重排模型的 ID。
        mode: (str):重排模式  local  remote
        batch_size (int): 批量处理文档时的大小。默认为 32。
        top_n (int): 重排后返回的文档数量。默认为 5。
        api_key (str): 重排模型 API 的密钥。默认为 "sk-"。
    """
    base_url: str
    model_id: str
    mode: str
    batch_size: int
    top_n: int
    api_key: str = os.getenv("RERANK_API_KEY")

@dataclass
class MilvusConfig:
    """
    Milvus 向量数据库配置。
    Attributes:
        url (str): Milvus 服务的 URL (例如 "http://localhost:19530")。
        collection_name (str): 默认的 Milvus 集合名称。
        dimension (int): 向量的维度，应与嵌入模型的维度匹配。
        index_params (Dict[str, Any]): 密集向量索引参数。
        sparse_index_params (Dict[str, Any]): 稀疏向量索引参数。
        search_params (Dict[str, Any]): 搜索参数。
        batch_size (int): 批量插入文档时的大小。默认为 100。
    """
    url: "localhost:19530"
    collection_name: str
    dimension: int
    index_params: Dict[str, Any]
    sparse_index_params: Dict[str, Any]
    search_params: Dict[str, Any]
    batch_size: int


@dataclass
class MinioConfig:
    """
    Minio 存储配置。
    Attributes:
        endpoint (str): Minio 服务的端点。
        access_key (str): Minio 访问密钥。
        secret_key (str): Minio 访问密钥。
        bucket_name (str): Minio 存储桶名称。
    """
    endpoint: "localhost:9000"
    access_key: "minioadmin"
    secret_key: "minioadmin"
    bucket_name: "bigrag"

@dataclass
class AppConfig:
    """
    应用程序的整体配置。
    Attributes:
        document_path (Path): 知识库文档的存储路径。
        embedding (EmbeddingConfig): 嵌入模型配置实例。
        llm (LLMConfig): LLM 模型配置实例。
        rerank (RerankConfig): 重排模型配置实例。
        milvus (MilvusConfig): Milvus 向量数据库配置实例。
        minio (MinioConfig): Minio 存储配置实例。
        cache_dir (Path): 缓存目录路径。默认为 "cache"。
        log_level (str): 日志级别。默认为 "INFO"。
        chunk_size (int): 文本块的最大字符数。默认为 1000。
        chunk_overlap (int): 文本块之间的重叠字符数，用于保留上下文。默认为 200。
    """
    document_path: Path
    embedding: EmbeddingConfig
    llm: LLMConfig
    rerank: RerankConfig
    milvus: MilvusConfig
    minio: MinioConfig
    cache_dir: Path
    log_level: str
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "300"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "100"))

# Embedding 模型具体配置实例
EMBEDDING_CONFIG = EmbeddingConfig(
    base_url=os.getenv("EMBEDDING_BASE_URL"),
    model_id=os.getenv("EMBEDDING_MODEL_ID"),
    dimension=int(os.getenv("EMBEDDING_DIMENSION")),
    batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE")),
    api_key=os.getenv("EMBEDDING_API_KEY")
)

# LLM 模型具体配置实例
LLM_CONFIG = LLMConfig(
    base_url=os.getenv("LLM_BASE_URL"),
    model_id=os.getenv("LLM_MODEL_ID"),
    api_key=os.getenv("LLM_API_KEY","")
)

# Rerank 模型具体配置实例
RERANK_CONFIG = RerankConfig(
    base_url=os.getenv("RERANK_BASE_URL"),
    model_id=os.getenv("RERANK_MODEL_ID"),
    mode=os.getenv("RERANK_MODE"),
    batch_size=int(os.getenv("RERANK_BATCH_SIZE")),
    top_n=int(os.getenv("RERANK_TOP_N")),
    api_key=os.getenv("RERANK_API_KEY")
)

# Milvus 向量数据库具体配置实例
MILVUS_CONFIG = MilvusConfig(
    url=f"http://{os.getenv('MILVUS_HOST')}:{os.getenv('MILVUS_PORT')}",
    collection_name=os.getenv("MILVUS_COLLECTION_NAME"),
    dimension=int(os.getenv("MILVUS_DIMENSION")),
    index_params={
        "metric_type": "IP",   ## 距离度量方式（L2/IP）   # 改为 IP 度量（稀疏索引唯一支持的类型）
        "index_type": "FLAT",   # 索引类型 IVF_FLAT   改用最简单的 FLAT 索引，无参数问题
        #"params": {"nlist": 1024}   # # IVF_FLAT 仅需 nlist，移除 efConstruction
        "params":{},     # # 空参数，避免任何参数错误
    },
    # 稀疏索引参数（测试阶段可注释，避免干扰） # 改为 None，暂不启用稀疏索引
    sparse_index_params=None,
    # sparse_index_params={
    #     "index_type": "SPARSE_WKS",
    #     "metric_type": "IP",
    #     "params": {}
    # },
# 搜索参数（仅保留 nprobe，移除多余参数）
    search_params={
        "metric_type": "IP",   #搜索参数同步改为 IP
        "params": {"nprobe": 64}
    },
    batch_size=int(os.getenv("MILVUS_BATCH_SIZE"))
)

# Minio配置
MINIO_CONFIG = MinioConfig(
    endpoint=os.getenv("MINIO_ENDPOINT"),
    access_key=os.getenv("MINIO_ACCESS_KEY"),
    secret_key=os.getenv("MINIO_SECRET_KEY"),
    bucket_name=os.getenv("MINIO_BUCKET_NAME"),  # 新增：补充必填的桶名
    # secure=os.getenv("MINIO_SECURE", "False").lower() == "true"  # 可选：布尔值转换
)

# 应用程序的最终配置实例
APP_CONFIG = AppConfig(
    document_path=Path(os.getenv("DOCUMENT_PATH")),
    embedding=EMBEDDING_CONFIG,
    llm=LLM_CONFIG,
    rerank=RERANK_CONFIG,
    milvus=MILVUS_CONFIG,
    minio=MINIO_CONFIG,
    cache_dir=Path(os.getenv("CACHE_DIR")),
    log_level=os.getenv("LOG_LEVEL")
)

# 知识库文档路径，供其他模块直接导入使用
DOCUMENT_PATH = APP_CONFIG.document_path
