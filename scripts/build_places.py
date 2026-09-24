"""Rebuild ORBIT's place data from GeoNames, with regions and other-language names.

    python scripts/build_places.py

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
import unicodedata
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from orbit.places import fold  # noqa: E402
import split_cities  # noqa: E402

DUMP = "https://download.geonames.org/export/dump/"
SOURCE = os.path.join(ROOT, "data", "geonames-cities.json")
MIN_POPULATION = 1000
SKIP_FEATURES = {"PPLH", "PPLQ", "PPLW", "PPLCH"}  # historical, abandoned, destroyed places
MAX_OTHER_NAMES = 12


def download(name):
    print("downloading", name, "…", flush=True)
    req = urllib.request.Request(DUMP + name, headers={"User-Agent": "ORBIT place builder"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def is_latin(text):
    """Letters are all Latin-script (so readable to ORBIT's users and searchable)."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(unicodedata.name(c, "").startswith("LATIN") for c in letters)


def other_names(main, utf8_name, alternates):
    """Useful extra search terms: the accented name plus Latin-script alternates,
    minus codes (NYC, ZRH), links and anything that folds to a name we have."""
    seen = {fold(main)}
    out = []
    for alt in [utf8_name, *alternates.split(",")]:
        alt = alt.strip()
        if not alt or len(alt) > 60 or "http" in alt or any(ch.isdigit() for ch in alt):
            continue
        if alt.isupper() and len(alt) <= 4:  # airport / abbreviation codes
            continue
        if not is_latin(alt):
            continue
        key = fold(alt)
        if key and key not in seen:
            seen.add(key)
            out.append(alt)
        if len(out) >= MAX_OTHER_NAMES:
            break
    return out


def parse_rows(city_lines, admin1_lines):
    """GeoNames text lines -> ORBIT rows, biggest places first."""
    regions = {}
    for line in admin1_lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3:
            regions[parts[0]] = parts[2] or parts[1]  # ASCII name, like the place names
    rows = []
    for line in city_lines:
        f = line.rstrip("\n").split("\t")
        if len(f) < 15 or f[7] in SKIP_FEATURES:
            continue
        population = int(f[14] or 0)
        if population < MIN_POPULATION:
            continue
        ascii_name = f[2] or f[1]
        rows.append([ascii_name, f[8], round(float(f[4]), 3), round(float(f[5]), 3), population,
                     regions.get(f"{f[8]}.{f[10]}"), other_names(ascii_name, f[1], f[3])])
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
