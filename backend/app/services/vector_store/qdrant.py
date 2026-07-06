from typing import List, Any, Optional, Dict, Tuple
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from app.core.config import settings

from .base import BaseVectorStore

class QdrantStore(BaseVectorStore):
    """Qdrant vector store implementation"""
    
    def __init__(self, collection_name: str, embedding_function: Embeddings, **kwargs):
        """Initialize Qdrant vector store"""
        # Qdrant 是可选向量库，延迟导入避免 Chroma/Milvus 场景被未安装依赖阻断。
        try:
            from langchain_community.vectorstores import Qdrant
        except ImportError as exc:
            raise RuntimeError("langchain-community with Qdrant support is required when VECTOR_STORE_TYPE=qdrant") from exc

        self._store = Qdrant(
            collection_name=collection_name,
            embeddings=embedding_function,
            url=settings.QDRANT_URL,
            prefer_grpc=settings.QDRANT_PREFER_GRPC
        )

    def ensure_collection(self) -> None:
        """Qdrant collection creation is handled by the LangChain wrapper."""
        return None
    
    def add_documents(self, documents: List[Document], ids: Optional[List[str]] = None) -> None:
        """Add documents to Qdrant"""
        # Stable IDs keep child chunks idempotent across re-indexing.
        if ids:
            self._store.add_documents(documents, ids=ids)
            return
        self._store.add_documents(documents)
    
    def delete(self, ids: List[str]) -> None:
        """Delete documents from Qdrant"""
        self._store.delete(ids)

    def delete_by_filter(self, filters: Dict[str, Any]) -> None:
        """Delete by filter for Qdrant is intentionally conservative in this demo."""
        raise NotImplementedError("Qdrant delete_by_filter requires a Qdrant Filter object.")
    
    def as_retriever(self, **kwargs: Any):
        """Return a retriever interface"""
        return self._store.as_retriever(**kwargs)
    
    def similarity_search(
        self,
        query: str,
        k: int = 4,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> List[Document]:
        """Search for similar documents in Qdrant"""
        if filters:
            kwargs["filter"] = filters
        return self._store.similarity_search(query, k=k, **kwargs)
    
    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> List[Tuple[Document, float]]:
        """Search for similar documents in Qdrant with score"""
        if filters:
            kwargs["filter"] = filters
        return self._store.similarity_search_with_score(query, k=k, **kwargs)

    def delete_collection(self) -> None:
        """Delete the entire collection"""
        self._store._client.delete_collection(self._store._collection_name)
