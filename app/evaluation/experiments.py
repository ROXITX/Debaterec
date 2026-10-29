"""Baseline comparison and ablation harness (PRD §13, §46, §63).

Run it with:

    python -m app.evaluation.experiments               # all conditions
    python -m app.evaluation.experiments --only E1,E4  # a subset
    python -m app.evaluation.experiments --sweep-alpha # tune the hybrid weight

Every condition goes through the same pipeline as the live application. There is
no separate "evaluation implementation" that could drift from the shipped one,
which is the usual way ablation numbers stop describing the real system.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from ..config import settings
from ..domains.registry import load_domain
from ..llm.factory import create_llm, llm_status, shutdown_llm
from ..pipeline import recommend
from . import metrics

QUERY_FILE = settings.root / "data" / "evaluation" / "queries.json"
REPORT_DIR = settings.root / "data" / "processed"

# The experimental matrix of PRD §63. `method` maps onto the debate engine's
# ablation switches; "popularity" and "tfidf" are handled separately because
# they bypass the pipeline entirely.
CONDITIONS = [
    ("E0", "popularity",     "Baseline A — rank by rating and popularity alone"),
    ("E1", "retrieval",      "Baseline C — hybrid retrieval only, no debate"),
    ("E2", "supporter_only", "Retrieval + Supporter"),
    ("E3", "no_judge",       "Retrieval + Supporter + Critic, rule-based aggregation"),
    ("E4", "debate",         "Full system — Supporter + Critic + Judge"),
]


def load_queries() -> list[dict]:
    with open(QUERY_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)["queries"]


async def run_condition(code: str, method: str, queries: list[dict], top_k: int = 5,
                        curated_only: bool = True) -> dict:
    per_query: list[dict] = []
    recommended_by_domain: dict[str, list[str]] = {}

    for case in queries:
        relevance = {k: float(v) for k, v in case["relevance"].items()}
        relevant = {k for k, v in relevance.items() if v >= 2}
        started = time.perf_counter()

        if method == "popularity":
            ranked, cards, calls = popularity_baseline(case["domain"], top_k, curated_only), [], 0
        else:
            payload = await recommend(case["query"], case["domain"], top_k, method,
                                      curated_only=curated_only)
            cards = payload["results"]
            ranked = [c["item_id"] for c in cards]
            calls = payload["metrics"].get("llm_calls", 0)

        seconds = time.perf_counter() - started
        recommended_by_domain.setdefault(case["domain"], []).extend(ranked)

        per_query.append({
            "id": case["id"],
            "domain": case["domain"],
            "p@5": round(metrics.precision_at_k(ranked, relevant, 5), 4),
            "r@5": round(metrics.recall_at_k(ranked, relevant, 5), 4),
            "ndcg@5": metrics.ndcg_at_k(ranked, relevance, 5),
            "mrr": round(metrics.mrr(ranked, relevant), 4),
            "hit@3": metrics.hit_rate(ranked, relevant, 3),
            "violation_rate": metrics.constraint_violation_rate(cards),
            "constraint_satisfaction": metrics.mean_constraint_satisfaction(cards),
            "seconds": round(seconds, 3),
            "llm_calls": calls,
            "explanation": metrics.explanation_depth(cards),
        })

    def column(name: str) -> list[float]:
        return [q[name] for q in per_query]

    cov = {
        domain: metrics.coverage(ids, len(load_domain(domain, True)))
        for domain, ids in recommended_by_domain.items()
    }

    return {
        "condition": code,
        "method": method,
        "queries": len(queries),
        "summary": {
            "p@5": metrics.describe(column("p@5")),
            "r@5": metrics.describe(column("r@5")),
            "ndcg@5": metrics.describe(column("ndcg@5")),
            "mrr": metrics.describe(column("mrr")),
            "hit@3": metrics.describe(column("hit@3")),
            "violation_rate": metrics.describe(column("violation_rate")),
            "constraint_satisfaction": metrics.describe(column("constraint_satisfaction")),
            "seconds": metrics.describe(column("seconds")),
            "llm_calls_total": sum(column("llm_calls")),
            "mean_cons_shown": round(
                sum(q["explanation"]["mean_cons"] for q in per_query) / max(len(per_query), 1), 3
            ),
            "share_with_a_criticism": round(
                sum(q["explanation"]["share_with_a_criticism"] for q in per_query) / max(len(per_query), 1), 3
            ),
        },
        "coverage": cov,
        "per_query": per_query,
    }


def popularity_baseline(domain: str, top_k: int, curated_only: bool = True) -> list[str]:
    """PRD §13 Baseline A. Ignores the query completely, which is the point:
    it establishes what a non-personalised system achieves on this test set."""
    items = sorted(
        load_domain(domain, curated_only),
        key=lambda i: ((i.rating or 0), i.popularity),
        reverse=True,
    )
    return [i.item_id for i in items[:top_k]]


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DebateRec baseline and ablation runner")
    parser.add_argument("--only", help="comma-separated condition codes, e.g. E1,E4")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0,
                        help="use only the first N labelled queries — for staying inside a "
                             "free-tier daily quota while still getting a directional result")
    parser.add_argument("--rpm", type=int, default=0,
                        help="override the requests-per-minute throttle for this run")
    parser.add_argument("--sweep-alpha", action="store_true", help="tune the hybrid retrieval weight")
    parser.add_argument("--out", default=str(REPORT_DIR / "experiment_report.json"))
    parser.add_argument("--full-catalogue", action="store_true",
                        help="evaluate against the full catalogue including generated filler "
                             "(metrics become uninterpretable; use only to measure latency at scale)")
    args = parser.parse_args(argv)

    queries = load_queries()
    if args.limit:
        queries = queries[:args.limit]
    if args.rpm:
        object.__setattr__(settings, "gemini_rpm", args.rpm)
    curated_only = not args.full_catalogue
    pool_note = ("curated records only" if curated_only
                 else "FULL catalogue including generated filler")
    print(f"\n  {len(queries)} labelled queries across {len({q['domain'] for q in queries})} domains")
    print(f"  Reasoning backend: {llm_status()}")
    print(f"  Evaluating against: {pool_note}")
    if settings.llm_provider == "gemini" and settings.gemini_api_key:
        per_query = 1 + 3 * settings.candidates_debate
        print(f"  Budget estimate   : up to ~{per_query} LLM calls per query for E4, "
              f"~{len(queries) * per_query} for that condition alone.")
        print(f"                      Throttled to {settings.gemini_rpm or 'unlimited'} requests/minute.")
    if not curated_only:
        print("  WARNING: the labelled set only covers curated records, so an unlabelled")
        print("           generated item in the top 5 counts as a miss. Relevance metrics")
        print("           from this mode are not comparable to the default run.")
    print()

    if args.sweep_alpha:
        return await sweep_alpha(queries, args.top_k)

    wanted = set((args.only or "").split(",")) if args.only else None
    report = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "provider": llm_status(),
              "pool": pool_note, "conditions": []}

    for code, method, label in CONDITIONS:
        if wanted and code not in wanted:
            continue
        print(f"  {code}  {label}")
        result = await run_condition(code, method, queries, args.top_k, curated_only)
        result["label"] = label
        report["conditions"].append(result)
        s = result["summary"]
        print(
            f"        P@5 {s['p@5']['mean']:.3f}   NDCG@5 {s['ndcg@5']['mean']:.3f}   "
            f"MRR {s['mrr']['mean']:.3f}   hard-violations {s['violation_rate']['mean']:.3f}   "
            f"{s['seconds']['mean']:.2f}s/query   {s['llm_calls_total']} LLM calls"
        )

    # Paired comparison of the full system against retrieval alone (PRD §66).
    by_code = {c["condition"]: c for c in report["conditions"]}
    if "E1" in by_code and "E4" in by_code:
        for metric in ("ndcg@5", "p@5", "violation_rate"):
            base = [q[metric] for q in by_code["E1"]["per_query"]]
            full = [q[metric] for q in by_code["E4"]["per_query"]]
            report.setdefault("significance", {})[f"E4_vs_E1_{metric}"] = {
                "wilcoxon": metrics.wilcoxon_signed_rank(full, base),
                "cohens_d": metrics.cohens_d(full, base),
                "mean_delta": round(
                    sum(full) / len(full) - sum(base) / len(base), 4
                ),
            }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n  Written to {out}\n")

    if "significance" in report:
        print("  Full system vs retrieval-only:")
        for key, value in report["significance"].items():
            w = value["wilcoxon"]
            note = w.get("note") or (
                f"p={w['p_two_sided']:.4f} "
                f"({'significant' if w.get('significant_at_05') else 'not significant'} at .05)"
            )
            print(f"    {key:26s} delta {value['mean_delta']:+.4f}  d={value['cohens_d']:+.3f}  {note}")
        print()

    await shutdown_llm()
    return 0


async def sweep_alpha(queries: list[dict], top_k: int) -> int:
    """PRD §37 asks for alpha to be evaluated rather than assumed."""
    from ..config import Settings

    print("  Sweeping the hybrid retrieval weight (retrieval-only condition)\n")
    print(f"  {'alpha':>6}  {'P@5':>6}  {'NDCG@5':>7}  {'MRR':>6}")
    original = settings.hybrid_alpha
    best = (None, -1.0)
    try:
        for alpha in [round(0.3 + 0.1 * i, 2) for i in range(8)]:
            object.__setattr__(settings, "hybrid_alpha", alpha)
            result = await run_condition("SWEEP", "retrieval", queries, top_k)
            s = result["summary"]
            print(f"  {alpha:>6.2f}  {s['p@5']['mean']:>6.3f}  {s['ndcg@5']['mean']:>7.3f}  {s['mrr']['mean']:>6.3f}")
            if s["ndcg@5"]["mean"] > best[1]:
                best = (alpha, s["ndcg@5"]["mean"])
    finally:
        object.__setattr__(settings, "hybrid_alpha", original)

    print(f"\n  Best NDCG@5 at alpha = {best[0]} ({best[1]:.3f}).")
    print("  Note this tunes the ceiling of the retrieval stage, not the debate.\n")
    await shutdown_llm()
    return 0


if __name__ == "__main__":
    create_llm()
    sys.exit(asyncio.run(main()))
