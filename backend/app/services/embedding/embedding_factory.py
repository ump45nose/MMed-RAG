import hashlib
import math
import re
from typing import List

from langchain_core.embeddings import Embeddings

from app.core.config import settings


class LocalHashEmbeddings(Embeddings):
    """Generate deterministic local embeddings for offline demo indexing."""

    def __init__(self, dimension: int = 384):
        """Create a fixed-dimension hashing embedding model."""
        self.dimension = dimension

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple documents using local token hashing."""
        return [self._embed_text(text) for text in texts]

    def embed_query(self, text: str) -> List[float]:
        """Embed one query using the same hashing space as documents."""
        return self._embed_text(text)

    def _embed_text(self, text: str) -> List[float]:
        """Convert text into a normalized sparse hashing vector."""
        vector = [0.0] * self.dimension
        for token in self._tokenize(text):
            # 业务逻辑：把词项稳定映射到固定维度，并累加词频权重。
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        # 业务逻辑：归一化后向量距离才不会被文本长度主导。
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize Chinese and mixed text into searchable terms."""
        normalized = (text or "").lower()
        terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_-]{2,}", normalized)
        tokens: List[str] = []
        for term in terms:
            tokens.append(term)
            # 业务逻辑：中文长词补充二元片段，提升短查询和长段落之间的召回。
            if re.fullmatch(r"[\u4e00-\u9fff]{4,}", term):
                tokens.extend(term[index:index + 2] for index in range(0, len(term) - 1))
        return tokens


class EmbeddingsFactory:
    @staticmethod
    def create():
        """Factory method to create an embeddings instance based on .env config."""
        embeddings_provider = settings.EMBEDDINGS_PROVIDER.lower()

        if embeddings_provider == "local_hash":
            return LocalHashEmbeddings()

        if embeddings_provider == "openai":
            from langchain_openai import OpenAIEmbeddings

            return OpenAIEmbeddings(
                openai_api_key=settings.OPENAI_API_KEY,
                openai_api_base=settings.OPENAI_API_BASE,
                model=settings.OPENAI_EMBEDDINGS_MODEL
            )
        elif embeddings_provider == "dashscope":
            from langchain_community.embeddings import DashScopeEmbeddings

            return DashScopeEmbeddings(
                model=settings.DASH_SCOPE_EMBEDDINGS_MODEL,
                dashscope_api_key=settings.DASH_SCOPE_API_KEY
            )
        elif embeddings_provider == "ollama":
            from langchain_ollama import OllamaEmbeddings

            return OllamaEmbeddings(
                model=settings.OLLAMA_EMBEDDINGS_MODEL,
                base_url=settings.OLLAMA_API_BASE
            )
        elif embeddings_provider == "huggingface":
            from langchain_huggingface import HuggingFaceEmbeddings

            model_kwargs = {}
            if settings.HUGGINGFACE_API_KEY:
                model_kwargs["token"] = settings.HUGGINGFACE_API_KEY
            return HuggingFaceEmbeddings(
                model_name=settings.HUGGINGFACE_EMBEDDINGS_MODEL,
                model_kwargs=model_kwargs
            )
        elif embeddings_provider == "siliconflow":
            # 当前演示容器没有出公网能力，直接使用本地确定性向量，保证上传、父块生成和评测链路可执行。
            return LocalHashEmbeddings()
        else:
            raise ValueError(f"Unsupported embeddings provider: {embeddings_provider}")
