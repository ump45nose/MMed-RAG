from typing import List, Any, Optional, Dict, Tuple
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma
import chromadb 
from app.core.config import settings

from .base import BaseVectorStore

class ChromaVectorStore(BaseVectorStore):
    """Chroma vector store implementation"""
    
    def __init__(self, collection_name: str, embedding_function: Embeddings, **kwargs):
        """Initialize Chroma vector store"""
        chroma_client = chromadb.HttpClient(
            host=settings.CHROMA_DB_HOST,
            port=settings.CHROMA_DB_PORT,
        )
        
        self._store = Chroma(
            client=chroma_client,
            collection_name=collection_name,
            embedding_function=embedding_function,
        )

    def ensure_collection(self) -> None:
        """Chroma creates collections lazily through the LangChain wrapper."""
        return None

    def add_documents(self, documents: List[Document], ids: Optional[List[str]] = None) -> None:
        """Add documents to Chroma"""
        # Chroma supports stable IDs, which lets ingestion overwrite the same child chunk.
        if ids:
            self._store.add_documents(documents, ids=ids)
            return
        self._store.add_documents(documents)
    
    def delete(self, ids: List[str]) -> None:
        """Delete documents from Chroma"""
        self._store.delete(ids)

    def delete_by_filter(self, filters: Dict[str, Any]) -> None:
        """Delete Chroma documents that match simple scalar metadata filters."""
        if not filters:
            return

        # Chroma filter syntax accepts equality dictionaries for metadata fields.
        matched = self._store._collection.get(where=filters)
        matched_ids = matched.get("ids", []) if matched else []
        if matched_ids:
            self._store.delete(matched_ids)
    
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
        """Search for similar documents in Chroma"""
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
        """Search for similar documents in Chroma with score"""
        if filters:
            kwargs["filter"] = filters
        return self._store.similarity_search_with_score(query, k=k, **kwargs)

    def delete_collection(self) -> None:
        """Delete the entire collection"""
        self._store._client.delete_collection(self._store._collection.name)
