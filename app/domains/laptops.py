"""Laptops adapter — source shape: {"laptops": [...]} with PascalCase keys and
numbers stored as strings with units ('8GB', '1.24kg', '512GB SSD')."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..schemas import Item
from .base import DomainAdapter, FacetSpec, TagSpec, clean, num, split_list


def _storage_gb(text: str) -> float | None:
    """'512GB SSD' -> 512, '1TB SSD' -> 1024."""
    n = num(text)
    if n is None:
        return None
    return n * 1024 if "tb" in str(text).lower() else n


def _vram_gb(gpu: str) -> float:
    """Dedicated GPU memory, 0 for integrated graphics."""
    low = gpu.lower()
    if "integrated" in low or "iris" in low or "uhd" in low or "adreno" in low or "apple" in low:
        return 0.0
    return num(gpu, 0.0) or 0.0


@dataclass
class LaptopsAdapter(DomainAdapter):
    key: str = "laptop"
    label: str = "Laptops"
    noun: str = "laptop"
    icon: str = "laptop"
    accent: str = "#a78bfa"
    blurb: str = "Laptops across price, weight, battery, GPU and use case."
    raw_file: str = "laptops.json"
    routing_words: tuple[str, ...] = (
        "laptop", "laptops", "notebook", "macbook", "thinkpad", "ultrabook", "chromebook",
        "gaming laptop", "computer", "pc", "workstation", "ram", "ssd", "cpu",
    )
    examples: tuple[str, ...] = (
        "a laptop under 70000 for programming, light enough to carry daily",
        "best machine for training ML models, budget is 1.5 lakh",
        "something under 1.3kg with all-day battery for college",
    )
    facets: tuple[FacetSpec, ...] = (
        FacetSpec("price", "Price", "INR", "lower",
                  ("price", "cost", "budget", "cheap", "expensive", "rupees", "inr", "lakh", "k", "affordable"),
                  low_words=("cheap", "budget", "affordable", "value"),
                  high_words=("premium", "high end"),
                  typical=(30000.0, 350000.0), scale_hint="in rupees; '1.5 lakh' = 150000"),
        FacetSpec("ram", "RAM", "GB", "higher",
                  ("ram", "memory"), high_words=("more ram", "lots of ram"), typical=(8.0, 36.0)),
        FacetSpec("storage", "Storage", "GB", "higher",
                  ("storage", "ssd", "disk", "space"), typical=(256.0, 1024.0)),
        FacetSpec("screen", "Screen size", "in", "neutral",
                  ("screen", "display", "size", "inch", "inches", "big screen", "small"),
                  low_words=("compact", "small", "portable"),
                  high_words=("big screen", "large display"), typical=(13.0, 16.2)),
        FacetSpec("weight", "Weight", "kg", "lower",
                  ("weight", "heavy", "light", "portable", "carry", "kg", "kilos"),
                  low_words=("light", "lightweight", "portable", "thin", "carry"),
                  high_words=("heavy", "desktop replacement"), typical=(1.0, 2.9)),
        FacetSpec("battery", "Battery life", "hours", "higher",
                  ("battery", "battery life", "hours", "backup", "all day", "unplugged"),
                  high_words=("all day battery", "long battery"), typical=(5.0, 18.0)),
        FacetSpec("vram", "GPU memory", "GB", "higher",
                  ("gpu", "graphics", "vram", "nvidia", "rtx", "dedicated graphics", "video card"),
                  high_words=("dedicated gpu", "strong gpu"), typical=(0.0, 8.0)),
        FacetSpec("rating", "Rating", "/5", "higher",
                  ("rating", "score", "reviews", "well reviewed", "good"), typical=(3.7, 4.8)),
    )
    tag_facets: tuple[TagSpec, ...] = (
        TagSpec("brand", "Brand", ("brand", "make", "company", "manufacturer"),
                ("apple", "dell", "lenovo", "hp", "asus", "acer", "msi", "samsung",
                 "microsoft", "infinix")),
        TagSpec("os", "Operating system", ("os", "operating system", "windows", "macos", "linux", "chromeos"),
                ("windows 11", "macos", "chromeos", "windows 11 arm")),
        TagSpec("form", "Form factor", ("type", "form factor", "category", "kind"),
                ("ultrabook", "notebook", "gaming", "workstation", "2-in-1", "chromebook")),
        TagSpec("use_case", "Best for", ("for", "use case", "purpose", "good for", "usage", "work"),
                ("students", "programming", "gaming", "video editing", "ml", "office",
                 "business", "travel", "content creation", "browsing", "3d rendering",
                 "streaming", "writing", "everyday")),
        TagSpec("display", "Display", ("display type", "oled", "panel", "screen quality", "retina", "touch"),
                ("oled", "ips", "amoled", "retina", "touch", "tn")),
    )

    def parse(self, raw: Any) -> Iterable[Item]:
        for i, rec in enumerate(raw.get("laptops", [])):
            company = clean(rec.get("Company"))
            product = clean(rec.get("Product"))
            gpu = clean(rec.get("Gpu"))
            screen_res = clean(rec.get("ScreenResolution"))
            facets = {
                "price": num(rec.get("Price_inr")),
                "ram": num(rec.get("Ram")),                       # '16GB' -> 16
                "storage": _storage_gb(rec.get("Memory", "")),    # '1TB SSD' -> 1024
                "screen": num(rec.get("Inches")),
                "weight": num(rec.get("Weight")),                 # '1.24kg' -> 1.24
                "battery": num(rec.get("BatteryHours")),
                "vram": _vram_gb(gpu),
                "rating": num(rec.get("Rating")),
            }
            panel_tags = [
                w for w in ("oled", "ips", "amoled", "retina", "touch", "tn")
                if w in screen_res.lower()
            ]
            use_cases = split_list(rec.get("UseCase"), seps=",")

            display: list[tuple[str, str]] = [("Brand", company)]
            if facets["price"]:
                display.append(("Price", f"₹{int(facets['price']):,}"))
            display.append(("Type", clean(rec.get("TypeName"))))
            display.append(("CPU", clean(rec.get("Cpu"))))
            if facets["ram"] and facets["storage"]:
                stor = facets["storage"]
                stor_txt = f"{stor / 1024:g}TB" if stor >= 1024 else f"{int(stor)}GB"
                display.append(("Memory", f"{int(facets['ram'])}GB RAM / {stor_txt} SSD"))
            display.append(("GPU", gpu))
            if facets["screen"]:
                display.append(("Display", f'{facets["screen"]}" — {screen_res}'))
            if facets["weight"]:
                display.append(("Weight", f"{facets['weight']} kg"))
            if facets["battery"]:
                display.append(("Battery", f"~{int(facets['battery'])} hours"))
            display.append(("OS", clean(rec.get("OpSys"))))
            if rec.get("Ports"):
                display.append(("Ports", clean(rec["Ports"])))
            if use_cases:
                display.append(("Best for", ", ".join(use_cases)))

            yield Item(
                item_id=f"laptop:L{i + 1:03d}",
                domain=self.key,
                title=f"{company} {product}",
                subtitle=clean(rec.get("Cpu")),
                description=clean(rec.get("Notes")),
                facets={k: v for k, v in facets.items() if v is not None},
                tags={
                    "brand": [company.lower()],
                    "os": [clean(rec.get("OpSys")).lower()],
                    "form": [clean(rec.get("TypeName")).lower()],
                    "use_case": [u.lower() for u in use_cases],
                    "display": panel_tags,
                },
                display=display,
                rating=facets["rating"],
                popularity=(facets["rating"] or 4.0) * 20,
                synthetic=bool(rec.get("synthetic")),
            )
