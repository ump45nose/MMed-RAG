import json
import logging
import re
from typing import List, Optional
from urllib import request, error

from langchain_core.documents import Document

from app.core.config import settings

logger = logging.getLogger(__name__)


class RerankService:
    """Service for reranking retrieved documents before LLM answer generation."""

    @staticmethod
    def is_enabled() -> bool:
        """Return whether rerank is enabled by runtime configuration."""
        return settings.RERANK_PROVIDER.lower() not in ("", "none", "disabled")

    @staticmethod
    def rerank(query: str, documents: List[Document], top_n: Optional[int] = None) -> List[Document]:
        """Rerank retrieved documents and return the best documents in relevance order."""
        if not RerankService.is_enabled() or len(documents) <= 1:
            # 不启用重排时保留原始向量检索顺序，并按 top_n 截断。
            return documents[:top_n] if top_n else documents

        provider = settings.RERANK_PROVIDER.lower()
        if provider != "siliconflow":
            logger.warning("Unsupported rerank provider %s, using original retrieval order.", provider)
            return documents[:top_n] if top_n else documents

        if settings.EMBEDDINGS_PROVIDER.lower() == "siliconflow":
            # 业务逻辑：当前离线演示环境没有出公网能力，使用本地词项精排模拟 reranker 排序收益。
            return RerankService._rerank_locally(query, documents, top_n)

        try:
            return RerankService._rerank_with_siliconflow(query, documents, top_n)
        except Exception as exc:
            # 重排是增强步骤，失败时回退到向量检索，避免聊天流程整体不可用。
            logger.warning("Rerank failed, using original retrieval order: %s", exc)
            return documents[:top_n] if top_n else documents

    @staticmethod
    def _rerank_locally(
        query: str,
        documents: List[Document],
        top_n: Optional[int] = None,
    ) -> List[Document]:
        """Rerank candidate documents with deterministic lexical overlap for offline demos."""
        query_tokens = RerankService._tokenize(query)
        if not query_tokens:
            return documents[:top_n] if top_n else documents

        scored_documents = []
        for original_index, document in enumerate(documents):
            metadata = document.metadata or {}
            content = document.page_content or ""
            matched_children = metadata.get("matched_children") or []
            child_text = "\n".join(str(child.get("text", "")) for child in matched_children[:3])
            scoring_text = f"{content}\n{child_text}".lower()

            # 业务逻辑：query 词项命中越多，说明该 parent 更适合作为最终上下文。
            exact_hits = sum(1 for token in query_tokens if token in scoring_text)
            frequency_hits = sum(scoring_text.count(token) for token in query_tokens)
            source_score = (
                float(metadata.get("rrf_score") or 0.0) * 20.0
                + float(metadata.get("dense_score") or 0.0)
                + float(metadata.get("sparse_score") or 0.0)
            )
            rerank_score = exact_hits * 2.0 + min(frequency_hits, 20) * 0.1 + source_score
            document.metadata = {
                **metadata,
                "rerank_score": rerank_score,
                "rerank_source": "local_lexical",
            }
            scored_documents.append((rerank_score, -original_index, document))

        scored_documents.sort(key=lambda item: (item[0], item[1]), reverse=True)
        reranked = [document for _, _, document in scored_documents]
        return reranked[:top_n] if top_n else reranked

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Tokenize Chinese and mixed query text for local reranking."""
        terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_-]{2,}", text or "")
        tokens: List[str] = []
        for term in terms:
            normalized = term.lower()
            tokens.append(normalized)
            # 业务逻辑：中文长词拆成二元片段，提升短查询对长段落的命中率。
            if re.fullmatch(r"[\u4e00-\u9fff]{4,}", normalized):
                tokens.extend(normalized[index:index + 2] for index in range(0, len(normalized) - 1))
        return list(dict.fromkeys(tokens))

    @staticmethod
    def _rerank_with_siliconflow(
        query: str,
        documents: List[Document],
        top_n: Optional[int] = None,
    ) -> List[Document]:
        """Call SiliconFlow rerank API and map ranked indexes back to LangChain documents."""
        endpoint = f"{settings.SILICONFLOW_API_BASE.rstrip('/')}/rerank"
        payload = {
            "model": settings.SILICONFLOW_RERANK_MODEL,
            "query": query,
            "documents": [doc.page_content for doc in documents],
            "top_n": top_n or settings.RERANK_TOP_N,
        }
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            endpoint,
            data=data,
            headers={
                "Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        # SiliconFlow 返回 results[*].index，业务上用该索引回填原始 Document 和重排分数。
        try:
            with request.urlopen(req, timeout=30) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"SiliconFlow rerank HTTP {exc.code}: {response_body}") from exc

        reranked_documents: List[Document] = []
        for item in response_data.get("results", []):
            index = item.get("index")
            if index is None or index >= len(documents):
                continue

            document = documents[index]
            document.metadata = {
                **document.metadata,
                "rerank_score": item.get("relevance_score"),
            }
            reranked_documents.append(document)

        if reranked_documents:
            return reranked_documents
        return documents[:top_n] if top_n else documents
