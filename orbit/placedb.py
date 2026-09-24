"""Every populated place in the world (GeoNames), in an SQLite file on the server.

Built once from GeoNames' full list (allCountries.zip, about 400 MB) by
`flask --app wsgi build-places`, or by itself on first start in production.
City search then finds every town, village and hamlet, and the globe asks it
for the villages around you at Town zoom. Until the file exists ORBIT uses the
bundled list of places with 1,000+ people (orbit/places.py).
"""

import io
import math
import os
import sqlite3
import threading
import unicodedata
import urllib.request
import zipfile

import click
from flask import current_app

from .geo import COUNTRIES_BY_ISO2
from .places import fold, index

DUMP = "https://download.geonames.org/export/dump/"
SKIP_FEATURES = {"PPLH", "PPLQ", "PPLW", "PPLCH", "PPLX"}  # historical/abandoned places, city districts
BIG = 1000             # places this size ship with the app; smaller ones are "villages"
MAX_OTHER_NAMES = 12   # extra search names kept per place (towns of BIG+ only)
# the globe's village layer keeps the biggest village in each grid cell, at three
# cell sizes (degrees) so any zoom gets roughly one village per label spacing
VILLAGE_LEVELS = {1: 0.4, 2: 0.2, 3: 0.1}

SCHEMA = """
CREATE TABLE places(id INTEGER PRIMARY KEY, name TEXT NOT NULL, iso2 TEXT NOT NULL,
                    lat REAL NOT NULL, lng REAL NOT NULL, pop INTEGER NOT NULL, admin TEXT);
CREATE TABLE names_load(key TEXT NOT NULL, kind INTEGER NOT NULL, pop INTEGER NOT NULL,
                        place INTEGER NOT NULL);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""


# ------------------------------------------------------------------ parsing

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


def read_regions(admin1_lines):
    regions = {}
    for line in admin1_lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3:
            regions[parts[0]] = parts[2] or parts[1]  # ASCII name, like the place names
    return regions


def iter_places(lines, regions, min_population=0):
    """GeoNames dump lines -> (id, name, iso2, lat, lng, population, region, other names).

    Names are GeoNames' plain-letter "asciiname": the globe's label font has no
    accents, and it matches the names in the bundled data."""
    for line in lines:
        f = line.rstrip("\n").split("\t")
        if len(f) < 15 or f[6] != "P" or f[7] in SKIP_FEATURES:
            continue
        population = int(f[14] or 0)
        name = f[2] or f[1]
        if population < min_population or not name or not f[8]:
            continue
        others = other_names(name, f[1], f[3]) if population >= BIG else \
            [f[1]] if fold(f[1]) != fold(name) else []
        yield (int(f[0]), name, f[8], round(float(f[4]), 4), round(float(f[5]), 4), population,
               regions.get(f"{f[8]}.{f[10]}"), others)


# ----------------------------------------------------------------- building

def build_database(path, lines, regions, log=print):
    """Write the places database to `path` (built beside it, then swapped in)."""
    tmp = path + ".building"
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE;" + SCHEMA)
    places, names, count = [], [], 0

    def flush():
        db.executemany("INSERT OR IGNORE INTO places VALUES(?,?,?,?,?,?,?)", places)
        db.executemany("INSERT INTO names_load VALUES(?,?,?,?)", names)
        places.clear()
        names.clear()

    for pid, name, iso2, lat, lng, pop, region, others in iter_places(lines, regions):
        places.append((pid, name, iso2, lat, lng, pop, region))
        forms = []
        for n in (name, *others):
            f = fold(n)
            if f and f not in forms:
                forms.append(f)
        for f in forms:
            names.append((f, 0, pop, pid))                       # the whole name
            words = f.split(" ")
            for i in range(1, len(words)):
                names.append((" ".join(words[i:]), 1, pop, pid))  # from a later word on
        count += 1
        if len(places) >= 50_000:
            flush()
            if count % 500_000 < 50_000:
                log(f"  {count:,} places read")
    flush()
    log(f"  {count:,} places — indexing names")

    # search tables, written in key order so the B-trees fill sequentially.
    # Towns get their own small table: short searches only need to look there.
    for table, where in (("names", ""), ("names_big", f"WHERE pop >= {BIG}")):
        db.execute(f"CREATE TABLE {table}(key TEXT NOT NULL, kind INTEGER NOT NULL, pop INTEGER NOT NULL, "
                   "place INTEGER NOT NULL, PRIMARY KEY(key, kind, pop, place)) WITHOUT ROWID")
        db.execute(f"INSERT OR IGNORE INTO {table} SELECT key, kind, pop, place FROM names_load {where} "
                   "ORDER BY key, kind, pop, place")
    db.execute("DROP TABLE names_load")

    log("  building the village layer")
    db.execute("CREATE TABLE villages(level INTEGER NOT NULL, row INTEGER NOT NULL, col INTEGER NOT NULL, "
               "place INTEGER NOT NULL, PRIMARY KEY(level, row, col)) WITHOUT ROWID")
    for level, size in VILLAGE_LEVELS.items():
        db.execute(f"""
            INSERT INTO villages
            SELECT {level}, r, c, id FROM (
                SELECT CAST((lat + 90) / {size} AS INTEGER) AS r, CAST((lng + 180) / {size} AS INTEGER) AS c,
                       id, ROW_NUMBER() OVER (
                           PARTITION BY CAST((lat + 90) / {size} AS INTEGER), CAST((lng + 180) / {size} AS INTEGER)
                           ORDER BY pop DESC, id) AS rn
                FROM places WHERE pop < {BIG})
            WHERE rn = 1 ORDER BY r, c""")
    db.execute("INSERT INTO meta VALUES('places', ?)", (str(count),))
    db.commit()
    db.execute("VACUUM")
    db.close()
    os.replace(tmp, path)
    log(f"  done: {os.path.getsize(path) / 1e6:.0f} MB")
    return count


def download(name, dest_dir):
    """Download a GeoNames dump file to disk (the full list is ~400 MB)."""
    dest = os.path.join(dest_dir, name)
    part = dest + ".part"
    req = urllib.request.Request(DUMP + name, headers={"User-Agent": "ORBIT place builder"})
    with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(part, dest)
    return dest


def build_from_geonames(path, log=print):
    """Download GeoNames' full list and build the places database at `path`."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    log("downloading GeoNames regions…")
    admin1 = download("admin1CodesASCII.txt", folder)
    with open(admin1, encoding="utf-8") as f:
        regions = read_regions(f)
    log("downloading GeoNames' full place list (~400 MB)…")
    archive = download("allCountries.zip", folder)
    try:
        with zipfile.ZipFile(archive) as z, z.open("allCountries.txt") as raw:
            return build_database(path, io.TextIOWrapper(raw, encoding="utf-8"), regions, log)
    finally:
        for leftover in (archive, admin1):
            if os.path.exists(leftover):
                os.remove(leftover)


