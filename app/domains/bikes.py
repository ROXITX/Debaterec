"""Bikes adapter — source shape: {"meta": {...}, "bikes": [...]} with a
pipe-delimited `good_for` string and ABS stored as free text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..schemas import Item
from .base import DomainAdapter, FacetSpec, TagSpec, clean, num, split_list


@dataclass
class BikesAdapter(DomainAdapter):
    key: str = "bike"
    label: str = "Bikes"
    noun: str = "motorcycle"
    icon: str = "bike"
    accent: str = "#ffd24d"
    blurb: str = "Motorcycles and scooters across price, mileage, weight and use."
    raw_file: str = "bikes.json"
    routing_words: tuple[str, ...] = (
        "bike", "bikes", "motorcycle", "motorbike", "scooter", "scooty", "two wheeler",
        "royal enfield", "pulsar", "activa", "cruiser", "commuter bike", "cc", "riding",
        "ride", "mileage bike",
    )
    examples: tuple[str, ...] = (
        "a beginner-friendly bike under 1.5 lakh with good mileage, not too heavy",
        "comfortable highway cruiser with dual-channel ABS under 2.5 lakh",
        "electric scooter for city commuting with the lowest running cost",
    )
    facets: tuple[FacetSpec, ...] = (
        FacetSpec("price", "Ex-showroom price", "INR", "lower",
                  ("price", "cost", "budget", "cheap", "expensive", "lakh", "rupees", "affordable"),
                  low_words=("cheap", "budget", "affordable", "economical"),
                  high_words=("premium",),
                  typical=(75000.0, 350000.0), scale_hint="in rupees; '1.5 lakh' = 150000"),
        FacetSpec("mileage", "Fuel economy", "kmpl", "higher",
                  ("mileage", "kmpl", "fuel economy", "efficiency", "average", "economy"),
                  high_words=("good mileage", "fuel efficient"), typical=(25.0, 70.0)),
        FacetSpec("range", "Electric range", "km", "higher",
                  ("range", "km range", "battery range"), typical=(80.0, 200.0)),
        FacetSpec("engine", "Engine", "cc", "higher",
                  ("engine", "cc", "displacement", "capacity", "cubic"),
                  high_words=("big engine", "powerful"), typical=(97.0, 460.0)),
        FacetSpec("power", "Power", "bhp", "higher",
                  ("power", "bhp", "horsepower", "fast", "quick", "performance"),
                  high_words=("powerful", "fast"), typical=(7.0, 46.0)),
        FacetSpec("weight", "Kerb weight", "kg", "lower",
                  ("weight", "heavy", "light", "kg", "manageable"),
                  low_words=("light", "lightweight", "manageable", "easy to handle", "not heavy"),
                  high_words=("heavy", "planted"), typical=(104.0, 200.0)),
        FacetSpec("seat_height", "Seat height", "mm", "lower",
                  ("seat height", "tall", "short rider", "height", "flat foot", "reach"),
                  low_words=("low seat", "short rider", "flat foot"),
                  high_words=("tall",), typical=(738.0, 830.0)),
        FacetSpec("rating", "Rating", "/5", "higher",
                  ("rating", "reviews", "reliable", "well reviewed", "good"), typical=(3.6, 4.6)),
    )
    tag_facets: tuple[TagSpec, ...] = (
        TagSpec("brand", "Brand", ("brand", "make", "company", "manufacturer"),
                ("royal enfield", "honda", "tvs", "bajaj", "yamaha", "ktm", "hero",
                 "suzuki", "kawasaki", "triumph", "jawa", "ola electric", "ather")),
        TagSpec("segment", "Segment", ("segment", "type", "category", "kind", "style"),
                ("cruiser", "adventure", "scooter", "electric scooter", "sport",
                 "street naked", "commuter", "roadster", "sport tourer", "scrambler",
                 "bobber", "sport commuter")),
        TagSpec("use", "Best for", ("for", "use", "good for", "purpose", "usage", "riding"),
                ("city commuting", "highway cruising", "touring", "off road", "track",
                 "weekend rides", "beginners", "style", "budget", "errands", "family",
                 "low running cost", "tech")),
        TagSpec("safety", "Braking", ("abs", "brakes", "braking", "safety", "dual channel"),
                ("dual-channel", "single-channel", "cornering dual-channel",
                 "switchable dual-channel", "none (cbs)")),
        TagSpec("posture", "Riding posture", ("posture", "position", "comfortable", "upright", "committed"),
                ("upright relaxed", "upright sporty", "committed sport", "step-through",
                 "upright adventure", "upright neutral", "feet forward")),
    )

    def parse(self, raw: Any) -> Iterable[Item]:
        for i, rec in enumerate(raw.get("bikes", [])):
            brand = clean(rec.get("brand"))
            facets = {
                "price": num(rec.get("price_inr")),
                "mileage": num(rec.get("mileage_kmpl")) or None,
                "range": num(rec.get("range_km")),
                "engine": num(rec.get("engine_cc")) or None,
                "power": num(rec.get("power_bhp")),
                "weight": num(rec.get("kerb_weight_kg")),
                "seat_height": num(rec.get("seat_height_mm")),
                "rating": num(rec.get("rating")),
            }
            abs_text = clean(rec.get("abs")).lower()
            # `good_for` is PIPE-delimited.
            uses = split_list(rec.get("good_for"), seps="|")
            segment = clean(rec.get("segment"))
            posture = clean(rec.get("riding_posture")).lower()

            display: list[tuple[str, str]] = [("Brand", brand), ("Segment", segment)]
            if facets["price"]:
                display.append(("Price", f"₹{int(facets['price']):,} ex-showroom"))
            if facets["engine"]:
                display.append(("Engine", f"{int(facets['engine'])} cc, {facets['power']} bhp, {num(rec.get('torque_nm'))} Nm"))
            elif facets["power"]:
                display.append(("Motor", f"{facets['power']} bhp, {num(rec.get('torque_nm'))} Nm"))
            if facets["mileage"]:
                display.append(("Mileage", f"{facets['mileage']} kmpl"))
            if facets["range"]:
                display.append(("Range", f"{int(facets['range'])} km claimed"))
            if facets["weight"]:
                display.append(("Kerb weight", f"{facets['weight']} kg"))
            if facets["seat_height"]:
                display.append(("Seat height", f"{int(facets['seat_height'])} mm"))
            display.append(("ABS", clean(rec.get("abs"))))
            if posture:
                display.append(("Riding posture", posture))
            if uses:
                display.append(("Best for", ", ".join(uses)))

            yield Item(
                item_id=f"bike:B{i + 1:03d}",
                domain=self.key,
                title=clean(rec.get("name")),
                subtitle=f"{segment} · {int(facets['engine']) if facets['engine'] else 'electric'}"
                         + ("cc" if facets["engine"] else ""),
                description=clean(rec.get("about")),
                facets={k: v for k, v in facets.items() if v is not None},
                tags={
                    "brand": [brand.lower()],
                    "segment": [segment.lower()],
                    "use": [u.lower() for u in uses],
                    "safety": [abs_text],
                    "posture": [posture],
                },
                display=display,
                rating=facets["rating"],
                popularity=(facets["rating"] or 4.0) * 20,
                synthetic=bool(rec.get("synthetic")),
            )
