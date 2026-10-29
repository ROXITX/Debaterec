#!/usr/bin/env python3
"""Catalogue generator — expands the curated seeds into full-scale catalogues.

    python data/build_catalogue.py            # ~11,000 records
    python data/build_catalogue.py --scale 3  # three times that
    python data/build_catalogue.py --restore  # back to seeds only

Reads `data/seed/*.json` and writes `data/raw/*.json`, which is what the
application loads. Deterministic: the same seed produces byte-identical output,
so an experiment run is reproducible.

WHAT IS REAL AND WHAT IS NOT
----------------------------
Every record from `data/seed/` is copied through **verbatim**. Those are the
curated, factually-checked entries — real films, real books, real phones — and
they are the only records the evaluation set labels.

Everything else is generated, and is marked `"synthetic": true` in the raw file.
Generated records exist to make the catalogue large enough to say anything
meaningful about retrieval behaviour, latency, coverage and diversity at scale.

Two deliberate honesty constraints govern the generator:

  * Synthetic films and books are credited to **invented** directors and
    authors. Attributing a film that does not exist to a real director would be
    fabricating a claim about a real person.
  * Synthetic products carry **invented brand names**. Inventing specifications
    and prices under a real manufacturer's name would be fabricating product
    information about a real company. Real brands appear only on seed records,
    so a query for "Samsung" still returns genuine entries.

The consequence for the write-up: use the full catalogue for scaling, latency,
coverage and diversity measurements, and the seed anchors for any claim about
recommendation *quality*.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

# The progress table uses box-drawing characters. A Windows console defaults to
# cp1252, which cannot encode them, and the script crashed with
# UnicodeEncodeError before writing anything. Force UTF-8 on stdout/stderr so the
# generator runs the same on every platform.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "data" / "seed"
RAW_DIR = ROOT / "data" / "raw"

RANDOM_SEED = 20260819

BASE_COUNTS = {
    "movies": 2400,
    "books": 2000,
    "courses": 1500,
    "phones": 1500,
    "laptops": 1400,
    "cars": 1300,
    "bikes": 1100,
}


def load_seed(name: str) -> dict | list:
    with open(SEED_DIR / f"{name}.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_raw(name: str, payload: dict | list) -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(RAW_DIR / f"{name}.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    return (RAW_DIR / f"{name}.json").stat().st_size


def rounded(value: float, step: int) -> int:
    """Prices in a real catalogue land on round numbers, not on 43871."""
    return int(round(value / step) * step)


# ---------------------------------------------------------------------------
# Shared name vocabulary for invented people and brands
# ---------------------------------------------------------------------------

FIRST_NAMES = """Ana Marcus Priya Ines Tomas Leila Soren Nadia Ravi Elena Idris Mei
Oskar Yusuf Clara Diego Amara Felix Noor Kiran Hana Lucas Zara Emil Rosa Anton
Sofia Malik Iris Bruno Talia Owen Nina Rafael Juno Ade Petra Kai Selma Otto
Rhea Vikram Greta Milo Asha Dario Lena Hugo Farah Jonas Ivy Rashid Mira Caspar
Neve Arun Sable Teo Lucia Bram Sana Enzo Wren Kofi Astrid Reza Delphine Matteo""".split()

LAST_NAMES = """Okonkwo Vaszary Lindqvist Moreau Castellan Ferreira Haddad Novak
Petrosyan Sandoval Bergström Iyer Kowalski Abelard Duarte Marchetti Osei Rahman
Vance Solberg Mancini Delacroix Farrow Nakamura Beaumont Quintero Halloran
Strand Achterberg Varga Lindgren Amari Chevalier Ortega Bellweather Kaminski
Rousseau Falkner Adeyemi Sarkis Wexler Mbeki Toivonen Cardoso Ashworth Grimaldi
Vandermeer Leclair Radovic Ashkani Pemberton Halvorsen Ibarra Novotny Stavros
Winterbourne Dagher Oyelaran Kristiansen Baptiste Serrano Falk Adeyinka""".split()

# Invented brand names for synthetic products. Chosen to be plainly fictional so
# nobody mistakes a generated spec sheet for a real manufacturer's claim.
PRODUCT_BRANDS = [
    "Nexora", "Volari", "Kestrel", "Auralis", "Zephyra", "Halcyon", "Veritek",
    "Lumendo", "Corvex", "Astrada", "Nimbus Labs", "Orryx", "Tessera", "Vantiq",
    "Pallas", "Meridian", "Solvane", "Aeronaut", "Cirrus One", "Ferrix",
]

VEHICLE_BRANDS = [
    "Aravind Motors", "Kestrel Auto", "Vantara", "Solvane Mobility", "Corvex Cars",
    "Meridian Drive", "Auralis Motors", "Nimbus Automotive", "Orryx Vehicles",
    "Tessera Motors", "Pallas Auto", "Veritek Mobility",
]

PROVIDERS = [
    "OpenCourse", "Lumen Academy", "Meridian Learning", "Northbridge Online",
    "Atlas Institute", "Cornerstone Academy", "BrightPath", "Kestrel School",
    "Vantage Learning", "Foundry Courses",
]


def person(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


# ---------------------------------------------------------------------------
# Movies
# ---------------------------------------------------------------------------

MOVIE_GENRES = {
    "Science Fiction": (["cerebral", "atmospheric", "tense"], ["space", "future", "simulation", "first contact", "time travel"]),
    "Action": (["kinetic", "spectacle", "tense"], ["chase", "heist", "revenge", "survival"]),
    "Comedy": (["funny", "light", "warm"], ["mistaken identity", "road trip", "workplace", "family"]),
    "Drama": (["emotional", "serious", "melancholy"], ["grief", "ambition", "family", "redemption"]),
    "Thriller": (["tense", "dark", "grim"], ["conspiracy", "manhunt", "twist ending", "surveillance"]),
    "Horror": (["dark", "unsettling", "grim"], ["haunting", "isolation", "possession", "folk horror"]),
    "Animation": (["colourful", "whimsical", "warm"], ["coming of age", "friendship", "quest"]),
    "Romance": (["warm", "emotional", "light"], ["second chances", "long distance", "rivals"]),
    "Crime": (["dark", "stylish", "tense"], ["heist", "undercover", "trial", "gang"]),
    "Mystery": (["cerebral", "atmospheric", "melancholy"], ["missing person", "cold case", "locked room"]),
    "Adventure": (["epic", "colourful", "kinetic"], ["expedition", "treasure", "voyage"]),
    "Fantasy": (["whimsical", "epic", "atmospheric"], ["prophecy", "magic", "another world"]),
    "Documentary": (["serious", "contemplative"], ["archive", "portrait", "investigation"]),
    "War": (["grim", "epic", "tense"], ["siege", "resistance", "aftermath"]),
    "History": (["serious", "epic", "contemplative"], ["dynasty", "revolution", "biography"]),
    "Family": (["warm", "light", "colourful"], ["holiday", "pets", "school"]),
    "Music": (["emotional", "warm", "kinetic"], ["band", "competition", "biography"]),
}

TITLE_ADJ = """Silent Crimson Hollow Distant Iron Gentle Broken Endless Pale Bright
Last First Quiet Burning Frozen Hidden Restless Northern Golden Bitter Wandering
Empty Sacred Electric Velvet Salt Winter Summer Glass Paper Wild Slow Vast""".split()

TITLE_NOUN = """Harbour Signal Orchard Machine Frontier Cathedral Archive Meridian
Lighthouse Passenger Cartographer Inheritance Reservoir Canyon Observatory
Threshold Almanac Migration Foundry Aviary Estuary Constellation Ledger Quarry
Corridor Testament Anthem Undertow Perimeter Ferry Verdict Hourglass Aqueduct""".split()

TITLE_PATTERNS = [
    "The {adj} {noun}",
    "{noun}",
    "{adj} {noun}",
    "The {noun} of {noun2}",
    "{noun} and {noun2}",
    "A {adj} {noun}",
    "{noun}: {adj} {noun2}",
    "Beyond the {noun}",
    "After the {noun}",
    "{adj} {noun}s",
]

MOVIE_PLOTS = [
    "A {role} returns to {place} and finds that {event}.",
    "Two {roles} are forced together when {event}.",
    "After {event}, a {role} must decide how far they are willing to go.",
    "A {role} investigating {thing} discovers that nothing about {place} is what it seems.",
    "Over one {period}, a {role} tries to hold {thing} together while {event}.",
    "A {role} takes one last job in {place}, and {event}.",
]
PLOT_ROLES = ["cartographer", "translator", "engineer", "detective", "doctor", "teacher",
              "pilot", "archivist", "smuggler", "biologist", "journalist", "conductor",
              "diver", "surveyor", "programmer", "midwife", "prosecutor"]
PLOT_PLACES = ["a coastal town", "a research station", "the capital", "a border village",
               "an orbital colony", "a shuttered factory", "a mountain observatory",
               "a flooded district", "a night train", "a desert outpost"]
PLOT_EVENTS = ["the records have been destroyed", "an old debt comes due",
               "a storm cuts the road", "the funding is pulled", "a body is found",
               "the signal returns after forty years", "the water starts rising",
               "their sister disappears", "the machine answers back"]
PLOT_THINGS = ["a missing shipment", "an unfinished manuscript", "a family estate",
               "a failing hospital", "an inherited debt", "a decommissioned satellite"]
PLOT_PERIODS = ["summer", "winter", "week", "harvest", "shift rotation", "election"]


def make_title(rng: random.Random) -> str:
    pattern = rng.choice(TITLE_PATTERNS)
    return pattern.format(
        adj=rng.choice(TITLE_ADJ),
        noun=rng.choice(TITLE_NOUN),
        noun2=rng.choice(TITLE_NOUN),
    )


def build_movies(rng: random.Random, count: int) -> list[dict]:
    out = []
    used: set[str] = set()
    for i in range(count):
        for _ in range(12):
            title = make_title(rng)
            if title not in used:
                break
        used.add(title)

        primary = rng.choice(list(MOVIE_GENRES))
        tones, keywords = MOVIE_GENRES[primary]
        genres = [primary]
        if rng.random() < 0.72:
            second = rng.choice(list(MOVIE_GENRES))
            if second != primary:
                genres.append(second)
                tones = tones + MOVIE_GENRES[second][0]
                keywords = keywords + MOVIE_GENRES[second][1]
        if rng.random() < 0.22:
            third = rng.choice(list(MOVIE_GENRES))
            if third not in genres:
                genres.append(third)

        # Runtime correlates with genre the way it does in reality: animation and
        # comedy run short, war and history run long.
        base_runtime = {"Animation": 94, "Comedy": 100, "Horror": 98, "Family": 96,
                        "Documentary": 92, "War": 138, "History": 140,
                        "Science Fiction": 126, "Drama": 120}.get(primary, 112)
        runtime = max(72, min(215, int(rng.gauss(base_runtime, 17))))

        year = int(min(2026, max(1938, rng.triangular(1938, 2026, 2014))))
        rating = round(min(9.2, max(3.6, rng.gauss(6.7, 0.95))), 1)
        popularity = round(min(99.0, max(3.0, rng.gauss(38, 21))), 1)

        plot = rng.choice(MOVIE_PLOTS).format(
            role=rng.choice(PLOT_ROLES),
            roles=rng.choice(PLOT_ROLES) + "s",
            place=rng.choice(PLOT_PLACES),
            event=rng.choice(PLOT_EVENTS),
            thing=rng.choice(PLOT_THINGS),
            period=rng.choice(PLOT_PERIODS),
        )

        language = rng.choices(["en", "ko", "ja", "fr", "es", "hi"],
                               weights=[70, 6, 7, 6, 6, 5])[0]
        certificate = rng.choices(["u", "ua", "a"], weights=[22, 45, 33])[0]
        if primary == "Horror":
            certificate = "a"
        if primary in {"Family", "Animation"}:
            certificate = rng.choice(["u", "ua"])

        out.append({
            "id": f"syn-mv-{i:05d}",
            "title": title,
            "overview": plot,
            "genres": genres,
            "release_date": f"{year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "runtime": runtime,
            "vote_average": rating,
            "popularity": popularity,
            "director": person(rng),
            "cast": [person(rng) for _ in range(rng.randint(2, 3))],
            "keywords": rng.sample(keywords, min(len(keywords), rng.randint(2, 3))),
            "tone": sorted(set(rng.sample(tones, min(len(tones), rng.randint(2, 3))))),
            "original_language": language,
            "certificate": certificate,
            "synthetic": True,
        })
    return out


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------

BOOK_CATEGORIES = {
    "Fiction": ["literary", "gripping", "quiet", "warm"],
    "Science Fiction": ["cerebral", "sweeping", "cold"],
    "Fantasy": ["dreamlike", "epic", "warm"],
    "Mystery": ["twisty", "tense", "gripping"],
    "Thriller": ["tense", "gripping", "dark"],
    "Psychology": ["practical", "rigorous", "accessible"],
    "Self Help": ["practical", "motivating", "blunt"],
    "Business": ["practical", "narrative", "opinionated"],
    "History": ["sweeping", "rigorous", "narrative"],
    "Science": ["rigorous", "clear", "accessible"],
    "Philosophy": ["dense", "contemplative", "provocative"],
    "Memoir": ["raw", "warm", "inspiring"],
    "Biography": ["narrative", "rigorous", "sweeping"],
    "Computer Science": ["rigorous", "practical", "mathematical"],
    "Machine Learning": ["rigorous", "practical", "mathematical"],
    "Programming": ["practical", "opinionated", "hands-on"],
    "Economics": ["contrarian", "rigorous", "accessible"],
    "Health": ["practical", "urgent", "accessible"],
    "Productivity": ["practical", "disciplined", "motivating"],
    "Classics": ["literary", "dense", "contemplative"],
    "Poetry": ["literary", "quiet", "melancholy"],
    "Travel": ["warm", "narrative", "vivid"],
}

BOOK_BLURBS = [
    "An examination of {topic}, built from {evidence} rather than assertion.",
    "A {tone} account of {topic}, aimed at readers with no background in the subject.",
    "Argues that {topic} is widely misunderstood, and sets out what the evidence supports instead.",
    "Follows {subject} across {span}, and asks what the story reveals about {topic}.",
    "A field guide to {topic} for people who have to make decisions about it.",
    "Traces the history of {topic} and the arguments it has survived.",
]
BOOK_TOPICS = ["attention", "risk", "memory", "cities", "supply chains", "habit formation",
               "language", "inequality", "immunity", "forecasting", "grief", "expertise",
               "networks", "sleep", "negotiation", "collapse", "craft", "measurement",
               "migration", "trust", "scarcity", "optimisation", "inference"]
BOOK_EVIDENCE = ["a decade of fieldwork", "case studies", "primary sources",
                 "longitudinal data", "interviews", "replicated experiments"]
BOOK_SUBJECTS = ["three families", "a single street", "one laboratory", "a failing company",
                 "an unnamed narrator", "two rival researchers", "a coastal community"]
BOOK_SPANS = ["forty years", "a single winter", "three generations", "one decade",
              "a century", "eighteen months"]


def build_books(rng: random.Random, count: int) -> list[dict]:
    out = []
    for i in range(count):
        category = rng.choice(list(BOOK_CATEGORIES))
        moods = BOOK_CATEGORIES[category]
        categories = [category]
        if rng.random() < 0.65:
            extra = rng.choice(list(BOOK_CATEGORIES))
            if extra != category:
                categories.append(extra)

        technical = category in {"Computer Science", "Machine Learning", "Programming",
                                 "Philosophy", "Science", "Economics"}
        level = rng.choices(
            ["beginner", "intermediate", "advanced"],
            weights=[20, 35, 45] if technical else [48, 34, 18],
        )[0]
        base_pages = {"beginner": 260, "intermediate": 340, "advanced": 470}[level]
        pages = max(96, min(980, int(rng.gauss(base_pages, 105))))
        year = int(min(2026, max(1890, rng.triangular(1890, 2026, 2015))))
        rating = round(min(4.85, max(3.05, rng.gauss(4.05, 0.32))), 2)
        ratings_count = int(max(400, rng.lognormvariate(10.4, 1.5)))

        blurb = rng.choice(BOOK_BLURBS).format(
            topic=rng.choice(BOOK_TOPICS),
            evidence=rng.choice(BOOK_EVIDENCE),
            subject=rng.choice(BOOK_SUBJECTS),
            span=rng.choice(BOOK_SPANS),
            tone=rng.choice(["patient", "brisk", "sceptical", "generous"]),
        )

        authors = person(rng)
        if rng.random() < 0.16:
            authors += f", {person(rng)}"

        out.append({
            "isbn13": f"979{i:010d}",
            "book_title": make_title(rng),
            "authors": authors,
            "categories": ", ".join(categories),
            "published_year": year,
            "num_pages": pages,
            "average_rating": rating,
            "ratings_count": ratings_count,
            "language": rng.choices(["en", "fr", "es", "de"], weights=[88, 4, 4, 4])[0],
            "reading_level": level,
            "blurb": blurb,
            "mood": ", ".join(rng.sample(moods, min(len(moods), 2))),
            "synthetic": True,
        })
    return out


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

COURSE_SUBJECTS = {
    "Machine Learning": ["python", "scikit-learn", "regression", "neural networks", "model evaluation"],
    "Deep Learning": ["pytorch", "tensorflow", "cnn", "transformers", "fine-tuning"],
    "Natural Language Processing": ["nlp", "tokenizers", "embeddings", "transformers", "sentiment analysis"],
    "Data Analysis": ["python", "pandas", "sql", "data visualization", "statistics"],
    "Web Development": ["html", "css", "javascript", "react", "node"],
    "Cloud Engineering": ["aws", "docker", "kubernetes", "ci cd", "terraform"],
    "Cyber Security": ["security", "cryptography basics", "network defence", "threat modelling"],
    "Statistics": ["statistics", "hypothesis testing", "probability", "r", "experimental design"],
    "Product Design": ["figma", "wireframing", "user research", "prototyping", "accessibility"],
    "Databases": ["sql", "databases", "indexing", "data modelling", "postgres"],
    "Recommender Systems": ["collaborative filtering", "evaluation metrics", "ndcg", "embeddings"],
    "Generative AI": ["llm", "prompt engineering", "rag", "embeddings", "fine-tuning"],
    "Mobile Development": ["kotlin", "swift", "flutter", "mobile ui"],
    "Finance": ["excel", "financial modelling", "valuation", "accounting"],
    "Project Management": ["agile", "scrum", "roadmapping", "stakeholders"],
    "Mathematics": ["linear algebra", "calculus", "numpy", "optimisation"],
}
COURSE_QUALIFIER = ["Foundations of", "Applied", "Practical", "Advanced", "Hands-On",
                    "Introduction to", "Professional", "Complete", "Modern", "Essential"]
COURSE_SUFFIX = ["", " Bootcamp", " Specialization", " Masterclass", " Workshop",
                 " Certificate", " Intensive", " for Practitioners", " from Scratch"]


def build_courses(rng: random.Random, count: int) -> list[dict]:
    out = []
    for i in range(count):
        subject = rng.choice(list(COURSE_SUBJECTS))
        skills = COURSE_SUBJECTS[subject]
        level = rng.choices(["Beginner", "Intermediate", "Advanced"], weights=[42, 39, 19])[0]

        name = f"{rng.choice(COURSE_QUALIFIER)} {subject}{rng.choice(COURSE_SUFFIX)}".strip()

        weeks = max(1, min(28, int(rng.gauss({"Beginner": 8, "Intermediate": 11, "Advanced": 14}[level], 5))))
        hours = max(2, min(14, int(rng.gauss(6, 2.4))))

        free = rng.random() < 0.24
        if free:
            price = 0
        else:
            price = rounded(rng.uniform(900, 7200) * {"Beginner": 0.85, "Intermediate": 1.0, "Advanced": 1.25}[level], 100)

        project = rng.choices(["yes", "partial", "no"], weights=[45, 33, 22])[0]
        certificate = "no" if free and rng.random() < 0.55 else rng.choice(["yes", "yes", "paid upgrade"])

        out.append({
            "course_id": f"SYN-C{i:05d}",
            "name": name,
            "provider": rng.choice(PROVIDERS),
            "instructor": person(rng),
            "level": level,
            "duration_weeks": weeks,
            "hours_per_week": hours,
            "price_inr": price,
            "rating": round(min(5.0, max(3.4, rng.gauss(4.45, 0.3))), 1),
            "enrolled": int(max(300, rng.lognormvariate(9.6, 1.6))),
            "skills": "|".join(rng.sample(skills, min(len(skills), rng.randint(3, 5)))),
            "certificate": certificate,
            "prerequisites": {"Beginner": "none", "Intermediate": "basic programming",
                              "Advanced": "prior experience in the subject"}[level],
            "format": rng.choice(["video + graded labs", "video + quizzes",
                                  "written + notebooks", "lectures + problem sets",
                                  "video + capstone"]),
            "project_based": project,
            "summary": f"A {level.lower()}-level route through {subject.lower()}, "
                       f"structured over {weeks} weeks at about {hours} hours a week.",
            "synthetic": True,
        })
    return out


# ---------------------------------------------------------------------------
# Phones
# ---------------------------------------------------------------------------

PHONE_LINES = ["Aero", "Nova", "Prime", "Edge", "Core", "Vertex", "Pulse", "Arc",
               "Flux", "Halo", "Origin", "Strata", "Neo", "Lumen"]
PHONE_SUFFIX = ["", " Pro", " Plus", " Ultra", " Lite", " SE", " Max", " Neo"]
PHONE_TAGS = ["camera", "gaming", "performance", "battery", "big battery", "fast charging",
              "compact", "clean software", "long updates", "design", "value", "premium",
              "lightweight", "budget", "ai features"]


def build_phones(rng: random.Random, count: int) -> list[dict]:
    out = []
    for i in range(count):
        brand = rng.choice(PRODUCT_BRANDS)
        model = f"{rng.choice(PHONE_LINES)} {rng.randint(4, 15)}{rng.choice(PHONE_SUFFIX)}"

        # Tier drives every other number, so the spec sheet stays internally
        # consistent: a budget phone never gets a flagship chipset.
        tier = rng.choices(["budget", "mid", "upper", "flagship"], weights=[27, 38, 22, 13])[0]
        ram = {"budget": [4, 6], "mid": [6, 8], "upper": [8, 12], "flagship": [12, 16]}[tier]
        ram_gb = rng.choice(ram)
        storage_gb = rng.choice({"budget": [64, 128], "mid": [128, 256],
                                 "upper": [128, 256], "flagship": [256, 512]}[tier])
        antutu = {"budget": (380, 640), "mid": (640, 1000),
                  "upper": (1000, 1600), "flagship": (1600, 2300)}[tier]
        benchmark = rng.randint(*antutu)

        base_price = {"budget": 12000, "mid": 24000, "upper": 46000, "flagship": 82000}[tier]
        price = rounded(
            base_price * rng.uniform(0.85, 1.25)
            + (ram_gb - 6) * 900 + (storage_gb - 128) * 22,
            500,
        )
        price = max(8999, price)

        screen = round(rng.uniform(6.1, 6.9) if tier != "budget" else rng.uniform(6.4, 6.8), 2)
        if rng.random() < 0.07:
            screen = round(rng.uniform(4.7, 6.1), 2)  # the rare compact model
        battery = rng.choice([4000, 4500, 5000, 5000, 5500, 6000, 6500])
        charging = rng.choice({"budget": [10, 18, 25], "mid": [25, 33, 45, 67],
                               "upper": [45, 67, 80, 100], "flagship": [65, 80, 100, 120]}[tier])
        camera = rng.choice({"budget": [13, 32, 48], "mid": [48, 50, 64],
                             "upper": [50, 64, 108], "flagship": [50, 108, 200]}[tier])
        weight = int(rng.gauss(190 + (screen - 6.5) * 30, 12))
        os_family = rng.choices(["Android", "HarmonyOS"], weights=[93, 7])[0]

        tags = rng.sample(PHONE_TAGS, rng.randint(2, 4))
        if battery >= 5500 and "big battery" not in tags:
            tags.append("big battery")
        if charging >= 80 and "fast charging" not in tags:
            tags.append("fast charging")
        if screen < 6.2 and "compact" not in tags:
            tags.append("compact")
        if tier == "flagship" and "premium" not in tags:
            tags.append("premium")

        out.append({
            "sku": f"SYN-PH-{i:05d}",
            "brand": brand,
            "model": model,
            "released": f"{rng.randint(2021, 2026)}-{rng.randint(1, 12):02d}",
            "price": {"mrp": rounded(price * 1.18, 500), "street": price},
            "specs": {
                "display": {"size_in": screen,
                            "refresh_hz": rng.choice([60, 90, 120, 120, 144, 165]),
                            "panel": rng.choice(["AMOLED", "OLED", "pOLED", "LCD"]),
                            "resolution": rng.choice(["1080x2400", "1220x2712", "1440x3200"])},
                "battery": {"capacity_mah": battery, "charging_w": charging,
                            "wireless": tier in {"upper", "flagship"} and rng.random() < 0.6},
                "camera": {"main_mp": camera, "ultrawide_mp": rng.choice([0, 8, 12, 13, 50]),
                           "front_mp": rng.choice([8, 13, 16, 32]), "ois": tier != "budget"},
                "performance": {"chipset": f"{brand} {rng.choice(['Helix', 'Torque', 'Kinetic', 'Vector'])} {rng.randint(500, 990)}",
                                "ram_gb": ram_gb, "storage_gb": storage_gb, "antutu_k": benchmark},
                "software": {"os": f"{os_family} {rng.randint(13, 17)}",
                             "update_years": rng.choice({"budget": [2, 2, 3], "mid": [2, 3, 4],
                                                         "upper": [3, 4, 5], "flagship": [4, 5, 6, 7]}[tier])},
            },
            "body": {"weight_g": weight,
                     "ip_rating": rng.choices(["none", "IP54", "IP64", "IP67", "IP68"],
                                              weights=[16, 22, 14, 20, 28])[0],
                     "material": rng.choice(["plastic", "glass", "aluminium", "titanium"])},
            "rating": round(min(4.8, max(3.4, rng.gauss(4.15, 0.32))), 1),
            "tags": sorted(set(tags)),
            "blurb": f"A {tier}-tier handset built around {tags[0]}, with a {screen}-inch panel "
                     f"and a {battery} mAh battery.",
            "synthetic": True,
        })
    return out


# ---------------------------------------------------------------------------
# Laptops
# ---------------------------------------------------------------------------

LAPTOP_LINES = ["Stratus", "Meridian", "Forge", "Atlas", "Quill", "Vector", "Slate",
                "Beacon", "Onyx", "Drift", "Summit", "Ember"]
LAPTOP_USES = ["students", "programming", "gaming", "video editing", "ml", "office",
               "business", "travel", "content creation", "browsing", "3d rendering",
               "streaming", "writing", "everyday"]


def build_laptops(rng: random.Random, count: int) -> list[dict]:
    out = []
    for i in range(count):
        brand = rng.choice(PRODUCT_BRANDS)
        form = rng.choices(["Ultrabook", "Notebook", "Gaming", "Workstation", "2-in-1", "Chromebook"],
                           weights=[24, 30, 22, 9, 10, 5])[0]

        gaming = form in {"Gaming", "Workstation"}
        ram = rng.choice([8, 16, 16, 32] if not gaming else [16, 16, 32, 64])
        storage_gb = rng.choice([256, 512, 512, 1024, 2048])
        vram = 0 if not gaming else rng.choice([4, 6, 8, 8, 12, 16])
        screen = round(rng.choice([13.3, 13.6, 14.0, 14.0, 15.6, 15.6, 16.0, 17.3]), 1)

        weight = round(
            {"Ultrabook": 1.25, "Notebook": 1.75, "Gaming": 2.35,
             "Workstation": 2.1, "2-in-1": 1.4, "Chromebook": 1.35}[form]
            + (screen - 14) * 0.09 + rng.uniform(-0.14, 0.2), 2)
        weight = max(0.95, weight)

        battery_hours = int(max(4, min(20, rng.gauss(
            {"Ultrabook": 14, "Notebook": 9, "Gaming": 6,
             "Workstation": 9, "2-in-1": 12, "Chromebook": 12}[form], 2.4))))

        price = rounded(
            26000 + ram * 1350 + storage_gb * 21 + vram * 5200
            + {"Ultrabook": 26000, "Notebook": 6000, "Gaming": 22000,
               "Workstation": 62000, "2-in-1": 24000, "Chromebook": -6000}[form]
            + rng.uniform(-9000, 16000),
            1000)
        price = max(24990, price)

        panel = rng.choices(["IPS", "OLED", "IPS", "AMOLED", "TN"], weights=[42, 24, 22, 8, 4])[0]
        resolution = rng.choice(["1920x1080", "1920x1200", "2560x1600", "2880x1800", "3200x2000"])
        os_name = rng.choices(["Windows 11", "Linux", "ChromeOS"], weights=[86, 9, 5])[0]
        if form == "Chromebook":
            os_name = "ChromeOS"

        uses = rng.sample(LAPTOP_USES, rng.randint(2, 4))
        if gaming and "gaming" not in uses:
            uses.append("gaming")
        if weight < 1.35 and "travel" not in uses:
            uses.append("travel")

        storage_text = f"{storage_gb // 1024}TB SSD" if storage_gb >= 1024 else f"{storage_gb}GB SSD"

        out.append({
            "Company": brand,
            "Product": f"{rng.choice(LAPTOP_LINES)} {rng.randint(3, 19)}"
                       + rng.choice(["", " Pro", " Air", " X", " Plus"]),
            "TypeName": form,
            "Inches": screen,
            "ScreenResolution": f"{resolution} {panel}",
            "Cpu": f"{brand} {rng.choice(['C-series', 'M-series', 'Ryzen-class', 'Core-class'])} "
                   f"{rng.randint(3, 9)}-{rng.randint(1000, 9999)}",
            "Ram": f"{ram}GB",
            "Memory": storage_text,
            "Gpu": "Integrated graphics" if vram == 0 else f"{brand} discrete {vram}GB",
            "OpSys": os_name,
            "Weight": f"{weight}kg",
            "BatteryHours": battery_hours,
            "Price_inr": price,
            "Rating": round(min(4.8, max(3.3, rng.gauss(4.1, 0.34))), 1),
            "UseCase": ", ".join(sorted(set(uses))),
            "Ports": rng.choice(["2x USB-C, 2x USB-A, HDMI", "2x Thunderbolt, USB-A, HDMI, SD",
                                 "USB-C, 3x USB-A, HDMI, ethernet", "2x USB-C, 3.5mm"]),
            "Notes": f"A {form.lower()} with {ram}GB of memory and {storage_text.lower()}, "
                     f"rated at about {battery_hours} hours of battery.",
            "synthetic": True,
        })
    return out


# ---------------------------------------------------------------------------
# Cars
# ---------------------------------------------------------------------------

CAR_LINES = ["Aria", "Terra", "Vista", "Nomad", "Cirro", "Delta", "Sierra", "Lumen",
             "Vanta", "Orbit", "Ridge", "Cove"]
CAR_TRIMS = ["Base", "LX", "VX", "ZX", "SX", "GT", "Signature", "Adventure", "Elite"]
CAR_FEATURES = ["sunroof", "adas", "360 camera", "ventilated seats", "cruise control",
                "wireless carplay", "panoramic sunroof", "6 airbags", "4x4",
                "wireless charging", "digital cluster", "hill assist"]


def build_cars(rng: random.Random, count: int) -> list[dict]:
    out = []
    for i in range(count):
        body = rng.choices(["Hatchback", "Sedan", "SUV", "MPV"], weights=[24, 20, 45, 11])[0]
        fuel = rng.choices(["Petrol", "Diesel", "Electric", "Hybrid", "CNG"],
                           weights=[44, 18, 19, 12, 7])[0]
        transmission = rng.choices(["Manual", "Automatic"], weights=[38, 62])[0]
        electric = fuel == "Electric"

        seats = 7 if body == "MPV" else rng.choices([5, 5, 5, 7], weights=[70, 12, 8, 10])[0]
        if body == "Hatchback":
            seats = 5

        engine_cc = 0 if electric else rng.choice([998, 1197, 1199, 1462, 1482, 1498, 1956, 1997, 2184])
        power = int(rng.gauss(165 if electric else engine_cc * 0.075 + 20, 18))
        power = max(55, min(320, power))

        if electric:
            mileage = 0.0
            range_km = int(rng.gauss(390, 85))
            range_km = max(150, min(620, range_km))
        else:
            base_mileage = {"Petrol": 18.5, "Diesel": 20.0, "Hybrid": 25.5, "CNG": 26.0}[fuel]
            mileage = round(max(9.0, min(32.0, rng.gauss(base_mileage - (power - 100) * 0.02, 2.6))), 2)
            range_km = None

        price_lakh = round(max(4.5, min(58.0, rng.gauss(
            {"Hatchback": 8.5, "Sedan": 15.0, "SUV": 18.0, "MPV": 17.0}[body]
            + (6.5 if electric else 0) + power * 0.035, 4.6))), 2)

        safety = rng.choices([2, 3, 4, 5], weights=[6, 18, 34, 42])[0]
        boot = int(rng.gauss({"Hatchback": 300, "Sedan": 480, "SUV": 400, "MPV": 260}[body], 65))
        boot = max(90, boot)

        features = rng.sample(CAR_FEATURES, rng.randint(3, 5))
        highlights = []
        if not electric and mileage >= 22:
            highlights.append("class-leading mileage")
        if safety == 5:
            highlights.append("5-star safety")
        if seats == 7:
            highlights.append("seven seats")
        if electric and range_km and range_km >= 420:
            highlights.append("long range")
        if not highlights:
            highlights.append(rng.choice(["comfortable ride", "easy to park", "strong resale"]))

        record = {
            "make": rng.choice(VEHICLE_BRANDS),
            "model": f"{rng.choice(CAR_LINES)}{rng.choice(['', ' ' + str(rng.randint(3, 9))])}",
            "variant": rng.choice(CAR_TRIMS),
            "year": rng.randint(2021, 2026),
            "body_type": body,
            "fuel_type": fuel,
            "transmission": transmission,
            "mileage_kmpl": mileage,
            "engine_cc": engine_cc,
            "power_bhp": power,
            "seating": seats,
            "boot_litres": boot,
            "ex_showroom_lakh": price_lakh,
            "safety_rating_ncap": safety,
            "user_rating": round(min(4.8, max(3.2, rng.gauss(4.05, 0.36))), 1),
            "highlights": highlights,
            "features": ";".join(features),
            "description": f"A {body.lower()} with a {fuel.lower()} powertrain and "
                           f"{transmission.lower()} transmission, seating {seats}.",
            "synthetic": True,
        }
        if electric:
            record["range_km"] = range_km
        out.append(record)
    return out


# ---------------------------------------------------------------------------
# Bikes
# ---------------------------------------------------------------------------

BIKE_BRANDS = ["Aravind Moto", "Kestrel Cycles", "Vantara Moto", "Solvane Two",
               "Corvex Moto", "Meridian Riders", "Auralis Moto", "Nimbus Cycles",
               "Orryx Moto", "Pallas Riders"]
BIKE_LINES = ["Trail", "Rover", "Dart", "Comet", "Ranger", "Vector", "Drift",
              "Summit", "Pulse", "Nomad", "Falcon"]
BIKE_USES = ["city commuting", "highway cruising", "touring", "off road", "track",
             "weekend rides", "beginners", "style", "budget", "errands", "family",
             "low running cost"]


def build_bikes(rng: random.Random, count: int) -> list[dict]:
    out = []
    for i in range(count):
        segment = rng.choices(
            ["Commuter", "Scooter", "Electric Scooter", "Sport Commuter", "Street Naked",
             "Cruiser", "Sport", "Adventure", "Roadster", "Scrambler"],
            weights=[16, 17, 11, 12, 12, 10, 8, 6, 5, 3])[0]
        electric = segment == "Electric Scooter"

        if electric:
            cc, power = 0, round(rng.uniform(4.0, 15.0), 1)
            mileage, range_km = 0.0, int(rng.gauss(120, 38))
            range_km = max(60, min(230, range_km))
            price = rounded(rng.gauss(118000, 32000), 1000)
        else:
            cc = rng.choice({"Commuter": [97, 110, 123, 125], "Scooter": [109, 110, 124, 125],
                             "Sport Commuter": [149, 155, 160], "Street Naked": [155, 160, 199, 249],
                             "Cruiser": [223, 348, 349], "Sport": [155, 249, 296, 373],
                             "Adventure": [199, 249, 411, 452], "Roadster": [349, 398],
                             "Scrambler": [223, 249]}.get(segment, [150]))
            power = round(max(6.0, min(46.0, cc * 0.093 + rng.uniform(-2.2, 3.4))), 1)
            mileage = round(max(24.0, min(72.0, rng.gauss(72 - cc * 0.085, 4.2))), 1)
            range_km = None
            price = rounded(52000 + cc * 480 + rng.uniform(-14000, 22000), 1000)
        price = max(58000, int(price))

        weight = int(rng.gauss(104 + cc * 0.22 if not electric else 112, 11))
        weight = max(96, min(230, weight))
        seat_height = int(rng.gauss(
            {"Scooter": 768, "Electric Scooter": 782, "Commuter": 790,
             "Cruiser": 795, "Adventure": 828, "Sport": 810}.get(segment, 800), 16))

        abs_text = rng.choices(
            ["none (CBS)", "single-channel", "dual-channel", "switchable dual-channel"],
            weights=[28, 26, 40, 6])[0]
        if electric:
            abs_text = "none (CBS)"

        uses = rng.sample(BIKE_USES, rng.randint(2, 3))
        if not electric and mileage >= 50 and "low running cost" not in uses:
            uses.append("low running cost")
        if weight <= 125 and "beginners" not in uses:
            uses.append("beginners")

        record = {
            "name": f"{rng.choice(BIKE_BRANDS)} {rng.choice(BIKE_LINES)} "
                    f"{cc if cc else rng.choice(['E', 'EV'])}",
            "brand": "",
            "segment": segment,
            "engine_cc": cc,
            "power_bhp": power,
            "torque_nm": round(power * rng.uniform(1.1, 1.6), 1),
            "mileage_kmpl": mileage,
            "kerb_weight_kg": weight,
            "seat_height_mm": seat_height,
            "fuel_tank_l": 0 if electric else round(rng.uniform(8.0, 17.0), 1),
            "abs": abs_text,
            "price_inr": price,
            "rating": round(min(4.7, max(3.3, rng.gauss(4.1, 0.33))), 1),
            "good_for": "|".join(sorted(set(uses))),
            "riding_posture": rng.choice(["upright relaxed", "upright sporty", "committed sport",
                                          "step-through", "upright adventure", "upright neutral"]),
            "about": f"A {segment.lower()} aimed at {uses[0]}, weighing {weight} kg.",
            "synthetic": True,
        }
        record["brand"] = record["name"].split(" ")[0] + " " + record["name"].split(" ")[1]
        if electric:
            record["range_km"] = range_km
        out.append(record)
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

BUILDERS = {
    "movies": build_movies,
    "books": build_books,
    "courses": build_courses,
    "phones": build_phones,
    "laptops": build_laptops,
    "cars": build_cars,
    "bikes": build_bikes,
}

# Where the records live inside each domain's own raw shape.
CONTAINER = {
    "movies": "movies",
    "books": "records",
    "courses": None,        # bare top-level array
    "phones": "data",
    "laptops": "laptops",
    "cars": "vehicles",
    "bikes": "bikes",
}


def build(scale: float = 1.0) -> dict[str, tuple[int, int, int]]:
    report: dict[str, tuple[int, int, int]] = {}

    for name, builder in BUILDERS.items():
        seed_payload = load_seed(name)
        key = CONTAINER[name]
        anchors = seed_payload if key is None else seed_payload.get(key, [])

        rng = random.Random(RANDOM_SEED + sum(ord(c) for c in name))
        target = int(BASE_COUNTS[name] * scale)
        generated = builder(rng, target)

        # Anchors first: a demo query should still surface the recognisable,
        # factually-checked entries rather than burying them in generated rows.
        records = list(anchors) + generated

        if key is None:
            payload: dict | list = records
        else:
            payload = dict(seed_payload)
            payload[key] = records
            payload["generated"] = {
                "curated_records": len(anchors),
                "synthetic_records": len(generated),
                "note": "Synthetic records are marked with \"synthetic\": true. They use invented "
                        "brands, authors and directors. See data/build_catalogue.py.",
            }

        size = write_raw(name, payload)
        report[name] = (len(anchors), len(generated), size)

    return report


def restore() -> None:
    for path in SEED_DIR.glob("*.json"):
        shutil.copy(path, RAW_DIR / path.name)
    print("  Restored data/raw from data/seed (curated records only).\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the DebateRec catalogues")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="multiplier on the base record counts")
    parser.add_argument("--restore", action="store_true",
                        help="restore the small curated catalogues")
    args = parser.parse_args()

    if args.restore:
        restore()
        return 0

    print(f"\n  Building catalogues at scale {args.scale}x (seed {RANDOM_SEED})\n")
    report = build(args.scale)

    total_curated = total_synth = total_bytes = 0
    print(f"  {'domain':10s} {'curated':>8s} {'generated':>10s} {'total':>8s} {'size':>9s}")
    print("  " + "─" * 50)
    for name, (curated, synth, size) in report.items():
        total_curated += curated
        total_synth += synth
        total_bytes += size
        print(f"  {name:10s} {curated:>8d} {synth:>10d} {curated + synth:>8d} {size / 1024:>8.0f}K")
    print("  " + "─" * 50)
    print(f"  {'total':10s} {total_curated:>8d} {total_synth:>10d} "
          f"{total_curated + total_synth:>8d} {total_bytes / 1048576:>7.1f}MB\n")
    print("  Curated records are unchanged and appear first in every file.")
    print("  Generated records are marked \"synthetic\": true.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
