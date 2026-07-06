from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.evaluation_service import DEFAULT_DATASET_PATH, EvaluationService

router = APIRouter()

LATEST_EVALUATION_RESULT: Optional[Dict[str, Any]] = None


class EvaluationRunRequest(BaseModel):
    """Request body for running the interview demo evaluation matrix."""

    dataset_path: Optional[str] = None
    kb_ids: Optional[List[int]] = None
    limit: Optional[int] = None


@router.post("/run")
def run_evaluation(
    request: EvaluationRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Run the ablation evaluation matrix and cache the latest result."""
    global LATEST_EVALUATION_RESULT
    try:
        service = EvaluationService(db)
        LATEST_EVALUATION_RESULT = service.run(
            dataset_path=request.dataset_path,
            kb_ids_override=request.kb_ids,
            limit=request.limit,
            current_user=current_user,
        )
        return LATEST_EVALUATION_RESULT
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Evaluation dataset not found: {exc}") from exc


@router.get("/latest")
def get_latest_evaluation(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the latest in-process evaluation result for the dashboard."""
    if not LATEST_EVALUATION_RESULT:
        service = EvaluationService(None)
        dataset = service.load_dataset(DEFAULT_DATASET_PATH)
        return {
            "dataset_path": DEFAULT_DATASET_PATH,
            "query_count": len(dataset),
            "dataset_summary": service.summarize_dataset(dataset),
            "ablation": [],
        }
    return LATEST_EVALUATION_RESULT


@router.get("/dataset/default")
def get_default_dataset(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return default dataset metadata and rows for manual labeling."""
    service = EvaluationService(db)
    dataset = service.load_dataset(DEFAULT_DATASET_PATH)
    return {
        "dataset_path": DEFAULT_DATASET_PATH,
        "query_count": len(dataset),
        "dataset_summary": service.summarize_dataset(dataset),
        "queries": [
            {
                **item.__dict__,
                "labeled": item.is_labeled,
            }
            for item in dataset
        ],
    }
