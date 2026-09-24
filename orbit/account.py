"""Your account: name and password changes, data export, deletion."""

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import click
from flask import Blueprint, Response, current_app, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from .auth import EMAIL_RE, login_required, login_user, password_problem, send_email, utc_stamp
from .db import connect, get_db
from .payloads import user_payload
from .trips import purge_trip
from .util import field, json_body, limiter, user_or_ip

bp = Blueprint("account", __name__, cli_group=None)


@bp.patch("/api/account")
@login_required
@limiter.limit("20/hour", key_func=user_or_ip)
def update_account(user):
    db = get_db()
    body = json_body()
    username = field(body, "username", 24)
    new_password = body.get("new_password") if isinstance(body.get("new_password"), str) else ""
    if username:
        db.execute("UPDATE users SET username=? WHERE id=?", (username, user["id"]))
    if new_password:
        current = body.get("current_password") if isinstance(body.get("current_password"), str) else ""
        if user["password_hash"] and not check_password_hash(user["password_hash"], current):
            return jsonify(error="Your current password isn't right."), 403
        problem = password_problem(new_password)
        if problem:
            return jsonify(error=problem), 400
        # bumping auth_version signs out every other device
        db.execute("UPDATE users SET password_hash=?, auth_version=auth_version+1 WHERE id=?",
                   (generate_password_hash(new_password), user["id"]))
    db.commit()
    user = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if new_password:
        login_user(user)  # keep this device signed in
    return jsonify(user_payload(db, user))


def export_data(db, user):
    uid = user["id"]

    def rows(sql, *args):
        return [dict(r) for r in db.execute(sql, args)]

    trips = rows("SELECT * FROM trips WHERE user_id=? ORDER BY id", uid)
    for t in trips:
        t["items"] = rows("SELECT * FROM trip_items WHERE trip_id=? ORDER BY id", t["id"])
        t["members"] = [r["username"] for r in rows(
            "SELECT u.username FROM trip_members m JOIN users u ON u.id=m.user_id "
            "WHERE m.trip_id=?", t["id"])]
    return {
        "account": {"username": user["username"], "email": user["email"],
                    "share_code": user["share_code"], "plan": user["plan"],
                    "created_at": user["created_at"],
                    "google_linked": bool(user["google_sub"])},
        "visited_countries": rows("SELECT country_code, country_name, added_at FROM visited "
                                  "WHERE user_id=? ORDER BY country_name", uid),
        "visited_places": rows("SELECT name, iso2, lat, lng, added_at FROM visited_cities "
                               "WHERE user_id=? ORDER BY name", uid),
        "wishlist": rows("SELECT place, country_name, created_at FROM wishlist "
                         "WHERE user_id=? ORDER BY id", uid),
        "friends": [r["username"] for r in rows(
            "SELECT u.username FROM friends f JOIN users u ON u.id=f.friend_id "
            "WHERE f.user_id=?", uid)],
        "trips": trips,
        "shared_trips_joined": rows(
            "SELECT t.destination, u.username AS owner FROM trip_members m "
            "JOIN trips t ON t.id=m.trip_id JOIN users u ON u.id=t.user_id "
            "WHERE m.user_id=?", uid),
    }


@bp.get("/api/account/export")
@login_required
@limiter.limit("10/hour", key_func=user_or_ip)
def export_account(user):
    body = json.dumps(export_data(get_db(), user), indent=2, default=str)
    return Response(body, mimetype="application/json", headers={
        "Content-Disposition": 'attachment; filename="orbit-export.json"'})


def delete_user(db, uid):
    """Everything the account owns or touched. No ON DELETE CASCADE on user_id,
    so remove dependants first."""
    for (trip_id,) in db.execute("SELECT id FROM trips WHERE user_id=?", (uid,)).fetchall():
        purge_trip(db, trip_id)
    for table in ("trip_votes", "trip_members", "visited", "visited_cities", "wishlist", "usage"):
        db.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
    db.execute("DELETE FROM friends WHERE user_id=? OR friend_id=?", (uid, uid))
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()


WARNING_DAYS = 7  # the deletion warning goes out this long before


