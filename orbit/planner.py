"""Trip planner: live Google Maps shortlists (metered), curated lists, city lookup."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, current_app, jsonify, request

from .auth import login_required
from .db import get_db
from .geo import ACTIVITIES, _norm, find_country
from .plans import live_lookups_left, record_usage
from .util import limiter, remember, user_or_ip

bp = Blueprint("planner", __name__)

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

_places_cache = {}  # dest.lower()|bias -> (timestamp, items)
PLACES_TTL = 6 * 3600
_geo_cache = {}
_cities_cache = {}


def maps_search_url(query):
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)


def open_meteo_search(name, count):
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": name, "count": count, "language": "en", "format": "json"})
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.load(r).get("results") or []


def geocode_place(place):
    """Rough centre for a free-text place via the Open-Meteo geocoder (cached)."""
    key = place.lower()
    if key in _geo_cache:
        return _geo_cache[key]
    first = place.split(",")[0].strip()
    hint = place.split(",")[-1].strip().lower() if "," in place else None
    results = []
    try:
        results = open_meteo_search(first, 10)
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
    remember(_geo_cache, key, (pick["latitude"], pick["longitude"]) if pick else None)
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
            "X-Goog-Api-Key": current_app.config["GOOGLE_MAPS_API_KEY"],
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


def _cache_key(dest_label, bias):
    return dest_label.lower() + "|" + (json.dumps(bias, sort_keys=True) if bias else "")


def cached_itinerary(dest_label, bias=None):
    cached = _places_cache.get(_cache_key(dest_label, bias))
    if cached and time.time() - cached[0] < PLACES_TTL:
        return cached[1]
    return None


def live_itinerary(dest_label, bias=None):
    """Top-rated real places from Google Maps, per category. None on any failure."""
    items, seen = [], set()
    for category, query in CATEGORY_QUERIES:
        try:
            places = places_text_search(query.format(dest_label), bias)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            current_app.logger.warning("Places lookup failed (%s): %s", category, exc)
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
    remember(_places_cache, _cache_key(dest_label, bias), (time.time(), items))
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


@bp.get("/api/itinerary")
@login_required
@limiter.limit("20/minute", key_func=user_or_ip)
def itinerary(user):
    place = (request.args.get("place") or "").strip()[:80]
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

    db = get_db()
    live_limited = False
    if current_app.config["GOOGLE_MAPS_API_KEY"]:
        if center is None and radius_km and not is_whole_country:
            center = geocode_place(place)
        bias = None
        if center and radius_km and not is_whole_country:
            bias = {"circle": {"center": {"latitude": center[0], "longitude": center[1]},
                               "radius": radius_km * 1000}}
        # cached answers are free; fresh ones spend the daily allowance
        live = cached_itinerary(place, bias)
        if live is None:
            if live_lookups_left(db, user) > 0:
                live = live_itinerary(place, bias)
                if live:
                    record_usage(db, user["id"], "places")
            else:
                live_limited = True
        if live:
            return jsonify(
                destination=place if bias else label,
                country=curated["country"] if curated else (country["name"] if country else None),
                tagline=curated["tagline"] if curated
                        else "Top-rated right now, pulled live from Google Maps.",
                curated=False, live=True, radius_km=radius_km if bias else None, items=live,
                live_left=live_lookups_left(db, user),
            )

    if curated:
        items = [
            {**item, "maps_url": maps_search_url(f"{item['title']} {curated['destination']}")}
            for item in curated["items"]
        ]
        return jsonify(destination=curated["destination"], country=curated["country"],
                       tagline=curated["tagline"], curated=True, live=False,
                       live_limited=live_limited, items=items)

    items = [
        {"category": cat, "title": title, "desc": desc.format(place=label),
         "maps_url": maps_search_url(f"{title} {label}")}
        for cat, title, desc in GENERIC_PLAN
    ]
    return jsonify(destination=label, country=country["name"] if country else None,
                   tagline="A starter shortlist - swap these for the real thing as you research.",
                   curated=False, live=False, live_limited=live_limited, items=items)


@bp.get("/api/cities")
@limiter.limit("60/minute")
def cities():
    """City lookup via the free Open-Meteo geocoder (no key needed)."""
    q = (request.args.get("q") or "").strip()[:60]
    if len(q) < 2:
        return jsonify([])
    key = q.lower()
    if key not in _cities_cache:
        try:
            results = open_meteo_search(q, 6)
        except (urllib.error.URLError, OSError, ValueError):
            return jsonify([])
        remember(_cities_cache, key, [
            {
                "name": res.get("name"),
                "country": res.get("country"),
                "iso2": (res.get("country_code") or "").upper(),
                "admin": res.get("admin1"),
                "lat": res.get("latitude"),
                "lng": res.get("longitude"),
            }
            for res in results
            if res.get("latitude") is not None
        ], limit=2000)
    return jsonify(_cities_cache[key])


@bp.get("/api/destinations")
def destinations():
    return jsonify([
        {"destination": d["destination"], "country": d["country"], "tagline": d["tagline"]}
        for d in ACTIVITIES
    ])
