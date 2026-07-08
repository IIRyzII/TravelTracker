"""ORBIT - travel tracker.

Flask backend: profiles, visited countries, wishlist, friends (share codes),
and a trip-planner that serves curated activity shortlists.

Run:  python app.py   ->  http://127.0.0.1:5000
"""

import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import Flask, g, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "traveltracker.db")
LEGACY_DB = os.path.join(BASE_DIR, "Visited_Places.DB")
GEOJSON_PATH = os.path.join(BASE_DIR, "static", "data", "countries.geojson")
ACTIVITIES_PATH = os.path.join(BASE_DIR, "data", "activities.json")

app = Flask(__name__, static_folder="static", static_url_path="/static")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE COLLATE NOCASE NOT NULL,
    share_code TEXT UNIQUE NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS visited(
    user_id INTEGER NOT NULL REFERENCES users(id),
    country_code TEXT NOT NULL,
    country_name TEXT NOT NULL,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, country_code)
);
CREATE TABLE IF NOT EXISTS wishlist(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    place TEXT NOT NULL,
    country_code TEXT,
    country_name TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS friends(
    user_id INTEGER NOT NULL REFERENCES users(id),
    friend_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY(user_id, friend_id)
);
CREATE TABLE IF NOT EXISTS trips(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    destination TEXT NOT NULL,
    country TEXT,
    tagline TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS trip_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    category TEXT,
    title TEXT NOT NULL,
    detail TEXT,
    rating REAL,
    rating_count INTEGER,
    address TEXT,
    maps_url TEXT,
    done INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS visited_cities(
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    iso2 TEXT NOT NULL DEFAULT '',
    lat REAL,
    lng REAL,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, name, iso2)
);
CREATE TABLE IF NOT EXISTS trip_members(
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY(trip_id, user_id)
);
CREATE TABLE IF NOT EXISTS trip_votes(
    item_id INTEGER NOT NULL REFERENCES trip_items(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY(item_id, user_id)
);
"""

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_google_key():
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key and os.path.exists(CONFIG_PATH):
        try:
            # utf-8-sig: tolerate the BOM that Notepad/PowerShell often write
            with open(CONFIG_PATH, encoding="utf-8-sig") as f:
                key = (json.load(f).get("google_maps_api_key") or "").strip()
        except (OSError, ValueError):
            pass
    return key or None


GOOGLE_KEY = load_google_key()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------- countries

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


# ------------------------------------------------------------------- users

def new_share_code(db):
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if not db.execute("SELECT 1 FROM users WHERE share_code=?", (code,)).fetchone():
            return code


def import_legacy(db, user_id):
    """Pull countries out of the original Visited_Places.DB into a new profile."""
    if not os.path.exists(LEGACY_DB):
        return 0
    try:
        legacy = sqlite3.connect(LEGACY_DB)
        rows = legacy.execute("SELECT Location_name FROM visited_countries").fetchall()
        legacy.close()
    except sqlite3.Error:
        return 0
    imported = 0
    for (name,) in rows:
        entry = find_country(name)
        if entry:
            db.execute(
                "INSERT OR IGNORE INTO visited(user_id, country_code, country_name) VALUES(?,?,?)",
                (user_id, entry["code"], entry["name"]),
            )
            imported += 1
    return imported


def user_payload(db, user):
    visited = [
        dict(r)
        for r in db.execute(
            "SELECT country_code AS code, country_name AS name FROM visited "
            "WHERE user_id=? ORDER BY country_name",
            (user["id"],),
        )
    ]
    wishlist = [
        dict(r)
        for r in db.execute(
            "SELECT id, place, country_code AS code, country_name AS country "
            "FROM wishlist WHERE user_id=? ORDER BY id DESC",
            (user["id"],),
        )
    ]
    visited_cities = [
        dict(r)
        for r in db.execute(
            "SELECT name, iso2, lat, lng FROM visited_cities WHERE user_id=? ORDER BY name",
            (user["id"],),
        )
    ]
    friends = []
    for r in db.execute(
        "SELECT u.id, u.username, u.share_code FROM friends f "
        "JOIN users u ON u.id=f.friend_id WHERE f.user_id=? ORDER BY u.username",
        (user["id"],),
    ):
        codes = {
            row["country_code"]
            for row in db.execute("SELECT country_code FROM visited WHERE user_id=?", (r["id"],))
        }
        mine = {v["code"] for v in visited}
        friends.append(
            {
                "id": r["id"],
                "username": r["username"],
                "visited_count": len(codes),
                "overlap": len(codes & mine),
            }
        )
    trips = []
    trip_rows = db.execute(
        "SELECT DISTINCT t.*, u.username AS owner_name FROM trips t "
        "JOIN users u ON u.id = t.user_id "
        "LEFT JOIN trip_members m ON m.trip_id = t.id "
        "WHERE t.user_id=? OR m.user_id=? ORDER BY t.id DESC",
        (user["id"], user["id"]),
    ).fetchall()
    for t in trip_rows:
        counts = db.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(done),0) d FROM trip_items WHERE trip_id=?",
            (t["id"],),
        ).fetchone()
        members = [r["username"] for r in db.execute(
            "SELECT u.username FROM trip_members m JOIN users u ON u.id=m.user_id "
            "WHERE m.trip_id=? ORDER BY u.username", (t["id"],))]
        trips.append({
            "id": t["id"], "destination": t["destination"], "country": t["country"],
            "created_at": t["created_at"], "flight_number": t["flight_number"],
            "start_date": t["start_date"], "end_date": t["end_date"],
            "item_count": counts["c"], "done_count": counts["d"],
            "owner": t["owner_name"], "is_owner": t["user_id"] == user["id"],
            "members": members,
        })
    return {
        "id": user["id"],
        "username": user["username"],
        "share_code": user["share_code"],
        "visited": visited,
        "visited_cities": visited_cities,
        "wishlist": wishlist,
        "friends": friends,
        "trips": trips,
        "live_places": bool(GOOGLE_KEY),
    }


def require_user(db):
    user_id = request.args.get("user_id") or (request.get_json(silent=True) or {}).get("user_id")
    if not user_id:
        return None
    return db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


# --------------------------------------------------------------------- api

@app.post("/api/profile")
def create_profile():
    body = request.get_json(force=True)
    username = (body.get("username") or "").strip()[:24]
    if not username:
        return jsonify(error="Please enter a name."), 400
    db = get_db()
    existing = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if existing:
        return jsonify(user_payload(db, existing))
    first_user = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0
    cur = db.execute(
        "INSERT INTO users(username, share_code) VALUES(?,?)",
        (username, new_share_code(db)),
    )
    user = db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
    if first_user:
        import_legacy(db, user["id"])
    db.commit()
    return jsonify(user_payload(db, user))


@app.get("/api/state")
def state():
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    return jsonify(user_payload(db, user))


@app.post("/api/visited")
def add_visited():
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    body = request.get_json(force=True)
    code = body.get("code")
    entry = COUNTRIES_BY_CODE.get(code)
    if not entry:
        return jsonify(error="Unknown country."), 400
    db.execute(
        "INSERT OR IGNORE INTO visited(user_id, country_code, country_name) VALUES(?,?,?)",
        (user["id"], entry["code"], entry["name"]),
    )
    # visiting a place also clears it from the wishlist
    db.execute(
        "DELETE FROM wishlist WHERE user_id=? AND country_code=? AND place=country_name",
        (user["id"], entry["code"]),
    )
    db.commit()
    return jsonify(user_payload(db, user))


@app.delete("/api/visited")
def remove_visited():
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    code = (request.get_json(force=True)).get("code")
    db.execute("DELETE FROM visited WHERE user_id=? AND country_code=?", (user["id"], code))
    # a visited city implies its country, so un-visiting the country clears its cities
    entry = COUNTRIES_BY_CODE.get(code)
    if entry and entry.get("iso2"):
        db.execute("DELETE FROM visited_cities WHERE user_id=? AND iso2=?",
                   (user["id"], entry["iso2"]))
    db.commit()
    return jsonify(user_payload(db, user))


@app.post("/api/visited_city")
def add_visited_city():
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()[:80]
    iso2 = (body.get("iso2") or "").strip().upper()[:2]
    if not name:
        return jsonify(error="Unknown place."), 400
    db.execute(
        "INSERT OR IGNORE INTO visited_cities(user_id, name, iso2, lat, lng) VALUES(?,?,?,?,?)",
        (user["id"], name, iso2, body.get("lat"), body.get("lng")),
    )
    # setting foot in a city means you've been to the country too
    country = COUNTRIES_BY_ISO2.get(iso2)
    if country:
        db.execute(
            "INSERT OR IGNORE INTO visited(user_id, country_code, country_name) VALUES(?,?,?)",
            (user["id"], country["code"], country["name"]),
        )
    db.commit()
    return jsonify(user_payload(db, user))


@app.delete("/api/visited_city")
def remove_visited_city():
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    body = request.get_json(force=True)
    db.execute(
        "DELETE FROM visited_cities WHERE user_id=? AND name=? AND iso2=?",
        (user["id"], (body.get("name") or "").strip(),
         (body.get("iso2") or "").strip().upper()),
    )
    db.commit()
    return jsonify(user_payload(db, user))


@app.post("/api/wishlist")
def add_wishlist():
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    body = request.get_json(force=True)
    place = (body.get("place") or "").strip()[:80]
    if not place:
        return jsonify(error="Please enter a place."), 400
    entry = COUNTRIES_BY_CODE.get(body.get("code")) or find_country(place)
    dupe = db.execute(
        "SELECT 1 FROM wishlist WHERE user_id=? AND lower(place)=lower(?)",
        (user["id"], place),
    ).fetchone()
    if not dupe:
        db.execute(
            "INSERT INTO wishlist(user_id, place, country_code, country_name) VALUES(?,?,?,?)",
            (user["id"], place, entry["code"] if entry else None, entry["name"] if entry else None),
        )
        db.commit()
    return jsonify(user_payload(db, user))


@app.delete("/api/wishlist/<int:item_id>")
def remove_wishlist(item_id):
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    db.execute("DELETE FROM wishlist WHERE id=? AND user_id=?", (item_id, user["id"]))
    db.commit()
    return jsonify(user_payload(db, user))


@app.post("/api/friends")
def add_friend():
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    code = ((request.get_json(force=True)).get("share_code") or "").strip().upper()
    friend = db.execute("SELECT * FROM users WHERE share_code=?", (code,)).fetchone()
    if not friend:
        return jsonify(error="No traveller found with that code."), 404
    if friend["id"] == user["id"]:
        return jsonify(error="That's your own code!"), 400
    db.execute("INSERT OR IGNORE INTO friends VALUES(?,?)", (user["id"], friend["id"]))
    db.execute("INSERT OR IGNORE INTO friends VALUES(?,?)", (friend["id"], user["id"]))
    db.commit()
    return jsonify(user_payload(db, user))


@app.delete("/api/friends/<int:friend_id>")
def remove_friend(friend_id):
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    db.execute(
        "DELETE FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)",
        (user["id"], friend_id, friend_id, user["id"]),
    )
    db.commit()
    return jsonify(user_payload(db, user))


@app.get("/api/compare/<int:friend_id>")
def compare(friend_id):
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    link = db.execute(
        "SELECT 1 FROM friends WHERE user_id=? AND friend_id=?", (user["id"], friend_id)
    ).fetchone()
    if not link:
        return jsonify(error="Not friends with that traveller."), 403
    friend = db.execute("SELECT * FROM users WHERE id=?", (friend_id,)).fetchone()
    visited = [
        dict(r)
        for r in db.execute(
            "SELECT country_code AS code, country_name AS name FROM visited "
            "WHERE user_id=? ORDER BY country_name",
            (friend_id,),
        )
    ]
    return jsonify(id=friend["id"], username=friend["username"], visited=visited)


# ---------------------------------------------------------------- planner

GENERIC_PLAN = [
    ("Must-see", "Historic core", "Walk the old town first - the landmarks, main square and viewpoints of {place} cluster there."),
    ("Must-see", "Signature landmark", "Look up the one sight {place} is famous for and book a timed ticket to skip the queue."),
    ("Activity", "Free walking tour", "A local-guided walking tour on day one makes the rest of a {place} trip make sense."),
    ("Activity", "Day trip out", "Set aside a day for the countryside, coast or nearest national park outside {place}."),
    ("Food & drink", "Market lunch", "Find the central food market - the cheapest way to eat like a local in {place}."),
    ("Food & drink", "One proper dinner", "Book one standout local-cuisine restaurant; ask hosts what {place} does best."),
    ("Night out", "Old-town bar crawl", "Start where the locals are at sunset and follow the noise - {place}'s bar streets find you."),
    ("Night out", "Evening viewpoint", "End one night at a rooftop or lookout over {place} after dark."),
]

CATEGORY_QUERIES = [
    ("Must-see", "top tourist attractions in {}"),
    ("Activity", "best things to do in {}"),
    ("Food & drink", "best restaurants in {}"),
    ("Night out", "best bars and nightlife in {}"),
]

_places_cache = {}  # dest.lower() -> (timestamp, items)
PLACES_TTL = 6 * 3600


def maps_search_url(query):
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)


_geo_cache = {}


def geocode_place(place):
    """Rough centre for a free-text place via the Open-Meteo geocoder (cached)."""
    key = place.lower()
    if key in _geo_cache:
        return _geo_cache[key]
    first = place.split(",")[0].strip()
    hint = place.split(",")[-1].strip().lower() if "," in place else None
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": first, "count": 10, "language": "en", "format": "json"})
    results = []
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            results = json.load(r).get("results") or []
    except (urllib.error.URLError, OSError, ValueError):
        pass
    pick = None
    if hint:  # "Chania, Greece" -> prefer the match whose country is Greece
        for res in results:
            if hint in {(res.get("country") or "").lower(), (res.get("admin1") or "").lower()}:
                pick = res
                break
    if not pick and results:
        pick = results[0]
    _geo_cache[key] = (pick["latitude"], pick["longitude"]) if pick else None
    return _geo_cache[key]


def places_text_search(query, bias=None, limit=10):
    payload = {"textQuery": query, "maxResultCount": limit}
    if bias:
        payload["locationBias"] = bias
    req = urllib.request.Request(
        "https://places.googleapis.com/v1/places:searchText",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_KEY,
            "X-Goog-FieldMask": "places.displayName,places.rating,"
                                "places.userRatingCount,places.formattedAddress,"
                                "places.googleMapsUri,places.regularOpeningHours",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.load(r).get("places", [])


def parse_open_days(place):
    """7-char bitmask, index 0 = Sunday, '1' = open at some point that day."""
    hours = place.get("regularOpeningHours")
    if not hours:
        return None
    periods = hours.get("periods") or []
    if not periods:
        return None
    days = ["0"] * 7
    for p in periods:
        o = p.get("open") or {}
        day = o.get("day")
        if day is None:
            continue
        # open 24/7 comes back as a single dayless-close period
        if p.get("close") is None and not o.get("hour"):
            return "1111111"
        if 0 <= day <= 6:
            days[day] = "1"
    return "".join(days)


def live_itinerary(dest_label, bias=None):
    """Top-rated real places from Google Maps, per category. None on any failure."""
    key = dest_label.lower() + "|" + (json.dumps(bias, sort_keys=True) if bias else "")
    cached = _places_cache.get(key)
    if cached and time.time() - cached[0] < PLACES_TTL:
        return cached[1]
    items, seen = [], set()
    for category, query in CATEGORY_QUERIES:
        try:
            places = places_text_search(query.format(dest_label), bias)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            app.logger.warning("Places lookup failed (%s): %s", category, exc)
            return None
        # best first: rating, backed by enough reviews to be trustworthy
        ranked = sorted(
            places,
            key=lambda p: (-(p.get("rating") or 0), -(p.get("userRatingCount") or 0)),
        )
        solid = [p for p in ranked if (p.get("userRatingCount") or 0) >= 100] or ranked
        added = 0
        for p in solid:
            name = (p.get("displayName") or {}).get("text")
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            items.append({
                "category": category,
                "title": name,
                "desc": p.get("formattedAddress") or "",
                "rating": p.get("rating"),
                "rating_count": p.get("userRatingCount"),
                "maps_url": p.get("googleMapsUri") or maps_search_url(f"{name} {dest_label}"),
                "open_days": parse_open_days(p),
            })
            added += 1
            if added >= 6:
                break
    if not items:
        return None
    _places_cache[key] = (time.time(), items)
    return items


def match_curated(place):
    normed = _norm(place)
    words = set(normed.split())
    for dest in ACTIVITIES:
        for alias in dest["names"]:
            a = _norm(alias)
            if a in normed or a in words or normed in a:
                return dest
    return None


@app.get("/api/itinerary")
def itinerary():
    place = (request.args.get("place") or "").strip()
    if not place:
        return jsonify(error="No place given."), 400
    try:
        center = (float(request.args["lat"]), float(request.args["lng"]))
    except (KeyError, ValueError):
        center = None
    try:
        radius_km = max(0, min(int(request.args.get("radius_km", 15)), 50))
    except ValueError:
        radius_km = 15
    curated = match_curated(place)
    country = find_country(place)
    label = curated["destination"] if curated else (country["name"] if country else place.title())
    # planning a whole country -> a tight radius makes no sense, search the lot
    is_whole_country = bool(country) and _norm(place) == _norm(country["name"])

    if GOOGLE_KEY:
        if center is None and radius_km and not is_whole_country:
            center = geocode_place(place)
        bias = None
        if center and radius_km and not is_whole_country:
            bias = {"circle": {"center": {"latitude": center[0], "longitude": center[1]},
                               "radius": radius_km * 1000}}
        live = live_itinerary(place, bias)
        if live:
            return jsonify(
                destination=place if bias else label,
                country=curated["country"] if curated else (country["name"] if country else None),
                tagline=curated["tagline"] if curated
                        else "Top-rated right now, pulled live from Google Maps.",
                curated=False, live=True, radius_km=radius_km if bias else None, items=live,
            )

    if curated:
        items = [
            {**item, "maps_url": maps_search_url(f"{item['title']} {curated['destination']}")}
            for item in curated["items"]
        ]
        return jsonify(destination=curated["destination"], country=curated["country"],
                       tagline=curated["tagline"], curated=True, live=False, items=items)

    items = [
        {"category": cat, "title": title, "desc": desc.format(place=label),
         "maps_url": maps_search_url(f"{title} {label}")}
        for cat, title, desc in GENERIC_PLAN
    ]
    return jsonify(destination=label, country=country["name"] if country else None,
                   tagline="A starter shortlist - swap these for the real thing as you research.",
                   curated=False, live=False, items=items)


@app.get("/api/cities")
def cities():
    """City lookup via the free Open-Meteo geocoder (no key needed)."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": q, "count": 6, "language": "en", "format": "json"})
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        return jsonify([])
    return jsonify([
        {
            "name": res.get("name"),
            "country": res.get("country"),
            "iso2": (res.get("country_code") or "").upper(),
            "admin": res.get("admin1"),
            "lat": res.get("latitude"),
            "lng": res.get("longitude"),
        }
        for res in data.get("results", [])
        if res.get("latitude") is not None
    ])


