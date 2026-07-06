from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.rag_trace import RagTrace
from app.models.user import User
from app.services.rag_trace_service import RagTraceService

router = APIRouter()


@router.get("", response_model=List[Dict[str, Any]])
def list_traces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List recent RAG traces for the current user."""
    query = db.query(RagTrace)
    if not current_user.is_superuser:
        # trace 可能包含检索片段和问题原文，必须按用户隔离。
        query = query.filter(RagTrace.user_id == current_user.id)

    rows = query.order_by(RagTrace.id.desc()).limit(min(limit, 200)).all()
    return [RagTraceService.to_dict(row) for row in rows]


@router.get("/{trace_id}", response_model=Dict[str, Any])
def get_trace(
    trace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return one trace if the current user is allowed to see it."""
    query = db.query(RagTrace).filter(RagTrace.id == trace_id)
    if not current_user.is_superuser:
        query = query.filter(RagTrace.user_id == current_user.id)

    trace = query.first()
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return RagTraceService.to_dict(trace)
