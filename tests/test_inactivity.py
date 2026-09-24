"""Accounts unused for ACCOUNT_INACTIVE_DAYS get a warning email, then are deleted."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from orbit import account

NOW = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)


def stamp(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def sent(monkeypatch):
    emails = []
    monkeypatch.setattr(account, "send_email",
                        lambda to, subject, text: emails.append((to, text)) or True)
    return emails


def set_last_active(app, uid, days_ago):
    db = sqlite3.connect(app.config["DATABASE_PATH"])
    db.execute("UPDATE users SET last_active_at=? WHERE id=?", (stamp(days_ago), uid))
    db.commit()
    db.close()


def purge(app, now):
    with app.app_context():
        db = account.connect(app.config["DATABASE_PATH"])
        try:
            return account.purge_inactive(db, now)
        finally:
            db.close()


def user_ids(app):
    db = sqlite3.connect(app.config["DATABASE_PATH"])
    ids = {r[0] for r in db.execute("SELECT id FROM users")}
    db.close()
    return ids


def test_warn_then_delete(app, make_user, sent):
    _, idle = make_user("Idle", email="idle@example.com")
    _, busy = make_user("Busy")
    set_last_active(app, idle["id"], 85)
    set_last_active(app, busy["id"], 10)

    assert purge(app, NOW) == {"warned": 1, "deleted": 0}
    assert sent[0][0] == "idle@example.com" and "8 December 2026" in sent[0][1]
    assert purge(app, NOW + timedelta(days=3)) == {"warned": 0, "deleted": 0}  # no repeat email
    assert purge(app, NOW + timedelta(days=7)) == {"warned": 0, "deleted": 1}
    assert user_ids(app) == {busy["id"]}


def test_long_idle_accounts_still_get_a_weeks_warning(app, make_user, sent):
    _, old = make_user("Old")
    set_last_active(app, old["id"], 400)
    assert purge(app, NOW) == {"warned": 1, "deleted": 0}
    assert purge(app, NOW + timedelta(days=6)) == {"warned": 0, "deleted": 0}
    assert purge(app, NOW + timedelta(days=7)) == {"warned": 0, "deleted": 1}


def test_signing_in_cancels_the_deletion(app, make_user, sent):
    client, idle = make_user("Idle", password="idle password")
    set_last_active(app, idle["id"], 85)
    purge(app, NOW)
    assert client.get("/api/state").status_code == 200  # coming back counts as activity
    assert purge(app, datetime.now(timezone.utc) + timedelta(days=8))["deleted"] == 0
    assert idle["id"] in user_ids(app)


def test_zero_days_turns_it_off(app, make_user, sent):
    app.config["ACCOUNT_INACTIVE_DAYS"] = 0
    _, idle = make_user("Idle")
    set_last_active(app, idle["id"], 1000)
    assert purge(app, NOW) == {"warned": 0, "deleted": 0}


def test_cli_runs_the_clean_up(app, make_user, sent):
    _, idle = make_user("Idle")
    real_age = (datetime.now(timezone.utc) - NOW).days  # the CLI uses today's date
    set_last_active(app, idle["id"], 85 - real_age)
    result = app.test_cli_runner().invoke(args=["purge-inactive"])
    assert result.exit_code == 0 and "'warned': 1" in result.output


def test_no_deletion_without_a_warning_email(app, make_user, monkeypatch):
    monkeypatch.setattr(account, "send_email", lambda to, subject, text: False)  # e.g. no RESEND_API_KEY
    _, idle = make_user("Idle")
    set_last_active(app, idle["id"], 400)
    assert purge(app, NOW) == {"warned": 0, "deleted": 0}
    assert purge(app, NOW + timedelta(days=30)) == {"warned": 0, "deleted": 0}
    assert idle["id"] in user_ids(app)
