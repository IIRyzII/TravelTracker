from orbit import create_app


def test_security_headers(client):
    resp = client.get("/")
    csp = resp.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-eval" not in csp
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "Strict-Transport-Security" not in resp.headers  # dev only over http
    assert client.get("/api/destinations").headers["Cache-Control"] == "no-store"


def test_hsts_and_secure_cookie_in_production(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "prod-secret")
    app = create_app({"DATABASE_PATH": str(tmp_path / "p.db"), "RATELIMIT_ENABLED": False})
    assert app.config["SESSION_COOKIE_SECURE"]
    assert "Strict-Transport-Security" in app.test_client().get("/").headers


def test_production_needs_a_secret(monkeypatch):
    import pytest
    monkeypatch.setenv("ORBIT_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        create_app()


def test_writes_must_be_json(make_user):
    c, _ = make_user()
    resp = c.post("/api/visited", data='{"code": "FRA"}', content_type="text/plain")
    assert resp.status_code == 415
    form = c.post("/api/visited", data={"code": "FRA"})
    assert form.status_code == 415


def test_cross_site_writes_blocked(make_user):
    c, _ = make_user()
    evil = c.post("/api/visited", json={"code": "FRA"},
                  headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert evil.status_code == 403
    evil_origin = c.post("/api/visited", json={"code": "FRA"},
                         headers={"Origin": "https://evil.example"})
    assert evil_origin.status_code == 403
    same = c.post("/api/visited", json={"code": "FRA"},
                  headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"})
    assert same.status_code == 200


def test_api_errors_are_json(client):
    assert client.get("/api/does-not-exist").json["error"]
    assert client.put("/api/visited", json={}).json["error"]  # 405


def test_malformed_bodies_dont_crash(make_user):
    c, _ = make_user()
    assert c.post("/api/visited", json=["not", "a", "dict"]).status_code == 400
    assert c.post("/api/visited", json={"code": ["FRA"]}).status_code == 400
    assert c.post("/api/friends", json={"share_code": 12345}).status_code == 404
    assert c.post("/api/trips", json={"destination": "X", "items": "nope"}).status_code == 400
    assert c.post("/api/trips", json={"destination": "X", "items": [1, 2]}).status_code == 400
    assert c.post("/api/trips/1/members", json={"friend_id": {"a": 1}}).status_code == 403


def test_login_is_rate_limited(tmp_path):
    app = create_app({"DATABASE_PATH": str(tmp_path / "rl.db"), "RATELIMIT_ENABLED": True})
    c = app.test_client()
    codes = [c.post("/api/auth/login", json={"email": "a@b.co", "password": "x" * 8}).status_code
             for _ in range(11)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429
    assert "Too many requests" in c.post("/api/auth/login", json={}).json["error"]


def test_static_caching(client):
    assert client.get("/static/js/app.js").headers["Cache-Control"] == "no-cache"
    assert "max-age" in client.get("/static/data/countries.geojson").headers["Cache-Control"]


def test_small_public_files(client):
    assert "Sitemap:" in client.get("/robots.txt").get_data(as_text=True)
    assert "<urlset" in client.get("/sitemap.xml").get_data(as_text=True)
    assert client.get("/healthz").json == {"ok": True}
