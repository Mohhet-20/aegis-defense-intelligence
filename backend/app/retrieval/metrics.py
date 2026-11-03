"""Standard rank-retrieval metrics over lists of ids and sets/maps of relevance."""
from __future__ import annotations

import math
from typing import Mapping, Sequence


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    top = ranked[:k]
    return sum(1 for r in top if r in relevant) / k


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float | None:
    """None (undefined) when there are no relevant documents."""
    if not relevant:
        return None
    return sum(1 for r in ranked[:k] if r in relevant) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    for i, r in enumerate(ranked, start=1):
        if r in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], gains: Mapping[str, float], k: int) -> float | None:
    """Graded-relevance nDCG; None if no document has positive gain."""
    ideal = sorted((g for g in gains.values() if g > 0), reverse=True)[:k]
    if not ideal:
        return None
    dcg = sum(gains.get(r, 0.0) / math.log2(i + 1) for i, r in enumerate(ranked[:k], start=1))
    idcg = sum(g / math.log2(i + 1) for i, g in enumerate(ideal, start=1))
    return dcg / idcg if idcg else None
