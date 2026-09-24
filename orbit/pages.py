"""The app shell, legal pages, and the small files crawlers and browsers ask for."""

import os

from flask import Blueprint, Response, current_app, jsonify, send_from_directory

from .config import BASE_DIR
from .db import get_db

bp = Blueprint("pages", __name__)

STATIC_DIR = os.path.join(BASE_DIR, "static")


def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/")
@bp.get("/reset")
def index():
    return _no_cache(send_from_directory(STATIC_DIR, "index.html"))


@bp.get("/privacy")
def privacy():
    return _no_cache(send_from_directory(os.path.join(STATIC_DIR, "legal"), "privacy.html"))


@bp.get("/terms")
def terms():
    return _no_cache(send_from_directory(os.path.join(STATIC_DIR, "legal"), "terms.html"))


@bp.get("/sw.js")
def service_worker():
    # served from the root so it can control the whole site
    resp = send_from_directory(os.path.join(STATIC_DIR, "js"), "sw.js",
                               mimetype="text/javascript")
    return _no_cache(resp)


@bp.get("/robots.txt")
def robots():
    url = current_app.config["APP_URL"]
    return Response(f"User-agent: *\nDisallow: /api/\nSitemap: {url}/sitemap.xml\n",
                    mimetype="text/plain")


@bp.get("/sitemap.xml")
def sitemap():
    url = current_app.config["APP_URL"]
    pages = "".join(f"<url><loc>{url}{p}</loc></url>" for p in ("/", "/privacy", "/terms"))
    return Response('<?xml version="1.0" encoding="UTF-8"?>'
                    f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{pages}</urlset>',
                    mimetype="application/xml")


@bp.get("/healthz")
def healthz():
    get_db().execute("SELECT 1").fetchone()
    return jsonify(ok=True)


@bp.get("/api/config")
def public_config():
    """What the signed-out page needs to know (e.g. whether to show Google sign-in)."""
    cfg = current_app.config
    return jsonify(google_client_id=cfg["GOOGLE_CLIENT_ID"],
                   live_places=bool(cfg["GOOGLE_MAPS_API_KEY"]))
