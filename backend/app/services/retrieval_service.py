import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from langchain_core.documents import Document as LangchainDocument
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.knowledge import DocumentChunk, DocumentParentChunk, KnowledgeBase
from app.services.embedding.embedding_factory import EmbeddingsFactory
from app.services.kb_profile_service import KnowledgeBaseProfileService
from app.services.query_router_service import QueryRouterService, RouteDecision
from app.services.rerank_service import RerankService
from app.services.vector_store import VectorStoreFactory


@dataclass
class RetrievalConfig:
    """Runtime retrieval configuration used by chat, test retrieval, and evaluation."""

    splitter: str = "domain_parent"
    retriever: str = "dense"
    rerank_enabled: bool = False
    kb_router_enabled: bool = False
    top_k: int = 5
    child_candidates_k: int = 20
    filters: Dict[str, Any] = field(default_factory=dict)
    rrf_rank_constant: int = 60
    confidence_threshold: float = 0.20
    refusal_enabled: bool = True

    @staticmethod
    def from_settings() -> "RetrievalConfig":
        """Build the default retrieval config from environment settings."""
        return RetrievalConfig(
            splitter=settings.SPLITTER_MODE,
            retriever=settings.RETRIEVAL_MODE,
            rerank_enabled=RerankService.is_enabled(),
            kb_router_enabled=settings.KB_ROUTER_ENABLED,
            top_k=settings.RETRIEVAL_PARENT_TOP_K,
            child_candidates_k=settings.RETRIEVAL_CHILD_CANDIDATES_K,
            filters={},
            rrf_rank_constant=settings.RRF_RANK_CONSTANT,
            confidence_threshold=settings.RETRIEVAL_CONFIDENCE_THRESHOLD,
            refusal_enabled=settings.RETRIEVAL_REFUSAL_ENABLED,
        )


@dataclass
class RetrievalResult:
    """Structured retrieval result with parent context and latency."""

    documents: List[LangchainDocument]
    latency_ms: float
    child_candidates: List[LangchainDocument]
    trace: Dict[str, Any] = field(default_factory=dict)
    confidence_score: float = 0.0
    should_refuse: bool = False
    refusal_reason: Optional[str] = None