_building = threading.Lock()


def build_in_background(app):
    """Production: build the database on first start if it isn't there yet."""
    path = app.config["PLACES_DB_PATH"]
    if os.path.exists(path) or not _building.acquire(blocking=False):
        return

    def job():
        try:
            build_from_geonames(path, log=lambda msg: app.logger.info("places: %s", msg))
        except Exception:
            app.logger.exception("Building the places database failed; will retry on next start")
        finally:
            _building.release()

    threading.Thread(target=job, daemon=True).start()


@click.command("build-places")
def build_places_command():
    """Download GeoNames' full place list and build the places database."""
    build_from_geonames(current_app.config["PLACES_DB_PATH"], log=click.echo)


# ----------------------------------------------------------------- querying

class PlaceDatabase:
    """Search and village lookups on a built places database (read-only)."""

    def __init__(self, path):
        self.path = path
        self._local = threading.local()

    def _db(self):
        db = getattr(self._local, "db", None)
        if db is None:
            db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
            db.row_factory = sqlite3.Row
            self._local.db = db
        return db

    def _places(self, ids):
        if not ids:
            return []
        rows = {r["id"]: r for r in self._db().execute(
            f"SELECT * FROM places WHERE id IN ({','.join('?' * len(ids))})", ids)}
        return [rows[i] for i in ids if i in rows]

    def search(self, query, limit=6):
        """Exact names first, then towns starting with the query, then any place
        starting with it — each group biggest place first."""
        q = fold(query)
        if len(q) < 2:
            return []
        db, hi = self._db(), q + "~"   # '~' sorts after every folded character
        ids = []

        def add(rows):
            for (place,) in rows:
                if place not in ids:
                    ids.append(place)

        add(db.execute("SELECT place FROM names WHERE key = ? AND kind = 0 "
                       "ORDER BY pop DESC LIMIT ?", (q, limit)))
        if len(ids) < limit:
            add(db.execute("SELECT place FROM names_big WHERE key > ? AND key < ? "
                           "GROUP BY place ORDER BY MIN(kind), MAX(pop) DESC LIMIT ?", (q, hi, limit * 2)))
        if len(ids) < limit and len(q) >= 3:
            # villages: bounded scan, so short common prefixes stay fast
            rows = db.execute("SELECT place, kind, pop FROM names WHERE key > ? AND key < ? "
                              "LIMIT 2000", (q, hi)).fetchall()
            rows.sort(key=lambda r: (r["kind"], -r["pop"]))
            add((r["place"],) for r in rows)
        return [self._result(r) for r in self._places(ids[:limit])]

    def villages_near(self, lat, lng, radius, limit=400):
        """The biggest villages (under 1,000 people) around a point, at most about
        one per label spacing — what the globe shows at Town zoom."""
        # the finest grid whose cells are at least half the label spacing at this zoom
        want = radius * 0.03
        level, size = next(((lv, s) for lv, s in sorted(VILLAGE_LEVELS.items(), key=lambda kv: kv[1])
                            if s >= want), (1, VILLAGE_LEVELS[1]))
        cos_lat = max(math.cos(math.radians(lat)), 0.05)
        span = radius / cos_lat
        rows = (max(0, int((lat - radius + 90) // size)), int((lat + radius + 90) // size))
        cols = round(360 / size)
        c0, c1 = int((lng - span + 180) // size), int((lng + span + 180) // size)
        if c1 - c0 >= cols - 1:
            ranges = [(0, cols - 1)]
        elif c0 < 0:
            ranges = [(c0 + cols, cols - 1), (0, c1)]
        elif c1 >= cols:
            ranges = [(c0, cols - 1), (0, c1 - cols)]
        else:
            ranges = [(c0, c1)]
        ids = []
        for lo, hi in ranges:
            ids += [r[0] for r in self._db().execute(
                "SELECT place FROM villages WHERE level = ? AND row BETWEEN ? AND ? AND col BETWEEN ? AND ?",
                (level, rows[0], rows[1], lo, hi))]
        out = []
        for chunk in range(0, len(ids), 900):
            for p in self._places(ids[chunk:chunk + 900]):
                d_lng = abs(p["lng"] - lng)
                d_lng = 360 - d_lng if d_lng > 180 else d_lng
                d = ((p["lat"] - lat) ** 2 + (d_lng * cos_lat) ** 2) ** 0.5
                if d <= radius:
                    out.append((-p["pop"], d, p))
        out.sort(key=lambda t: (t[0], t[1]))
        return [{"name": p["name"], "iso2": p["iso2"], "lat": p["lat"], "lng": p["lng"], "pop": p["pop"]}
                for _, _, p in out[:limit]]

    def find(self, text):
        head, _, hint = text.partition(",")
        results = self.search(head, limit=25)
        hint = fold(hint)
        if hint:
            for r in results:
                if hint in {fold(r["country"] or ""), fold(r["admin"] or ""), r["iso2"].lower()}:
                    return r
        return results[0] if results else None

    @staticmethod
    def _result(row):
        country = COUNTRIES_BY_ISO2.get(row["iso2"])
        return {"name": row["name"], "iso2": row["iso2"], "lat": row["lat"], "lng": row["lng"],
                "pop": row["pop"], "admin": row["admin"], "country": country["name"] if country else None}


_open = {}


def database():
    """The places database, once it's been built (None until then)."""
    path = current_app.config["PLACES_DB_PATH"]
    if path not in _open and os.path.exists(path):
        _open[path] = PlaceDatabase(path)
    return _open.get(path)


def searcher():
    """What city search runs on: every place once the database exists, the
    bundled 1,000+ list until then."""
    return database() or index()
