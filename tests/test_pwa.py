import json
import os
import re

from orbit.config import BASE_DIR

STATIC = os.path.join(BASE_DIR, "static")


def test_service_worker_precaches_every_module(client):
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.content_type
    assert sw.headers["Cache-Control"] == "no-cache"
    listed = set(re.findall(r'"(/static/js/[^"]+\.js)"', sw.get_data(as_text=True)))
    modules = {
        "/static/" + os.path.relpath(os.path.join(root, name), STATIC).replace(os.sep, "/")
        for root, _, files in os.walk(os.path.join(STATIC, "js"))
        for name in files if name.endswith(".js") and name != "sw.js"
    }
    assert modules - listed == set(), "add new modules to SHELL in static/js/sw.js"
    # every precached URL must exist, or the service worker fails to install
    for path in re.findall(r'^\s+"(/[^"]*)",$', sw.get_data(as_text=True), re.M):
        assert client.get(path).status_code == 200, path


def test_manifest_and_icons(client):
    manifest = json.loads(client.get("/static/manifest.webmanifest").data)
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
    purposes = {i.get("purpose", "any") for i in manifest["icons"]}
    assert "maskable" in purposes
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200, icon["src"]


def test_shell_has_public_url_for_link_previews(app, client):
    app.config["APP_URL"] = "https://orbit.example"
    html = client.get("/").get_data(as_text=True)
    assert '<meta property="og:image" content="https://orbit.example/static/icons/og-image.png">' in html
    assert "__APP_URL__" not in html
    assert client.get("/static/icons/og-image.png").status_code == 200


def test_reset_link_serves_the_app(client):
    assert b'id="authOverlay"' in client.get("/reset?token=abc").data


def test_legal_pages(client):
    for path in ("/privacy", "/terms"):
        resp = client.get(path)
        assert resp.status_code == 200 and b"<h1>" in resp.data