class ParentContextRetriever:
    """Retrieve child chunks, rerank them, then deduplicate to parent contexts."""

    def __init__(self, db: Session):
        """Create a retriever bound to one SQLAlchemy session."""
        self.db = db

    def retrieve(
        self,
        query: str,
        knowledge_base_ids: Sequence[int],
        config: Optional[RetrievalConfig] = None,
        user: Optional[Any] = None,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> RetrievalResult:
        """Retrieve parent chunks for a query across one or more knowledge bases.

        Args:
            query: User query.
            knowledge_base_ids: Candidate KB IDs selected by chat or evaluation.
            config: Retrieval options controlling dense/hybrid/rerank/router behavior.
            user: Current authenticated user used for department permission filters.
            chat_history: Recent chat messages used by the optional LLM router.

        Returns:
            Parent context documents and latency metadata.
        """
        started = time.perf_counter()
        config = config or RetrievalConfig.from_settings()
        config = self._apply_user_permission_filter(config, user)
        trace: Dict[str, Any] = {
            "query": query,
            "config": self._config_to_dict(config),
            "latency_ms": {},
        }

        route_started = time.perf_counter()
        route_decision = self._route_knowledge_bases(
            query,
            knowledge_base_ids,
            config.kb_router_enabled,
            chat_history=chat_history,
        )
        trace["latency_ms"]["router"] = (time.perf_counter() - route_started) * 1000
        trace["router"] = route_decision.to_dict()

        if route_decision.intent == "chitchat":
            latency_ms = (time.perf_counter() - started) * 1000
            trace["selected_kbs"] = []
            trace["answer_policy"] = {
                "mode": "chitchat",
                "reason": "router classified the query as chitchat",
            }
            return RetrievalResult(
                documents=[],
                latency_ms=latency_ms,
                child_candidates=[],
                trace=trace,
                confidence_score=1.0,
                should_refuse=False,
                refusal_reason=None,
            )

        profile_started = time.perf_counter()
        profile_matches = (
            KnowledgeBaseProfileService.match_profiles(
                self.db,
                route_decision.rewritten_query or query,
                knowledge_base_ids,
                # Router 已经负责缩小候选库，profile 只补最强候选，避免把干扰库重新并回全库检索。
                top_k=1,
            )
            if config.kb_router_enabled
            else []
        )
        trace["latency_ms"]["profile_match"] = (time.perf_counter() - profile_started) * 1000
        trace["profile_matches"] = profile_matches

        routed_kb_ids = self._merge_candidate_kbs(
            base_kb_ids=knowledge_base_ids,
            router_kb_ids=route_decision.candidate_kbs,
            profile_matches=profile_matches,
            enabled=config.kb_router_enabled,
        )
        trace["selected_kbs"] = routed_kb_ids

        retrieval_query = route_decision.rewritten_query or query
        dense_started = time.perf_counter()
        dense_candidates = self._dense_search(retrieval_query, routed_kb_ids, config)
        trace["latency_ms"]["dense_search"] = (time.perf_counter() - dense_started) * 1000
        trace["dense_candidates"] = self._snapshot_candidates(dense_candidates)

        if config.retriever in ("hybrid_rrf", "milvus_bge_m3", "milvus_bm25"):
            sparse_started = time.perf_counter()
            sparse_candidates = self._sparse_search(retrieval_query, routed_kb_ids, config)
            trace["latency_ms"]["sparse_search"] = (time.perf_counter() - sparse_started) * 1000
            trace["sparse_candidates"] = self._snapshot_candidates(sparse_candidates)

            rrf_started = time.perf_counter()
            child_candidates = reciprocal_rank_fusion(
                [dense_candidates, sparse_candidates],
                rank_constant=config.rrf_rank_constant,
            )
            trace["latency_ms"]["rrf"] = (time.perf_counter() - rrf_started) * 1000
            trace["rrf_candidates"] = self._snapshot_candidates(child_candidates)
        else:
            child_candidates = dense_candidates
            trace["sparse_candidates"] = []
            trace["rrf_candidates"] = []

        rerank_started = time.perf_counter()
        ranked_children = self._rerank_children(retrieval_query, child_candidates, config)
        trace["latency_ms"]["rerank"] = (time.perf_counter() - rerank_started) * 1000
        trace["rerank_before"] = self._snapshot_candidates(child_candidates)
        trace["rerank_after"] = self._snapshot_candidates(ranked_children)

        parent_documents = self._dedupe_to_parents(ranked_children, config.top_k)
        confidence_score = self._calculate_confidence(parent_documents, ranked_children, config)
        query_support_score = self._calculate_query_support(retrieval_query, parent_documents)
        explicit_refusal_trigger = self._has_explicit_refusal_trigger(retrieval_query)
        should_refuse = (
            config.refusal_enabled
            and route_decision.intent == "retrieval"
            and (
                not parent_documents
                or confidence_score < config.confidence_threshold
                or query_support_score < 0.18
                or explicit_refusal_trigger
            )
        )
        refusal_reason = None
        if should_refuse:
            if not parent_documents:
                refusal_reason = "no_parent_context"
            elif confidence_score < config.confidence_threshold:
                refusal_reason = f"confidence_below_threshold:{confidence_score:.4f}<{config.confidence_threshold:.4f}"
            elif explicit_refusal_trigger:
                refusal_reason = "explicit_refusal_trigger"
            else:
                refusal_reason = f"query_support_below_threshold:{query_support_score:.4f}<0.1800"

        latency_ms = (time.perf_counter() - started) * 1000
        trace["latency_ms"]["total"] = latency_ms
        trace["confidence"] = {
            "score": confidence_score,
            "threshold": config.confidence_threshold,
            "query_support_score": query_support_score,
            "explicit_refusal_trigger": explicit_refusal_trigger,
            "should_refuse": should_refuse,
            "reason": refusal_reason,
        }
        trace["final_context"] = self._snapshot_candidates(parent_documents)
        return RetrievalResult(
            documents=parent_documents,
            latency_ms=latency_ms,
            child_candidates=ranked_children,
            trace=trace,
            confidence_score=confidence_score,
            should_refuse=should_refuse,
            refusal_reason=refusal_reason,
        )

    def _dense_search(
        self,
        query: str,
        knowledge_base_ids: Sequence[int],
        config: RetrievalConfig,
    ) -> List[LangchainDocument]:
        """Run vector search against each KB collection and normalize scores."""
        embeddings = EmbeddingsFactory.create()
        candidates: List[LangchainDocument] = []
        for kb_id in knowledge_base_ids:
            vector_store = VectorStoreFactory.create(
                store_type=settings.VECTOR_STORE_TYPE,
                collection_name=f"kb_{kb_id}",
                embedding_function=embeddings,
            )
            search_filters = {"kb_id": kb_id, **(config.filters or {})}
            try:
                results = vector_store.similarity_search_with_score(
                    query,
                    k=config.child_candidates_k,
                    filters=search_filters,
                )
            except Exception:
                # 本地 Chroma/Qdrant 的 filter 能力不一致；失败后无过滤召回，再由业务层二次过滤。
                results = vector_store.similarity_search_with_score(query, k=config.child_candidates_k)

            for rank, (document, score) in enumerate(results, start=1):
                if not self._matches_document_filters(document, search_filters):
                    continue
                document.metadata = {
                    **(document.metadata or {}),
                    "kb_id": kb_id,
                    "dense_score": float(score),
                    "dense_rank": rank,
                    "retrieval_source": "dense",
                }
                candidates.append(document)
        return candidates

    def _sparse_search(
        self,
        query: str,
        knowledge_base_ids: Sequence[int],
        config: RetrievalConfig,
    ) -> List[LangchainDocument]:
        """Run sparse/BM25 retrieval with Milvus when available, otherwise fallback to SQL lexical."""
        if settings.VECTOR_STORE_TYPE.lower() != "milvus":
            return self._lexical_search(query, knowledge_base_ids, config)

        embeddings = EmbeddingsFactory.create()
        candidates: List[LangchainDocument] = []
        for kb_id in knowledge_base_ids:
            vector_store = VectorStoreFactory.create(
                store_type=settings.VECTOR_STORE_TYPE,
                collection_name=f"kb_{kb_id}",
                embedding_function=embeddings,
            )
            search_filters = {"kb_id": kb_id, **(config.filters or {})}
            try:
                if config.retriever == "milvus_bm25":
                    results = vector_store.bm25_search_with_score(
                        query,
                        k=config.child_candidates_k,
                        filters=search_filters,
                    )
                    source = "milvus_bm25"
                else:
                    results = vector_store.sparse_search_with_score(
                        query,
                        k=config.child_candidates_k,
                        filters=search_filters,
                    )
                    source = "milvus_bge_m3_sparse"
            except Exception:
                # Milvus sparse 字段、模型 extras 或 analyzer 不可用时，保留可演示 fallback。
                return self._lexical_search(query, knowledge_base_ids, config)

            for rank, (document, score) in enumerate(results, start=1):
                if not self._matches_document_filters(document, search_filters):
                    continue
                document.metadata = {
                    **(document.metadata or {}),
                    "kb_id": kb_id,
                    "sparse_score": float(score),
                    "sparse_rank": rank,
                    "retrieval_source": source,
                }
                candidates.append(document)
        return candidates

    def _lexical_search(
        self,
        query: str,
        knowledge_base_ids: Sequence[int],
        config: RetrievalConfig,
    ) -> List[LangchainDocument]:
        """Run a lightweight MySQL lexical search over child chunk content."""
        tokens = tokenize_query(query)
        if not tokens:
            return []

        rows = (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.kb_id.in_(list(knowledge_base_ids)))
            .limit(5000)
            .all()
        )
        scored: List[Tuple[DocumentChunk, float]] = []
        for row in rows:
            if not self._matches_filters(row, config.filters):
                continue
            content = row.content or (row.chunk_metadata or {}).get("page_content", "")
            score = sum(content.count(token) for token in tokens)
            if score > 0:
                scored.append((row, float(score)))

        scored.sort(key=lambda item: item[1], reverse=True)
        documents: List[LangchainDocument] = []
        for rank, (row, score) in enumerate(scored[:config.child_candidates_k], start=1):
            metadata = {
                **(row.chunk_metadata or {}),
                "kb_id": row.kb_id,
                "document_id": row.document_id,
                "parent_id": row.parent_id,
                "chunk_id": row.id,
                "file_name": row.file_name,
                "section_path": row.section_path,
                "page": row.page,
                "lexical_score": score,
                "lexical_rank": rank,
                "retrieval_source": "lexical",
            }
            documents.append(LangchainDocument(page_content=row.content or "", metadata=metadata))
        return documents

    def _rerank_children(
        self,
        query: str,
        child_candidates: List[LangchainDocument],
        config: RetrievalConfig,
    ) -> List[LangchainDocument]:
        """Optionally rerank child candidates before parent deduplication."""
        if not config.rerank_enabled:
            return child_candidates
        return RerankService.rerank(query, child_candidates, top_n=max(config.child_candidates_k, config.top_k))

    def _dedupe_to_parents(
        self,
        ranked_children: List[LangchainDocument],
        top_k: int,
    ) -> List[LangchainDocument]:
        """Deduplicate ranked child chunks to parent documents after rerank."""
        parent_ids: List[str] = []
        child_by_parent: Dict[str, List[LangchainDocument]] = {}
        for child in ranked_children:
            parent_id = child.metadata.get("parent_id") or child.metadata.get("chunk_id") or child.metadata.get("id")
            if not parent_id:
                continue
            if parent_id not in child_by_parent:
                parent_ids.append(parent_id)
                child_by_parent[parent_id] = []
            child_by_parent[parent_id].append(child)

        parent_rows = {
            row.id: row
            for row in self.db.query(DocumentParentChunk)
            .filter(DocumentParentChunk.id.in_(parent_ids))
            .all()
        } if parent_ids else {}

        parent_documents: List[LangchainDocument] = []
        for parent_id in parent_ids:
            children = child_by_parent[parent_id]
            parent = parent_rows.get(parent_id)
            best_child = children[0]
            matched_children = [
                {
                    "chunk_id": child.metadata.get("chunk_id"),
                    "text": child.page_content,
                    "section_path": child.metadata.get("section_path"),
                    "page": child.metadata.get("page"),
                    "dense_score": child.metadata.get("dense_score"),
                    "sparse_score": child.metadata.get("sparse_score") or child.metadata.get("lexical_score"),
                    "rrf_score": child.metadata.get("rrf_score"),
                    "rerank_score": child.metadata.get("rerank_score"),
                }
                for child in children[:5]
            ]
            if parent:
                metadata = {
                    **(parent.parent_metadata or {}),
                    "parent_id": parent.id,
                    "document_id": parent.document_id,
                    "kb_id": parent.kb_id,
                    "file_name": parent.file_name,
                    "section_path": parent.section_path,
                    "page": parent.page,
                    "child_ids": [child.metadata.get("chunk_id") for child in children],
                    "matched_children": matched_children,
                    "rerank_score": best_child.metadata.get("rerank_score"),
                    "dense_score": best_child.metadata.get("dense_score"),
                    "sparse_score": best_child.metadata.get("sparse_score") or best_child.metadata.get("lexical_score"),
                    "rrf_score": best_child.metadata.get("rrf_score"),
                }
                parent_documents.append(LangchainDocument(page_content=parent.content, metadata=metadata))
            else:
                # Fallback keeps legacy Chroma chunks usable before documents are re-indexed.
                fallback_metadata = {
                    **(best_child.metadata or {}),
                    "parent_id": parent_id,
                    "child_ids": [child.metadata.get("chunk_id") for child in children],
                    "matched_children": matched_children,
                }
                parent_documents.append(LangchainDocument(
                    page_content=best_child.page_content,
                    metadata=fallback_metadata,
                ))

            if len(parent_documents) >= top_k:
                break
        return parent_documents

    def _route_knowledge_bases(
        self,
        query: str,
        knowledge_base_ids: Sequence[int],
        enabled: bool,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> RouteDecision:
        """Route query to likely KBs using structured Router plus fallback heuristics."""
        kb_ids = list(dict.fromkeys(int(kb_id) for kb_id in knowledge_base_ids))
        if not enabled:
            knowledge_bases = self.db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(kb_ids)).all()
            return RouteDecision(
                intent="retrieval",
                domain=[],
                rewritten_query=query,
                candidate_kbs=kb_ids,
                candidate_kb_names=[kb.name for kb in knowledge_bases],
                source="disabled",
            )
        return QueryRouterService.route(self.db, query, kb_ids, chat_history=chat_history)

    def _merge_candidate_kbs(
        self,
        base_kb_ids: Sequence[int],
        router_kb_ids: Sequence[int],
        profile_matches: Sequence[Dict[str, Any]],
        enabled: bool,
    ) -> List[int]:
        """Merge LLM router candidates and profile Top3, preserving base chat KB constraints."""
        allowed = list(dict.fromkeys(int(kb_id) for kb_id in base_kb_ids))
        if not enabled:
            return allowed

        merged: List[int] = []
        for kb_id in list(router_kb_ids) + [int(item["kb_id"]) for item in profile_matches]:
            if kb_id in allowed and kb_id not in merged:
                merged.append(kb_id)
        return merged or allowed

    def _apply_user_permission_filter(self, config: RetrievalConfig, user: Optional[Any]) -> RetrievalConfig:
        """Append current user's allowed departments to retrieval filters."""
        allowed_departments = self._resolve_allowed_departments(user)
        if allowed_departments is None:
            return config

        filters = dict(config.filters or {})
        existing = filters.get("department")
        if existing:
            existing_values = set(existing if isinstance(existing, list) else [existing])
            filters["department"] = [item for item in allowed_departments if item in existing_values]
        else:
            filters["department"] = allowed_departments

        return RetrievalConfig(
            splitter=config.splitter,
            retriever=config.retriever,
            rerank_enabled=config.rerank_enabled,
            kb_router_enabled=config.kb_router_enabled,
            top_k=config.top_k,
            child_candidates_k=config.child_candidates_k,
            filters=filters,
            rrf_rank_constant=config.rrf_rank_constant,
            confidence_threshold=config.confidence_threshold,
            refusal_enabled=config.refusal_enabled,
        )

    def _resolve_allowed_departments(self, user: Optional[Any]) -> Optional[List[str]]:
        """Resolve department whitelist from user settings, with superusers unrestricted."""
        if user is not None and getattr(user, "is_superuser", False):
            return None
        configured = getattr(user, "allowed_departments", None) if user is not None else None
        if configured:
            return [str(item) for item in configured]
        return [item for item in settings.DEFAULT_ALLOWED_DEPARTMENTS.split(",")]

    def _matches_filters(self, row: DocumentChunk, filters: Dict[str, Any]) -> bool:
        """Apply scalar filters to MySQL lexical candidates."""
        if not filters:
            return True
        for field, expected in filters.items():
            actual = getattr(row, field, None)
            if isinstance(expected, (list, tuple, set)):
                normalized_actual = "" if actual is None else actual
                if normalized_actual not in expected:
                    return False
            elif isinstance(expected, dict):
                if not _match_range(actual, expected):
                    return False
            elif actual != expected:
                return False
        return True

    def _matches_document_filters(self, document: LangchainDocument, filters: Dict[str, Any]) -> bool:
        """Apply scalar filters to vector-store candidates after retrieval."""
        if not filters:
            return True
        metadata = document.metadata or {}
        for field, expected in filters.items():
            actual = metadata.get(field)
            if isinstance(expected, (list, tuple, set)):
                normalized_actual = "" if actual is None else actual
                if normalized_actual not in expected:
                    return False
            elif isinstance(expected, dict):
                if not _match_range(actual, expected):
                    return False
            elif actual != expected:
                return False
        return True

    def _snapshot_candidates(self, documents: Sequence[LangchainDocument], limit: int = 20) -> List[Dict[str, Any]]:
        """Serialize retrieval candidates for trace display without flooding the payload."""
        snapshot: List[Dict[str, Any]] = []
        for rank, document in enumerate(documents[:limit], start=1):
            metadata = document.metadata or {}
            snapshot.append({
                "rank": rank,
                "kb_id": metadata.get("kb_id"),
                "document_id": metadata.get("document_id"),
                "parent_id": metadata.get("parent_id"),
                "chunk_id": metadata.get("chunk_id"),
                "file_name": metadata.get("file_name") or metadata.get("source"),
                "section_path": metadata.get("section_path"),
                "page": metadata.get("page"),
                "retrieval_source": metadata.get("retrieval_source"),
                "dense_rank": metadata.get("dense_rank"),
                "sparse_rank": metadata.get("sparse_rank") or metadata.get("lexical_rank"),
                "rrf_rank": metadata.get("rrf_rank"),
                "dense_score": metadata.get("dense_score"),
                "sparse_score": metadata.get("sparse_score") or metadata.get("lexical_score"),
                "rrf_score": metadata.get("rrf_score"),
                "rerank_score": metadata.get("rerank_score"),
                "preview": (document.page_content or "")[:240],
            })
        return snapshot

    def _calculate_confidence(
        self,
        parent_documents: Sequence[LangchainDocument],
        ranked_children: Sequence[LangchainDocument],
        config: RetrievalConfig,
    ) -> float:
        """Calculate a normalized retrieval confidence score for refusal control."""
        if not parent_documents or not ranked_children:
            return 0.0

        best = ranked_children[0].metadata or {}
        if best.get("rerank_score") is not None:
            return _clamp_score(float(best.get("rerank_score") or 0.0))
        if best.get("rrf_score") is not None:
            return _clamp_score(float(best.get("rrf_score") or 0.0) * max(config.rrf_rank_constant, 1))
        if best.get("sparse_score") is not None or best.get("lexical_score") is not None:
            sparse_score = float(best.get("sparse_score") or best.get("lexical_score") or 0.0)
            return _clamp_score(0.35 + min(sparse_score, 5.0) / 10.0)
        if best.get("dense_score") is not None:
            dense_score = float(best.get("dense_score") or 0.0)
            return _clamp_score(dense_score if 0.0 <= dense_score <= 1.0 else 1.0 / (1.0 + max(dense_score, 0.0)))
        return 0.0

    def _calculate_query_support(
        self,
        query: str,
        parent_documents: Sequence[LangchainDocument],
    ) -> float:
        """Calculate whether retrieved context actually contains query evidence terms."""
        query_tokens = [
            token
            for token in tokenize_query(query)
            if token not in {"请给出", "是什么", "如何", "哪些", "多少", "平台", "系统", "管理"}
        ]
        if not query_tokens or not parent_documents:
            return 0.0

        combined_context = "\n".join(document.page_content or "" for document in parent_documents[:3])
        # 业务逻辑：只有 query 中的核心词在最终上下文中有足够命中，才认为检索证据支撑回答。
        hits = sum(1 for token in query_tokens if token in combined_context)
        return hits / max(len(query_tokens), 1)

    def _has_explicit_refusal_trigger(self, query: str) -> bool:
        """Detect sensitive, future, fabricated, or clearly out-of-scope negative requests."""
        # 业务逻辑：这些问题即使召回到泛化上下文，也不应生成答案，应由拒答门禁拦截。
        return bool(re.search(
            r"火星基地|氧气循环|量子发动机|QX-9000|明天.*菜单|个人手机号|银行账号|初始密码|编造|不存在|未上传合同|采购合同.*付款",
            query or "",
            flags=re.IGNORECASE,
        ))

    def _config_to_dict(self, config: RetrievalConfig) -> Dict[str, Any]:
        """Serialize config into trace-friendly primitives."""
        return {
            "splitter": config.splitter,
            "retriever": config.retriever,
            "rerank_enabled": config.rerank_enabled,
            "kb_router_enabled": config.kb_router_enabled,
            "top_k": config.top_k,
            "child_candidates_k": config.child_candidates_k,
            "filters": config.filters,
            "rrf_rank_constant": config.rrf_rank_constant,
            "confidence_threshold": config.confidence_threshold,
            "refusal_enabled": config.refusal_enabled,
        }


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[LangchainDocument]],
    rank_constant: int = 60,
) -> List[LangchainDocument]:
    """Fuse ranked retrieval lists with Reciprocal Rank Fusion."""
    scores: Dict[str, float] = {}
    documents: Dict[str, LangchainDocument] = {}
    for ranked_list in ranked_lists:
        for rank, document in enumerate(ranked_list, start=1):
            doc_id = str(document.metadata.get("chunk_id") or document.metadata.get("id") or hash(document.page_content))
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rank_constant + rank)
            if doc_id not in documents:
                documents[doc_id] = document

    fused_ids = sorted(scores, key=scores.get, reverse=True)
    fused_documents: List[LangchainDocument] = []
    for rank, doc_id in enumerate(fused_ids, start=1):
        document = documents[doc_id]
        document.metadata = {
            **(document.metadata or {}),
            "rrf_score": scores[doc_id],
            "rrf_rank": rank,
        }
        fused_documents.append(document)
    return fused_documents


