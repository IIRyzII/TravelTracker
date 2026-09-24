"""Saved trips: shortlists, check-offs, crew members and votes."""

import re

from flask import Blueprint, jsonify

from .auth import login_required
from .db import get_db
from .payloads import trip_payload, user_payload
from .util import field, json_body, number

bp = Blueprint("trips", __name__)


def clean_flight(value):
    value = (value if isinstance(value, str) else "").strip().upper().replace(" ", "")[:8]
    return value or None


def clean_date(value):
    value = (value if isinstance(value, str) else "").strip()[:10]
    return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None


def clean_url(value):
    """Only https links get stored — they're rendered as hrefs for the whole crew."""
    value = (value if isinstance(value, str) else "").strip()[:500]
    return value if value.startswith("https://") else None


def clean_open_days(value):
    return value if isinstance(value, str) and re.fullmatch(r"[01]{7}", value) else None


def owned_trip(db, user, trip_id):
    return db.execute("SELECT * FROM trips WHERE id=? AND user_id=?",
                      (trip_id, user["id"])).fetchone()


def accessible_trip(db, user, trip_id):
    """The trip, if the user owns it or was invited to it."""
    return db.execute(
        "SELECT t.* FROM trips t LEFT JOIN trip_members m ON m.trip_id=t.id AND m.user_id=? "
        "WHERE t.id=? AND (t.user_id=? OR m.user_id IS NOT NULL)",
        (user["id"], trip_id, user["id"])).fetchone()


def purge_trip(db, trip_id):
    db.execute("DELETE FROM trip_votes WHERE item_id IN (SELECT id FROM trip_items WHERE trip_id=?)",
               (trip_id,))
    db.execute("DELETE FROM trip_members WHERE trip_id=?", (trip_id,))
    db.execute("DELETE FROM trip_items WHERE trip_id=?", (trip_id,))
    db.execute("DELETE FROM trips WHERE id=?", (trip_id,))


@bp.post("/api/trips")
@login_required
def save_trip(user):
    db = get_db()
    body = json_body()
    destination = field(body, "destination", 80)
    items = [it for it in (body.get("items") or []) if isinstance(it, dict)] \
        if isinstance(body.get("items"), list) else []
    if not destination or not items:
        return jsonify(error="Pick at least one thing to do first."), 400
    cur = db.execute(
        "INSERT INTO trips(user_id, destination, country, tagline, flight_number, start_date, end_date) "
        "VALUES(?,?,?,?,?,?,?)",
        (user["id"], destination, field(body, "country", 80) or None,
         field(body, "tagline", 300) or None, clean_flight(body.get("flight_number")),
         clean_date(body.get("start_date")), clean_date(body.get("end_date"))),
    )
    trip_id = cur.lastrowid
    invites = body.get("invite_ids") if isinstance(body.get("invite_ids"), list) else []
    for fid in {i for i in invites if isinstance(i, int)}:
        is_friend = db.execute(
            "SELECT 1 FROM friends WHERE user_id=? AND friend_id=?", (user["id"], fid)
        ).fetchone()
        if is_friend:
            db.execute("INSERT OR IGNORE INTO trip_members VALUES(?,?)", (trip_id, fid))
    for it in items[:60]:
        count = number(it.get("rating_count"))
        db.execute(
            "INSERT INTO trip_items(trip_id, category, title, detail, rating, rating_count, address, maps_url, open_days) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (trip_id, field(it, "category", 40), field(it, "title", 120),
             field(it, "desc", 300), number(it.get("rating")),
             int(count) if count is not None else None, field(it, "address", 200),
             clean_url(it.get("maps_url")), clean_open_days(it.get("open_days"))),
        )
    db.commit()
    payload = user_payload(db, user)
    payload["saved_trip_id"] = trip_id
    return jsonify(payload)


@bp.get("/api/trips/<int:trip_id>")
@login_required
def get_trip(user, trip_id):
    db = get_db()
    trip = accessible_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Trip not found."), 404
    return jsonify(trip_payload(db, trip, user))


@bp.delete("/api/trips/<int:trip_id>")
@login_required
def delete_trip(user, trip_id):
    db = get_db()
    if owned_trip(db, user, trip_id):
        purge_trip(db, trip_id)
        db.commit()
    return jsonify(user_payload(db, user))


@bp.post("/api/trips/<int:trip_id>/members")
@login_required
def invite_member(user, trip_id):
    db = get_db()
    trip = owned_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Only the trip owner can invite people."), 403
    friend_id = json_body().get("friend_id")
    if not isinstance(friend_id, int):
        return jsonify(error="You can only invite your friends."), 400
    is_friend = db.execute(
        "SELECT 1 FROM friends WHERE user_id=? AND friend_id=?", (user["id"], friend_id)
    ).fetchone()
    if not is_friend:
        return jsonify(error="You can only invite your friends."), 400
    db.execute("INSERT OR IGNORE INTO trip_members VALUES(?,?)", (trip_id, friend_id))
    db.commit()
    return jsonify(trip_payload(db, trip, user))


@bp.delete("/api/trips/<int:trip_id>/members/<int:member_id>")
@login_required
def remove_member(user, trip_id, member_id):
    db = get_db()
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


@bp.post("/api/trips/<int:trip_id>/items/<int:item_id>/vote")
@login_required
def vote_item(user, trip_id, item_id):
    db = get_db()
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


@bp.post("/api/trips/<int:trip_id>/details")
@login_required
def trip_details(user, trip_id):
    db = get_db()
    trip = owned_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Trip not found."), 404
    body = json_body()
    db.execute(
        "UPDATE trips SET flight_number=?, start_date=?, end_date=? WHERE id=?",
        (clean_flight(body.get("flight_number")), clean_date(body.get("start_date")),
         clean_date(body.get("end_date")), trip_id),
    )
    db.commit()
    trip = owned_trip(db, user, trip_id)
    return jsonify(trip_payload(db, trip, user))


@bp.post("/api/trips/<int:trip_id>/items/<int:item_id>/toggle")
@login_required
def toggle_trip_item(user, trip_id, item_id):
    db = get_db()
    trip = accessible_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Trip not found."), 404
    db.execute("UPDATE trip_items SET done = 1 - done WHERE id=? AND trip_id=?", (item_id, trip_id))
    db.commit()
    return jsonify(trip_payload(db, trip, user))


@bp.delete("/api/trips/<int:trip_id>/items/<int:item_id>")
@login_required
def delete_trip_item(user, trip_id, item_id):
    db = get_db()
    trip = owned_trip(db, user, trip_id)
    if not trip:
        return jsonify(error="Only the trip owner can remove items."), 403
    db.execute("DELETE FROM trip_votes WHERE item_id IN "
               "(SELECT id FROM trip_items WHERE id=? AND trip_id=?)", (item_id, trip_id))
    db.execute("DELETE FROM trip_items WHERE id=? AND trip_id=?", (item_id, trip_id))
    db.commit()
    return jsonify(trip_payload(db, trip, user))