# ------------------------------------------------------------------- trips

@app.post("/api/trips")
def save_trip():
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    body = request.get_json(force=True)
    destination = (body.get("destination") or "").strip()[:80]
    items = body.get("items") or []
    if not destination or not items:
        return jsonify(error="Pick at least one thing to do first."), 400
    cur = db.execute(
        "INSERT INTO trips(user_id, destination, country, tagline, flight_number, start_date, end_date) "
        "VALUES(?,?,?,?,?,?,?)",
        (user["id"], destination, body.get("country"), body.get("tagline"),
         clean_flight(body.get("flight_number")), clean_date(body.get("start_date")),
         clean_date(body.get("end_date"))),
    )
    trip_id = cur.lastrowid
    for fid in set(body.get("invite_ids") or []):
        is_friend = db.execute(
            "SELECT 1 FROM friends WHERE user_id=? AND friend_id=?", (user["id"], fid)
        ).fetchone()
        if is_friend:
            db.execute("INSERT OR IGNORE INTO trip_members VALUES(?,?)", (trip_id, fid))
    for it in items[:60]:
        db.execute(
            "INSERT INTO trip_items(trip_id, category, title, detail, rating, rating_count, address, maps_url, open_days) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (trip_id, it.get("category"), (it.get("title") or "")[:120],
             (it.get("desc") or "")[:300], it.get("rating"), it.get("rating_count"),
             (it.get("address") or "")[:200], it.get("maps_url"), it.get("open_days")),
        )
    db.commit()
    payload = user_payload(db, user)
    payload["saved_trip_id"] = trip_id
    return jsonify(payload)


