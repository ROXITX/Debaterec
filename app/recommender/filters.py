"""Deterministic constraint auditing (PRD §20).

This module is the system's ground truth. Every constraint is evaluated in
Python, before any model is called, and the resulting `ConstraintCheck` list is
handed to the agents as fact. The Critic is told to trust it, and the Judge is
told to override any argument that contradicts it.

That ordering is deliberate: it is what stops a fluent but wrong Supporter
argument from moving an item up the ranking, which is the main failure mode of
LLM-as-a-judge systems (PRD §48).
"""

from __future__ import annotations

from ..domains.base import DomainAdapter
from ..schemas import CategoricalConstraint, ConstraintCheck, Item, NumericConstraint, QuerySpec


def _format_actual(item: Item, constraint: NumericConstraint, adapter: DomainAdapter) -> str:
    value = item.facet(constraint.facet)
    if value is None:
        return "not recorded"
    spec = adapter.facet(constraint.facet)
    unit = f" {spec.unit}" if spec and spec.unit else ""
    if constraint.facet == "price":
        return "Free" if value <= 0 else f"₹{value:,.0f}"
    if value == int(value):
        return f"{int(value)}{unit}"
    return f"{value:g}{unit}"


def audit(item: Item, spec: QuerySpec, adapter: DomainAdapter) -> list[ConstraintCheck]:
    checks: list[ConstraintCheck] = []

    for c in spec.numeric:
        actual = item.facet(c.facet)
        ok = c.satisfied_by(actual)
        checks.append(ConstraintCheck(
            label=c.human(),
            facet=c.facet,
            hard=c.hard,
            status="unknown" if ok is None else ("pass" if ok else "fail"),
            actual=_format_actual(item, c, adapter),
            degree=round(c.degree(actual), 3),
            importance=c.importance,
            target=c.value,
            actual_value=actual,
            op=c.op.value,
            unit=c.unit or "",
        ))

    for c in spec.categorical:
        values = item.tag(c.facet)
        degree = c.degree(values)
        violated = c.violated_by(values)
        if not values:
            status = "unknown"
        elif violated:
            status = "fail"
        elif degree >= 0.5:
            status = "pass"
        else:
            status = "fail"
        checks.append(ConstraintCheck(
            label=c.human(),
            facet=c.facet,
            hard=c.hard,
            status=status,
            actual=", ".join(values[:6]) if values else "not recorded",
            degree=round(degree, 3),
            importance=c.importance,
        ))

    return checks


def hard_violations(checks: list[ConstraintCheck]) -> list[ConstraintCheck]:
    return [c for c in checks if c.hard and c.status == "fail"]


def constraint_score(checks: list[ConstraintCheck]) -> float:
    """Importance-weighted satisfaction across every constraint, in [0, 1]."""
    if not checks:
        return 0.75  # nothing asked for: neutral-positive
    total = sum(c.importance for c in checks) or 1.0
    return sum(c.degree * c.importance for c in checks) / total


def preference_score(checks: list[ConstraintCheck]) -> float:
    """Soft-constraint satisfaction only — how well tastes (as opposed to
    requirements) were met. Reported separately so the UI can distinguish
    "meets your rules" from "matches your taste"."""
    soft = [c for c in checks if not c.hard]
    if not soft:
        return 0.75
    total = sum(c.importance for c in soft) or 1.0
    return sum(c.degree * c.importance for c in soft) / total


def apply_hard_filters(
    items: list[Item], spec: QuerySpec, adapter: DomainAdapter
) -> tuple[list[Item], list[Item], bool]:
    """Split the catalogue into (kept, rejected, relaxed).

    `relaxed` is True when enforcing the hard constraints would leave too little
    to work with. Rather than telling the user "no results", the pipeline keeps
    going and the Critic surfaces the violation on every card — which is the
    behaviour PRD §50 Failure Case 2 asks for.
    """
    if not spec.hard_constraints:
        return list(items), [], False

    kept, rejected = [], []
    for item in items:
        if hard_violations(audit(item, spec, adapter)):
            rejected.append(item)
        else:
            kept.append(item)

    if len(kept) < 3:
        return list(items), [], True
    return kept, rejected, False


def quality_prior(item: Item, adapter: DomainAdapter, stats: dict[str, dict[str, float]]) -> float:
    """A small popularity/rating prior in [0, 1] (the PRD §13 Baseline A signal).

    Kept deliberately weak. It breaks ties between otherwise equal candidates
    without letting blockbusters bulldoze a well-matched niche item.
    """
    parts: list[float] = []
    for facet in ("rating", "popularity"):
        value = item.facet(facet)
        band = stats.get(facet)
        if value is None or not band:
            continue
        lo, hi = band["min"], band["max"]
        if hi > lo:
            parts.append((value - lo) / (hi - lo))
    if not parts:
        return 0.5
    return sum(parts) / len(parts)
