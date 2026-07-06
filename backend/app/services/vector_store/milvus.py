import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.core.config import settings

from .base import BaseVectorStore

logger = logging.getLogger(__name__)


def build_milvus_filter_expr(filters: Optional[Dict[str, Any]]) -> str:
    """Build a Milvus boolean expression from simple scalar metadata filters.

    Args:
        filters: Equality, list-membership, or range operator filters.

    Returns:
        A Milvus filter expression string. Empty string means no filter.
    """
    if not filters:
        return ""

    expressions: List[str] = []
    for field, value in filters.items():
        if value is None or value == "":
            continue

        # Dict values support the small operator set needed by effective_date filters.
        if isinstance(value, dict):
            for operator, operand in value.items():
                if operand is None or operand == "":
                    continue
                milvus_operator = {
                    "$gte": ">=",
                    "$gt": ">",
                    "$lte": "<=",
                    "$lt": "<",
                    "$ne": "!=",
                    "$eq": "==",
                }.get(operator)
                if milvus_operator:
                    expressions.append(f"{field} {milvus_operator} {_format_milvus_value(operand)}")
            continue

        # List values map to Milvus `in` expressions for fields like kb_id/doc_type.
        if isinstance(value, (list, tuple, set)):
            values = [_format_milvus_value(item) for item in value if item is not None and item != ""]
            if values:
                expressions.append(f"{field} in [{', '.join(values)}]")
            continue

        expressions.append(f"{field} == {_format_milvus_value(value)}")

    return " and ".join(expressions)


def build_milvus_jieba_analyzer_params() -> Dict[str, Any]:
    """Return analyzer params for Chinese BM25 full-text search in Milvus."""
    return {
        "tokenizer": settings.MILVUS_TEXT_ANALYZER or "jieba",
        "filter": ["lowercase"],
    }


