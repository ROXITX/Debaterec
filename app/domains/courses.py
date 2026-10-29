"""Courses adapter — source shape: a bare top-level ARRAY, with pipe-delimited
`skills` and price already in rupees."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..schemas import Item
from .base import DomainAdapter, FacetSpec, TagSpec, clean, num, split_list


@dataclass
class CoursesAdapter(DomainAdapter):
    key: str = "course"
    label: str = "Courses"
    noun: str = "course"
    icon: str = "cap"
    accent: str = "#3ddc97"
    blurb: str = "Online courses across level, price, duration and format."
    raw_file: str = "courses.json"
    routing_words: tuple[str, ...] = (
        "course", "courses", "learn", "learning", "study", "certification", "certificate",
        "tutorial", "bootcamp", "mooc", "coursera", "udemy", "edx", "class", "training",
        "beginner", "upskill", "syllabus",
    )
    examples: tuple[str, ...] = (
        "beginner machine-learning course, project-based, finish in three months",
        "free NLP course with real coding, I already know Python",
        "something under 2000 rupees that gets me a certificate for my CV",
    )
    facets: tuple[FacetSpec, ...] = (
        FacetSpec("price", "Price", "INR", "lower",
                  ("price", "cost", "fee", "budget", "cheap", "expensive", "free", "rupees", "inr", "affordable"),
                  low_words=("cheap", "affordable", "free", "budget", "inexpensive", "low cost"),
                  high_words=("premium",),
                  typical=(0.0, 6000.0), scale_hint="in rupees; free courses are 0"),
        FacetSpec("weeks", "Duration", "weeks", "lower",
                  ("duration", "weeks", "months", "length", "time", "long", "short", "quick"),
                  low_words=("short", "quick", "fast", "crash course"),
                  high_words=("comprehensive", "in depth", "long"),
                  typical=(1.0, 24.0), scale_hint="three months = 12 weeks"),
        FacetSpec("hours_per_week", "Weekly effort", "hrs/week", "lower",
                  ("hours per week", "effort", "workload", "commitment", "intensity", "time per week"),
                  low_words=("light", "part time", "low commitment"),
                  high_words=("intensive", "full time"),
                  typical=(3.0, 10.0)),
        FacetSpec("rating", "Rating", "/5", "higher",
                  ("rating", "score", "highly rated", "well reviewed", "good", "best"),
                  high_words=("highly rated", "best", "top rated", "acclaimed"),
                  typical=(4.0, 5.0)),
        FacetSpec("popularity", "Enrolled", "learners", "higher",
                  ("popularity", "popular", "enrolled", "well known", "famous", "niche"),
                  low_words=("niche", "obscure", "lesser known"),
                  high_words=("popular", "famous", "widely taken"),
                  typical=(30000.0, 4500000.0)),
    )
    tag_facets: tuple[TagSpec, ...] = (
        TagSpec("skill", "Skills", ("skill", "skills", "topic", "subject", "about", "learn", "technology"),
                ("python", "machine learning", "deep learning", "nlp", "sql", "statistics",
                 "react", "javascript", "aws", "docker", "kubernetes", "excel", "figma",
                 "transformers", "llm", "prompt engineering", "algorithms", "security",
                 "data visualization", "pytorch", "tensorflow", "mlops", "embeddings")),
        TagSpec("level", "Level", ("level", "difficulty", "beginner", "advanced", "intermediate", "experience"),
                ("beginner", "intermediate", "advanced")),
        TagSpec("provider", "Provider", ("provider", "platform", "site", "university", "from"),
                ("coursera", "udemy", "edx", "fast.ai", "hugging face", "youtube", "google", "ibm")),
        TagSpec("format", "Format", ("format", "style", "project based", "hands on", "video", "reading"),
                ("video", "notebooks", "problem sets", "labs", "capstone", "project based",
                 "hands-on", "written")),
        TagSpec("certificate", "Certificate", ("certificate", "certification", "credential", "cv", "resume"),
                ("yes", "no", "paid upgrade")),
    )

    def parse(self, raw: Any) -> Iterable[Item]:
        records = raw if isinstance(raw, list) else raw.get("courses", [])
        for rec in records:
            price = num(rec.get("price_inr"), 0.0)
            weeks = num(rec.get("duration_weeks"))
            hpw = num(rec.get("hours_per_week"))
            rating = num(rec.get("rating"))
            enrolled = num(rec.get("enrolled"), 0.0) or 0.0
            # `skills` is PIPE-delimited in this dataset.
            skills = split_list(rec.get("skills"), seps="|")
            level = clean(rec.get("level")).lower()
            provider = clean(rec.get("provider"))
            fmt = split_list(rec.get("format"), seps="+,")
            if str(rec.get("project_based", "")).lower() in {"yes", "partial"}:
                fmt.append("project based")
            cert = clean(rec.get("certificate")).lower()

            total_hours = (weeks or 0) * (hpw or 0)
            display: list[tuple[str, str]] = [("Provider", provider)]
            if rec.get("instructor"):
                display.append(("Instructor", clean(rec["instructor"])))
            if level:
                display.append(("Level", level))
            if weeks:
                months = weeks / 4.345
                display.append(("Duration", f"{int(weeks)} weeks (~{months:.1f} months)"))
            if hpw:
                display.append(("Effort", f"{hpw:g} hrs/week (~{total_hours:.0f} hrs total)"))
            display.append(("Price", "Free" if not price else f"₹{int(price):,}"))
            if cert:
                display.append(("Certificate", cert))
            if skills:
                display.append(("Skills", ", ".join(skills)))
            if rec.get("prerequisites"):
                display.append(("Prerequisites", clean(rec["prerequisites"])))
            if enrolled:
                display.append(("Enrolled", f"{int(enrolled):,}"))

            yield Item(
                item_id=f"course:{rec.get('course_id')}",
                domain=self.key,
                title=clean(rec.get("name")),
                subtitle=f"{provider} · {level}".strip(" ·"),
                description=clean(rec.get("summary")),
                facets={
                    k: v for k, v in {
                        "price": price, "weeks": weeks, "hours_per_week": hpw,
                        "rating": rating, "popularity": enrolled,
                    }.items() if v is not None
                },
                tags={
                    "skill": [s.lower() for s in skills],
                    "level": [level] if level else [],
                    "provider": [provider.lower()],
                    "format": [f.lower() for f in fmt],
                    "certificate": [cert] if cert else [],
                },
                display=display,
                rating=rating,
                popularity=enrolled,
                synthetic=bool(rec.get("synthetic")),
            )
