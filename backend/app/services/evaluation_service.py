import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.services.evaluation_metrics import mean, ndcg_at_k, percentile, recall_at_k, reciprocal_rank
from app.services.retrieval_service import ParentContextRetriever, RetrievalConfig


DEFAULT_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "evaluation",
    "datasets",
    "interview_demo.jsonl",
)


@dataclass
class EvaluationQuery:
    """One labeled query in the retrieval evaluation dataset."""

    query: str
    type: str
    kb_ids: List[int]
    relevant_parent_ids: List[str]
    answerable: bool
    notes: str = ""
    expected_answer: str = ""
    evidence_keywords: List[str] = field(default_factory=list)
    difficulty: str = "medium"

    @property
    def is_labeled(self) -> bool:
        """Return whether this query has real parent IDs that can score retrieval metrics."""
        if not self.answerable:
            return True
        return bool(self.relevant_parent_ids) and not any(
            parent_id.startswith("TODO_") for parent_id in self.relevant_parent_ids
        )


class EvaluationService:
    """Run ablation retrieval evaluation for the interview demo."""

    ABLATION_CONFIGS = [
        ("baseline: dense only + 裸切分", RetrievalConfig(splitter="naive", retriever="dense", rerank_enabled=False, kb_router_enabled=False, top_k=5, child_candidates_k=10, refusal_enabled=False)),
        ("+ 领域分块 + 父子检索", RetrievalConfig(splitter="domain_parent", retriever="dense", rerank_enabled=False, kb_router_enabled=False, top_k=5, child_candidates_k=20, refusal_enabled=False)),
        ("+ hybrid RRF", RetrievalConfig(splitter="domain_parent", retriever="hybrid_rrf", rerank_enabled=False, kb_router_enabled=False, top_k=5, child_candidates_k=20, refusal_enabled=False)),
        ("+ reranker", RetrievalConfig(splitter="domain_parent", retriever="hybrid_rrf", rerank_enabled=True, kb_router_enabled=False, top_k=5, child_candidates_k=30, refusal_enabled=False)),
        ("+ router + hybrid + reranker + refusal", RetrievalConfig(splitter="domain_parent", retriever="hybrid_rrf", rerank_enabled=True, kb_router_enabled=True, top_k=5, child_candidates_k=30, refusal_enabled=True)),
    ]

    def __init__(self, db: Optional[Session]):
        """Create an evaluation service bound to a database session."""
        self.db = db

    def load_dataset(self, dataset_path: Optional[str] = None, limit: Optional[int] = None) -> List[EvaluationQuery]:
        """Load a JSONL retrieval dataset from disk."""
        path = dataset_path or DEFAULT_DATASET_PATH
        queries: List[EvaluationQuery] = []
        with open(path, "r", encoding="utf-8") as dataset_file:
            for line in dataset_file:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                queries.append(EvaluationQuery(
                    query=item["query"],
                    type=item.get("type", "事实型"),
                    kb_ids=[int(kb_id) for kb_id in item.get("kb_ids", [])],
                    relevant_parent_ids=[str(parent_id) for parent_id in item.get("relevant_parent_ids", [])],
                    answerable=bool(item.get("answerable", True)),
                    notes=item.get("notes", ""),
                    expected_answer=item.get("expected_answer", ""),
                    evidence_keywords=[str(keyword) for keyword in item.get("evidence_keywords", [])],
                    difficulty=item.get("difficulty", "medium"),
                ))
                if limit and len(queries) >= limit:
                    break
        return queries

    def run(
        self,
        dataset_path: Optional[str] = None,
        kb_ids_override: Optional[Sequence[int]] = None,
        limit: Optional[int] = None,
        current_user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Run the ablation matrix and return an API-friendly report."""
        dataset = self.load_dataset(dataset_path, limit)
        dataset_summary = self.summarize_dataset(dataset)
        retriever = ParentContextRetriever(self.db)
        report_rows: List[Dict[str, Any]] = []

        for config_name, config in self.ABLATION_CONFIGS:
            query_results: List[Dict[str, Any]] = []
            latencies: List[float] = []
            answerable_recalls: List[float] = []
            answerable_mrrs: List[float] = []
            answerable_ndcgs: List[float] = []
            negative_passes: List[float] = []

            for item in dataset:
                kb_ids = list(kb_ids_override or item.kb_ids)
                if not kb_ids:
                    query_results.append({
                        "query": item.query,
                        "type": item.type,
                        "error": "missing kb_ids",
                    })
                    continue

                retrieval_result = retriever.retrieve(item.query, kb_ids, config, user=current_user)
                parent_ids = [str(document.metadata.get("parent_id")) for document in retrieval_result.documents]
                latencies.append(retrieval_result.latency_ms)

                if item.answerable:
                    if item.is_labeled:
                        recall = recall_at_k(parent_ids, item.relevant_parent_ids, 5)
                        mrr = reciprocal_rank(parent_ids, item.relevant_parent_ids)
                        ndcg = ndcg_at_k(parent_ids, item.relevant_parent_ids, 10)
                        answerable_recalls.append(recall)
                        answerable_mrrs.append(mrr)
                        answerable_ndcgs.append(ndcg)
                    else:
                        # 未绑定真实 parent_id 的样本只参与页面展示，避免把占位符误计为检索失败。
                        recall = mrr = ndcg = 0.0
                else:
                    # 负例直接验证拒答门禁，而不是只看是否召回到了上下文。
                    negative_passes.append(1.0 if retrieval_result.should_refuse else 0.0)
                    recall = mrr = ndcg = 0.0

                query_results.append({
                    "query": item.query,
                    "type": item.type,
                    "answerable": item.answerable,
                    "labeled": item.is_labeled,
                    "difficulty": item.difficulty,
                    "expected_answer": item.expected_answer,
                    "evidence_keywords": item.evidence_keywords,
                    "relevant_parent_ids": item.relevant_parent_ids,
                    "retrieved_parent_ids": parent_ids,
                    "recall_at_5": recall,
                    "mrr": mrr,
                    "ndcg_at_10": ndcg,
                    "latency_ms": retrieval_result.latency_ms,
                    "confidence_score": retrieval_result.confidence_score,
                    "refused": retrieval_result.should_refuse,
                    "refusal_reason": retrieval_result.refusal_reason,
                })

            report_rows.append({
                "config": config_name,
                "retrieval_config": asdict(config),
                "recall_at_5": mean(answerable_recalls),
                "mrr": mean(answerable_mrrs),
                "ndcg_at_10": mean(answerable_ndcgs),
                "p95_latency_ms": percentile(latencies, 95),
                "negative_refusal_rate": mean(negative_passes),
                "labeled_query_count": dataset_summary["labeled_query_count"],
                "unlabeled_query_count": dataset_summary["unlabeled_query_count"],
                "answerable_query_count": dataset_summary["answerable_query_count"],
                "negative_query_count": dataset_summary["negative_query_count"],
                "queries": query_results,
            })

        return {
            "dataset_path": dataset_path or DEFAULT_DATASET_PATH,
            "query_count": len(dataset),
            "dataset_summary": dataset_summary,
            "ablation": report_rows,
        }

    def summarize_dataset(self, dataset: Sequence[EvaluationQuery]) -> Dict[str, Any]:
        """Build dataset coverage and labeling statistics for the report page."""
        type_counts: Dict[str, int] = {}
        difficulty_counts: Dict[str, int] = {}
        for item in dataset:
            type_counts[item.type] = type_counts.get(item.type, 0) + 1
            difficulty_counts[item.difficulty] = difficulty_counts.get(item.difficulty, 0) + 1

        answerable_count = sum(1 for item in dataset if item.answerable)
        labeled_count = sum(1 for item in dataset if item.is_labeled)
        labeled_answerable_count = sum(1 for item in dataset if item.answerable and item.is_labeled)
        return {
            "query_count": len(dataset),
            "answerable_query_count": answerable_count,
            "negative_query_count": len(dataset) - answerable_count,
            "labeled_query_count": labeled_count,
            "unlabeled_query_count": len(dataset) - labeled_count,
            "labeled_answerable_query_count": labeled_answerable_count,
            "unlabeled_answerable_query_count": answerable_count - labeled_answerable_count,
            "label_coverage": labeled_count / len(dataset) if dataset else 0.0,
            "answerable_label_coverage": labeled_answerable_count / answerable_count if answerable_count else 0.0,
            "type_counts": type_counts,
            "difficulty_counts": difficulty_counts,
        }
