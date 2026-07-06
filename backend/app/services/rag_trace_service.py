from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.rag_trace import RagTrace


class RagTraceService:
    """Persist and serialize self-hosted RAG trace records."""

    @staticmethod
    def create_trace(
        db: Session,
        *,
        user_id: int,
        chat_id: Optional[int],
        query: str,
        retrieval_result: Any,
        answer_policy: Dict[str, Any],
    ) -> RagTrace:
        """Create a trace row from a retrieval result and answer policy."""
        route = (retrieval_result.trace or {}).get("router", {})
        trace = RagTrace(
            user_id=user_id,
            chat_id=chat_id,
            query=query,
            rewritten_query=route.get("rewritten_query"),
            intent=route.get("intent"),
            domains=route.get("domain"),
            candidate_kbs=route.get("candidate_kbs"),
            selected_kbs=(retrieval_result.trace or {}).get("selected_kbs"),
            retrieval_trace=RagTraceService._truncate_payload(retrieval_result.trace or {}),
            answer_policy=answer_policy,
            latency_breakdown=(retrieval_result.trace or {}).get("latency_ms"),
            total_latency_ms=retrieval_result.latency_ms,
            confidence_score=retrieval_result.confidence_score,
            refused=retrieval_result.should_refuse,
            refusal_reason=retrieval_result.refusal_reason,
        )
        db.add(trace)
        db.commit()
        db.refresh(trace)
        return trace

    @staticmethod
    def to_dict(trace: RagTrace) -> Dict[str, Any]:
        """Serialize a trace row for API responses and chat envelopes."""
        return {
            "id": trace.id,
            "user_id": trace.user_id,
            "chat_id": trace.chat_id,
            "query": trace.query,
            "rewritten_query": trace.rewritten_query,
            "intent": trace.intent,
            "domains": trace.domains or [],
            "candidate_kbs": trace.candidate_kbs or [],
            "selected_kbs": trace.selected_kbs or [],
            "retrieval_trace": trace.retrieval_trace or {},
            "answer_policy": trace.answer_policy or {},
            "latency_breakdown": trace.latency_breakdown or {},
            "total_latency_ms": trace.total_latency_ms,
            "confidence_score": trace.confidence_score,
            "refused": trace.refused,
            "refusal_reason": trace.refusal_reason,
            "created_at": trace.created_at.isoformat() if trace.created_at else None,
        }

    @staticmethod
    def _truncate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Keep trace JSON readable by trimming oversized text fields."""
        def trim(value: Any) -> Any:
            if isinstance(value, str):
                return value[:2000]
            if isinstance(value, list):
                return [trim(item) for item in value[:80]]
            if isinstance(value, dict):
                return {key: trim(item) for key, item in value.items()}
            return value

        return trim(payload)