def clean_flight(value):
    value = (value or "").strip().upper().replace(" ", "")[:8]
    return value or None


def clean_date(value):
    value = (value or "").strip()[:10]
    return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None


def trip_payload(db, trip, user):
    items = [dict(r) for r in db.execute(
        "SELECT i.id, i.category, i.title, i.detail, i.rating, i.rating_count, "
        "i.address, i.maps_url, i.open_days, i.done, "
        "(SELECT COUNT(*) FROM trip_votes v WHERE v.item_id=i.id) AS votes, "
        "EXISTS(SELECT 1 FROM trip_votes v WHERE v.item_id=i.id AND v.user_id=?) AS my_vote "
        "FROM trip_items i WHERE i.trip_id=? ORDER BY i.id", (user["id"], trip["id"]))]
    owner = db.execute("SELECT id, username FROM users WHERE id=?", (trip["user_id"],)).fetchone()
    members = [dict(r) for r in db.execute(
        "SELECT u.id, u.username FROM trip_members m JOIN users u ON u.id=m.user_id "
        "WHERE m.trip_id=? ORDER BY u.username", (trip["id"],))]
    return {"id": trip["id"], "destination": trip["destination"], "country": trip["country"],
            "tagline": trip["tagline"], "created_at": trip["created_at"],
            "flight_number": trip["flight_number"], "start_date": trip["start_date"],
            "end_date": trip["end_date"], "items": items,
            "owner": dict(owner), "members": members,
            "is_owner": trip["user_id"] == user["id"]}


