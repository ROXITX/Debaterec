"""The NLP stage: natural language in, structured `QuerySpec` out.

Two extractors run and are merged:

  * **rules** (`parser.extract`) — deterministic, unit-aware, always available.
    High precision on explicit constraints ("under 30k", "after 2015").
  * **LLM** — catches implicit and compositional preferences that no rule set
    covers ("for my mother who has never ridden before" implies a low seat
    height, light weight and beginner-friendliness).

Merge policy: the rule extractor is authoritative for any facet it resolved,
because it cannot hallucinate a number. The LLM may only *add* facets the rules
missed, and may promote a constraint to hard when the sentence really does
contain an obligation. This keeps the measurable behaviour deterministic while
still getting the LLM's coverage — and it is the reason the extraction layer can
be evaluated separately from the debate layer.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from ..domains.base import DomainAdapter
from ..domains.registry import REGISTRY, domain_stats, get_adapter, route
from ..llm.base import LLMClient
from ..schemas import CategoricalConstraint, NumericConstraint, Op, QuerySpec
from . import parser

# ---------------------------------------------------------------------------
# LLM extraction contract
# ---------------------------------------------------------------------------


class _LLMNumeric(BaseModel):
    facet: str
    op: str = "lte"
    value: float
    value2: float | None = None
    hard: bool = False
    importance: float = 0.7


class _LLMCategorical(BaseModel):
    facet: str
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    hard: bool = False
    importance: float = 0.7


class _LLMExtraction(BaseModel):
    semantic_query: str = ""
    numeric: list[_LLMNumeric] = Field(default_factory=list)
    categorical: list[_LLMCategorical] = Field(default_factory=list)
    tone: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


EXTRACTION_SYSTEM = """You convert a person's recommendation request into structured preferences.

You are given the exact facet vocabulary of one domain. You must use ONLY facet
names from that list. Never invent a facet.

Rules you must follow:
1. A constraint is HARD only when the sentence expresses an obligation or a firm
   ceiling ("must", "needs to", "no more than", "only", "cannot exceed", a stated
   budget). Wishes ("preferably", "ideally", "would like", "maybe") are SOFT.
2. Capture NEGATIVE preferences in `exclude`, never as an `include` of the opposite.
3. Convert units to the unit stated for the facet. Two hours is 120 minutes.
   Three months is 13 weeks. "30k" is 30000. "1.5 lakh" is 150000.
4. Capture IMPLICIT preferences that follow from the situation the person
   describes, and mark them soft with lower importance. Someone describing a
   first-time rider implies light weight and a low seat; someone describing daily
   train commuting implies portability.
5. `importance` is 0 to 1 and reflects how much the person seems to care.
6. If the request is too vague to rank well, list what is missing in `ambiguities`.
7. Reply with ONLY a JSON object. No commentary."""

EXTRACTION_TEMPLATE = """{schema}

OUTPUT SHAPE:
{{
  "semantic_query": "a short paraphrase of what they actually want, for semantic search",
  "numeric": [{{"facet": "...", "op": "lte|gte|between|approx", "value": 0, "value2": null, "hard": false, "importance": 0.7}}],
  "categorical": [{{"facet": "...", "include": [], "exclude": [], "hard": false, "importance": 0.7}}],
  "tone": ["..."],
  "ambiguities": ["..."]
}}

USER REQUEST:
\"\"\"{query}\"\"\""""


DOMAIN_SYSTEM = """You classify which catalogue a recommendation request belongs to.
Reply with ONLY a JSON object: {"domain": "<key>", "confidence": 0.0-1.0, "reason": "<8 words>"}.
If the request does not fit any catalogue, use "domain": "none"."""


# ---------------------------------------------------------------------------
# Domain routing
# ---------------------------------------------------------------------------


async def detect_domain(query: str, requested: str, llm: LLMClient | None) -> tuple[str, float, str, dict]:
    """Returns (domain, confidence, source, per-domain rule scores)."""
    if requested and requested != "auto":
        if requested not in REGISTRY:
            raise KeyError(requested)
        _, _, scores = route(query)
        return requested, 1.0, "user", scores

    domain, confidence, scores = route(query)
    if confidence >= 0.6 or llm is None:
        return domain, confidence, "rules", scores

    # Rules were unsure — ask the model, but only accept a known domain.
    options = "\n".join(f'  - "{a.key}": {a.label} — {a.blurb}' for a in REGISTRY.values())
    raw = await llm.generate(
        DOMAIN_SYSTEM,
        f"CATALOGUES:\n{options}\n\nREQUEST:\n\"\"\"{query}\"\"\"",
        role="router",
        json_mode=True,
    )
    try:
        data = json.loads(raw) if raw.strip().startswith("{") else {}
    except json.JSONDecodeError:
        data = {}
    picked = str(data.get("domain", "")).strip().lower()
    if picked in REGISTRY:
        return picked, float(data.get("confidence", 0.7) or 0.7), "llm", scores
    return domain, confidence, "rules", scores


