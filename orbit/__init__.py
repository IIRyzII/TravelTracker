"""ORBIT — a globe-first travel tracker.

create_app() wires config, the database, security headers and the blueprints.
"""

import os
from urllib.parse import urlsplit

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from whitenoise import WhiteNoise

from . import account, auth, pages, planner, social, travel, trips
from .config import BASE_DIR, load_config
from .db import close_db, init_db
from .util import limiter

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://accounts.google.com/gsi/client",
    # templates set inline style="" attributes; scripts stay strict
    "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style",
    "img-src 'self' data: blob: https://*.googleusercontent.com",
    "connect-src 'self' https://accounts.google.com/gsi/",
    "frame-src https://accounts.google.com/gsi/",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

# long-lived: vendor code and map data (URLs are versioned by the app)
LONG_CACHE_PREFIXES = ("/static/vendor/", "/static/data/", "/static/icons/")


def _static_headers(headers, _path, url):
    if any(url.startswith(p) for p in LONG_CACHE_PREFIXES):
        headers["Cache-Control"] = "public, max-age=604800"
    else:
        # app code: always revalidate (cheap 304s) so modules never mix versions
        headers["Cache-Control"] = "no-cache"


def create_app(overrides=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(load_config())
    if overrides:
        app.config.update(overrides)

    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.wsgi_app = WhiteNoise(
        app.wsgi_app, root=os.path.join(BASE_DIR, "static"), prefix="static/",
        autorefresh=not app.config["PRODUCTION"], add_headers_function=_static_headers,
    )

    init_db(app.config["DATABASE_PATH"])
    app.teardown_appcontext(close_db)
    limiter.init_app(app)

    for module in (auth, travel, social, trips, planner, account, pages):
        app.register_blueprint(module.bp)

    @app.before_request
    def housekeeping():
        account.schedule_purge(app)  # daily inactive-account clean-up

    @app.before_request
    def guard_writes():
        """Block cross-site writes: JSON only, from our own origin."""
        if request.method not in UNSAFE_METHODS or not request.path.startswith("/api/"):
            return None
        if not request.is_json:
            return jsonify(error="Expected a JSON request."), 415
        site = request.headers.get("Sec-Fetch-Site")
        if site and site not in ("same-origin", "none"):
            return jsonify(error="Cross-site request blocked."), 403
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(error="Cross-site request blocked."), 403
        return None

    @app.after_request
    def security_headers(resp):
        h = resp.headers
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if app.config["PRODUCTION"]:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        return resp

    @app.errorhandler(HTTPException)
    def http_error(exc):
        if not request.path.startswith("/api/"):
            return exc
        if exc.code == 429:
            message = "Too many requests — give it a minute and try again."
        else:
            message = exc.description or exc.name
        return jsonify(error=message), exc.code

    @app.errorhandler(Exception)
    def server_error(exc):
        app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        if request.path.startswith("/api/"):
            return jsonify(error="Something went wrong on our side — please try again."), 500
        return "Something went wrong on our side — please try again.", 500

    return app