def purge_inactive(db, now=None):
    """Warn, then delete, accounts nobody has used for ACCOUNT_INACTIVE_DAYS.

    An account is only deleted once a warning email has actually been sent,
    at least WARNING_DAYS earlier. Signing in again cancels it
    (auth.touch_activity)."""
    days = current_app.config["ACCOUNT_INACTIVE_DAYS"]
    if days <= 0:
        return {"warned": 0, "deleted": 0}
    now = now or datetime.now(timezone.utc)
    warned = deleted = 0
    stale = db.execute(
        "SELECT * FROM users WHERE last_active_at < ? AND deletion_warned_at IS NULL",
        (utc_stamp(now - timedelta(days=days - WARNING_DAYS)),)).fetchall()
    for user in stale:
        last = datetime.strptime(user["last_active_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        goes = max(last + timedelta(days=days), now + timedelta(days=WARNING_DAYS))
        if user["email"]:
            sent = send_email(
                user["email"], "Your ORBIT account will be deleted soon",
                f"Hi {user['username']},\n\nYou haven't used ORBIT for a while, so your "
                f"account and travel map will be deleted on {goes.day} {goes:%B %Y}.\n\n"
                f"To keep them, just sign in before then:\n{current_app.config['APP_URL']}\n\n"
                "If you're happy for it to go, you don't need to do anything.")
            if not sent:
                continue  # no warning, no deletion (e.g. email isn't set up yet)
        db.execute("UPDATE users SET deletion_warned_at=? WHERE id=?", (utc_stamp(now), user["id"]))
        warned += 1
    db.commit()
    for (uid,) in db.execute(
            "SELECT id FROM users WHERE last_active_at < ? AND deletion_warned_at <= ?",
            (utc_stamp(now - timedelta(days=days)),
             utc_stamp(now - timedelta(days=WARNING_DAYS)))).fetchall():
        delete_user(db, uid)
        deleted += 1
    return {"warned": warned, "deleted": deleted}


_next_purge = [0.0]
_purge_lock = threading.Lock()


def schedule_purge(app):
    """Run purge_inactive at most once a day, off the request thread."""
    if app.config["ACCOUNT_INACTIVE_DAYS"] <= 0 or app.config.get("TESTING"):
        return
    with _purge_lock:
        if time.time() < _next_purge[0]:
            return
        _next_purge[0] = time.time() + 24 * 3600

    def job():
        with app.app_context():
            db = connect(app.config["DATABASE_PATH"])
            try:
                result = purge_inactive(db)
                if result["warned"] or result["deleted"]:
                    app.logger.info("Inactive accounts: %s", result)
            except Exception:
                app.logger.exception("Inactive-account clean-up failed")
            finally:
                db.close()

    threading.Thread(target=job, daemon=True).start()


@bp.cli.command("purge-inactive")
def purge_inactive_command():
    """Warn / delete accounts unused for ACCOUNT_INACTIVE_DAYS (also runs daily by itself)."""
    db = connect(current_app.config["DATABASE_PATH"])
    click.echo(purge_inactive(db))
    db.close()


@bp.delete("/api/account")
@login_required
@limiter.limit("10/hour", key_func=user_or_ip)
def delete_account(user):
    body = json_body()
    if field(body, "confirm", 20) != "DELETE":
        return jsonify(error='Type DELETE to confirm.'), 400
    if user["password_hash"]:
        password = body.get("password") if isinstance(body.get("password"), str) else ""
        if not check_password_hash(user["password_hash"], password):
            return jsonify(error="Your password isn't right."), 403
    delete_user(get_db(), user["id"])
    session.clear()
    return jsonify(ok=True)


@bp.cli.command("claim-profile")
@click.argument("username")
@click.argument("email")
@click.password_option()
def claim_profile(username, email, password):
    """Give a profile from before accounts existed an email + password."""
    email = email.strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise click.ClickException("That doesn't look like an email address.")
    problem = password_problem(password)
    if problem:
        raise click.ClickException(problem)
    db = connect(current_app.config["DATABASE_PATH"])
    rows = db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchall()
    if len(rows) != 1:
        raise click.ClickException(f"Found {len(rows)} profiles called {username!r} — need exactly one.")
    if db.execute("SELECT 1 FROM users WHERE email=? AND id<>?", (email, rows[0]["id"])).fetchone():
        raise click.ClickException("Another account already uses that email.")
    db.execute("UPDATE users SET email=?, password_hash=?, auth_version=auth_version+1, "
               "last_active_at=CURRENT_TIMESTAMP, deletion_warned_at=NULL WHERE id=?",
               (email, generate_password_hash(password), rows[0]["id"]))
    db.commit()
    db.close()
    click.echo(f"{rows[0]['username']} can now sign in as {email}.")