def owned_trip(db, user, trip_id):
    return db.execute("SELECT * FROM trips WHERE id=? AND user_id=?",
                      (trip_id, user["id"])).fetchone()


def accessible_trip(db, user, trip_id):
    """The trip, if the user owns it or was invited to it."""
    return db.execute(
        "SELECT t.* FROM trips t LEFT JOIN trip_members m ON m.trip_id=t.id AND m.user_id=? "
        "WHERE t.id=? AND (t.user_id=? OR m.user_id IS NOT NULL)",
        (user["id"], trip_id, user["id"])).fetchone()


@app.get("/api/trips/<int:trip_id>")
def get_trip(trip_id):
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    trip = accessible_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Trip not found."), 404
    return jsonify(trip_payload(db, trip, user))


@app.delete("/api/trips/<int:trip_id>")
def delete_trip(trip_id):
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    if owned_trip(db, user, trip_id):
        db.execute("DELETE FROM trip_votes WHERE item_id IN (SELECT id FROM trip_items WHERE trip_id=?)",
                   (trip_id,))
        db.execute("DELETE FROM trip_members WHERE trip_id=?", (trip_id,))
        db.execute("DELETE FROM trip_items WHERE trip_id=?", (trip_id,))
        db.execute("DELETE FROM trips WHERE id=?", (trip_id,))
        db.commit()
    return jsonify(user_payload(db, user))