def _format_milvus_value(value: Any) -> str:
    """Format a Python scalar for a Milvus boolean expression."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    # json.dumps handles quotes and backslashes in Chinese file names or section paths.
    return json.dumps(str(value), ensure_ascii=False)


class MilvusVectorStore(BaseVectorStore):
    """Milvus vector store implementation for production-style scalar filtering."""

    def __init__(self, collection_name: str, embedding_function: Embeddings, **kwargs):
        """Initialize Milvus vector store without forcing a connection at import time."""
        self.collection_name = collection_name
        self.embedding_function = embedding_function
        self.dimension = kwargs.get("dimension") or settings.MILVUS_DIMENSION
        self._client = None

    @property
    def client(self):
        """Lazily create the Milvus client so Chroma-only local development still works."""
        if self._client is None:
            try:
                from pymilvus import MilvusClient
            except ImportError as exc:
                raise RuntimeError("pymilvus is required when VECTOR_STORE_TYPE=milvus") from exc

            token = settings.MILVUS_TOKEN or None
            self._client = MilvusClient(
                uri=settings.MILVUS_URI,
                token=token,
                db_name=settings.MILVUS_DB_NAME,
            )
        return self._client

    def ensure_collection(self) -> None:
        """Ensure the Milvus collection and vector index exist."""
        if self.client.has_collection(self.collection_name):
            return

        dimension = self._resolve_dimension()
        from pymilvus import DataType

        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=dimension)
        self._add_text_field(schema, DataType)
        if settings.MILVUS_ENABLE_SPARSE:
            # learned sparse 和 BM25 sparse 分字段存储，便于面试时清晰解释两种方案。
            schema.add_field(field_name=settings.MILVUS_SPARSE_FIELD, datatype=DataType.SPARSE_FLOAT_VECTOR)
            schema.add_field(field_name=settings.MILVUS_BM25_FIELD, datatype=DataType.SPARSE_FLOAT_VECTOR)
            self._try_add_bm25_function(schema)
        schema.add_field(field_name="kb_id", datatype=DataType.INT64)
        schema.add_field(field_name="document_id", datatype=DataType.INT64)
        schema.add_field(field_name="parent_id", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="file_name", datatype=DataType.VARCHAR, max_length=1024)
        schema.add_field(field_name="doc_type", datatype=DataType.VARCHAR, max_length=100)
        schema.add_field(field_name="department", datatype=DataType.VARCHAR, max_length=100)
        schema.add_field(field_name="effective_date", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="section_path", datatype=DataType.VARCHAR, max_length=2048)
        schema.add_field(field_name="page", datatype=DataType.INT64)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type=settings.MILVUS_METRIC_TYPE,
        )
        if settings.MILVUS_ENABLE_SPARSE:
            self._try_add_sparse_index(index_params, settings.MILVUS_SPARSE_FIELD)
            self._try_add_sparse_index(index_params, settings.MILVUS_BM25_FIELD)
        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )

    def add_documents(self, documents: List[Document], ids: Optional[List[str]] = None) -> None:
        """Embed and upsert child documents into Milvus."""
        if not documents:
            return

        self.ensure_collection()
        vectors = self.embedding_function.embed_documents([doc.page_content for doc in documents])
        sparse_vectors = self._embed_sparse_documents([doc.page_content for doc in documents])
        rows = []
        for index, doc in enumerate(documents):
            metadata = doc.metadata or {}
            chunk_id = (ids[index] if ids else metadata.get("chunk_id")) or metadata.get("id")
            if not chunk_id:
                raise ValueError("Milvus add_documents requires stable chunk IDs.")

            # Store only child text in Milvus; parent text remains in MySQL DocStore.
            row = {
                "id": str(chunk_id),
                "vector": vectors[index],
                "text": doc.page_content[:65535],
                "kb_id": int(metadata.get("kb_id") or 0),
                "document_id": int(metadata.get("document_id") or 0),
                "parent_id": str(metadata.get("parent_id") or ""),
                "chunk_id": str(chunk_id),
                "file_name": str(metadata.get("file_name") or metadata.get("source") or ""),
                "doc_type": str(metadata.get("doc_type") or ""),
                "department": str(metadata.get("department") or ""),
                "effective_date": str(metadata.get("effective_date") or ""),
                "section_path": str(metadata.get("section_path") or "")[:2048],
                "page": int(metadata.get("page") or 0),
                **{f"meta_{key}": value for key, value in metadata.items() if _is_dynamic_scalar(value)},
            }
            if index < len(sparse_vectors):
                # BGE-M3 learned sparse 向量只在依赖可用时写入；BM25 sparse 由 Milvus function 生成。
                row[settings.MILVUS_SPARSE_FIELD] = sparse_vectors[index]
            rows.append(row)

        self.client.upsert(collection_name=self.collection_name, data=rows)

    def delete(self, ids: List[str]) -> None:
        """Delete Milvus rows by primary key IDs."""
        if not ids or not self.client.has_collection(self.collection_name):
            return
        self.client.delete(collection_name=self.collection_name, ids=[str(item) for item in ids])

    def delete_by_filter(self, filters: Dict[str, Any]) -> None:
        """Delete Milvus rows by scalar filter expression."""
        expr = build_milvus_filter_expr(filters)
        if not expr or not self.client.has_collection(self.collection_name):
            return
        self.client.delete(collection_name=self.collection_name, filter=expr)

    def as_retriever(self, **kwargs: Any):
        """Return a minimal retriever adapter for legacy LangChain call sites."""
        vector_store = self

        class _MilvusRetriever:
            """Small adapter exposing the retriever methods used by LangChain helpers."""

            def invoke(self, query: str) -> List[Document]:
                """Synchronously retrieve documents for a query."""
                search_kwargs = kwargs.get("search_kwargs", {})
                return vector_store.similarity_search(
                    query=query,
                    k=search_kwargs.get("k", 4),
                    filters=search_kwargs.get("filters"),
                )

            async def ainvoke(self, payload: Dict[str, Any]) -> List[Document]:
                """Asynchronously retrieve documents for history-aware wrappers."""
                query = payload.get("input") if isinstance(payload, dict) else str(payload)
                return self.invoke(query)

        return _MilvusRetriever()

    def similarity_search(
        self,
        query: str,
        k: int = 4,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> List[Document]:
        """Search Milvus and return LangChain documents."""
        return [doc for doc, _score in self.similarity_search_with_score(query, k, filters, **kwargs)]

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> List[Tuple[Document, float]]:
        """Search Milvus and return documents with vector scores."""
        if not self.client.has_collection(self.collection_name):
            return []

        query_vector = self.embedding_function.embed_query(query)
        expr = build_milvus_filter_expr(filters)
        results = self.client.search(
            collection_name=self.collection_name,
            data=[query_vector],
            anns_field=settings.MILVUS_DENSE_FIELD,
            limit=k,
            filter=expr or "",
            output_fields=self._output_fields(),
            search_params={"metric_type": settings.MILVUS_METRIC_TYPE},
        )

        return self._hits_to_documents(results)

    def sparse_search_with_score(
        self,
        query: str,
        k: int = 4,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Tuple[Document, float]]:
        """Search learned sparse vectors generated by BGE-M3."""
        if not settings.MILVUS_ENABLE_SPARSE or not self.client.has_collection(self.collection_name):
            return []

        sparse_queries = self._embed_sparse_queries([query])
        if not sparse_queries:
            return []

        expr = build_milvus_filter_expr(filters)
        results = self.client.search(
            collection_name=self.collection_name,
            data=sparse_queries,
            anns_field=settings.MILVUS_SPARSE_FIELD,
            limit=k,
            filter=expr or "",
            output_fields=self._output_fields(),
            search_params={"metric_type": "IP"},
        )
        return self._hits_to_documents(results)

    def bm25_search_with_score(
        self,
        query: str,
        k: int = 4,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Tuple[Document, float]]:
        """Search Milvus BM25 sparse field generated from analyzed text."""
        if not settings.MILVUS_ENABLE_SPARSE or not self.client.has_collection(self.collection_name):
            return []

        expr = build_milvus_filter_expr(filters)
        results = self.client.search(
            collection_name=self.collection_name,
            data=[query],
            anns_field=settings.MILVUS_BM25_FIELD,
            limit=k,
            filter=expr or "",
            output_fields=self._output_fields(),
            search_params={"metric_type": "BM25"},
        )
        return self._hits_to_documents(results)

    def _hits_to_documents(self, results: Any) -> List[Tuple[Document, float]]:
        """Convert Milvus hits to LangChain documents with scores."""
        documents: List[Tuple[Document, float]] = []
        for hit in results[0] if results else []:
            entity = _extract_entity(hit)
            score = _extract_score(hit)
            metadata = {key: value for key, value in entity.items() if key != "text"}
            documents.append((Document(page_content=entity.get("text", ""), metadata=metadata), score))
        return documents

    def delete_collection(self) -> None:
        """Delete the entire Milvus collection."""
        if self.client.has_collection(self.collection_name):
            self.client.drop_collection(self.collection_name)

    def _resolve_dimension(self) -> int:
        """Resolve embedding dimension from config or a one-time probe call."""
        if self.dimension:
            return int(self.dimension)

        # A probe avoids hardcoding model dimensions when switching embedding providers.
        self.dimension = len(self.embedding_function.embed_query("dimension probe"))
        return int(self.dimension)

    def _output_fields(self) -> List[str]:
        """Return scalar fields required by citations, filters, and trace panels."""
        return [
            "text",
            "kb_id",
            "document_id",
            "parent_id",
            "chunk_id",
            "file_name",
            "doc_type",
            "department",
            "effective_date",
            "section_path",
            "page",
        ]

    def _add_text_field(self, schema: Any, data_type: Any) -> None:
        """Add text field with jieba analyzer when the installed pymilvus supports it."""
        try:
            schema.add_field(
                field_name="text",
                datatype=data_type.VARCHAR,
                max_length=65535,
                enable_analyzer=True,
                analyzer_params=build_milvus_jieba_analyzer_params(),
            )
        except TypeError:
            # 旧版 pymilvus 不接受 analyzer 参数时保留普通文本字段，BM25 自动降级为不可用。
            schema.add_field(field_name="text", datatype=data_type.VARCHAR, max_length=65535)

    def _try_add_bm25_function(self, schema: Any) -> None:
        """Attach a Milvus BM25 function when the client version exposes Function APIs."""
        try:
            from pymilvus import Function, FunctionType

            bm25_function = Function(
                name="text_bm25_function",
                input_field_names=["text"],
                output_field_names=[settings.MILVUS_BM25_FIELD],
                function_type=FunctionType.BM25,
            )
            schema.add_function(bm25_function)
        except Exception as exc:
            logger.warning("Milvus BM25 function is unavailable, BM25 mode will fallback: %s", exc)

    def _try_add_sparse_index(self, index_params: Any, field_name: str) -> None:
        """Add sparse inverted index while tolerating older Milvus deployments."""
        try:
            index_params.add_index(
                field_name=field_name,
                index_type="SPARSE_INVERTED_INDEX",
                metric_type="IP",
            )
        except Exception as exc:
            logger.warning("Milvus sparse index for %s is unavailable: %s", field_name, exc)

    def _embed_sparse_documents(self, texts: List[str]) -> List[Any]:
        """Generate BGE-M3 sparse document embeddings when optional model extras exist."""
        if not settings.MILVUS_ENABLE_SPARSE or settings.MILVUS_HYBRID_MODE.lower() != "bge_m3":
            return []
        return self._embed_bge_m3_sparse(texts, mode="documents")

    def _embed_sparse_queries(self, texts: List[str]) -> List[Any]:
        """Generate BGE-M3 sparse query embeddings when optional model extras exist."""
        if not settings.MILVUS_ENABLE_SPARSE:
            return []
        return self._embed_bge_m3_sparse(texts, mode="queries")

    def _embed_bge_m3_sparse(self, texts: List[str], mode: str) -> List[Any]:
        """Call pymilvus model BGEM3 embedding function and normalize sparse output."""
        try:
            from pymilvus.model.hybrid import BGEM3EmbeddingFunction
        except Exception as exc:
            logger.warning("pymilvus[model] is required for BGE-M3 sparse vectors: %s", exc)
            return []

        if not hasattr(self, "_bge_m3_sparse_ef"):
            self._bge_m3_sparse_ef = BGEM3EmbeddingFunction(use_fp16=False, device="cpu")

        embeddings = self._bge_m3_sparse_ef(texts)
        if isinstance(embeddings, dict):
            sparse = embeddings.get("sparse") or embeddings.get("sparse_vectors") or []
            return list(sparse)
        if hasattr(embeddings, "get"):
            sparse = embeddings.get("sparse", [])
            return list(sparse)
        logger.warning("Unexpected BGE-M3 sparse embedding shape in %s mode", mode)
        return []


def _extract_entity(hit: Any) -> Dict[str, Any]:
    """Normalize Milvus search hit shapes across pymilvus client versions."""
    if isinstance(hit, dict):
        return dict(hit.get("entity") or hit)
    entity = getattr(hit, "entity", None)
    if isinstance(entity, dict):
        return dict(entity)
    return {}


def _extract_score(hit: Any) -> float:
    """Normalize Milvus search score across pymilvus client versions."""
    if isinstance(hit, dict):
        return float(hit.get("distance", hit.get("score", 0.0)) or 0.0)
    return float(getattr(hit, "distance", getattr(hit, "score", 0.0)) or 0.0)


def _is_dynamic_scalar(value: Any) -> bool:
    """Keep dynamic metadata limited to scalar values Milvus can index or return cheaply."""
    return isinstance(value, (str, int, float, bool)) or value is None
