"""Split the GeoNames places into two files the globe loads in stages.

    python scripts/split_cities.py

data/geonames-cities.json holds 137k places ([name, iso2, lat, lng, population],
sorted by population, from GeoNames — CC BY 4.0). Phones shouldn't download all
5 MB just to show cities, so:

  static/data/cities-1.json   population >= 15,000 — loaded at City zoom
  static/data/cities-2.json   everything smaller   — loaded at Town zoom (or
                                                     prefetched on good connections)

Bump DATA_VERSION in static/js/globe.js after regenerating.
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "data", "geonames-cities.json")
OUT = os.path.join(ROOT, "static", "data")
CITY_MIN_POP = 15_000


def main():
    with open(SOURCE, encoding="utf-8") as f:
        places = json.load(f)
    cities = [p for p in places if p[4] >= CITY_MIN_POP]
    towns = [p for p in places if p[4] < CITY_MIN_POP]
    for name, rows in (("cities-1.json", cities), ("cities-2.json", towns)):
        path = os.path.join(OUT, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
        print(f"{name}: {len(rows):,} places, {os.path.getsize(path) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