@app.post("/api/trips/<int:trip_id>/members")
def invite_member(trip_id):
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    trip = owned_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Only the trip owner can invite people."), 403
    friend_id = (request.get_json(force=True)).get("friend_id")
    is_friend = db.execute(
        "SELECT 1 FROM friends WHERE user_id=? AND friend_id=?", (user["id"], friend_id)
    ).fetchone()
    if not is_friend:
        return jsonify(error="You can only invite your friends."), 400
    db.execute("INSERT OR IGNORE INTO trip_members VALUES(?,?)", (trip_id, friend_id))
    db.commit()
    return jsonify(trip_payload(db, trip, user))


@app.delete("/api/trips/<int:trip_id>/members/<int:member_id>")
def remove_member(trip_id, member_id):
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    trip = accessible_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Trip not found."), 404
    is_owner = trip["user_id"] == user["id"]
    if not is_owner and member_id != user["id"]:
        return jsonify(error="You can only remove yourself."), 403
    db.execute("DELETE FROM trip_members WHERE trip_id=? AND user_id=?", (trip_id, member_id))
    db.execute(
        "DELETE FROM trip_votes WHERE user_id=? AND item_id IN (SELECT id FROM trip_items WHERE trip_id=?)",
        (member_id, trip_id),
    )
    db.commit()
    if member_id == user["id"]:  # leaving — their trip list changed
        return jsonify(user_payload(db, user))
    return jsonify(trip_payload(db, trip, user))


