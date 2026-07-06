from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

class BaseVectorStore(ABC):
    """Abstract base class for vector store implementations"""
    
    @abstractmethod
    def __init__(self, collection_name: str, embedding_function: Embeddings, **kwargs):
        """Initialize the vector store"""
        pass
    
    @abstractmethod
    def ensure_collection(self) -> None:
        """Ensure the target collection exists before writes or searches."""
        pass

    @abstractmethod
    def add_documents(self, documents: List[Document], ids: Optional[List[str]] = None) -> None:
        """Add or update documents in the vector store."""
        pass
    
    @abstractmethod
    def delete(self, ids: List[str]) -> None:
        """Delete documents from the vector store"""
        pass

    @abstractmethod
    def delete_by_filter(self, filters: Dict[str, Any]) -> None:
        """Delete documents matched by scalar metadata filters."""
        pass
    
    @abstractmethod
    def as_retriever(self, **kwargs: Any):
        """Return a retriever interface for the vector store"""
        pass
    
    @abstractmethod
    def similarity_search(
        self,
        query: str,
        k: int = 4,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> List[Document]:
        """Search for similar documents"""
        pass
    
    @abstractmethod
    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> List[Tuple[Document, float]]:
        """Search for similar documents with score"""
        pass

    @abstractmethod
    def delete_collection(self) -> None:
        """Delete the entire collection"""
        pass
