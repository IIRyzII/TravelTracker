import re

import pytest

from orbit import auth

from .conftest import signup


def test_signup_signs_you_in(client):
    user = signup(client, "Ann", email="ann@example.com")
    assert user["username"] == "Ann"
    assert user["email"] == "ann@example.com"
    assert user["has_password"] and not user["google_linked"]
    assert re.fullmatch(r"[A-Z2-9]{6}", user["share_code"])
    assert client.get("/api/state").json["id"] == user["id"]


def test_signup_validation(client):
    bad = [
        ({"email": "nope", "password": "longenough", "username": "A"}, "valid email"),
        ({"email": "a@b.co", "password": "short", "username": "A"}, "at least 8"),
        ({"email": "a@b.co", "password": "longenough", "username": ""}, "call you"),
    ]
    for body, msg in bad:
        resp = client.post("/api/auth/signup", json=body)
        assert resp.status_code == 400 and msg in resp.json["error"]


def test_duplicate_email_rejected(client, app):
    signup(client, email="dupe@example.com")
    other = app.test_client()
    resp = other.post("/api/auth/signup",
                      json={"email": "DUPE@example.com", "password": "longenough", "username": "B"})
    assert resp.status_code == 409


def test_display_names_need_not_be_unique(make_user):
    _, a = make_user("Sam")
    _, b = make_user("Sam")
    assert a["id"] != b["id"]


def test_login_logout(client, app):
    signup(client, email="log@example.com", password="right password")
    client.post("/api/auth/logout", json={})
    assert client.get("/api/state").status_code == 401

    fresh = app.test_client()
    wrong = fresh.post("/api/auth/login", json={"email": "log@example.com", "password": "nope nope"})
    assert wrong.status_code == 401 and wrong.json["error"] == "Wrong email or password."
    unknown = fresh.post("/api/auth/login", json={"email": "who@example.com", "password": "x" * 9})
    assert unknown.status_code == 401 and unknown.json["error"] == wrong.json["error"]
    ok = fresh.post("/api/auth/login", json={"email": "LOG@example.com", "password": "right password"})
    assert ok.status_code == 200
    assert fresh.get("/api/state").status_code == 200


def test_old_name_only_login_is_gone(client):
    resp = client.post("/api/profile", json={"username": "Ann"})
    assert resp.status_code in (404, 405)


def test_password_change_signs_out_other_devices(app):
    laptop = app.test_client()
    signup(laptop, email="two@example.com", password="first password")
    phone = app.test_client()
    phone.post("/api/auth/login", json={"email": "two@example.com", "password": "first password"})
    assert phone.get("/api/state").status_code == 200

    resp = laptop.patch("/api/account", json={"current_password": "first password",
                                              "new_password": "second password"})
    assert resp.status_code == 200
    assert laptop.get("/api/state").status_code == 200  # this device stays in
    assert phone.get("/api/state").status_code == 401   # the other one is out


def test_password_change_needs_current_password(client):
    signup(client, password="first password")
    resp = client.patch("/api/account", json={"current_password": "guess",
                                              "new_password": "second password"})
    assert resp.status_code == 403


def test_password_reset_works_once(client, app, monkeypatch):
    sent = []
    monkeypatch.setattr(auth, "send_email", lambda to, subject, text: sent.append(text))
    signup(client, email="reset@example.com", password="old password")

    resp = client.post("/api/auth/forgot", json={"email": "reset@example.com"})
    assert resp.status_code == 200 and len(sent) == 1
    token = re.search(r"token=(\S+)", sent[0]).group(1)
    # unknown emails get the same answer and no email
    same = client.post("/api/auth/forgot", json={"email": "nobody@example.com"})
    assert same.json["message"] == resp.json["message"] and len(sent) == 1

    fresh = app.test_client()
    ok = fresh.post("/api/auth/reset", json={"token": token, "password": "new password"})
    assert ok.status_code == 200 and fresh.get("/api/state").status_code == 200
    again = fresh.post("/api/auth/reset", json={"token": token, "password": "another one"})
    assert again.status_code == 400 and "already been used" in again.json["error"]

    assert fresh.post("/api/auth/login", json={"email": "reset@example.com",
                                               "password": "old password"}).status_code == 401
    assert fresh.post("/api/auth/login", json={"email": "reset@example.com",
                                               "password": "new password"}).status_code == 200
    # the reset also signed out the session that existed before it
    assert client.get("/api/state").status_code == 401


def test_bad_reset_token(client):
    resp = client.post("/api/auth/reset", json={"token": "garbage", "password": "new password"})
    assert resp.status_code == 400


@pytest.fixture
def google_app(app, monkeypatch):
    app.config["GOOGLE_CLIENT_ID"] = "client-123"
    claims = {}

    def fake_verify(credential, client_id):
        assert client_id == "client-123"
        if credential != "good-token":
            raise ValueError("bad token")
        return dict(claims)

    monkeypatch.setattr(auth, "verify_google_token", fake_verify)
    return app, claims


def test_google_signin_creates_account(google_app):
    app, claims = google_app
    claims.update(sub="g-1", email="gee@example.com", email_verified=True, given_name="Gee")
    c = app.test_client()
    resp = c.post("/api/auth/google", json={"credential": "good-token"})
    assert resp.status_code == 201
    assert resp.json["username"] == "Gee" and resp.json["google_linked"]
    assert not resp.json["has_password"]
    again = app.test_client().post("/api/auth/google", json={"credential": "good-token"})
    assert again.status_code == 200 and again.json["id"] == resp.json["id"]


def test_google_links_existing_email_account(google_app):
    app, claims = google_app
    c = app.test_client()
    user = signup(c, email="link@example.com")
    claims.update(sub="g-2", email="link@example.com", email_verified=True)
    resp = app.test_client().post("/api/auth/google", json={"credential": "good-token"})
    assert resp.json["id"] == user["id"] and resp.json["google_linked"]


def test_google_rejects_bad_or_unverified(google_app):
    app, claims = google_app
    c = app.test_client()
    assert c.post("/api/auth/google", json={"credential": "forged"}).status_code == 401
    claims.update(sub="g-3", email="x@example.com", email_verified=False)
    assert c.post("/api/auth/google", json={"credential": "good-token"}).status_code == 401


def test_google_off_without_client_id(client):
    assert client.post("/api/auth/google", json={"credential": "x"}).status_code == 404
    assert client.get("/api/config").json["google_client_id"] is None