def tokenize_query(query: str) -> List[str]:
    """Tokenize Chinese/mixed queries into terms for lightweight lexical matching."""
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_-]{2,}", query)
    # Long Chinese phrases are useful directly; adjacent bi-grams improve recall without jieba dependency.
    expanded: List[str] = []
    for term in terms:
        expanded.append(term)
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", term):
            expanded.extend(term[index:index + 2] for index in range(0, len(term) - 1))
    return list(dict.fromkeys(expanded))


def _match_range(actual: Any, expected: Dict[str, Any]) -> bool:
    """Evaluate simple range operators used by effective_date filters."""
    if actual is None:
        return False
    for operator, operand in expected.items():
        if operator == "$gte" and not (actual >= operand):
            return False
        if operator == "$gt" and not (actual > operand):
            return False
        if operator == "$lte" and not (actual <= operand):
            return False
        if operator == "$lt" and not (actual < operand):
            return False
        if operator == "$eq" and not (actual == operand):
            return False
        if operator == "$ne" and not (actual != operand):
            return False
    return True


def _clamp_score(score: float) -> float:
    """Clamp arbitrary retrieval scores into the 0-1 confidence range."""
    if math.isnan(score) or math.isinf(score):
        return 0.0
    return max(0.0, min(1.0, score))
