"""City and town search over the bundled GeoNames places — no outside service.

data/geonames-cities.json rows are [name, iso2, lat, lng, population] sorted by
population, optionally followed by [region, [other names…]] once enriched by
scripts/build_places.py. The globe's city labels come from the same file, so a
place found here has exactly the name its dot on the globe has.
"""

import json
import os
import re
import threading
import unicodedata

from .config import BASE_DIR
from .geo import COUNTRIES_BY_ISO2

SOURCE = os.path.join(BASE_DIR, "data", "geonames-cities.json")

# letters NFKD can't split into base + accent
_LETTERS = str.maketrans({"ß": "ss", "ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "œ": "oe",
                          "Œ": "oe", "ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "ı": "i", "þ": "th"})


def fold(text):
    """The form names are matched in: lower-case, no accents, forgiving of
    spelling variants — 'Zürich', 'Zuerich' and 'zurich' all become 'zurich',
    'St. Ives' and 'Saint Ives' both 'st ives'."""
    text = unicodedata.normalize("NFKD", text.translate(_LETTERS))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\b(saint|ste)\b", "st", text).strip()


class PlaceIndex:
    def __init__(self, rows):
        self.rows = rows
        self.names = []    # per row: the folded forms of every name it goes by
        self.prefix = {}   # first two letters of any word of any name -> row numbers
        for i, row in enumerate(rows):
            forms = {fold(n) for n in [row[0], *(row[6] if len(row) > 6 else [])]} - {""}
            self.names.append(forms)
            for key in {w[:2] for f in forms for w in f.split()}:
                self.prefix.setdefault(key, []).append(i)

    def search(self, query, limit=6):
        """Exact names first, then names starting with the query, then names with
        a word starting with it — each group biggest place first."""
        q = fold(query)
        if len(q) < 2:
            return []
        groups = ([], [], [])
        for i in self.prefix.get(q[:2], ()):
            forms = self.names[i]
            if q in forms:
                groups[0].append(i)
            elif any(f.startswith(q) for f in forms):
                groups[1].append(i)
            elif any((" " + f).find(" " + q) >= 0 for f in forms):
                groups[2].append(i)
        return [self._result(i) for i in (groups[0] + groups[1] + groups[2])[:limit]]

    def find(self, text):
        """Best single match for free text like 'Chania, Greece' (the part after
        the comma picks between same-named places by country or region)."""
        head, _, hint = text.partition(",")
        results = self.search(head, limit=25)
        hint = fold(hint)
        if hint:
            for r in results:
                if hint in {fold(r["country"] or ""), fold(r["admin"] or ""), r["iso2"].lower()}:
                    return r
        return results[0] if results else None

    def _result(self, i):
        row = self.rows[i]
        country = COUNTRIES_BY_ISO2.get(row[1])
        return {"name": row[0], "iso2": row[1], "lat": row[2], "lng": row[3], "pop": row[4],
                "admin": row[5] if len(row) > 5 and row[5] else None,
                "country": country["name"] if country else None}


_index = None
_lock = threading.Lock()


def index():
    """The shared index, built on first use (about a second)."""
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                with open(SOURCE, encoding="utf-8") as f:
                    _index = PlaceIndex(json.load(f))
    return _index
