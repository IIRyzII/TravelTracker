"""Settings, all overridable from the environment (see DEPLOY.md)."""

import json
import os
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def _google_maps_key():
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key and os.path.exists(CONFIG_PATH):
        try:
            # utf-8-sig: tolerate the BOM that Notepad/PowerShell often write
            with open(CONFIG_PATH, encoding="utf-8-sig") as f:
                key = (json.load(f).get("google_maps_api_key") or "").strip()
        except (OSError, ValueError):
            pass
    if key == "PASTE-YOUR-KEY-HERE":
        key = ""
    return key or None


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def load_config():
    env = os.environ.get("ORBIT_ENV", "development").strip().lower()
    production = env == "production"
    secret = os.environ.get("SECRET_KEY", "").strip()
    if not secret:
        if production:
            raise RuntimeError("SECRET_KEY must be set when ORBIT_ENV=production")
        secret = "dev-only-not-a-secret"
    return {
        "ORBIT_ENV": env,
        "PRODUCTION": production,
        "SECRET_KEY": secret,
        "DATABASE_PATH": os.environ.get("DATABASE_PATH")
        or os.path.join(BASE_DIR, "traveltracker.db"),
        "APP_URL": (os.environ.get("APP_URL") or "http://127.0.0.1:5000").rstrip("/"),
        # trust X-Forwarded-* from one proxy hop (Render, Fly, Railway...)
        "TRUST_PROXY": os.environ.get("TRUST_PROXY", "1" if production else "0") == "1",
        "GOOGLE_MAPS_API_KEY": _google_maps_key(),
        "GOOGLE_CLIENT_ID": os.environ.get("GOOGLE_CLIENT_ID", "").strip() or None,
        "RESEND_API_KEY": os.environ.get("RESEND_API_KEY", "").strip() or None,
        "MAIL_FROM": os.environ.get("MAIL_FROM") or "ORBIT <noreply@example.com>",
        # live Google Maps shortlists per user per day, and a hard daily budget
        "PLACES_FREE_DAILY": _int("PLACES_FREE_DAILY", 3),
        "PLACES_PRO_DAILY": _int("PLACES_PRO_DAILY", 40),
        "PLACES_GLOBAL_DAILY_CAP": _int("PLACES_GLOBAL_DAILY_CAP", 300),
        "SESSION_COOKIE_NAME": "orbit_session",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": production,
        "PERMANENT_SESSION_LIFETIME": timedelta(days=90),
        "MAX_CONTENT_LENGTH": 256 * 1024,
        "RATELIMIT_ENABLED": os.environ.get("RATELIMIT_ENABLED", "1") == "1",
        "RATELIMIT_STORAGE_URI": os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
        "RATELIMIT_HEADERS_ENABLED": True,
    }
