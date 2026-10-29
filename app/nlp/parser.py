"""Deterministic preference extraction.

This is the rule-based half of the NLP layer. It runs on every query, with or
without an LLM, and it is what makes the system testable: the same sentence
always produces the same constraints.

It handles the four things that actually break naive keyword systems:

  * unit-aware numbers — "30k", "1.5 lakh", "two hours", "three months",
    "under 250 pages", "over 40 kmpl" all resolve to the right facet,
  * comparison direction — under / at least / between / around,
  * hard vs soft — "must be under 120 minutes" is a filter,
    "preferably under 120 minutes" is a preference (PRD §20),
  * negation — "not horror", "no diesel", "avoid long books".
"""

from __future__ import annotations

import re

from ..domains.base import DomainAdapter
from ..schemas import CategoricalConstraint, NumericConstraint, Op, QuerySpec

# ---------------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------------

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "hundred": 100, "couple": 2, "few": 3,
}

MULTIPLIERS = {
    "k": 1_000, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000,
    "lac": 100_000, "l": 100_000, "crore": 10_000_000, "cr": 10_000_000,
    "m": 1_000_000, "million": 1_000_000,
}

LTE_CUES = (
    "under", "below", "less than", "at most", "no more than", "not more than",
    "within", "up to", "upto", "max", "maximum", "cheaper than", "under about",
    "lighter than", "shorter than", "smaller than", "budget of", "budget is",
    "or less", "or under", "or below",
)
GTE_CUES = (
    "over", "above", "more than", "at least", "minimum", "min", "no less than",
    "greater than", "longer than", "bigger than", "higher than", "starting from",
    "or more", "plus", "atleast",
)
APPROX_CUES = ("around", "about", "roughly", "approximately", "near", "circa", "~")

HARD_CUES = (
    "must", "must be", "need", "needs to", "has to", "have to", "required",
    "strictly", "only", "absolutely", "non-negotiable", "no more than",
    "cannot", "can't", "hard limit", "maximum of", "at most", "definitely",
)
SOFT_CUES = (
    "prefer", "preferably", "ideally", "would like", "nice to have", "maybe",
    "if possible", "somewhat", "kind of", "sort of", "hopefully", "leaning",
)

NEGATION_CUES = (
    "not", "no", "don't", "dont", "do not", "avoid", "without", "except",
    "never", "nothing", "hate", "dislike", "anything but", "other than",
    "isn't", "steer clear",
)

# Unit token -> the canonical facet unit it maps onto.
UNIT_HINTS: dict[str, str] = {
    "minute": "minutes", "minutes": "minutes", "min": "minutes", "mins": "minutes",
    "hour": "hours", "hours": "hours", "hr": "hours", "hrs": "hours",
    "week": "weeks", "weeks": "weeks", "month": "months", "months": "months",
    "page": "pages", "pages": "pages", "pg": "pages",
    "kmpl": "kmpl", "mileage": "kmpl",
    "km": "km", "kms": "km", "kilometre": "km", "kilometres": "km",
    "mah": "mAh", "watt": "W", "watts": "W", "w": "W",
    "mp": "MP", "megapixel": "MP", "megapixels": "MP",
    "gb": "GB", "tb": "GB",
    "inch": "in", "inches": "in", "in": "in", '"': "in",
    "hz": "Hz",
    "gram": "g", "grams": "g", "g": "g",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg",
    "cc": "cc",
    "bhp": "bhp", "hp": "bhp", "horsepower": "bhp",
    "star": "stars", "stars": "stars",
    "seat": "seats", "seats": "seats", "seater": "seats",
    "litre": "litres", "litres": "litres", "liter": "litres", "liters": "litres", "l": "litres",
    "year": "years", "years": "years", "yr": "years",
}

CURRENCY_CUES = ("₹", "rs", "rs.", "inr", "rupees", "rupee", "budget", "price", "cost", "spend", "under")

# The \b after the multiplier group matters: without it the "m" of "months"
# is read as the "million" multiplier and "three months" becomes 3,000,000.
_NUM_TOKEN = re.compile(
    r"(?P<num>\d+(?:\.\d+)?|\b(?:" + "|".join(NUMBER_WORDS) + r")\b)"
    r"\s*(?P<mult>(?:k|thousand|lakhs?|lac|crore|cr|m|million)\b)?"
    r"\s*(?P<unit>[a-z\"]+)?",
    re.IGNORECASE,
)

