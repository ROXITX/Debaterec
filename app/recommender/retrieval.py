"""Stage-one candidate generation (PRD §12).

    catalogue -> hard filter -> hybrid score -> top N -> diversify -> debate pool

The hybrid score is the PRD §37 formula:

    HybridScore = alpha * SemanticScore + (1 - alpha) * MetadataScore

with a small quality prior folded into the metadata half. Running the debate on
8 candidates instead of the whole catalogue is what keeps a request to a handful
of LLM calls rather than hundreds (PRD §70).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import settings
from ..domains.registry import domain_stats, get_adapter
from ..schemas import ConstraintCheck, Item, QuerySpec
from . import filters
from .index import build_index


@dataclass
class Candidate:
    item: Item
    semantic: float
    metadata: float
    prior: float
    hybrid: float
    checks: list[ConstraintCheck]
    constraint_score: float
    preference_score: float

    @property
    def hard_fail(self) -> bool:
        return bool(filters.hard_violations(self.checks))


@dataclass
class RetrievalResult:
    candidates: list[Candidate]
    pool_size: int
    filtered_out: int
    relaxed: bool
    stage1_size: int


def adaptive_alpha(spec: QuerySpec) -> float:
    """How much to trust text similarity versus explicit constraint matching.

    A vague request ("something funny and clever") has nothing to check, so
    similarity should carry it. A precise one ("under 15 lakh, 5-star, not
    diesel") states most of what matters in structured form, and leaning on text
    similarity there is how a diesel SUV at 25 lakh ends up in a list that
    explicitly excluded both. Alpha therefore slides down as the query gets more
    specific. The endpoints are hyperparameters — PRD §37 asks for them to be
    tuned experimentally, and `evaluation/experiments.py` sweeps them.
    """
    weight = sum(c.importance for c in (*spec.numeric, *spec.categorical))
    return round(max(0.42, settings.hybrid_alpha - 0.075 * weight), 3)


def retrieve(spec: QuerySpec, limit: int | None = None, curated_only: bool = False) -> RetrievalResult:
    adapter = get_adapter(spec.domain)
    index = build_index(spec.domain, curated_only)
    stats = domain_stats(spec.domain, curated_only)
    limit = limit or settings.candidates_stage1

    kept, rejected, relaxed = filters.apply_hard_filters(list(index.items), spec, adapter)
    keep_ids = {it.item_id for it in kept}

    query_text = " ".join(filter(None, [
        spec.semantic_query or spec.raw_query,
        " ".join(spec.keywords[:10]),
        " ".join(v for c in spec.categorical for v in c.include),
    ]))
    semantic_all = index.semantic_scores(query_text)
    alpha = adaptive_alpha(spec)

    candidates: list[Candidate] = []
    for position, item in enumerate(index.items):
        if item.item_id not in keep_ids:
            continue
        checks = filters.audit(item, spec, adapter)
        c_score = filters.constraint_score(checks)
        p_score = filters.preference_score(checks)
        prior = filters.quality_prior(item, adapter, stats)
        semantic = float(semantic_all[position])
        # Metadata half: mostly explicit constraint satisfaction, lightly
        # seasoned with the quality prior so ties resolve sensibly.
        metadata = 0.82 * c_score + 0.18 * prior
        hybrid = alpha * semantic + (1 - alpha) * metadata
        candidates.append(Candidate(
            item=item, semantic=round(semantic, 4), metadata=round(metadata, 4),
            prior=round(prior, 4), hybrid=round(hybrid, 4), checks=checks,
            constraint_score=round(c_score, 4), preference_score=round(p_score, 4),
        ))

    candidates.sort(key=lambda c: c.hybrid, reverse=True)
    return RetrievalResult(
        candidates=candidates[:limit],
        pool_size=len(index.items),
        filtered_out=len(rejected),
        relaxed=relaxed,
        stage1_size=len(candidates[:limit]),
    )


def diversify(candidates: list[Candidate], k: int, penalty: float = 0.22) -> list[Candidate]:
    """Maximal-marginal-relevance style selection over tag overlap (PRD §42).

    Without this the debate pool tends to fill with five near-identical items —
    five Nolan films, five Royal Enfields — and the user learns nothing from the
    comparison even if each individual pick is defensible.
    """
    if k >= len(candidates):
        return list(candidates)

    chosen: list[Candidate] = []
    remaining = list(candidates)
    while remaining and len(chosen) < k:
        best, best_score = None, -1e9
        for cand in remaining:
            overlap = max((_similarity(cand.item, s.item) for s in chosen), default=0.0)
            score = cand.hybrid - penalty * overlap
            if score > best_score:
                best, best_score = cand, score
        chosen.append(best)  # type: ignore[arg-type]
        remaining.remove(best)  # type: ignore[arg-type]
    return chosen


def _similarity(a: Item, b: Item) -> float:
    """Jaccard over the union of every tag facet."""
    ta = {f"{k}:{v}" for k, vals in a.tags.items() for v in vals}
    tb = {f"{k}:{v}" for k, vals in b.tags.items() for v in vals}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def intra_list_diversity(items: list[Item]) -> float:
    """Mean pairwise dissimilarity of a result list — the PRD §42 metric."""
    if len(items) < 2:
        return 1.0
    sims = [
        _similarity(items[i], items[j])
        for i in range(len(items))
        for j in range(i + 1, len(items))
    ]
    return round(1.0 - float(np.mean(sims)), 4)
