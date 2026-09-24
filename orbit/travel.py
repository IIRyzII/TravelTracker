"""Where you've been and where you want to go."""

from flask import Blueprint, jsonify

from .auth import login_required
from .db import get_db
from .geo import COUNTRIES_BY_CODE, COUNTRIES_BY_ISO2, find_country
from .payloads import user_payload
from .places import fold
from .util import field, json_body, number

bp = Blueprint("travel", __name__)


@bp.get("/api/state")
@login_required
def state(user):
    return jsonify(user_payload(get_db(), user))


@bp.post("/api/visited")
@login_required
def add_visited(user):
    db = get_db()
    entry = COUNTRIES_BY_CODE.get(field(json_body(), "code", 8))
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


@bp.delete("/api/visited")
@login_required
def remove_visited(user):
    db = get_db()
    code = field(json_body(), "code", 8)
    db.execute("DELETE FROM visited WHERE user_id=? AND country_code=?", (user["id"], code))
    # a visited city implies its country, so un-visiting the country clears its cities
    entry = COUNTRIES_BY_CODE.get(code)
    if entry and entry.get("iso2"):
        db.execute("DELETE FROM visited_cities WHERE user_id=? AND iso2=?",
                   (user["id"], entry["iso2"]))
    db.commit()
    return jsonify(user_payload(db, user))


def same_city_rows(db, user, name, iso2):
    """The user's logged cities that are this place, however it was spelt."""
    key = fold(name)
    return [r for r in db.execute("SELECT name, iso2 FROM visited_cities WHERE user_id=? AND iso2=?",
                                  (user["id"], iso2))
            if fold(r["name"]) == key]


@bp.post("/api/visited_city")
@login_required
def add_visited_city(user):
    db = get_db()
    body = json_body()
    name = field(body, "name", 80)
    iso2 = field(body, "iso2", 2).upper()
    if not name:
        return jsonify(error="Unknown place."), 400
    # 'Zürich' and 'Zuerich' are the same place — don't log it twice
    if not same_city_rows(db, user, name, iso2):
        db.execute(
            "INSERT INTO visited_cities(user_id, name, iso2, lat, lng) VALUES(?,?,?,?,?)",
            (user["id"], name, iso2, number(body.get("lat")), number(body.get("lng"))),
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


@bp.delete("/api/visited_city")
@login_required
def remove_visited_city(user):
    db = get_db()
    body = json_body()
    for row in same_city_rows(db, user, field(body, "name", 80), field(body, "iso2", 2).upper()):
        db.execute("DELETE FROM visited_cities WHERE user_id=? AND name=? AND iso2=?",
                   (user["id"], row["name"], row["iso2"]))
    db.commit()
    return jsonify(user_payload(db, user))


@bp.post("/api/wishlist")
@login_required
def add_wishlist(user):
    db = get_db()
    body = json_body()
    place = field(body, "place", 80)
    if not place:
        return jsonify(error="Please enter a place."), 400
    entry = COUNTRIES_BY_CODE.get(field(body, "code", 8)) or find_country(place)
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


@bp.delete("/api/wishlist/<int:item_id>")
@login_required
def remove_wishlist(user, item_id):
    db = get_db()
    db.execute("DELETE FROM wishlist WHERE id=? AND user_id=?", (item_id, user["id"]))
    db.commit()
    return jsonify(user_payload(db, user))
