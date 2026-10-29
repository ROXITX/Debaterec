"""Cars adapter — source shape: {"vehicles": [...]}, price in LAKHS, with a
semicolon-delimited `features` string alongside a real `highlights` array."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..schemas import Item
from .base import DomainAdapter, FacetSpec, TagSpec, clean, num, split_list


@dataclass
class CarsAdapter(DomainAdapter):
    key: str = "car"
    label: str = "Cars"
    noun: str = "car"
    icon: str = "car"
    accent: str = "#ff8a4d"
    blurb: str = "Cars across price, mileage, safety, seating and body type."
    raw_file: str = "cars.json"
    routing_words: tuple[str, ...] = (
        "car", "cars", "vehicle", "sedan", "suv", "hatchback", "mpv", "automatic",
        "manual", "petrol", "diesel", "electric car", "ev", "mileage", "kmpl",
        "seven seater", "7 seater", "family car", "drive",
    )
    examples: tuple[str, ...] = (
        "family car under 15 lakh with 5-star safety and good mileage",
        "an automatic seven-seater, not diesel, comfortable for long drives",
        "electric SUV with over 400 km range under 25 lakh",
    )
    facets: tuple[FacetSpec, ...] = (
        FacetSpec("price", "Ex-showroom price", "INR", "lower",
                  ("price", "cost", "budget", "cheap", "expensive", "lakh", "lakhs", "rupees", "affordable"),
                  low_words=("cheap", "budget", "affordable", "economical"),
                  high_words=("premium", "luxury"),
                  typical=(500000.0, 4500000.0), scale_hint="stored in RUPEES; '15 lakh' = 1500000"),
        FacetSpec("mileage", "Fuel economy", "kmpl", "higher",
                  ("mileage", "kmpl", "fuel economy", "efficiency", "economy", "consumption", "average"),
                  high_words=("good mileage", "fuel efficient", "high mileage"),
                  typical=(12.0, 28.0)),
        FacetSpec("range", "Electric range", "km", "higher",
                  ("range", "km range", "battery range", "driving range"),
                  high_words=("long range",), typical=(150.0, 550.0)),
        FacetSpec("seats", "Seating", "seats", "higher",
                  ("seats", "seating", "seater", "capacity", "people", "passengers"),
                  high_words=("seven seater", "big family"), typical=(4.0, 7.0)),
        FacetSpec("boot", "Boot space", "litres", "higher",
                  ("boot", "boot space", "luggage", "trunk", "storage", "bags"),
                  high_words=("big boot", "lots of luggage"), typical=(100.0, 530.0)),
        FacetSpec("power", "Power", "bhp", "higher",
                  ("power", "bhp", "horsepower", "performance", "fast", "quick", "engine power"),
                  high_words=("powerful", "fast", "quick"), typical=(65.0, 205.0)),
        FacetSpec("engine", "Engine", "cc", "higher",
                  ("engine", "cc", "displacement", "capacity"), typical=(1000.0, 2800.0)),
        FacetSpec("safety", "Crash rating", "stars", "higher",
                  ("safety", "safety rating", "ncap", "stars", "crash", "safe"),
                  high_words=("safe", "5 star", "safest", "good safety"), typical=(2.0, 5.0)),
        FacetSpec("rating", "Owner rating", "/5", "higher",
                  ("rating", "reviews", "owner rating", "well reviewed", "reliable"),
                  typical=(3.5, 4.6)),
        FacetSpec("year", "Model year", "", "higher",
                  ("year", "model year", "new", "latest"), typical=(2020.0, 2026.0)),
    )
    tag_facets: tuple[TagSpec, ...] = (
        TagSpec("brand", "Make", ("brand", "make", "company", "manufacturer"),
                ("maruti suzuki", "hyundai", "tata", "mahindra", "toyota", "honda", "kia",
                 "skoda", "volkswagen", "mg", "byd", "renault", "jeep", "citroen")),
        TagSpec("body", "Body type", ("body", "body type", "type", "shape", "segment"),
                ("hatchback", "sedan", "suv", "mpv")),
        TagSpec("fuel", "Fuel", ("fuel", "fuel type", "petrol", "diesel", "electric", "hybrid", "cng"),
                ("petrol", "diesel", "electric", "hybrid", "cng")),
        TagSpec("transmission", "Transmission", ("transmission", "gearbox", "automatic", "manual", "amt", "dct"),
                ("manual", "automatic")),
        TagSpec("feature", "Features", ("feature", "features", "equipment", "sunroof", "adas", "camera"),
                ("sunroof", "adas", "360 camera", "ventilated seats", "cruise control",
                 "wireless carplay", "panoramic sunroof", "6 airbags", "4x4")),
        TagSpec("highlight", "Known for", ("known for", "good at", "strength", "reputation"),
                ("class-leading mileage", "5-star safety", "seven seats", "strong resale",
                 "cheap to service", "long range", "road presence")),
    )

    def parse(self, raw: Any) -> Iterable[Item]:
        for i, rec in enumerate(raw.get("vehicles", [])):
            make = clean(rec.get("make"))
            model = clean(rec.get("model"))
            variant = clean(rec.get("variant"))
            # Price arrives in LAKHS here and is normalised to rupees so that
            # "under 15 lakh" and "under 1500000" are the same constraint.
            price = (num(rec.get("ex_showroom_lakh")) or 0) * 100000
            fuel = clean(rec.get("fuel_type")).lower()
            facets = {
                "price": price or None,
                "mileage": num(rec.get("mileage_kmpl")) or None,
                "range": num(rec.get("range_km")),
                "seats": num(rec.get("seating")),
                "boot": num(rec.get("boot_litres")),
                "power": num(rec.get("power_bhp")),
                "engine": num(rec.get("engine_cc")) or None,
                "safety": num(rec.get("safety_rating_ncap")),
                "rating": num(rec.get("user_rating")),
                "year": num(rec.get("year")),
            }
            # `features` is SEMICOLON-delimited; `highlights` is a real array.
            features = split_list(rec.get("features"), seps=";")
            highlights = split_list(rec.get("highlights"))

            display: list[tuple[str, str]] = [("Make", make)]
            if price:
                display.append(("Price", f"₹{price / 100000:.2f} lakh ex-showroom"))
            display.append(("Body", clean(rec.get("body_type"))))
            display.append(("Fuel", clean(rec.get("fuel_type"))))
            display.append(("Transmission", clean(rec.get("transmission"))))
            if facets["mileage"]:
                display.append(("Mileage", f"{facets['mileage']} kmpl"))
            if facets["range"]:
                display.append(("Range", f"{int(facets['range'])} km claimed"))
            if facets["engine"]:
                display.append(("Engine", f"{int(facets['engine'])} cc, {int(facets['power'] or 0)} bhp"))
            elif facets["power"]:
                display.append(("Motor", f"{int(facets['power'])} bhp"))
            if facets["seats"]:
                display.append(("Seating", f"{int(facets['seats'])} seats"))
            if facets["boot"]:
                display.append(("Boot", f"{int(facets['boot'])} litres"))
            if facets["safety"]:
                display.append(("Safety", f"{int(facets['safety'])}-star NCAP"))
            if features:
                display.append(("Features", ", ".join(features)))

            yield Item(
                item_id=f"car:C{i + 1:03d}",
                domain=self.key,
                title=f"{make} {model}",
                subtitle=f"{variant} · {clean(rec.get('body_type'))}".strip(" ·"),
                description=clean(rec.get("description")),
                facets={k: v for k, v in facets.items() if v is not None},
                tags={
                    "brand": [make.lower()],
                    "body": [clean(rec.get("body_type")).lower()],
                    "fuel": [fuel],
                    "transmission": [clean(rec.get("transmission")).lower()],
                    "feature": [f.lower() for f in features],
                    "highlight": [h.lower() for h in highlights],
                },
                display=display,
                rating=facets["rating"],
                popularity=(facets["rating"] or 4.0) * 20,
                synthetic=bool(rec.get("synthetic")),
            )
