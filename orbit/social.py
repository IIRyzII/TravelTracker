"""Friends via share codes, and overlaying a friend's map on yours."""

from flask import Blueprint, jsonify

from .auth import login_required, new_share_code
from .db import get_db
from .payloads import user_payload
from .util import field, json_body, limiter, user_or_ip

bp = Blueprint("social", __name__)


@bp.post("/api/friends")
@login_required
@limiter.limit("20/hour", key_func=user_or_ip)  # share codes can't be brute-forced
def add_friend(user):
    db = get_db()
    code = field(json_body(), "share_code", 12).upper()
    friend = db.execute("SELECT * FROM users WHERE share_code=?", (code,)).fetchone()
    if not friend:
        return jsonify(error="No traveller found with that code."), 404
    if friend["id"] == user["id"]:
        return jsonify(error="That's your own code!"), 400
    db.execute("INSERT OR IGNORE INTO friends VALUES(?,?)", (user["id"], friend["id"]))
    db.execute("INSERT OR IGNORE INTO friends VALUES(?,?)", (friend["id"], user["id"]))
    db.commit()
    payload = user_payload(db, user)
    payload["added_friend"] = friend["username"]
    return jsonify(payload)


@bp.delete("/api/friends/<int:friend_id>")
@login_required
def remove_friend(user, friend_id):
    db = get_db()
    db.execute(
        "DELETE FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)",
        (user["id"], friend_id, friend_id, user["id"]),
    )
    db.commit()
    return jsonify(user_payload(db, user))


@bp.get("/api/compare/<int:friend_id>")
@login_required
def compare(user, friend_id):
    db = get_db()
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


@bp.post("/api/share_code/rotate")
@login_required
@limiter.limit("10/hour", key_func=user_or_ip)
def rotate_share_code(user):
    """New code if the old one leaked — existing friends stay friends."""
    db = get_db()
    db.execute("UPDATE users SET share_code=? WHERE id=?", (new_share_code(db), user["id"]))
    db.commit()
    user = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    return jsonify(user_payload(db, user))
