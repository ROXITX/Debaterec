"""Domain registry and rule-based domain routing.

Adding an eighth domain: write the adapter, import it, append it to `ADAPTERS`.
Nothing else in the codebase changes.
"""

from __future__ import annotations

import re
from functools import lru_cache

from ..config import settings
from ..schemas import Item
from .base import DomainAdapter
from .bikes import BikesAdapter
from .books import BooksAdapter
from .cars import CarsAdapter
from .courses import CoursesAdapter
from .laptops import LaptopsAdapter
from .movies import MoviesAdapter
from .phones import PhonesAdapter

ADAPTERS: list[DomainAdapter] = [
    MoviesAdapter(),
    BooksAdapter(),
    CoursesAdapter(),
    PhonesAdapter(),
    LaptopsAdapter(),
    CarsAdapter(),
    BikesAdapter(),
]

REGISTRY: dict[str, DomainAdapter] = {a.key: a for a in ADAPTERS}


def get_adapter(domain: str) -> DomainAdapter:
    if domain not in REGISTRY:
        raise KeyError(f"unknown domain {domain!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[domain]


@lru_cache(maxsize=None)
def load_domain(domain: str, curated_only: bool = False) -> tuple[Item, ...]:
    """Load a catalogue.

    `curated_only` drops the procedurally generated filler, leaving the
    hand-checked records. The evaluation harness uses it: the labelled query set
    only covers curated records, so an unlabelled synthetic item appearing in the
    top 5 would be counted as a miss regardless of whether it was a sensible
    recommendation, and every metric would be depressed for a reason that has
    nothing to do with ranking quality.
    """
    items = get_adapter(domain).load(settings.data_raw)
    if curated_only:
        return tuple(i for i in items if not i.synthetic)
    return tuple(items)


def load_all() -> dict[str, tuple[Item, ...]]:
    return {key: load_domain(key) for key in REGISTRY}


@lru_cache(maxsize=None)
def domain_stats(domain: str, curated_only: bool = False) -> dict[str, dict[str, float]]:
    """Per-facet percentiles over the real catalogue.

    Vague language needs a reference point. "A cheap phone" should mean cheap
    *relative to the phones that exist*, so the NLP layer reads its thresholds
    from here instead of from a constant baked into the code.
    """
    items = load_domain(domain, curated_only)
    adapter = get_adapter(domain)
    out: dict[str, dict[str, float]] = {}
    for facet in adapter.facets:
        values = sorted(i.facets[facet.name] for i in items if facet.name in i.facets)
        if len(values) < 3:
            continue
        out[facet.name] = {
            "min": values[0],
            "max": values[-1],
            "p35": _quantile(values, 0.35),
            "p50": _quantile(values, 0.50),
            "p65": _quantile(values, 0.65),
        }
    return out


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return round(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac, 3)


def catalogue() -> list[dict]:
    out = []
    for adapter in ADAPTERS:
        load_domain(adapter.key)  # ensures counts are populated
        out.append(adapter.as_dict())
    return out


# ---------------------------------------------------------------------------
# Rule-based domain routing (PRD §10.3)
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"[a-z0-9][a-z0-9'&.+-]*")


def route(query: str) -> tuple[str, float, dict[str, float]]:
    """Score every domain against the query. Returns (domain, confidence, scores).

    Evidence is weighted by how *specific* a signal is: an explicit routing word
    ("laptop") outweighs a brand name, which outweighs a generic tag value that
    several domains share ("performance", "budget").
    """
    text = " " + query.lower().strip() + " "
    tokens = set(_TOKEN.findall(text))
    scores: dict[str, float] = {}

    for adapter in ADAPTERS:
        score = 0.0
        for word in adapter.routing_words:
            if " " in word:
                if word in text:
                    score += 4.0
            elif word in tokens:
                score += 3.0
            elif word.endswith("s") and word[:-1] in tokens:
                score += 3.0

        # Brand / provider names are strong but not decisive signals.
        for tag_name in ("brand", "provider", "director", "author"):
            spec = adapter.tag_spec(tag_name)
            if not spec:
                continue
            for value in spec.vocabulary:
                if value and value in text:
                    score += 2.0

        # Generic vocabulary overlap — weak evidence, breaks ties only.
        overlap = tokens & adapter.vocabulary()
        score += 0.35 * len(overlap)
        scores[adapter.key] = round(score, 3)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

    if best_score <= 0.9:
        return best, 0.0, scores  # nothing recognisable — caller should ask

    margin = (best_score - runner_up) / max(best_score, 1e-6)
    confidence = min(0.99, 0.45 + 0.55 * margin)
    return best, round(confidence, 3), scores