# How far before a number a comparison cue may sit and still govern it.
# "under 30k" binds; the "under" in "under 15 lakh with 5 star safety" does not
# reach across to the 5.
CUE_RADIUS = 8


def _value(num_text: str, mult_text: str | None) -> float:
    base = NUMBER_WORDS.get(num_text.lower())
    if base is None:
        base = float(num_text)
    mult = MULTIPLIERS.get((mult_text or "").lower(), 1)
    return float(base) * mult


def _window(text: str, start: int, end: int, before: int = 46, after: int = 26) -> str:
    return text[max(0, start - before): min(len(text), end + after)]


def _op_from_context(text: str, start: int, default: Op) -> Op | None:
    """Find the comparison cue nearest to (and before) the number.

    Returns None when no cue is close enough, which tells the caller to fall back
    to the facet's own natural direction rather than guessing "at most".
    """
    left = text[max(0, start - CUE_RADIUS - 12): start]
    best: tuple[int, Op] | None = None
    for cues, op in ((LTE_CUES, Op.LTE), (GTE_CUES, Op.GTE), (APPROX_CUES, Op.APPROX)):
        for cue in cues:
            i = left.rfind(cue)
            if i < 0:
                continue
            distance = len(left) - (i + len(cue))
            if distance > CUE_RADIUS:
                continue
            if best is None or distance < best[0]:
                best = (distance, op)
    if best is not None:
        return best[1]
    return None if default is None else None


def _hardness(text: str, start: int) -> bool:
    """Hardness is judged from the clause the number sits in, not the whole
    sentence — otherwise one "must" anywhere turns every preference into a
    filter and the result set collapses to nothing."""
    left = text[max(0, start - 46): start]
    clause = re.split(r"[,;.]| and | but | with ", left)[-1] if left else ""
    scope = clause if clause.strip() else left
    if any(c in scope for c in SOFT_CUES):
        return False
    return any(c in scope for c in HARD_CUES)


def _facet_by_unit(adapter: DomainAdapter, unit: str) -> str | None:
    """Map a spelled unit onto a facet of this domain."""
    canonical = UNIT_HINTS.get(unit.lower())
    if not canonical:
        return None
    for f in adapter.facets:
        if f.unit and f.unit.lower() == canonical.lower():
            return f.name
    # Cross-unit equivalences the adapters normalise internally.
    equivalents = {
        "hours": {"movie": "runtime"},
        "minutes": {"movie": "runtime"},
        "months": {"course": "weeks"},
        "weeks": {"course": "weeks"},
        "years": {"phone": "updates", "laptop": None},
    }
    return (equivalents.get(canonical) or {}).get(adapter.key)


def _convert(value: float, unit: str, facet_name: str, adapter: DomainAdapter) -> float:
    """Unit conversions the user expects to be implicit."""
    canonical = UNIT_HINTS.get(unit.lower(), "")
    if facet_name == "runtime" and canonical == "hours":
        return value * 60
    if facet_name == "weeks" and canonical == "months":
        return round(value * 4.345)
    if facet_name == "storage" and unit.lower() == "tb":
        return value * 1024
    return value


