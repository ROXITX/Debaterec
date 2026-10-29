"""Judge agent (PRD §17) — synthesises both sides into a score and a verdict."""

from __future__ import annotations

from ..config import settings
from ..schemas import CriticOutput, JudgeOutput, SupporterOutput
from .base import AgentContext, DebateAgent

SHAPE = """{
  "final_score": 0.0,
  "decision": "recommend | consider | reject",
  "confidence": 0.0,
  "matched_preferences": ["what genuinely matched"],
  "tradeoffs": ["what the person gives up, specifically"],
  "reason": "1-2 sentences addressed to the person, naming the deciding facts"
}"""


class JudgeAgent(DebateAgent):
    role = "judge"
    prompt_name = "judge"
    schema = JudgeOutput

    def user_prompt(self, ctx: AgentContext, supporter=None, critic=None, rebuttal=None, **kwargs) -> str:
        sup = "\n".join(f"  + {p}" for p in (supporter.fit_points + supporter.strengths)) or "  (nothing offered)"
        crit = "\n".join(f"  - {w}" for w in critic.weaknesses) or "  (no objections raised)"
        blocks = [
            ctx.domain_line(),
            ctx.preferences_block(),
            ctx.candidate_block(),
            ctx.audit_block(),
            ctx.retrieval_block(),
            f"SUPPORTER (score {supporter.support_score}/10, evidence fields: "
            f"{', '.join(supporter.evidence_fields) or 'none cited'}):\n{sup}",
            f"CRITIC (survives-scrutiny score {critic.critic_score}/10):\n{crit}",
        ]
        if critic.tradeoffs:
            blocks.append("CRITIC TRADE-OFFS:\n" + "\n".join(f"  ~ {t}" for t in critic.tradeoffs))
        if critic.unsupported_claims:
            blocks.append(
                "CRITIC FLAGGED AS UNSUPPORTED:\n"
                + "\n".join(f"  ! {c}" for c in critic.unsupported_claims)
                + "\nDiscount any Supporter point listed here."
            )
        if rebuttal:
            blocks.append(f"SUPPORTER REBUTTAL:\n  {rebuttal}")
        blocks += [
            f"OUTPUT SHAPE:\n{SHAPE}",
            "TASK: Decide how this candidate should be scored for this person, and explain it to them.",
        ]
        return "\n\n".join(blocks)

    async def run(self, ctx: AgentContext, **kwargs):  # type: ignore[override]
        # PRD §71: a stronger model may be reserved for final judgement only.
        if settings.gemini_judge_model and settings.llm_provider == "gemini":
            kwargs.setdefault("model", settings.gemini_judge_model)
        return await super().run(ctx, **kwargs)

    def heuristic(self, ctx: AgentContext, supporter=None, critic=None, **kwargs) -> JudgeOutput:
        supporter = supporter or SupporterOutput()
        critic = critic or CriticOutput()
        checks = ctx.candidate.checks
        hard_fail = [c for c in checks if c.hard and c.status == "fail"]
        matched = [c.facet for c in checks if c.status == "pass"]

        score = _blend(ctx, supporter, critic)
        if hard_fail:
            score = min(score, 4.0)

        known = [c for c in checks if c.status != "unknown"]
        coverage = len(known) / len(checks) if checks else 0.6
        confidence = 0.35 + 0.45 * coverage + 0.20 * ctx.candidate.constraint_score

        # A candidate that clearly misses something the person cared about is
        # never a clean "recommend", however well it scores elsewhere.
        notable_miss = any(
            c.status == "fail" and c.importance >= 0.65 and c.degree < 0.55 for c in checks
        )
        if hard_fail:
            decision = "reject"
        elif score >= settings.threshold_recommend and not notable_miss:
            decision = "recommend"
        elif score >= settings.threshold_consider:
            decision = "consider"
        else:
            decision = "reject"

        reason = _reason(ctx, checks, hard_fail, decision)
        return JudgeOutput(
            item_id=ctx.candidate.item.item_id,
            final_score=round(min(10.0, max(0.0, score)), 2),
            decision=decision,  # type: ignore[arg-type]
            confidence=round(min(0.98, max(0.05, confidence)), 2),
            matched_preferences=matched,
            tradeoffs=critic.tradeoffs,
            reason=reason,
        )


def _blend(ctx: AgentContext, supporter: SupporterOutput, critic: CriticOutput) -> float:
    """The transparent hybrid score of PRD §19.

        FinalScore = 0.35R + 0.25S + 0.20E + 0.10C + 0.10P - lambda * CriticPenalty

    R retrieval relevance, S supporter score, E evidence quality, C constraint
    satisfaction, P preference match. Every weight lives in config.py and is
    swept by evaluation/experiments.py — the PRD is explicit that these are
    hyperparameters, not settled values.
    """
    s = settings
    evidence = _evidence_quality(ctx, supporter)
    base = 10.0 * (
        s.w_retrieval * ctx.candidate.semantic
        + s.w_support * (supporter.support_score / 10.0)
        + s.w_evidence * evidence
        + s.w_constraint * ctx.candidate.constraint_score
        + s.w_preference * ctx.candidate.preference_score
    )
    penalty = max(0.0, (10.0 - critic.critic_score) / 10.0)
    return base - s.critic_penalty_lambda * penalty * 3.0


def _evidence_quality(ctx: AgentContext, supporter: SupporterOutput) -> float:
    """How much of the argument rests on data that actually exists.

    Two components: how many of the person's constraints could be checked at all,
    and whether the Supporter cited fields rather than asserting.
    """
    checks = ctx.candidate.checks
    coverage = (
        len([c for c in checks if c.status != "unknown"]) / len(checks) if checks else 0.6
    )
    cited = min(1.0, len(supporter.evidence_fields) / 4.0) if supporter.evidence_fields else 0.35
    return round(0.65 * coverage + 0.35 * cited, 4)


def _phrase(label: str) -> str:
    """Turn an internal constraint label into something readable in a sentence."""
    return (
        label.replace("must have ", "")
        .replace("must be ", "")
        .replace("prefers ", "")
        .replace(" at most ", " under ")
        .replace(" at least ", " of at least ")
        .replace("no ", "no ")
    )


def _reason(ctx, checks, hard_fail, decision: str) -> str:
    name = ctx.candidate.item.title
    passed = [c for c in checks if c.status == "pass"]
    failed = [c for c in checks if c.status == "fail"]

    if hard_fail:
        c = hard_fail[0]
        return f"{name} breaks a requirement you set — you asked for {_phrase(c.label)}, and it is {c.actual}."

    if passed:
        good = " and ".join(_phrase(c.label) for c in passed[:2])
        if failed:
            bad = failed[0]
            return (
                f"{name} gives you {good}. The compromise is {_phrase(bad.label)}, "
                f"where it comes in at {bad.actual}."
            )
        return f"{name} meets everything you asked for, including {good}."

    if decision == "reject":
        return f"{name} does not line up with what you described on any of the points you raised."
    return f"{name} is the closest available match on overall description, though nothing you specified could be verified against its data."
