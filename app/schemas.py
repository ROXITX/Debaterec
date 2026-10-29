"""Common data contracts shared by every layer and every domain.

The single most important idea in this file is that *preferences are typed
constraints over named facets*, not domain-specific fields. "under two hours"
(movies), "under 40k rupees" (phones), "under three months" (courses) and
"above 40 kmpl" (bikes) all become the same `NumericConstraint` object with a
different facet name. That is what lets one retrieval engine, one debate
engine and one judge serve seven domains without branching.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Preference representation (PRD §11)
# ---------------------------------------------------------------------------


class Op(str, Enum):
    LTE = "lte"
    GTE = "gte"
    BETWEEN = "between"
    APPROX = "approx"


class NumericConstraint(BaseModel):
    """A constraint over a numeric facet such as price, runtime or rating."""

    facet: str
    op: Op
    value: float
    value2: float | None = None
    hard: bool = False
    importance: float = Field(default=0.7, ge=0.0, le=1.0)
    unit: str | None = None
    source: str = "query"  # query | feedback | memory | default
    # How far a miss has to be before it stops mattering. Set from the spread of
    # this facet across the real catalogue. Without it, decay is normalised by
    # the constraint value itself, and "after 2015" would rate a 1984 film at
    # 97% satisfied simply because 31 is small next to 2015.
    scale: float | None = None

    def satisfied_by(self, actual: float | None) -> bool | None:
        """None means "unknown" — the item simply lacks this facet."""
        if actual is None:
            return None
        if self.op is Op.LTE:
            return actual <= self.value
        if self.op is Op.GTE:
            return actual >= self.value
        if self.op is Op.BETWEEN:
            hi = self.value2 if self.value2 is not None else self.value
            return min(self.value, hi) <= actual <= max(self.value, hi)
        # APPROX: within 15% of the target
        return abs(actual - self.value) <= max(abs(self.value) * 0.15, 1e-9)

    def degree(self, actual: float | None) -> float:
        """Graded satisfaction in [0, 1] — soft constraints decay, not cliff.

        A 130-minute film against "preferably under 120" should not score the
        same as a 200-minute one. Missing data returns a neutral 0.5 so an item
        is neither rewarded nor punished for an incomplete record.
        """
        if actual is None:
            return 0.5
        ok = self.satisfied_by(actual)
        if ok:
            return 1.0
        # Prefer the catalogue spread; fall back to the constraint value, and
        # never let the two disagree by orders of magnitude.
        if self.scale and self.scale > 0:
            scale = min(abs(self.value) or self.scale, self.scale)
        else:
            scale = abs(self.value)
        scale = max(scale, 1e-6)
        if self.op is Op.LTE:
            overshoot = (actual - self.value) / scale
        elif self.op is Op.GTE:
            overshoot = (self.value - actual) / scale
        elif self.op is Op.BETWEEN:
            hi = max(self.value, self.value2 or self.value)
            lo = min(self.value, self.value2 or self.value)
            overshoot = (actual - hi) / scale if actual > hi else (lo - actual) / scale
        else:
            overshoot = abs(actual - self.value) / scale
        # 0% over -> 1.0, 50% over -> 0.0
        return max(0.0, 1.0 - max(overshoot, 0.0) * 2.0)

    def _quantity(self, value: float) -> str:
        if self.unit == "INR":
            return "free" if value <= 0 else f"₹{value:,.0f}"
        unit = f" {self.unit}" if self.unit else ""
        return f"{_num(value)}{unit}"

    def human(self) -> str:
        label = self.facet.replace("_", " ")
        if self.op is Op.LTE:
            body = f"{label} at most {self._quantity(self.value)}"
        elif self.op is Op.GTE:
            body = f"{label} at least {self._quantity(self.value)}"
        elif self.op is Op.BETWEEN:
            body = (f"{label} between {self._quantity(self.value)} "
                    f"and {self._quantity(self.value2 or self.value)}")
        else:
            body = f"{label} around {self._quantity(self.value)}"
        return ("must have " if self.hard else "prefers ") + body


class CategoricalConstraint(BaseModel):
    """Include / exclude sets over a tag facet such as genre, brand or fuel."""

    facet: str
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    hard: bool = False
    importance: float = Field(default=0.7, ge=0.0, le=1.0)
    source: str = "query"

    @field_validator("include", "exclude", mode="before")
    @classmethod
    def _lower(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        return [str(x).strip().lower() for x in v if str(x).strip()]

    def degree(self, values: list[str] | None) -> float:
        if not values:
            return 0.5
        have = {v.lower() for v in values}

        def hit(wanted: str) -> bool:
            return any(wanted in h or h in wanted for h in have)

        score = 0.5
        if self.include:
            matched = sum(1 for w in self.include if hit(w))
            score = matched / len(self.include)
        if self.exclude and any(hit(w) for w in self.exclude):
            score = 0.0
        return score

    def violated_by(self, values: list[str] | None) -> bool:
        if not values:
            return False
        have = {v.lower() for v in values}

        def hit(wanted: str) -> bool:
            return any(wanted in h or h in wanted for h in have)

        if self.exclude and any(hit(w) for w in self.exclude):
            return True
        if self.hard and self.include and not any(hit(w) for w in self.include):
            return True
        return False

    def human(self) -> str:
        label = self.facet.replace("_", " ")
        bits = []
        if self.include:
            bits.append(f"{label}: {', '.join(self.include)}")
        if self.exclude:
            bits.append(f"no {', '.join(self.exclude)}")
        return ("must be " if self.hard else "prefers ") + "; ".join(bits)


class QuerySpec(BaseModel):
    """The structured output of the NLP layer — the system's internal query."""

    raw_query: str
    domain: str
    domain_confidence: float = 0.5
    domain_source: Literal["user", "llm", "rules"] = "rules"
    intent: str = "recommend"
    keywords: list[str] = Field(default_factory=list)
    semantic_query: str = ""
    numeric: list[NumericConstraint] = Field(default_factory=list)
    categorical: list[CategoricalConstraint] = Field(default_factory=list)
    tone: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    extraction_source: Literal["llm", "rules", "hybrid"] = "rules"

    @property
    def hard_constraints(self) -> list[NumericConstraint | CategoricalConstraint]:
        return [c for c in (*self.numeric, *self.categorical) if c.hard]

    def summary_lines(self) -> list[str]:
        return [c.human() for c in (*self.numeric, *self.categorical)]


