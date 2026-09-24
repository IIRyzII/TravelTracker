"""What each plan gets, and metered usage of paid APIs.

Round 2 (ORBIT Pro via Stripe) only has to set users.plan = 'pro'.
"""

from datetime import datetime, timezone

from flask import current_app


def entitlements(user):
    cfg = current_app.config
    if user["plan"] == "pro":
        return {"plan": "pro", "live_lookups_per_day": cfg["PLACES_PRO_DAILY"]}
    return {"plan": "free", "live_lookups_per_day": cfg["PLACES_FREE_DAILY"]}


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def usage_today(db, user_id, kind):
    row = db.execute("SELECT count FROM usage WHERE user_id=? AND day=? AND kind=?",
                     (user_id, today(), kind)).fetchone()
    return row["count"] if row else 0


def record_usage(db, user_id, kind):
    db.execute(
        "INSERT INTO usage(user_id, day, kind, count) VALUES(?,?,?,1) "
        "ON CONFLICT(user_id, day, kind) DO UPDATE SET count = count + 1",
        (user_id, today(), kind),
    )
    db.commit()


def live_lookups_left(db, user):
    """Live Google Maps shortlists this user can still run today (0 if the
    site-wide daily budget is spent)."""
    total = db.execute("SELECT COALESCE(SUM(count), 0) c FROM usage WHERE day=? AND kind='places'",
                       (today(),)).fetchone()["c"]
    if total >= current_app.config["PLACES_GLOBAL_DAILY_CAP"]:
        return 0
    allowed = entitlements(user)["live_lookups_per_day"]
    return max(0, allowed - usage_today(db, user["id"], "places"))
