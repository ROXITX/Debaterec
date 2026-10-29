"""Ranking metrics (PRD §41–§43).

Implemented directly rather than pulled from a library so the report can state
exactly which definition was used — the NDCG in particular has several
conventions and reviewers ask.
"""

from __future__ import annotations

import math
from statistics import mean, median, pstdev


def precision_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top = ranked_ids[:k]
    return sum(1 for i in top if i in relevant) / k


def recall_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = ranked_ids[:k]
    return sum(1 for i in top if i in relevant) / len(relevant)


def dcg(gains: list[float]) -> float:
    # Standard log2(rank + 1) discount, rank starting at 1.
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranked_ids: list[str], relevance: dict[str, float], k: int) -> float:
    gains = [relevance.get(i, 0.0) for i in ranked_ids[:k]]
    ideal = sorted(relevance.values(), reverse=True)[:k]
    denominator = dcg(ideal)
    return round(dcg(gains) / denominator, 4) if denominator > 0 else 0.0


def mrr(ranked_ids: list[str], relevant: set[str]) -> float:
    for position, item_id in enumerate(ranked_ids, start=1):
        if item_id in relevant:
            return 1.0 / position
    return 0.0


def hit_rate(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    return 1.0 if any(i in relevant for i in ranked_ids[:k]) else 0.0


def coverage(all_recommended: list[str], catalogue_size: int) -> float:
    """Proportion of the catalogue the system is capable of surfacing (PRD §43)."""
    if catalogue_size <= 0:
        return 0.0
    return round(len(set(all_recommended)) / catalogue_size, 4)


def constraint_violation_rate(results: list[dict]) -> float:
    """Share of returned items that break at least one hard constraint.

    This is the metric that speaks directly to RQ2 — whether the Critic reduces
    unsuitable recommendations.
    """
    if not results:
        return 0.0
    bad = 0
    for card in results:
        checks = card.get("checks", [])
        if any(c.get("hard") and c.get("status") == "fail" for c in checks):
            bad += 1
    return round(bad / len(results), 4)


def mean_constraint_satisfaction(results: list[dict]) -> float:
    degrees = [
        c.get("degree", 0.0)
        for card in results
        for c in card.get("checks", [])
    ]
    return round(mean(degrees), 4) if degrees else 0.0


def explanation_depth(results: list[dict]) -> dict:
    """A cheap proxy for explanation quality that needs no human panel.

    Not a substitute for the Likert study in PRD §44 — it measures whether an
    explanation exists and is specific, not whether it is good.
    """
    pros = [len(c.get("pros", [])) for c in results]
    cons = [len(c.get("cons", [])) for c in results]
    tradeoffs = [len(c.get("tradeoffs", [])) for c in results]
    lengths = [len(c.get("why", "")) for c in results]
    return {
        "mean_pros": round(mean(pros), 2) if pros else 0,
        "mean_cons": round(mean(cons), 2) if cons else 0,
        "mean_tradeoffs": round(mean(tradeoffs), 2) if tradeoffs else 0,
        "mean_reason_chars": round(mean(lengths), 1) if lengths else 0,
        "share_with_a_criticism": round(sum(1 for c in cons if c > 0) / len(cons), 3) if cons else 0,
    }


def describe(values: list[float]) -> dict:
    """Mean, median, spread and a normal-approximation 95% interval.

    PRD §66 is explicit that accuracy alone is not enough; every reported number
    should carry its uncertainty.
    """
    if not values:
        return {"n": 0}
    n = len(values)
    sd = pstdev(values) if n > 1 else 0.0
    half_width = 1.96 * sd / math.sqrt(n) if n > 1 else 0.0
    m = mean(values)
    return {
        "n": n,
        "mean": round(m, 4),
        "median": round(median(values), 4),
        "sd": round(sd, 4),
        "ci95": [round(m - half_width, 4), round(m + half_width, 4)],
    }


def cohens_d(a: list[float], b: list[float]) -> float:
    """Effect size for a paired comparison of two systems."""
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    diffs = [x - y for x, y in zip(a, b)]
    sd = pstdev(diffs)
    return round(mean(diffs) / sd, 4) if sd > 0 else 0.0


def wilcoxon_signed_rank(a: list[float], b: list[float]) -> dict:
    """Non-parametric paired test (PRD §66), implemented without SciPy.

    Uses the normal approximation, which is adequate above roughly ten pairs and
    keeps the project free of another dependency. Ties are dropped, as is
    conventional. For a final report, confirm with a full implementation.
    """
    diffs = [x - y for x, y in zip(a, b) if abs(x - y) > 1e-12]
    n = len(diffs)
    if n < 6:
        return {"n": n, "note": "too few non-tied pairs for a meaningful test"}

    ranked = sorted(enumerate(diffs), key=lambda kv: abs(kv[1]))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(abs(ranked[j + 1][1]) - abs(ranked[i][1])) < 1e-12:
            j += 1
        average_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[ranked[k][0]] = average_rank
        i = j + 1

    w_plus = sum(r for r, d in zip(ranks, diffs) if d > 0)
    w_minus = sum(r for r, d in zip(ranks, diffs) if d < 0)
    w = min(w_plus, w_minus)
    mu = n * (n + 1) / 4
    sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    z = (w - mu) / sigma if sigma > 0 else 0.0
    p = 2 * (1 - _normal_cdf(abs(z)))
    return {
        "n": n, "w_plus": round(w_plus, 2), "w_minus": round(w_minus, 2),
        "z": round(z, 4), "p_two_sided": round(p, 5),
        "significant_at_05": bool(p < 0.05),
    }


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
