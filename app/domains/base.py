"""Domain adapter contract.

A domain contributes four things and nothing else:

  1. a *facet schema* — the numeric dimensions it can be constrained on,
     each with a unit, a direction ("is more better?") and natural-language
     aliases,
  2. a *tag schema* — its categorical dimensions,
  3. routing vocabulary so the NLP layer can recognise the domain,
  4. a `load()` that turns its own idiosyncratic raw file into `Item`s.

Everything downstream — retrieval, constraint checking, the debate, the judge,
the UI — is written against `Item` and never against a domain. Adding an eighth
domain means adding one file and no edits anywhere else.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..schemas import Item


@dataclass(frozen=True)
class FacetSpec:
    """One numeric dimension of a domain."""

    name: str
    label: str
    unit: str = ""
    better: str = "higher"  # "higher" | "lower" | "neutral"
    aliases: tuple[str, ...] = ()
    # Words that imply "I want a LOW value of this facet", e.g. cheap -> price.
    low_words: tuple[str, ...] = ()
    high_words: tuple[str, ...] = ()
    # Typical range, used to normalise scores and to interpret bare numbers.
    typical: tuple[float, float] = (0.0, 1.0)
    scale_hint: str = ""  # e.g. "rupees", shown to the LLM


@dataclass(frozen=True)
class TagSpec:
    """One categorical dimension of a domain."""

    name: str
    label: str
    aliases: tuple[str, ...] = ()
    vocabulary: tuple[str, ...] = ()


@dataclass
class DomainAdapter(ABC):
    key: str = ""
    label: str = ""
    noun: str = ""
    icon: str = ""
    accent: str = "#7c5cff"
    blurb: str = ""
    routing_words: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    facets: tuple[FacetSpec, ...] = ()
    tag_facets: tuple[TagSpec, ...] = ()
    raw_file: str = ""
    _items: list[Item] | None = field(default=None, init=False, repr=False)

    # -- required ----------------------------------------------------------
    @abstractmethod
    def parse(self, raw: Any) -> Iterable[Item]:
        """Turn the domain's own raw structure into Items."""

    # -- shared ------------------------------------------------------------
    def load(self, data_dir: Path) -> list[Item]:
        if self._items is None:
            with open(data_dir / self.raw_file, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            items = list(self.parse(raw))
            for it in items:
                it.text_blob = self.build_text(it)
                if not it.accent:
                    it.accent = self.accent
            self._items = items
        return self._items

    def build_text(self, item: Item) -> str:
        """Retrieval text (PRD §36). Title and tags are repeated deliberately:
        lexical retrieval should weight them above prose."""
        parts = [item.title, item.title, item.subtitle, item.description]
        for _, values in item.tags.items():
            parts.extend(values)
            parts.extend(values)
        for label, value in item.display:
            parts.append(f"{label} {value}")
        return " \n".join(p for p in parts if p)

    def facet(self, name: str) -> FacetSpec | None:
        for f in self.facets:
            if f.name == name:
                return f
        return None

    def tag_spec(self, name: str) -> TagSpec | None:
        for t in self.tag_facets:
            if t.name == name:
                return t
        return None

    def resolve_facet(self, token: str) -> str | None:
        """Map a free-text word onto one of this domain's facet names."""
        t = token.strip().lower().replace("-", " ")
        for f in self.facets:
            if t == f.name or t == f.label.lower() or t in f.aliases:
                return f.name
        for f in self.facets:
            if any(a in t or t in a for a in f.aliases):
                return f.name
        return None

    def resolve_tag(self, token: str) -> str | None:
        t = token.strip().lower().replace("-", " ")
        for tg in self.tag_facets:
            if t == tg.name or t == tg.label.lower() or t in tg.aliases:
                return tg.name
        return None

    def describe_for_llm(self) -> str:
        """The facet contract handed to the extraction model, so it can only
        emit facet names that actually exist in this domain."""
        lines = [f"DOMAIN: {self.key} ({self.label})", "NUMERIC FACETS (name | unit | direction):"]
        for f in self.facets:
            arrow = "lower is usually better" if f.better == "lower" else (
                "higher is usually better" if f.better == "higher" else "neutral"
            )
            unit = f.unit or "unitless"
            lines.append(f"  - {f.name} | {unit} | {arrow}" + (f" | {f.scale_hint}" if f.scale_hint else ""))
        lines.append("CATEGORICAL FACETS (name | example values):")
        for t in self.tag_facets:
            vocab = ", ".join(t.vocabulary[:14]) if t.vocabulary else "free text"
            lines.append(f"  - {t.name} | {vocab}")
        return "\n".join(lines)

    def vocabulary(self) -> set[str]:
        words: set[str] = set()
        for f in self.facets:
            words.update(f.aliases)
            words.update(f.low_words)
            words.update(f.high_words)
        for t in self.tag_facets:
            words.update(t.aliases)
            words.update(v.lower() for v in t.vocabulary)
        words.update(self.routing_words)
        return {w for w in words if w}

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "noun": self.noun,
            "icon": self.icon,
            "accent": self.accent,
            "blurb": self.blurb,
            "examples": list(self.examples),
            "count": len(self._items or []),
        }


# ---------------------------------------------------------------------------
# Parsing helpers — the small, unglamorous functions that absorb the fact that
# every real dataset stores its numbers differently.
# ---------------------------------------------------------------------------

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def num(value: Any, default: float | None = None) -> float | None:
    """Pull a number out of 8, '8', '8GB', '1.24kg', '512GB SSD', '₹1,299'."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "")
    m = _NUM.search(text)
    return float(m.group()) if m else default


def split_list(value: Any, seps: str = "|,;/") -> list[str]:
    """Accept a real list, or a string delimited by any of `seps`."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value)
    pattern = "[" + re.escape(seps) + "]"
    return [p.strip() for p in re.split(pattern, text) if p.strip()]


def year_of(value: Any) -> float | None:
    """Handle 2014, '2014', '2014-11-05' and '2024-05'."""
    if value is None:
        return None
    m = re.search(r"(19|20)\d{2}", str(value))
    return float(m.group()) if m else None


def yes_no(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "true", "1", "y", "available"}


def money(value: Any, multiplier: float = 1.0) -> float | None:
    n = num(value)
    return None if n is None else n * multiplier


def clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()
