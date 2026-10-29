"""Debate orchestration (PRD §18).

The protocol is deliberately *controlled* rather than a free agent-to-agent
conversation: unrestricted chat between two LLMs is expensive, hard to bound and
almost impossible to evaluate. Here every candidate goes through the same fixed
sequence, which makes the debate layer measurable as an independent component —
the whole point of the project.

    round 1   Supporter states the case
    round 2   Critic challenges it, having seen the case
    round 3   Supporter rebuts (optional, off by default for latency)
    round 4   Judge decides

Rounds run in phases across candidates rather than candidate-by-candidate, for
two reasons: every candidate's Supporter call can go out concurrently, and the
UI can show one honest "the Supporters are arguing / the Critics are responding"
progression instead of a scrambled order.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from ..config import settings
from ..domains.registry import get_adapter
from ..llm.base import LLMClient, gather_limited
from ..recommender.retrieval import Candidate
from ..schemas import CriticOutput, DebateResult, JudgeOutput, QuerySpec, SupporterOutput
from .base import AgentContext
from .critic import CriticAgent
from .judge import JudgeAgent
from .supporter import SupporterAgent

Emit = Callable[[dict], Awaitable[None]]

REBUTTAL_SYSTEM = (
    "You are the SUPPORTER, responding to the Critic's objections in a structured "
    "recommendation debate. Concede any objection that the data supports — conceding "
    "clearly is more useful than defending. Rebut only where the CANDIDATE DATA "
    "genuinely contradicts the Critic. Two sentences maximum. Reply with "
    'ONLY {"rebuttal": "..."}.'
)


class DebateEngine:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm
        self.supporter = SupporterAgent(llm)
        self.critic = CriticAgent(llm)
        self.judge = JudgeAgent(llm)

    @property
    def mode(self) -> str:
        return "llm" if self.llm is not None else "deterministic"

    async def run(
        self,
        spec: QuerySpec,
        candidates: list[Candidate],
        *,
        method: str = "debate",
        emit: Emit | None = None,
    ) -> list[DebateResult]:
        adapter = get_adapter(spec.domain)
        contexts = [AgentContext(spec, adapter, c, i) for i, c in enumerate(candidates)]

        async def send(payload: dict) -> None:
            if emit:
                await emit(payload)

        # --- retrieval-only baseline (PRD §46 Experiment A) ----------------
        if method == "retrieval":
            return [_retrieval_only(ctx) for ctx in contexts]

        # --- round 1: Supporter -------------------------------------------
        await send({"type": "round", "round": "supporter", "status": "start", "count": len(contexts)})
        supporters = await self._phase(
            [self.supporter.run(ctx) for ctx in contexts], contexts, "supporter", send, SupporterOutput
        )
        await send({"type": "round", "round": "supporter", "status": "end"})

        # --- round 2: Critic ----------------------------------------------
        if method == "supporter_only":
            critics = [CriticAgent(None).heuristic(ctx) for ctx in contexts]
        else:
            await send({"type": "round", "round": "critic", "status": "start", "count": len(contexts)})
            critics = await self._phase(
                [self.critic.run(ctx, supporter=s) for ctx, s in zip(contexts, supporters)],
                contexts, "critic", send, CriticOutput,
            )
            await send({"type": "round", "round": "critic", "status": "end"})

        # --- round 3: optional rebuttal ------------------------------------
        rebuttals: list[str | None] = [None] * len(contexts)
        if settings.debate_rebuttal and self.llm is not None and method == "debate":
            await send({"type": "round", "round": "rebuttal", "status": "start", "count": len(contexts)})
            rebuttals = await self._rebuttals(contexts, supporters, critics, send)
            await send({"type": "round", "round": "rebuttal", "status": "end"})

        # --- round 4: Judge -------------------------------------------------
        # `supporter_only` must skip the judge too. It previously did not, which
        # made condition E2 "retrieval + Supporter + Judge" while the report
        # called it "retrieval + Supporter" — so the isolated effect of the
        # Supporter was never actually measured.
        if method in {"no_judge", "supporter_only"}:
            judges = [
                JudgeAgent(None).heuristic(ctx, supporter=s, critic=c)
                for ctx, s, c in zip(contexts, supporters, critics)
            ]
        else:
            await send({"type": "round", "round": "judge", "status": "start", "count": len(contexts)})
            judges = await self._phase(
                [
                    self.judge.run(ctx, supporter=s, critic=c, rebuttal=r)
                    for ctx, s, c, r in zip(contexts, supporters, critics, rebuttals)
                ],
                contexts, "judge", send, JudgeOutput,
            )
            await send({"type": "round", "round": "judge", "status": "end"})

        results = [
            _assemble(ctx, s, c, j, r)
            for ctx, s, c, j, r in zip(contexts, supporters, critics, judges, rebuttals)
        ]
        return results

    # -- internals ---------------------------------------------------------
    async def _phase(self, coros, contexts, role: str, send: Emit, schema) -> list[Any]:
        for ctx in contexts:
            await send({
                "type": "agent", "role": role, "status": "thinking",
                "item_id": ctx.candidate.item.item_id, "title": ctx.candidate.item.title,
                "accent": ctx.candidate.item.accent,
            })
        started = time.perf_counter()
        raw = await gather_limited(list(coros), limit=6)
        outputs = []
        for ctx, value in zip(contexts, raw):
            if isinstance(value, Exception):
                if "rate limit" in str(value).lower() or "quota" in str(value).lower():
                    raise value
            if isinstance(value, Exception) or value is None:
                agent = {"supporter": self.supporter, "critic": self.critic, "judge": self.judge}[role]
                value = agent.heuristic(ctx)
            outputs.append(value)
            await send({
                "type": "agent", "role": role, "status": "done",
                "item_id": ctx.candidate.item.item_id, "title": ctx.candidate.item.title,
                "accent": ctx.candidate.item.accent,
                "payload": _agent_payload(role, value),
            })
        await send({
            "type": "timing", "round": role, "seconds": round(time.perf_counter() - started, 2),
        })
        return outputs

    async def _rebuttals(self, contexts, supporters, critics, send: Emit) -> list[str | None]:
        async def one(ctx, sup, crit):
            if not crit.weaknesses:
                return None
            objections = "\n".join(f"  - {w}" for w in crit.weaknesses)
            prompt = "\n\n".join([
                ctx.candidate_block(),
                ctx.audit_block(),
                f"THE CRITIC OBJECTED:\n{objections}",
                'Reply with ONLY {"rebuttal": "..."}.',
            ])
            try:
                raw = await self.llm.generate(REBUTTAL_SYSTEM, prompt, role="rebuttal", json_mode=True)
                from ..llm.base import extract_json

                return str(extract_json(raw).get("rebuttal", "")).strip() or None
            except Exception:  # noqa: BLE001
                return None

        out = await gather_limited(
            [one(ctx, s, c) for ctx, s, c in zip(contexts, supporters, critics)], limit=6
        )
        cleaned = []
        for v in out:
            if isinstance(v, Exception):
                if "rate limit" in str(v).lower() or "quota" in str(v).lower():
                    raise v
                cleaned.append(None)
            else:
                cleaned.append(v)
        for ctx, text in zip(contexts, cleaned):
            if text:
                await send({
                    "type": "agent", "role": "rebuttal", "status": "done",
                    "item_id": ctx.candidate.item.item_id, "title": ctx.candidate.item.title,
                    "accent": ctx.candidate.item.accent, "payload": {"rebuttal": text},
                })
        return cleaned


def _agent_payload(role: str, value) -> dict:
    if role == "supporter":
        return {
            "score": value.support_score,
            "points": (value.fit_points + value.strengths)[:4],
            "matches": value.preference_matches[:5],
        }
    if role == "critic":
        return {
            "score": value.critic_score,
            "points": value.weaknesses[:4] or ["No material objection to this candidate."],
            "tradeoffs": value.tradeoffs[:2],
            "flags": value.unsupported_claims[:2],
        }
    return {
        "score": value.final_score,
        "decision": value.decision,
        "confidence": value.confidence,
        "points": [value.reason] if value.reason else [],
        "tradeoffs": value.tradeoffs[:2],
    }


def _assemble(ctx: AgentContext, sup, crit, judge, rebuttal) -> DebateResult:
    from .judge import _evidence_quality

    return DebateResult(
        item=ctx.candidate.item,
        retrieval_score=ctx.candidate.semantic,
        constraint_score=ctx.candidate.constraint_score,
        preference_score=ctx.candidate.preference_score,
        evidence_score=_evidence_quality(ctx, sup),
        supporter=sup,
        critic=crit,
        judge=judge,
        rebuttal=rebuttal,
        checks=ctx.candidate.checks,
        final_score=judge.final_score,
    )


def _retrieval_only(ctx: AgentContext) -> DebateResult:
    """Baseline C from PRD §13: retrieval score alone, no argumentation."""
    item = ctx.candidate.item
    score = round(10.0 * ctx.candidate.hybrid, 2)
    return DebateResult(
        item=item,
        retrieval_score=ctx.candidate.semantic,
        constraint_score=ctx.candidate.constraint_score,
        preference_score=ctx.candidate.preference_score,
        evidence_score=0.0,
        supporter=SupporterOutput(item_id=item.item_id, support_score=score),
        critic=CriticOutput(item_id=item.item_id, critic_score=score),
        judge=JudgeOutput(
            item_id=item.item_id, final_score=score,
            decision="recommend" if score >= 7 else "consider",
            confidence=round(ctx.candidate.hybrid, 2),
            reason="Ranked by hybrid retrieval score only — no debate was run for this comparison condition.",
        ),
        checks=ctx.candidate.checks,
        final_score=score,
    )