@app.post("/api/trips/<int:trip_id>/items/<int:item_id>/vote")
def vote_item(trip_id, item_id):
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    trip = accessible_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Trip not found."), 404
    item = db.execute(
        "SELECT 1 FROM trip_items WHERE id=? AND trip_id=?", (item_id, trip_id)
    ).fetchone()
    if not item:
        return jsonify(error="No such item."), 404
    existing = db.execute(
        "SELECT 1 FROM trip_votes WHERE item_id=? AND user_id=?", (item_id, user["id"])
    ).fetchone()
    if existing:
        db.execute("DELETE FROM trip_votes WHERE item_id=? AND user_id=?", (item_id, user["id"]))
    else:
        db.execute("INSERT INTO trip_votes VALUES(?,?)", (item_id, user["id"]))
    db.commit()
    return jsonify(trip_payload(db, trip, user))


@app.post("/api/trips/<int:trip_id>/details")
def trip_details(trip_id):
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    trip = owned_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Trip not found."), 404
    body = request.get_json(force=True)
    db.execute(
        "UPDATE trips SET flight_number=?, start_date=?, end_date=? WHERE id=?",
        (clean_flight(body.get("flight_number")), clean_date(body.get("start_date")),
         clean_date(body.get("end_date")), trip_id),
    )
    db.commit()
    trip = owned_trip(db, user, trip_id)
    return jsonify(trip_payload(db, trip, user))


