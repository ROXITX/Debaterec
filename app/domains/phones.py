"""Phones adapter — source shape: {"data": [...]} with DEEPLY NESTED specs.

This is the adapter that most clearly justifies the pattern: nothing about the
raw file resembles the movies file, yet the Item it produces is identical in
structure and the debate engine cannot tell them apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..schemas import Item
from .base import DomainAdapter, FacetSpec, TagSpec, clean, num, split_list, year_of


def _dig(d: Any, *path: str, default: Any = None) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


@dataclass
class PhonesAdapter(DomainAdapter):
    key: str = "phone"
    label: str = "Phones"
    noun: str = "phone"
    icon: str = "phone"
    accent: str = "#4dc9ff"
    blurb: str = "Smartphones across price, camera, battery and performance."
    raw_file: str = "phones.json"
    routing_words: tuple[str, ...] = (
        "phone", "phones", "smartphone", "smartphones", "mobile", "handset", "iphone",
        "android", "pixel", "galaxy", "oneplus", "redmi", "camera phone", "flagship",
    )
    examples: tuple[str, ...] = (
        "a phone under 30000 with the best possible camera and big battery",
        "compact flagship under 200g, I don't care about price",
        "best gaming phone under 40k with fast charging, not too heavy",
    )
    facets: tuple[FacetSpec, ...] = (
        FacetSpec("price", "Street price", "INR", "lower",
                  ("price", "cost", "budget", "cheap", "expensive", "rupees", "inr", "k", "affordable", "under"),
                  low_words=("cheap", "budget", "affordable", "value", "inexpensive"),
                  high_words=("premium", "flagship", "expensive"),
                  typical=(15000.0, 150000.0), scale_hint="in rupees; '30k' means 30000"),
        FacetSpec("battery", "Battery", "mAh", "higher",
                  ("battery", "mah", "battery life", "backup", "endurance"),
                  high_words=("big battery", "long battery", "all day", "two day"),
                  typical=(2000.0, 6000.0)),
        FacetSpec("charging", "Charging", "W", "higher",
                  ("charging", "fast charging", "charge speed", "watt", "w"),
                  high_words=("fast charging", "quick charge"),
                  typical=(18.0, 120.0)),
        FacetSpec("camera", "Main camera", "MP", "higher",
                  ("camera", "megapixel", "mp", "photography", "photos", "pictures"),
                  high_words=("best camera", "great camera", "photography"),
                  typical=(12.0, 200.0)),
        FacetSpec("ram", "RAM", "GB", "higher",
                  ("ram", "memory"), high_words=("more ram",), typical=(4.0, 16.0)),
        FacetSpec("storage", "Storage", "GB", "higher",
                  ("storage", "rom", "space", "gb storage"), typical=(64.0, 512.0)),
        FacetSpec("screen", "Screen size", "in", "neutral",
                  ("screen", "display", "size", "inch", "inches", "big screen", "small", "compact"),
                  low_words=("compact", "small", "one hand", "pocketable"),
                  high_words=("big screen", "large display"),
                  typical=(4.7, 6.9)),
        FacetSpec("refresh", "Refresh rate", "Hz", "higher",
                  ("refresh", "refresh rate", "hz", "smooth", "120hz"), typical=(60.0, 165.0)),
        FacetSpec("weight", "Weight", "g", "lower",
                  ("weight", "heavy", "light", "grams", "g"),
                  low_words=("light", "lightweight", "not heavy"),
                  high_words=("heavy",), typical=(140.0, 240.0)),
        FacetSpec("performance", "Benchmark", "k AnTuTu", "higher",
                  ("performance", "speed", "fast", "processor", "chipset", "benchmark", "gaming", "powerful"),
                  high_words=("fast", "powerful", "flagship performance", "gaming"),
                  typical=(500.0, 2200.0)),
        FacetSpec("updates", "Update support", "years", "higher",
                  ("updates", "software support", "os updates", "longevity", "future proof"),
                  high_words=("long updates", "future proof"), typical=(2.0, 7.0)),
        FacetSpec("rating", "Rating", "/5", "higher",
                  ("rating", "score", "reviews", "well reviewed", "good"), typical=(3.7, 4.8)),
        FacetSpec("year", "Released", "", "higher",
                  ("year", "released", "launch", "new", "latest", "old"),
                  high_words=("latest", "newest", "new"), typical=(2022.0, 2026.0)),
    )
    tag_facets: tuple[TagSpec, ...] = (
        TagSpec("brand", "Brand", ("brand", "make", "company", "manufacturer"),
                ("apple", "samsung", "google", "oneplus", "xiaomi", "nothing", "motorola",
                 "vivo", "realme", "iqoo", "poco", "asus")),
        TagSpec("os", "OS", ("os", "operating system", "android", "ios", "software"),
                ("android", "ios")),
        TagSpec("feature", "Strengths", ("feature", "good for", "use case", "for", "priority"),
                ("camera", "gaming", "performance", "battery", "big battery", "fast charging",
                 "compact", "clean software", "long updates", "design", "value", "premium",
                 "foldable", "lightweight", "ai features", "budget", "ecosystem", "video")),
        TagSpec("build", "Build", ("build", "material", "waterproof", "ip rating", "ip68"),
                ("titanium", "aluminium", "glass", "plastic", "ip68", "ip67", "ip54")),
    )

    def parse(self, raw: Any) -> Iterable[Item]:
        for rec in raw.get("data", []):
            brand = clean(rec.get("brand"))
            model = clean(rec.get("model"))
            price = num(_dig(rec, "price", "street")) or num(_dig(rec, "price", "mrp"))
            facets = {
                "price": price,
                "battery": num(_dig(rec, "specs", "battery", "capacity_mah")),
                "charging": num(_dig(rec, "specs", "battery", "charging_w")),
                "camera": num(_dig(rec, "specs", "camera", "main_mp")),
                "ram": num(_dig(rec, "specs", "performance", "ram_gb")),
                "storage": num(_dig(rec, "specs", "performance", "storage_gb")),
                "screen": num(_dig(rec, "specs", "display", "size_in")),
                "refresh": num(_dig(rec, "specs", "display", "refresh_hz")),
                "weight": num(_dig(rec, "body", "weight_g")),
                "performance": num(_dig(rec, "specs", "performance", "antutu_k")),
                "updates": num(_dig(rec, "specs", "software", "update_years")),
                "rating": num(rec.get("rating")),
                "year": year_of(rec.get("released")),
            }
            os_name = clean(_dig(rec, "specs", "software", "os", default=""))
            os_family = "ios" if "ios" in os_name.lower() else "android"
            chipset = clean(_dig(rec, "specs", "performance", "chipset", default=""))
            ip = clean(_dig(rec, "body", "ip_rating", default=""))
            material = clean(_dig(rec, "body", "material", default=""))
            tags_list = [t.lower() for t in split_list(rec.get("tags"))]

            display: list[tuple[str, str]] = [("Brand", brand)]
            if price:
                display.append(("Price", f"₹{int(price):,}"))
            if chipset:
                display.append(("Chipset", chipset))
            ram, storage = facets["ram"], facets["storage"]
            if ram and storage:
                display.append(("Memory", f"{int(ram)}GB RAM / {int(storage)}GB storage"))
            scr, hz, panel = facets["screen"], facets["refresh"], clean(_dig(rec, "specs", "display", "panel", default=""))
            if scr:
                display.append(("Display", f"{scr}\" {panel} {int(hz) if hz else ''}Hz".strip()))
            batt, chg = facets["battery"], facets["charging"]
            if batt:
                display.append(("Battery", f"{int(batt)} mAh, {int(chg) if chg else '?'}W charging"))
            cam = facets["camera"]
            if cam:
                ultra = num(_dig(rec, "specs", "camera", "ultrawide_mp"), 0)
                display.append(("Camera", f"{int(cam)}MP main" + (f" + {int(ultra)}MP ultrawide" if ultra else "")))
            if facets["weight"]:
                display.append(("Weight", f"{int(facets['weight'])} g"))
            if os_name:
                display.append(("Software", f"{os_name}, {int(facets['updates']) if facets['updates'] else '?'} yrs of updates"))
            if ip and ip != "none":
                display.append(("Water resistance", ip))

            yield Item(
                item_id=f"phone:{rec.get('sku')}",
                domain=self.key,
                title=f"{brand} {model}",
                subtitle=chipset,
                description=clean(rec.get("blurb")),
                facets={k: v for k, v in facets.items() if v is not None},
                tags={
                    "brand": [brand.lower()],
                    "os": [os_family],
                    "feature": tags_list,
                    "build": [t for t in (material.lower(), ip.lower()) if t and t != "none"],
                },
                display=display,
                rating=facets["rating"],
                popularity=(facets["rating"] or 4.0) * 20,
                synthetic=bool(rec.get("synthetic")),
            )
