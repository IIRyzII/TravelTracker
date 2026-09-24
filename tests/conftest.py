import itertools

import pytest

from orbit import create_app

_emails = itertools.count(1)


@pytest.fixture
def app(tmp_path):
    return create_app({
        "DATABASE_PATH": str(tmp_path / "test.db"),
        "SECRET_KEY": "test-secret",
        "RATELIMIT_ENABLED": False,
        "GOOGLE_MAPS_API_KEY": None,
        "GOOGLE_CLIENT_ID": None,
        "RESEND_API_KEY": None,
        "TESTING": True,
    })


@pytest.fixture
def client(app):
    return app.test_client()


def signup(client, username="Ann", email=None, password="correct horse"):
    email = email or f"user{next(_emails)}@example.com"
    resp = client.post("/api/auth/signup",
                       json={"email": email, "password": password, "username": username})
    assert resp.status_code == 201, resp.json
    return resp.json


@pytest.fixture
def make_user(app):
    """A signed-in test client plus its payload: client, user = make_user('Bo')."""
    def make(username="Ann", **kw):
        c = app.test_client()
        return c, signup(c, username, **kw)
    return make
