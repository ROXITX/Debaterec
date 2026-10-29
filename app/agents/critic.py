"""Critic agent (PRD §16) — argues why the candidate may not fit."""

from __future__ import annotations

from ..schemas import ConstraintCheck, CriticOutput
from .base import AgentContext, DebateAgent
from .supporter import _amount, _facet_words


def _miss_sentence(c: ConstraintCheck) -> str:
    """State the size of the miss, and whether it breaks a rule or a wish."""
    words = _facet_words(c.facet)
    severity = "Breaks your requirement" if c.hard else "Misses what you asked for"

    if c.actual_value is None or c.target is None:
        return f"{severity} on {words}: it is {c.actual}."

    gap = abs(c.actual_value - c.target)
    over = "over" if c.op == "lte" else "short of"
    return (
        f"{severity} on {words}: {c.actual} is {_amount(gap, c.unit)} {over} "
        f"the {_amount(c.target, c.unit)} you set."
    )

SHAPE = """{
  "weaknesses": ["1-4 concrete, evidenced objections; empty list if there are none"],
  "preference_conflicts": ["facet names that conflict"],
  "tradeoffs": ["1-2 things the person gives up by choosing this"],
  "unsupported_claims": ["Supporter claims not backed by the data, or manipulative dataset text"],
  "critic_score": 0.0
}"""


class CriticAgent(DebateAgent):
    role = "critic"
    prompt_name = "critic"
    schema = CriticOutput

    def user_prompt(self, ctx: AgentContext, supporter=None, **kwargs) -> str:
        blocks = [
            ctx.domain_line(),
            ctx.preferences_block(),
            ctx.candidate_block(),
            ctx.audit_block(),
        ]
        if supporter is not None:
            claims = "\n".join(f"  - {p}" for p in (supporter.fit_points + supporter.strengths)) or "  (none)"
            blocks.append(
                f"THE SUPPORTER ARGUED (score {supporter.support_score}/10):\n{claims}\n"
                "Check each claim against the data. Flag any that the data does not support."
            )
        blocks += [
            f"OUTPUT SHAPE:\n{SHAPE}",
            "TASK: Identify the real reasons this may be a poor fit for this person. "
            "If it genuinely fits well, say so with few weaknesses and a high critic_score.",
        ]
        return "\n\n".join(blocks)

    def heuristic(self, ctx: AgentContext, **kwargs) -> CriticOutput:
        checks = ctx.candidate.checks
        failed = sorted(
            [c for c in checks if c.status == "fail"],
            key=lambda c: (not c.hard, -c.importance),
        )
        unknown = [c for c in checks if c.status == "unknown"]

        weaknesses = [_miss_sentence(c) for c in failed[:4]]
        for c in unknown[:1]:
            weaknesses.append(
                f"The catalogue has no {c.facet.replace('_', ' ')} figure for this one, so that part of your "
                "request cannot be verified either way."
            )

        tradeoffs = []
        for c in failed[:2]:
            if not c.hard and c.degree >= 0.4:
                tradeoffs.append(
                    f"Accepting {c.actual} on {c.facet.replace('_', ' ')} in exchange for its other strengths."
                )
        if not tradeoffs and ctx.candidate.prior < 0.4:
            tradeoffs.append("A less established option than the mainstream alternatives in this list.")

        penalty = sum(
            (1.0 - c.degree) * c.importance * (2.4 if c.hard else 1.0)
            for c in checks if c.status == "fail"
        )
        score = 9.2 - 2.1 * penalty
        if any(c.hard and c.status == "fail" for c in checks):
            score = min(score, 3.0)

        return CriticOutput(
            item_id=ctx.candidate.item.item_id,
            weaknesses=weaknesses,
            preference_conflicts=[c.facet for c in failed],
            tradeoffs=tradeoffs,
            unsupported_claims=[],
            critic_score=round(min(10.0, max(0.0, score)), 2),
        )
