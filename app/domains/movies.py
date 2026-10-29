"""Movies adapter — source shape: {"movies": [ flat records ]}."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..schemas import Item
from .base import DomainAdapter, FacetSpec, TagSpec, clean, num, split_list, year_of


@dataclass
class MoviesAdapter(DomainAdapter):
    key: str = "movie"
    label: str = "Movies"
    noun: str = "film"
    icon: str = "film"
    accent: str = "#ff5c8a"
    blurb: str = "Feature films across genre, era, runtime and tone."
    raw_file: str = "movies.json"
    routing_words: tuple[str, ...] = (
        "movie", "movies", "film", "films", "cinema", "watch", "netflix", "director",
        "actor", "sci-fi movie", "thriller", "rom com", "screening", "flick",
    )
    examples: tuple[str, ...] = (
        "a funny science-fiction movie from after 2015, under two hours",
        "something dark and tense but not horror, with a strong ending",
        "animated film the whole family can watch, nothing too long",
    )
    facets: tuple[FacetSpec, ...] = (
        FacetSpec("runtime", "Runtime", "minutes", "lower",
                  ("runtime", "length", "duration", "long", "short", "minutes", "hours", "time"),
                  low_words=("short", "quick", "brief", "not too long"),
                  high_words=("long", "epic", "lengthy"),
                  typical=(80.0, 200.0), scale_hint="two hours = 120"),
        FacetSpec("year", "Release year", "", "higher",
                  ("year", "release year", "released", "modern", "recent", "old", "new", "era"),
                  low_words=("old", "classic", "vintage", "retro"),
                  high_words=("modern", "recent", "new", "latest"),
                  typical=(1930.0, 2026.0)),
        FacetSpec("rating", "Rating", "/10", "higher",
                  ("rating", "score", "imdb", "rated", "highly rated", "acclaimed", "good"),
                  high_words=("highly rated", "acclaimed", "critically", "best"),
                  typical=(5.0, 9.0)),
        FacetSpec("popularity", "Popularity", "", "higher",
                  ("popularity", "popular", "famous", "mainstream", "obscure", "hidden gem"),
                  low_words=("obscure", "hidden gem", "underrated", "lesser known"),
                  high_words=("popular", "famous", "blockbuster", "mainstream"),
                  typical=(50.0, 100.0)),
    )
    tag_facets: tuple[TagSpec, ...] = (
        TagSpec("genre", "Genre", ("genre", "genres", "category", "kind", "type"),
                ("science fiction", "action", "comedy", "drama", "thriller", "horror",
                 "animation", "romance", "crime", "mystery", "adventure", "fantasy",
                 "family", "war", "history", "music")),
        TagSpec("tone", "Tone", ("tone", "mood", "vibe", "feel", "atmosphere"),
                ("dark", "funny", "light", "emotional", "tense", "cerebral", "epic",
                 "warm", "grim", "whimsical", "colourful", "serious", "uplifting")),
        TagSpec("director", "Director", ("director", "directed by", "filmmaker")),
        TagSpec("cast", "Cast", ("actor", "actress", "starring", "cast", "lead")),
        TagSpec("keyword", "Themes", ("theme", "about", "keyword", "topic", "plot")),
        TagSpec("language", "Language", ("language", "subtitles", "foreign"),
                ("english", "korean", "japanese")),
        TagSpec("certificate", "Certificate", ("age rating", "certificate", "family friendly"),
                ("universal", "parental guidance", "adults only")),
    )

    LANGUAGES = {"en": "english", "ko": "korean", "ja": "japanese"}
    CERTIFICATES = {"u": "universal", "ua": "parental guidance", "a": "adults only"}

    def parse(self, raw: Any) -> Iterable[Item]:
        for rec in raw.get("movies", []):
            runtime = num(rec.get("runtime"))
            year = year_of(rec.get("release_date"))
            rating = num(rec.get("vote_average"))
            pop = num(rec.get("popularity"), 0.0) or 0.0
            genres = split_list(rec.get("genres"))
            tone = split_list(rec.get("tone"))
            cast = split_list(rec.get("cast"))
            director = clean(rec.get("director"))

            display: list[tuple[str, str]] = []
            if genres:
                display.append(("Genres", ", ".join(genres)))
            if year:
                display.append(("Year", str(int(year))))
            if runtime:
                hrs, mins = divmod(int(runtime), 60)
                display.append(("Runtime", f"{int(runtime)} min ({hrs}h {mins:02d}m)"))
            if director:
                display.append(("Director", director))
            if cast:
                display.append(("Cast", ", ".join(cast[:3])))
            if tone:
                display.append(("Tone", ", ".join(tone)))
            if rec.get("certificate"):
                display.append(("Certificate", clean(rec["certificate"])))
            if rec.get("original_language"):
                display.append(("Language", clean(rec["original_language"]).upper()))

            yield Item(
                item_id=f"movie:{rec['id']}",
                domain=self.key,
                title=clean(rec.get("title")),
                subtitle=", ".join(genres[:3]),
                description=clean(rec.get("overview")),
                facets={
                    k: v for k, v in {
                        "runtime": runtime, "year": year, "rating": rating, "popularity": pop
                    }.items() if v is not None
                },
                tags={
                    "genre": [g.lower() for g in genres],
                    "tone": [t.lower() for t in tone],
                    "director": [director.lower()] if director else [],
                    "cast": [c.lower() for c in cast],
                    "keyword": [k.lower() for k in split_list(rec.get("keywords"))],
                    "language": [self.LANGUAGES.get(clean(rec.get("original_language")).lower(), "english")],
                    "certificate": [self.CERTIFICATES.get(clean(rec.get("certificate")).lower(), "")],
                },
                display=display,
                rating=rating,
                popularity=pop,
                synthetic=bool(rec.get("synthetic")),
            )
