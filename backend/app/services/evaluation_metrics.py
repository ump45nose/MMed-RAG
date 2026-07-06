import math
from typing import Iterable, List, Sequence


def recall_at_k(retrieved_parent_ids: Sequence[str], relevant_parent_ids: Sequence[str], k: int) -> float:
    """Compute parent-level Recall@k for one query."""
    relevant = set(relevant_parent_ids)
    if not relevant:
        return 0.0
    retrieved = set(retrieved_parent_ids[:k])
    return len(retrieved & relevant) / len(relevant)


def reciprocal_rank(retrieved_parent_ids: Sequence[str], relevant_parent_ids: Sequence[str]) -> float:
    """Compute reciprocal rank for the first relevant parent hit."""
    relevant = set(relevant_parent_ids)
    if not relevant:
        return 0.0
    for index, parent_id in enumerate(retrieved_parent_ids, start=1):
        if parent_id in relevant:
            return 1.0 / index
    return 0.0


def ndcg_at_k(retrieved_parent_ids: Sequence[str], relevant_parent_ids: Sequence[str], k: int) -> float:
    """Compute binary-relevance nDCG@k on parent IDs."""
    relevant = set(relevant_parent_ids)
    if not relevant:
        return 0.0

    dcg = 0.0
    for index, parent_id in enumerate(retrieved_parent_ids[:k], start=1):
        if parent_id in relevant:
            dcg += 1.0 / math.log2(index + 1)

    ideal_hits = min(len(relevant), k)
    ideal_dcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def percentile(values: Sequence[float], percentile_value: float) -> float:
    """Compute a nearest-rank percentile for latency reporting."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = max(1, math.ceil((percentile_value / 100.0) * len(sorted_values)))
    return sorted_values[min(rank - 1, len(sorted_values) - 1)]


def mean(values: Iterable[float]) -> float:
    """Compute arithmetic mean with an empty-list guard."""
    values_list = list(values)
    if not values_list:
        return 0.0
    return sum(values_list) / len(values_list)
