import os
from typing import List, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "RAG Web UI"  # Project name
    VERSION: str = "0.1.0"  # Project version
    API_V1_STR: str = "/api"  # API version string

    # MySQL settings
    MYSQL_SERVER: str = os.getenv("MYSQL_SERVER", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "ragwebui")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "ragwebui")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "ragwebui")
    SQLALCHEMY_DATABASE_URI: Optional[str] = None

    @property
    def get_database_url(self) -> str:
        if self.SQLALCHEMY_DATABASE_URI:
            return self.SQLALCHEMY_DATABASE_URI
        return (
            f"mysql+mysqlconnector://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_SERVER}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        )

    # JWT settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

    # Runtime timezone setting
    TZ: str = os.getenv("TZ", "Asia/Shanghai")

    # Chat Provider settings
    CHAT_PROVIDER: str = os.getenv("CHAT_PROVIDER", "openai")

    # Embeddings settings
    EMBEDDINGS_PROVIDER: str = os.getenv("EMBEDDINGS_PROVIDER", "openai")

    # Retrieval settings
    RETRIEVAL_TOP_K: int = int(os.getenv("RETRIEVAL_TOP_K", "4"))
    RETRIEVAL_PARENT_TOP_K: int = int(os.getenv("RETRIEVAL_PARENT_TOP_K", "5"))
    RETRIEVAL_CHILD_CANDIDATES_K: int = int(os.getenv("RETRIEVAL_CHILD_CANDIDATES_K", "20"))
    RETRIEVAL_MODE: str = os.getenv("RETRIEVAL_MODE", "dense")
    SPLITTER_MODE: str = os.getenv("SPLITTER_MODE", "domain_parent")
    KB_ROUTER_ENABLED: bool = os.getenv("KB_ROUTER_ENABLED", "false").lower() == "true"
    KB_ROUTER_LLM_ENABLED: bool = os.getenv("KB_ROUTER_LLM_ENABLED", "false").lower() == "true"
    RERANK_PROVIDER: str = os.getenv("RERANK_PROVIDER", "none")
    RERANK_TOP_N: int = int(os.getenv("RERANK_TOP_N", "4"))
    RERANK_CANDIDATES_K: int = int(os.getenv("RERANK_CANDIDATES_K", "8"))
    RRF_RANK_CONSTANT: int = int(os.getenv("RRF_RANK_CONSTANT", "60"))
    RETRIEVAL_CONFIDENCE_THRESHOLD: float = float(os.getenv("RETRIEVAL_CONFIDENCE_THRESHOLD", "0.20"))
    RETRIEVAL_REFUSAL_ENABLED: bool = os.getenv("RETRIEVAL_REFUSAL_ENABLED", "true").lower() == "true"
    DEFAULT_ALLOWED_DEPARTMENTS: str = os.getenv("DEFAULT_ALLOWED_DEPARTMENTS", "医工,后勤,其他,")

    # MinIO settings
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    MINIO_BUCKET_NAME: str = os.getenv("MINIO_BUCKET_NAME", "documents")

    # OpenAI settings
    OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "your-openai-api-key-here")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4")
    OPENAI_EMBEDDINGS_MODEL: str = os.getenv("OPENAI_EMBEDDINGS_MODEL", "text-embedding-ada-002")

    # SiliconFlow settings
    SILICONFLOW_API_BASE: str = os.getenv("SILICONFLOW_API_BASE", "https://api.siliconflow.cn/v1")
    SILICONFLOW_API_KEY: str = os.getenv("SILICONFLOW_API_KEY", "")
    SILICONFLOW_EMBEDDINGS_MODEL: str = os.getenv("SILICONFLOW_EMBEDDINGS_MODEL", "BAAI/bge-m3")
    SILICONFLOW_RERANK_MODEL: str = os.getenv("SILICONFLOW_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

    # DashScope settings
    DASH_SCOPE_API_KEY: str = os.getenv("DASH_SCOPE_API_KEY", "")
    DASH_SCOPE_EMBEDDINGS_MODEL: str = os.getenv("DASH_SCOPE_EMBEDDINGS_MODEL", "")

    # Vector Store settings
    VECTOR_STORE_TYPE: str = os.getenv("VECTOR_STORE_TYPE", "chroma")

    # Chroma DB settings
    CHROMA_DB_HOST: str = os.getenv("CHROMA_DB_HOST", "chromadb")
    CHROMA_DB_PORT: int = int(os.getenv("CHROMA_DB_PORT", "8000"))

    # Qdrant DB settings
    QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    QDRANT_PREFER_GRPC: bool = os.getenv("QDRANT_PREFER_GRPC", "true").lower() == "true"

    # Milvus settings
    MILVUS_URI: str = os.getenv("MILVUS_URI", "http://localhost:19530")
    MILVUS_TOKEN: str = os.getenv("MILVUS_TOKEN", "")
    MILVUS_DB_NAME: str = os.getenv("MILVUS_DB_NAME", "default")
    MILVUS_DIMENSION: int = int(os.getenv("MILVUS_DIMENSION", "0"))
    MILVUS_METRIC_TYPE: str = os.getenv("MILVUS_METRIC_TYPE", "COSINE")
    MILVUS_ENABLE_SPARSE: bool = os.getenv("MILVUS_ENABLE_SPARSE", "true").lower() == "true"
    MILVUS_DENSE_FIELD: str = os.getenv("MILVUS_DENSE_FIELD", "vector")
    MILVUS_SPARSE_FIELD: str = os.getenv("MILVUS_SPARSE_FIELD", "sparse_vector")
    MILVUS_BM25_FIELD: str = os.getenv("MILVUS_BM25_FIELD", "bm25_sparse_vector")
    MILVUS_TEXT_ANALYZER: str = os.getenv("MILVUS_TEXT_ANALYZER", "jieba")
    MILVUS_HYBRID_MODE: str = os.getenv("MILVUS_HYBRID_MODE", "bge_m3")

    # Metadata suggestion settings
    METADATA_LLM_ENABLED: bool = os.getenv("METADATA_LLM_ENABLED", "false").lower() == "true"

    # Deepseek settings
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_API_BASE: str = "https://api.deepseek.com/v1"  # 默认 API 地址
    DEEPSEEK_MODEL: str = "deepseek-chat"  # 默认模型名称

    # MiniMax settings
    MINIMAX_API_KEY: str = ""
    MINIMAX_API_BASE: str = "https://api.minimax.io/v1"
    MINIMAX_MODEL: str = "MiniMax-M2.7"

    # Ollama settings
    OLLAMA_API_BASE: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "deepseek-r1:7b"
    OLLAMA_EMBEDDINGS_MODEL: str = os.getenv(
        "OLLAMA_EMBEDDINGS_MODEL", "nomic-embed-text"
    )  # Added this line

    # HuggingFace settings
    HUGGINGFACE_API_KEY: str = os.getenv("HUGGINGFACE_API_KEY", "")
    HUGGINGFACE_EMBEDDINGS_MODEL: str = os.getenv(
        "HUGGINGFACE_EMBEDDINGS_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )

    class Config:
        env_file = ".env"


settings = Settings()
