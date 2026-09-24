"""Accounts: sessions, email + password, Google sign-in, password reset."""

import functools
import hashlib
import json
import re
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, jsonify, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .payloads import user_payload
from .util import field, json_body, limiter

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
MIN_PASSWORD = 8
RESET_MAX_AGE = 3600  # seconds a reset link stays valid
# compared against when the email is unknown, so both paths cost the same
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


# ---------------------------------------------------------------- sessions

def current_user():
    if "user" not in g:
        g.user = None
        uid = session.get("uid")
        if uid:
            row = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            # a password change bumps auth_version, which signs out other sessions
            if row and row["auth_version"] == session.get("av"):
                g.user = row
                touch_activity(row)
            else:
                session.clear()
    return g.user


def login_required(view):
    """Pass the signed-in user row as the view's first argument, or 401."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify(error="Please sign in first."), 401
        return view(user, *args, **kwargs)
    return wrapped


def login_user(user):
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    session["av"] = user["auth_version"]
    g.user = user
    touch_activity(user)


TIMESTAMP = "%Y-%m-%d %H:%M:%S"  # SQLite's CURRENT_TIMESTAMP format (UTC)


def utc_stamp(when):
    return when.strftime(TIMESTAMP)


def touch_activity(user):
    """Record that the account is in use (at most one write a day). Using ORBIT
    also cancels a pending inactivity deletion."""
    day_ago = utc_stamp(datetime.now(timezone.utc) - timedelta(days=1))
    if user["deletion_warned_at"] or not user["last_active_at"] or user["last_active_at"] < day_ago:
        db = get_db()
        db.execute("UPDATE users SET last_active_at=CURRENT_TIMESTAMP, deletion_warned_at=NULL "
                   "WHERE id=?", (user["id"],))
        db.commit()


def new_share_code(db):
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if not db.execute("SELECT 1 FROM users WHERE share_code=?", (code,)).fetchone():
            return code


def create_user(db, username, email=None, password=None, google_sub=None):
    cur = db.execute(
        "INSERT INTO users(username, email, password_hash, google_sub, share_code, last_active_at) "
        "VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)",
        (username, email, generate_password_hash(password) if password else None,
         google_sub, new_share_code(db)),
    )
    db.commit()
    return db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()


def password_problem(password):
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters for your password."
    if len(password) > 200:
        return "That password is too long."
    return None


def signed_in(db, user, status=200):
    login_user(user)
    return jsonify(user_payload(db, user)), status


# ----------------------------------------------------------- email + password

@bp.post("/api/auth/signup")
@limiter.limit("10/minute")
def signup():
    body = json_body()
    email = field(body, "email", 254).lower()
    password = body.get("password") if isinstance(body.get("password"), str) else ""
    username = field(body, "username", 24)
    if not EMAIL_RE.fullmatch(email):
        return jsonify(error="Please enter a valid email address."), 400
    if not username:
        return jsonify(error="Please tell us what to call you."), 400
    problem = password_problem(password)
    if problem:
        return jsonify(error=problem), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        return jsonify(error="There's already an account with that email — sign in instead."), 409
    user = create_user(db, username, email=email, password=password)
    return signed_in(db, user, 201)


@bp.post("/api/auth/login")
@limiter.limit("10/minute")
def login():
    body = json_body()
    email = field(body, "email", 254).lower()
    password = body.get("password") if isinstance(body.get("password"), str) else ""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    stored = user["password_hash"] if user and user["password_hash"] else _DUMMY_HASH
    if not (check_password_hash(stored, password) and user and user["password_hash"]):
        return jsonify(error="Wrong email or password."), 401
    return signed_in(db, user)


@bp.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


# ------------------------------------------------------------------ google

def verify_google_token(credential, client_id):
    """Claims from a Google Identity Services ID token (raises ValueError if bad)."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)


@bp.post("/api/auth/google")
@limiter.limit("10/minute")
def google_signin():
    client_id = current_app.config["GOOGLE_CLIENT_ID"]
    if not client_id:
        return jsonify(error="Google sign-in isn't set up on this server."), 404
    credential = field(json_body(), "credential", 4096)
    try:
        claims = verify_google_token(credential, client_id)
    except ValueError:
        return jsonify(error="Google sign-in failed — please try again."), 401
    sub = claims.get("sub")
    email = (claims.get("email") or "").lower() or None
    if not sub or not claims.get("email_verified"):
        return jsonify(error="Your Google account's email isn't verified."), 401

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE google_sub=?", (sub,)).fetchone()
    if not user and email:
        # same verified email as an existing account -> link it
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user:
            db.execute("UPDATE users SET google_sub=? WHERE id=?", (sub, user["id"]))
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if user:
        return signed_in(db, user)
    name = (claims.get("given_name") or claims.get("name") or (email or "Traveller").split("@")[0])
    user = create_user(db, name.strip()[:24] or "Traveller", email=email, google_sub=sub)
    return signed_in(db, user, 201)


# ---------------------------------------------------------- password reset

def _reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="orbit-password-reset")


def _hash_fingerprint(user):
    """Changes whenever the password does, so a reset link works only once."""
    return hashlib.sha256((user["password_hash"] or "none").encode()).hexdigest()[:16]


def make_reset_token(user):
    return _reset_serializer().dumps({"uid": user["id"], "fp": _hash_fingerprint(user)})


def send_email(to, subject, text):
    """Send through Resend's HTTP API; without a key, log it (local dev)."""
    key = current_app.config["RESEND_API_KEY"]
    if not key:
        current_app.logger.warning("Email not sent (no RESEND_API_KEY) to %s: %s\n%s",
                                   to, subject, text)
        return False
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({"from": current_app.config["MAIL_FROM"], "to": [to],
                         "subject": subject, "text": text}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "ORBIT/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8):
            return True
    except (urllib.error.URLError, OSError) as exc:
        current_app.logger.error("Email to %s failed: %s", to, exc)
        return False


@bp.post("/api/auth/forgot")
@limiter.limit("5/hour")
def forgot_password():
    email = field(json_body(), "email", 254).lower()
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if user:
        link = f"{current_app.config['APP_URL']}/reset?token={make_reset_token(user)}"
        send_email(email, "Reset your ORBIT password",
                   f"Hi {user['username']},\n\nSet a new ORBIT password here (the link "
                   f"works once, for the next hour):\n\n{link}\n\n"
                   "If you didn't ask for this, you can ignore this email.")
    # same answer either way, so this can't be used to find out who has an account
    return jsonify(ok=True, message="If that email has an account, a reset link is on its way.")


@bp.post("/api/auth/reset")
@limiter.limit("10/hour")
def reset_password():
    body = json_body()
    password = body.get("password") if isinstance(body.get("password"), str) else ""
    problem = password_problem(password)
    if problem:
        return jsonify(error=problem), 400
    try:
        data = _reset_serializer().loads(field(body, "token", 1000), max_age=RESET_MAX_AGE)
    except SignatureExpired:
        return jsonify(error="That reset link has expired — request a new one."), 400
    except BadSignature:
        return jsonify(error="That reset link isn't valid."), 400
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (data.get("uid"),)).fetchone()
    if not user or data.get("fp") != _hash_fingerprint(user):
        return jsonify(error="That reset link has already been used."), 400
    db.execute("UPDATE users SET password_hash=?, auth_version=auth_version+1 WHERE id=?",
               (generate_password_hash(password), user["id"]))
    db.commit()
    user = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    return signed_in(db, user)
