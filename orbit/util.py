"""Shared request helpers and the rate limiter."""

from flask import request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def user_or_ip():
    """Rate-limit key: the signed-in account, else the client address."""
    uid = session.get("uid")
    return f"user:{uid}" if uid else get_remote_address()


limiter = Limiter(get_remote_address)


def json_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def field(body, key, limit=200):
    """A trimmed string field from a JSON body ('' if missing or not a string)."""
    value = body.get(key)
    return value.strip()[:limit] if isinstance(value, str) else ""


def number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def remember(cache, key, value, limit=500):
    """Store in a dict cache, dropping the oldest entries past `limit`."""
    cache[key] = value
    while len(cache) > limit:
        cache.pop(next(iter(cache)))
