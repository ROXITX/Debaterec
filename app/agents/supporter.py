"""Supporter agent (PRD §15) — argues why the candidate fits."""

from __future__ import annotations

from ..schemas import ConstraintCheck, SupporterOutput
from .base import AgentContext, DebateAgent


def _facet_words(facet: str) -> str:
    return facet.replace("_", " ")


def _number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:g}"


def _amount(value: float, unit: str) -> str:
    """Render a quantity the way a person would write it in that unit."""
    if unit == "INR":
        return f"₹{value:,.0f}"
    return _number(value) + (f" {unit}" if unit else "")


def _margin_sentence(c: ConstraintCheck) -> str:
    """Say how much headroom there is, which the audit chip cannot show."""
    words = _facet_words(c.facet)

    if c.actual_value is None or c.target is None:
        return f"Matches on {words}: {c.actual}."

    gap = abs(c.actual_value - c.target)
    if c.op == "lte":
        if gap < 1e-9:
            return f"{words.capitalize()} lands exactly on your limit at {c.actual}."
        return f"{c.actual} on {words} — {_amount(gap, c.unit)} inside your limit of {_amount(c.target, c.unit)}."
    if c.op == "gte":
        if gap < 1e-9:
            return f"{words.capitalize()} meets your floor exactly at {c.actual}."
        return f"{c.actual} on {words} — {_amount(gap, c.unit)} above the {_amount(c.target, c.unit)} you wanted."
    return f"{words.capitalize()} is {c.actual}, in the range you asked for."

SHAPE = """{
  "fit_points": ["2-4 short, concrete reasons this fits THEIR request"],
  "strengths": ["1-3 notable strengths, only if evidenced"],
  "preference_matches": ["facet names that are genuinely satisfied"],
  "evidence_fields": ["the CANDIDATE DATA field names you relied on"],
  "support_score": 0.0
}"""


class SupporterAgent(DebateAgent):
    role = "supporter"
    prompt_name = "supporter"
    schema = SupporterOutput

    def user_prompt(self, ctx: AgentContext, **kwargs) -> str:
        return "\n\n".join([
            ctx.domain_line(),
            ctx.preferences_block(),
            ctx.candidate_block(),
            ctx.audit_block(),
            ctx.retrieval_block(),
            f"OUTPUT SHAPE:\n{SHAPE}",
            "TASK: Make the strongest honest case for this candidate. Ground every claim in the data above.",
        ])

    def heuristic(self, ctx: AgentContext, **kwargs) -> SupporterOutput:
        checks = ctx.candidate.checks
        passed = [c for c in checks if c.status == "pass"]
        near = [c for c in checks if c.status == "fail" and c.degree >= 0.6]

        item = ctx.candidate.item
        # Restating the constraint audit would be useless — the interface already
        # shows it. The argument is worth making only if it adds something, so
        # each point reports the *margin*: how much room is left, not just that
        # the box is ticked.
        fit_points = [
            _margin_sentence(c) for c in sorted(passed, key=lambda c: -c.importance)[:4]
        ]
        for c in near[:1]:
            fit_points.append(
                f"Only just outside on {_facet_words(c.facet)} at {c.actual} — close enough to be worth a look."
            )

        strengths: list[str] = []
        if item.rating is not None and ctx.candidate.prior >= 0.6:
            strengths.append(f"Well regarded at {item.rating}, near the top of this catalogue.")
        if ctx.candidate.semantic >= 0.72:
            strengths.append("Its description lines up closely with how you phrased the request.")
        if item.description:
            first = item.description.split(". ")[0].strip().rstrip(".")
            if first and len(first) > 24:
                strengths.append(f"{first}.")
        if not fit_points and not strengths:
            fit_points.append(f"{item.title} is the closest available match on overall description.")

        base = 4.0 + 5.5 * ctx.candidate.constraint_score
        base += 0.6 * ctx.candidate.semantic
        if any(c.hard and c.status == "fail" for c in checks):
            base = min(base, 3.5)

        return SupporterOutput(
            item_id=item.item_id,
            fit_points=fit_points,
            strengths=strengths,
            preference_matches=[c.facet for c in passed],
            evidence_fields=sorted({label for label, _ in item.display})[:6],
            support_score=round(min(10.0, max(0.0, base)), 2),
        )