def _facet_by_nearby_words(adapter: DomainAdapter, ctx: str) -> str | None:
    """No unit given — infer the facet from the words around the number."""
    best: tuple[int, str] | None = None
    for f in adapter.facets:
        for alias in f.aliases:
            i = ctx.rfind(alias)
            if i >= 0 and (best is None or i > best[0]):
                best = (i, f.name)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def extract(
    query: str,
    adapter: DomainAdapter,
    stats: dict[str, dict[str, float]] | None = None,
) -> QuerySpec:
    """`stats` carries real percentiles per facet from the loaded catalogue, so
    that vague words like "cheap" or "big battery" resolve against what actually
    exists rather than against a hard-coded guess."""
    stats = stats or {}
    text = " " + re.sub(r"\s+", " ", query.lower().strip()) + " "
    numeric: list[NumericConstraint] = []
    seen_facets: set[str] = set()

    # --- numeric constraints ----------------------------------------------
    for m in _NUM_TOKEN.finditer(text):
        num_text, mult_text, unit = m.group("num"), m.group("mult"), (m.group("unit") or "")
        if unit.lower() in NUMBER_WORDS or unit.lower() in {"and", "or", "the", "a", "of", "for", "with"}:
            unit = ""
        try:
            value = _value(num_text, mult_text)
        except ValueError:
            continue

        ctx = _window(text, m.start(), m.end())
        facet_name = _facet_by_unit(adapter, unit) if unit else None

        # A number with a rupee multiplier or currency word is a price.
        if facet_name is None and (mult_text or any(c in ctx for c in CURRENCY_CUES)):
            if adapter.facet("price") is not None:
                # Guard: "under 5 stars" or "after 2015" are not prices.
                if not (1900 <= value <= 2100 and not mult_text) and unit.lower() not in UNIT_HINTS:
                    facet_name = "price"

        # A bare four-digit number in 1900-2100 is a year, where the domain has one.
        if facet_name is None and 1900 <= value <= 2100 and not mult_text and adapter.facet("year"):
            facet_name = "year"

        if facet_name is None:
            facet_name = _facet_by_nearby_words(adapter, ctx)
        if facet_name is None or adapter.facet(facet_name) is None:
            continue

        value = _convert(value, unit, facet_name, adapter)
        spec = adapter.facet(facet_name)

        op = _op_from_context(text, m.start(), None)
        if op is None:
            # No cue within reach. Fall back to the facet's own direction:
            # "5 star safety" and "16GB RAM" are floors; "1.3kg" is a ceiling.
            op = Op.LTE if (spec and spec.better == "lower") else Op.GTE
        # Year phrasing that the generic cue list does not cover.
        if facet_name == "year":
            if re.search(r"\b(after|since|newer than|post|from)\b", text[max(0, m.start() - 22): m.start()]):
                op = Op.GTE
            elif re.search(r"\b(before|older than|pre)\b", text[max(0, m.start() - 22): m.start()]):
                op = Op.LTE

        if facet_name in seen_facets:
            continue
        seen_facets.add(facet_name)
        hard = _hardness(text, m.start())
        numeric.append(
            NumericConstraint(
                facet=facet_name, op=op, value=value, hard=hard,
                importance=0.9 if hard else 0.72, unit=spec.unit if spec else None,
                scale=_scale_for(facet_name, spec, stats),
            )
        )

    # --- qualitative numeric preferences ("cheap", "lightweight", "big battery")
    for f in adapter.facets:
        if f.name in seen_facets:
            continue
        pct = stats.get(f.name, {})
        lo, hi = f.typical
        low_target = _tidy(pct.get("p35", lo + 0.35 * (hi - lo)))
        high_target = _tidy(pct.get("p65", lo + 0.65 * (hi - lo)))

        hit = _find_qualitative(text, f.low_words)
        direction = "low"
        if hit is None:
            hit = _find_qualitative(text, f.high_words)
            direction = "high"
        if hit is None:
            continue

        negated = hit[1]
        # "not too heavy" is a request for a LOW weight, even though the matched
        # word came from the high-value list.
        if negated:
            direction = "low" if direction == "high" else "high"
        scale = _scale_for(f.name, f, stats)
        if direction == "low":
            numeric.append(NumericConstraint(
                facet=f.name, op=Op.LTE, value=low_target, hard=False,
                importance=0.6, unit=f.unit, source="query", scale=scale,
            ))
        else:
            numeric.append(NumericConstraint(
                facet=f.name, op=Op.GTE, value=high_target, hard=False,
                importance=0.6, unit=f.unit, source="query", scale=scale,
            ))
        seen_facets.add(f.name)

    # --- categorical constraints ------------------------------------------
    categorical: list[CategoricalConstraint] = []
    for tag in adapter.tag_facets:
        include, exclude = [], []
        hard = False
        for value in tag.vocabulary:
            # Values shorter than three characters ("a", "u", "en") would match
            # inside ordinary prose and produce nonsense constraints.
            if not value or len(value) < 3:
                continue
            idx = _phrase_index(text, value)
            if idx is None:
                continue
            prefix = text[max(0, idx - 28): idx]
            if _negated(prefix):
                exclude.append(value)
            else:
                include.append(value)
                if _hardness(text, idx):
                    hard = True
        if include or exclude:
            categorical.append(CategoricalConstraint(
                facet=tag.name, include=include, exclude=exclude,
                hard=hard and bool(include), importance=0.85 if exclude else 0.75,
            ))

    keywords = _keywords(text, adapter)
    return QuerySpec(
        raw_query=query.strip(),
        domain=adapter.key,
        intent=f"{adapter.key}_recommendation",
        keywords=keywords,
        semantic_query=query.strip(),
        numeric=numeric,
        categorical=categorical,
        tone=[c for cc in categorical if cc.facet in {"tone", "mood"} for c in cc.include],
        extraction_source="rules",
    )