@app.post("/api/trips/<int:trip_id>/items/<int:item_id>/toggle")
def toggle_trip_item(trip_id, item_id):
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    trip = accessible_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Trip not found."), 404
    db.execute("UPDATE trip_items SET done = 1 - done WHERE id=? AND trip_id=?", (item_id, trip_id))
    db.commit()
    return jsonify(trip_payload(db, trip, user))


@app.delete("/api/trips/<int:trip_id>/items/<int:item_id>")
def delete_trip_item(trip_id, item_id):
    db = get_db()
    user = require_user(db)
    if not user:
        return jsonify(error="Unknown profile."), 404
    trip = owned_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Only the trip owner can remove items."), 403
    db.execute("DELETE FROM trip_votes WHERE item_id=?", (item_id,))
    db.execute("DELETE FROM trip_items WHERE id=? AND trip_id=?", (item_id, trip_id))
    db.commit()
    return jsonify(trip_payload(db, trip, user))


@app.get("/api/destinations")
def destinations():
    return jsonify([
        {"destination": d["destination"], "country": d["country"], "tagline": d["tagline"]}
        for d in ACTIVITIES
    ])


# --------------------------------------------------------------------- app

@app.get("/")
def index():
    return send_from_directory("static", "index.html")


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    # additive migrations for databases created before these columns existed
    trip_cols = {r[1] for r in db.execute("PRAGMA table_info(trips)")}
    if "flight_number" not in trip_cols:
        db.execute("ALTER TABLE trips ADD COLUMN flight_number TEXT")
        db.execute("ALTER TABLE trips ADD COLUMN start_date TEXT")
        db.execute("ALTER TABLE trips ADD COLUMN end_date TEXT")
    item_cols = {r[1] for r in db.execute("PRAGMA table_info(trip_items)")}
    if "open_days" not in item_cols:
        db.execute("ALTER TABLE trip_items ADD COLUMN open_days TEXT")
    db.commit()
    db.close()


init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
