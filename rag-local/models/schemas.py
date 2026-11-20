from typing import List, Optional
from pydantic import BaseModel, Field

from config.config import APP_CONFIG

class QueryRequest(BaseModel):
    """
    查询请求模型。
    Attributes:
        query (str): 用户查询文本。
        collection_name (str): Milvus 集合名称，默认为配置文件中的名称。
        k (int): 初步检索的文档数量。默认为 5。
        rerank_top_n (int): 重排后返回的最终文档数量。默认为 3。
        hybrid_alpha (float): 混合搜索权重 (0-1)，1 表示完全使用密集向量，0 表示完全使用稀疏向量。默认为 0.7。
    """
    query: str = Field(..., min_length=1, description="用户查询文本，不能为空。")
    collection_name: Optional[str] = Field(APP_CONFIG.milvus.collection_name, description="Milvus 集合名称，默认为配置文件中的名称。")
    k: Optional[int] = Field(5, ge=1, description="初步检索的文档数量，必须大于等于1。")
    rerank_top_n: Optional[int] = Field(3, ge=1, description="重排后返回的最终文档数量，必须大于等于1。")
    hybrid_alpha: Optional[float] = Field(0.7, ge=0.0, le=1.0, description="混合搜索权重 (0-1)，1 表示完全使用密集向量，0 表示完全使用稀疏向量。")

class IngestRequest(BaseModel):
    """
    文档摄取响应模型。
    Attributes:
        message (str): 摄取结果消息。
        documents_ingested (int): 成功摄取的文档数量。
        collection_name (str): 摄取文档的集合名称。
    """
    collection_name: Optional[str] = Field(APP_CONFIG.milvus.collection_name, description="Milvus 集合名称，默认为配置文件中的名称。")
    file_paths: List[str] = Field(..., min_items=1, description="要摄取的文档路径列表，不能为空。")

class IngestResponse(BaseModel):
    """
    文档摄取响应模型。
    Attributes:
        message (str): 摄取结果消息。
        documents_ingested (int): 成功摄取的文档数量。
        collection_name (str): 摄取文档的集合名称。
    """
    message: str
    documents_ingested: int
    collection_name: str

class QueryResponse(BaseModel):
    """
    查询响应模型。
    Attributes:
        query (str): 原始查询文本。
        answer (str): LLM 生成的答案。
        source_documents (List[dict]): 来源文档列表，包含文档内容片段和元数据。
    """
    query: str
    answer: str
    source_documents: List[dict]
