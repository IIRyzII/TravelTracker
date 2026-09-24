"""Country lookup (Natural Earth) and the curated destination shortlists."""

import json
import os
import re

from .config import BASE_DIR

GEOJSON_PATH = os.path.join(BASE_DIR, "static", "data", "countries.geojson")
ACTIVITIES_PATH = os.path.join(BASE_DIR, "data", "activities.json")

# Natural Earth leaves ISO_A2 as -99 for a few countries
ISO2_FIX = {"FRA": "FR", "NOR": "NO", "CYN": "CY", "SOL": "SO"}


def _load_countries():
    with open(GEOJSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    by_code, by_name, by_iso2 = {}, {}, {}
    for feat in data["features"]:
        p = feat["properties"]
        code = p["ADM0_A3"]
        iso2 = p.get("ISO_A2")
        if not (isinstance(iso2, str) and re.fullmatch(r"[A-Z]{2}", iso2)):
            iso2 = ISO2_FIX.get(code)
        entry = {"code": code, "name": p["ADMIN"], "continent": p["CONTINENT"], "iso2": iso2}
        by_code[code] = entry
        if iso2:
            by_iso2[iso2] = entry
        for key in {p["ADMIN"], p["NAME"], p.get("NAME_LONG") or ""}:
            if key:
                by_name[key.lower()] = entry
    return by_code, by_name, by_iso2


COUNTRIES_BY_CODE, COUNTRIES_BY_NAME, COUNTRIES_BY_ISO2 = _load_countries()

with open(ACTIVITIES_PATH, encoding="utf-8") as f:
    ACTIVITIES = json.load(f)


def _norm(text):
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def find_country(text):
    """Match free text like 'Crete, Greece' to a country entry."""
    if not text:
        return None
    lowered = text.lower().strip()
    if lowered in COUNTRIES_BY_NAME:
        return COUNTRIES_BY_NAME[lowered]
    normed = _norm(text)
    words = set(normed.split())
    for name, entry in COUNTRIES_BY_NAME.items():
        if name in normed or _norm(name) in words:
            return entry
    return None