def _tidy(value: float) -> float:
    """Round a percentile-derived threshold to a number a person would say.

    "Weight at most 139.1 kg" is a spurious level of precision for what the
    person actually said, which was "not too heavy".
    """
    magnitude = abs(value)
    if magnitude >= 100000:
        return round(value, -4)
    if magnitude >= 10000:
        return round(value, -3)
    if magnitude >= 1000:
        return round(value, -2)
    if magnitude >= 100:
        return round(value, -1)
    if magnitude >= 10:
        return round(value)
    return round(value, 1)


def _scale_for(facet_name: str, spec, stats: dict[str, dict[str, float]]) -> float | None:
    """The spread of this facet across the catalogue, used to decide how badly a
    near-miss should be punished."""
    band = stats.get(facet_name)
    if band and band["max"] > band["min"]:
        return float(band["max"] - band["min"])
    typical = getattr(spec, "typical", None)
    if typical and typical[1] > typical[0]:
        return float(typical[1] - typical[0])
    return None


def _variants(phrase: str) -> list[str]:
    """Surface forms of a catalogue value that a person might actually type.

    People do not write catalogue labels. They write "nothing animated" when the
    tag is "animation", "beginner friendly" when the tag is "beginners", and
    "comedic" when the genre is "comedy". A full stemmer would be overkill and
    would introduce false matches; these four narrow rules cover the cases that
    occur in practice.
    """
    out = [phrase]
    if phrase.endswith("s"):
        out.append(phrase[:-1])
    else:
        out.append(phrase + "s")
    if phrase.endswith("ion") and len(phrase) > 5:
        stem = phrase[:-3]
        out += [stem + "ed", stem + "e", stem + "ing"]
    if phrase.endswith("y") and len(phrase) > 3:
        out += [phrase[:-1] + "ies", phrase[:-1] + "ic"]
    if phrase.endswith("e") and len(phrase) > 3:
        out.append(phrase[:-1] + "ing")
    return out


def _phrase_index(text: str, phrase: str) -> int | None:
    """Word-boundary search over a value and its plausible surface forms."""
    for v in _variants(phrase):
        m = re.search(r"(?<![a-z])" + re.escape(v) + r"(?![a-z])", text)
        if m:
            return m.start()
    return None


def _phrase_in(text: str, phrase: str) -> bool:
    return _phrase_index(text, phrase) is not None


def _find_qualitative(text: str, words: tuple[str, ...]) -> tuple[str, bool] | None:
    """Return (matched word, whether it was negated) for the first hit."""
    for w in words:
        idx = _phrase_index(text, w)
        if idx is None:
            continue
        prefix = text[max(0, idx - 24): idx]
        return w, _negated(prefix)
    return None


def _negated(prefix: str) -> bool:
    return any(re.search(r"(?<![a-z])" + re.escape(c) + r"(?![a-z])", prefix) for c in NEGATION_CUES)


_STOP = set(
    """a an the i want need looking for me my some something anything please can you
    recommend suggest give show find best good great with without under over more less
    than that which what is are be am and or but not no of to in on at it its for from
    about like would should could really very just also too only up down out so as""".split()
)


def _keywords(text: str, adapter: DomainAdapter) -> list[str]:
    words = re.findall(r"[a-z][a-z'-]{2,}", text)
    seen, out = set(), []
    for w in words:
        if w in _STOP or w in adapter.routing_words or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out[:16]
