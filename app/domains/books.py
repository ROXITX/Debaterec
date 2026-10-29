"""Books adapter — source shape: {"records": [...]} with COMMA-DELIMITED
`categories` strings and Goodreads-style column names."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..schemas import Item
from .base import DomainAdapter, FacetSpec, TagSpec, clean, num, split_list, year_of


@dataclass
class BooksAdapter(DomainAdapter):
    key: str = "book"
    label: str = "Books"
    noun: str = "book"
    icon: str = "book"
    accent: str = "#ffab4d"
    blurb: str = "Fiction and non-fiction across length, difficulty and mood."
    raw_file: str = "books.json"
    routing_words: tuple[str, ...] = (
        "book", "books", "read", "reading", "novel", "author", "paperback",
        "fiction", "non-fiction", "nonfiction", "memoir", "textbook", "page-turner",
    )
    examples: tuple[str, ...] = (
        "a beginner-friendly psychology book that is practical, not theoretical",
        "short literary fiction under 250 pages with a strange atmosphere",
        "a rigorous machine learning textbook, I don't mind length",
    )
    facets: tuple[FacetSpec, ...] = (
        FacetSpec("pages", "Page count", "pages", "lower",
                  ("pages", "page count", "length", "long", "short", "thick", "thin"),
                  low_words=("short", "quick read", "slim", "brief"),
                  high_words=("long", "doorstop", "comprehensive"),
                  typical=(150.0, 900.0)),
        FacetSpec("year", "Published", "", "higher",
                  ("year", "published", "publication year", "modern", "recent", "old", "classic"),
                  low_words=("classic", "old", "vintage"),
                  high_words=("modern", "recent", "new", "contemporary"),
                  typical=(1800.0, 2026.0)),
        FacetSpec("rating", "Rating", "/5", "higher",
                  ("rating", "score", "goodreads", "highly rated", "acclaimed", "well reviewed"),
                  high_words=("highly rated", "acclaimed", "best", "top rated"),
                  typical=(3.4, 4.6)),
        FacetSpec("popularity", "Ratings count", "ratings", "higher",
                  ("popularity", "popular", "famous", "bestseller", "obscure", "underrated"),
                  low_words=("obscure", "underrated", "hidden gem", "lesser known"),
                  high_words=("popular", "bestseller", "famous", "widely read"),
                  typical=(20000.0, 3000000.0)),
    )
    tag_facets: tuple[TagSpec, ...] = (
        TagSpec("category", "Category", ("genre", "category", "categories", "subject", "topic", "about"),
                ("fiction", "science fiction", "fantasy", "psychology", "self help",
                 "business", "history", "science", "philosophy", "memoir", "thriller",
                 "mystery", "classics", "computer science", "machine learning",
                 "programming", "economics", "productivity", "health")),
        TagSpec("level", "Reading level", ("level", "difficulty", "beginner", "advanced", "technical", "accessible"),
                ("beginner", "intermediate", "advanced")),
        TagSpec("mood", "Mood", ("mood", "tone", "vibe", "style", "feel"),
                ("practical", "motivating", "dense", "rigorous", "funny", "bleak",
                 "warm", "gripping", "cerebral", "gentle", "accessible", "melancholy")),
        TagSpec("author", "Author", ("author", "writer", "written by", "by")),
        TagSpec("language", "Language", ("language",), ("en",)),
    )

    def parse(self, raw: Any) -> Iterable[Item]:
        for rec in raw.get("records", []):
            pages = num(rec.get("num_pages"))
            year = year_of(rec.get("published_year"))
            rating = num(rec.get("average_rating"))
            count = num(rec.get("ratings_count"), 0.0) or 0.0
            # `categories` is a comma-delimited STRING here, unlike movies' array.
            cats = split_list(rec.get("categories"), seps=",")
            authors = split_list(rec.get("authors"), seps=",")
            mood = split_list(rec.get("mood"), seps=",")
            level = clean(rec.get("reading_level")).lower()

            display: list[tuple[str, str]] = []
            if authors:
                display.append(("Author", ", ".join(authors)))
            if cats:
                display.append(("Categories", ", ".join(cats)))
            if year:
                display.append(("Published", str(int(year))))
            if pages:
                display.append(("Pages", str(int(pages))))
            if level:
                display.append(("Reading level", level))
            if mood:
                display.append(("Mood", ", ".join(mood)))
            if count:
                display.append(("Ratings", f"{int(count):,}"))

            yield Item(
                item_id=f"book:{rec.get('isbn13')}",
                domain=self.key,
                title=clean(rec.get("book_title")),
                subtitle=", ".join(authors),
                description=clean(rec.get("blurb")),
                facets={
                    k: v for k, v in {
                        "pages": pages, "year": year, "rating": rating, "popularity": count
                    }.items() if v is not None
                },
                tags={
                    "category": [c.lower() for c in cats],
                    "level": [level] if level else [],
                    "mood": [m.lower() for m in mood],
                    "author": [a.lower() for a in authors],
                    "language": [clean(rec.get("language")).lower()],
                },
                display=display,
                rating=rating,
                popularity=count,
                synthetic=bool(rec.get("synthetic")),
            )