# ---------------------------------------------------------------------------
# Item representation (PRD §23) — one schema, seven domains
# ---------------------------------------------------------------------------


class Item(BaseModel):
    item_id: str
    domain: str
    title: str
    subtitle: str = ""
    description: str = ""

    # Numeric facets in *normalized units* (see each adapter for the contract).
    facets: dict[str, float] = Field(default_factory=dict)
    # Categorical facets.
    tags: dict[str, list[str]] = Field(default_factory=dict)
    # Ordered, human-readable spec rows for the UI.
    display: list[tuple[str, str]] = Field(default_factory=list)

    rating: float | None = None
    popularity: float = 0.0
    accent: str = ""  # optional per-item accent colour hint for the UI
    # True for procedurally generated catalogue filler. The evaluation harness
    # excludes these, because the labelled query set only covers curated records
    # and an unlabelled item in the top 5 is scored as a miss whether or not it
    # was a good recommendation.
    synthetic: bool = False

    # Cached retrieval text; built once by the adapter.
    text_blob: str = ""

    def facet(self, name: str) -> float | None:
        return self.facets.get(name)

    def tag(self, name: str) -> list[str]:
        return self.tags.get(name, [])

    def evidence_block(self) -> str:
        """Exactly the item information an agent is allowed to reason from.

        Everything here is untrusted dataset content; the prompt builder wraps
        it in a delimiter and instructs the model to treat it as data only.
        """
        lines = [f"Title: {self.title}"]
        if self.subtitle:
            lines.append(f"Subtitle: {self.subtitle}")
        for key, value in self.display:
            lines.append(f"{key}: {value}")
        if self.rating is not None:
            lines.append(f"Rating: {self.rating}")
        if self.description:
            lines.append(f"Description: {self.description}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent outputs (PRD §15–§17)
# ---------------------------------------------------------------------------


class SupporterOutput(BaseModel):
    item_id: str = ""
    fit_points: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    preference_matches: list[str] = Field(default_factory=list)
    evidence_fields: list[str] = Field(default_factory=list)
    support_score: float = Field(default=5.0, ge=0.0, le=10.0)


class CriticOutput(BaseModel):
    item_id: str = ""
    weaknesses: list[str] = Field(default_factory=list)
    preference_conflicts: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    critic_score: float = Field(default=5.0, ge=0.0, le=10.0)


class JudgeOutput(BaseModel):
    item_id: str = ""
    final_score: float = Field(default=5.0, ge=0.0, le=10.0)
    decision: Literal["recommend", "consider", "reject"] = "consider"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    matched_preferences: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    reason: str = ""


class ConstraintCheck(BaseModel):
    """Deterministic, code-computed constraint audit.

    This runs *before* any LLM sees the candidate. The agents receive it as
    ground truth, which is the main defence against a persuasive-but-wrong
    argument swaying the ranking.
    """

    label: str
    facet: str
    hard: bool
    status: Literal["pass", "fail", "unknown"]
    actual: str = ""
    degree: float = 0.5
    importance: float = 0.7
    # Raw numbers kept alongside the formatted string so an agent can talk about
    # the *margin* ("10 g under your limit") rather than restating the check.
    target: float | None = None
    actual_value: float | None = None
    op: str = ""
    unit: str = ""


class DebateResult(BaseModel):
    rank: int = 0
    item: Item
    retrieval_score: float = 0.0
    constraint_score: float = 0.0
    preference_score: float = 0.0
    evidence_score: float = 0.0
    supporter: SupporterOutput
    critic: CriticOutput
    judge: JudgeOutput
    rebuttal: str | None = None
    checks: list[ConstraintCheck] = Field(default_factory=list)
    final_score: float = 0.0

    def as_card(self) -> dict:
        return {
            "rank": self.rank,
            "item_id": self.item.item_id,
            "domain": self.item.domain,
            "synthetic": self.item.synthetic,
            "title": self.item.title,
            "subtitle": self.item.subtitle,
            "description": self.item.description,
            "display": [list(d) for d in self.item.display],
            "accent": self.item.accent,
            "score": round(self.final_score, 2),
            "confidence": round(self.judge.confidence, 2),
            "decision": self.judge.decision,
            "why": self.judge.reason,
            "pros": self.supporter.fit_points or self.supporter.strengths,
            "cons": self.critic.weaknesses,
            "tradeoffs": self.judge.tradeoffs or self.critic.tradeoffs,
            "matched": self.judge.matched_preferences or self.supporter.preference_matches,
            "checks": [c.model_dump() for c in self.checks],
            "breakdown": {
                "retrieval": round(self.retrieval_score, 3),
                "supporter": round(self.supporter.support_score, 2),
                "critic": round(self.critic.critic_score, 2),
                "evidence": round(self.evidence_score, 3),
                "constraints": round(self.constraint_score, 3),
                "preferences": round(self.preference_score, 3),
            },
            "debate": {
                "supporter": self.supporter.model_dump(),
                "critic": self.critic.model_dump(),
                "judge": self.judge.model_dump(),
                "rebuttal": self.rebuttal,
            },
        }


# ---------------------------------------------------------------------------
# API payloads
# ---------------------------------------------------------------------------


class RecommendRequest(BaseModel):
    query: str
    domain: str = "auto"
    top_k: int = 5
    session_id: str = "anon"
    method: Literal["debate", "retrieval", "supporter_only", "no_judge", "llm_direct"] = "debate"
    curated_only: bool = False


class FeedbackRequest(BaseModel):
    session_id: str = "anon"
    item_id: str
    domain: str = ""
    feedback: Literal["liked", "disliked", "loved", "blocked"]
    comment: str = ""


def _num(x: float) -> str:
    return str(int(x)) if abs(x - round(x)) < 1e-9 else f"{x:g}"
