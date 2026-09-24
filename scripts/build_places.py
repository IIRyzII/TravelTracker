"""Refresh the place list that ships with ORBIT (towns of 1,000+ people).

    python scripts/build_places.py

Optional: the server's own database of every place (orbit/placedb.py) already
gives search the regions and other-language names. This refreshes the bundled
list the globe draws its city and town labels from, and the search the app
falls back on before that database is built.

Downloads cities1000.zip and admin1CodesASCII.txt from download.geonames.org
(free, CC BY 4.0 — already credited in the app), then writes:

  data/geonames-cities.json   [name, iso2, lat, lng, population, region, [other names]]
                              — what city search runs on (orbit/places.py)
  static/data/cities-1.json   } the globe's city and town labels (name, iso2, lat,
  static/data/cities-2.json   } lng, population only), via split_cities.py

Names on the globe stay in plain letters because the globe's label font has no
accented characters ("Zurich" not "Zürich"); the accented and local-language
names ("Zürich", "München", "Firenze", "Lisboa") become search terms instead.
Commit the three files afterwards — the app picks up the new data by itself.
"""

import io
import json
import os
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from orbit.placedb import BIG, iter_places, read_regions  # noqa: E402
import split_cities  # noqa: E402

DUMP = "https://download.geonames.org/export/dump/"
SOURCE = os.path.join(ROOT, "data", "geonames-cities.json")


def download(name):
    print("downloading", name, "…", flush=True)
    req = urllib.request.Request(DUMP + name, headers={"User-Agent": "ORBIT place builder"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def parse_rows(city_lines, admin1_lines):
    """GeoNames text lines -> ORBIT rows (towns of 1,000+), biggest places first."""
    rows = [[name, iso2, round(lat, 3), round(lng, 3), pop, region, others]
            for _, name, iso2, lat, lng, pop, region, others
            in iter_places(city_lines, read_regions(admin1_lines), min_population=BIG)]
    rows.sort(key=lambda r: -r[4])
    return rows


def main():
    with zipfile.ZipFile(io.BytesIO(download("cities1000.zip"))) as z:
        cities = z.read("cities1000.txt").decode("utf-8").splitlines()
    admin1 = download("admin1CodesASCII.txt").decode("utf-8").splitlines()
    rows = parse_rows(cities, admin1)
    with open(SOURCE, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{os.path.relpath(SOURCE, ROOT)}: {len(rows):,} places, "
          f"{os.path.getsize(SOURCE) / 1e6:.1f} MB")
    split_cities.main()
    print("done — commit data/geonames-cities.json and static/data/cities-*.json")


if __name__ == "__main__":
    main()