# ---------------------------------------------------------------------------
# Preference extraction
# ---------------------------------------------------------------------------


async def understand(
    query: str,
    requested_domain: str = "auto",
    llm: LLMClient | None = None,
) -> QuerySpec:
    domain, confidence, source, _scores = await detect_domain(query, requested_domain, llm)
    adapter = get_adapter(domain)

    spec = parser.extract(query, adapter, domain_stats(domain, False))
    spec.domain = domain
    spec.domain_confidence = confidence
    spec.domain_source = source  # type: ignore[assignment]

    if llm is not None:
        enriched = await _llm_extract(query, adapter, llm)
        if enriched is not None:
            _merge(spec, enriched, adapter)
            spec.extraction_source = "hybrid"

    if not spec.semantic_query:
        spec.semantic_query = query.strip()
    if not spec.numeric and not spec.categorical:
        spec.ambiguities.append(
            f"No specific constraints were detected — ranking will rely on overall {adapter.noun} quality and text similarity."
        )
    return spec


async def _llm_extract(query: str, adapter: DomainAdapter, llm: LLMClient) -> _LLMExtraction | None:
    prompt = EXTRACTION_TEMPLATE.format(schema=adapter.describe_for_llm(), query=query.strip())
    return await llm.structured(EXTRACTION_SYSTEM, prompt, _LLMExtraction, role="extractor")


def _merge(spec: QuerySpec, llm_out: _LLMExtraction, adapter: DomainAdapter) -> None:
    if llm_out.semantic_query:
        spec.semantic_query = llm_out.semantic_query.strip()

    have_numeric = {c.facet for c in spec.numeric}
    for cand in llm_out.numeric:
        facet = adapter.resolve_facet(cand.facet) or cand.facet
        fspec = adapter.facet(facet)
        if fspec is None:
            continue  # model invented a facet — drop it
        if facet in have_numeric:
            # Rules already resolved this one; only allow a hardness promotion.
            if cand.hard:
                for existing in spec.numeric:
                    if existing.facet == facet and _has_obligation(spec.raw_query):
                        existing.hard = True
                        existing.importance = max(existing.importance, 0.9)
            continue
        try:
            op = Op(cand.op.lower())
        except ValueError:
            op = Op.LTE
        band = domain_stats(adapter.key).get(facet, {})
        spread = (band.get("max", 0) - band.get("min", 0)) or (fspec.typical[1] - fspec.typical[0])
        spec.numeric.append(NumericConstraint(
            facet=facet, op=op, value=float(cand.value),
            value2=cand.value2, hard=bool(cand.hard) and _has_obligation(spec.raw_query),
            importance=min(max(cand.importance, 0.0), 1.0),
            unit=fspec.unit, source="llm", scale=float(spread) or None,
        ))
        have_numeric.add(facet)

    have_cat = {c.facet: c for c in spec.categorical}
    for cand in llm_out.categorical:
        facet = adapter.resolve_tag(cand.facet) or cand.facet
        if adapter.tag_spec(facet) is None:
            continue
        if facet in have_cat:
            existing = have_cat[facet]
            for v in cand.include:
                v = v.strip().lower()
                if v and v not in existing.include and v not in existing.exclude:
                    existing.include.append(v)
            for v in cand.exclude:
                v = v.strip().lower()
                if v and v not in existing.exclude:
                    existing.exclude.append(v)
                    if v in existing.include:
                        existing.include.remove(v)
            continue
        cc = CategoricalConstraint(
            facet=facet, include=cand.include, exclude=cand.exclude,
            hard=bool(cand.hard) and _has_obligation(spec.raw_query),
            importance=min(max(cand.importance, 0.0), 1.0), source="llm",
        )
        if cc.include or cc.exclude:
            spec.categorical.append(cc)
            have_cat[facet] = cc

    for t in llm_out.tone:
        t = t.strip().lower()
        if t and t not in spec.tone:
            spec.tone.append(t)
    for a in llm_out.ambiguities:
        a = a.strip()
        if a and a not in spec.ambiguities:
            spec.ambiguities.append(a)


def _has_obligation(query: str) -> bool:
    """Guard against the model over-eagerly marking wishes as hard filters."""
    low = " " + query.lower() + " "
    return any(c in low for c in parser.HARD_CUES)


def spec_debug(spec: QuerySpec) -> dict[str, Any]:
    return {
        "domain": spec.domain,
        "domain_confidence": spec.domain_confidence,
        "domain_source": spec.domain_source,
        "extraction_source": spec.extraction_source,
        "semantic_query": spec.semantic_query,
        "constraints": [
            {
                "text": c.human(),
                "facet": c.facet,
                "hard": c.hard,
                "importance": round(c.importance, 2),
                "source": c.source,
            }
            for c in (*spec.numeric, *spec.categorical)
        ],
        "keywords": spec.keywords[:10],
        "ambiguities": spec.ambiguities,
    }
