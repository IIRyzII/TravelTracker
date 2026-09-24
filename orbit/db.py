"""SQLite access and schema migrations (tracked with PRAGMA user_version)."""

import sqlite3

from flask import current_app, g

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE COLLATE NOCASE NOT NULL,
    share_code TEXT UNIQUE NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS visited(
    user_id INTEGER NOT NULL REFERENCES users(id),
    country_code TEXT NOT NULL,
    country_name TEXT NOT NULL,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, country_code)
);
CREATE TABLE IF NOT EXISTS wishlist(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    place TEXT NOT NULL,
    country_code TEXT,
    country_name TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS friends(
    user_id INTEGER NOT NULL REFERENCES users(id),
    friend_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY(user_id, friend_id)
);
CREATE TABLE IF NOT EXISTS trips(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    destination TEXT NOT NULL,
    country TEXT,
    tagline TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS trip_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    category TEXT,
    title TEXT NOT NULL,
    detail TEXT,
    rating REAL,
    rating_count INTEGER,
    address TEXT,
    maps_url TEXT,
    done INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS visited_cities(
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    iso2 TEXT NOT NULL DEFAULT '',
    lat REAL,
    lng REAL,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, name, iso2)
);
CREATE TABLE IF NOT EXISTS trip_members(
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY(trip_id, user_id)
);
CREATE TABLE IF NOT EXISTS trip_votes(
    item_id INTEGER NOT NULL REFERENCES trip_items(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY(item_id, user_id)
);
"""


def migrate_1(db):
    """The original schema, plus the columns added before migrations were tracked."""
    db.executescript(BASE_SCHEMA)
    trip_cols = {r[1] for r in db.execute("PRAGMA table_info(trips)")}
    if "flight_number" not in trip_cols:
        db.execute("ALTER TABLE trips ADD COLUMN flight_number TEXT")
        db.execute("ALTER TABLE trips ADD COLUMN start_date TEXT")
        db.execute("ALTER TABLE trips ADD COLUMN end_date TEXT")
    item_cols = {r[1] for r in db.execute("PRAGMA table_info(trip_items)")}
    if "open_days" not in item_cols:
        db.execute("ALTER TABLE trip_items ADD COLUMN open_days TEXT")
    db.execute("PRAGMA user_version = 1")
    db.commit()


def migrate_2(db):
    """Real accounts: email/password/Google on users, display names no longer unique."""
    # SQLite can't drop a UNIQUE constraint, so rebuild the table (the documented
    # 12-step recipe); foreign keys must be off outside the transaction for that
    db.execute("PRAGMA foreign_keys = OFF")
    db.executescript("""
    BEGIN;
    CREATE TABLE users_new(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        email TEXT UNIQUE COLLATE NOCASE,
        password_hash TEXT,
        google_sub TEXT UNIQUE,
        share_code TEXT UNIQUE NOT NULL,
        auth_version INTEGER NOT NULL DEFAULT 1,
        plan TEXT NOT NULL DEFAULT 'free',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    INSERT INTO users_new(id, username, share_code, created_at)
        SELECT id, username, share_code, created_at FROM users;
    DROP TABLE users;
    ALTER TABLE users_new RENAME TO users;
    CREATE TABLE usage(
        user_id INTEGER NOT NULL REFERENCES users(id),
        day TEXT NOT NULL,
        kind TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(user_id, day, kind)
    );
    CREATE INDEX idx_usage_day ON usage(day, kind);
    CREATE INDEX idx_wishlist_user ON wishlist(user_id);
    CREATE INDEX idx_friends_friend ON friends(friend_id);
    CREATE INDEX idx_trips_user ON trips(user_id);
    CREATE INDEX idx_trip_items_trip ON trip_items(trip_id);
    CREATE INDEX idx_trip_members_user ON trip_members(user_id);
    CREATE INDEX idx_trip_votes_user ON trip_votes(user_id);
    PRAGMA user_version = 2;
    COMMIT;
    """)
    db.execute("PRAGMA foreign_keys = ON")


MIGRATIONS = [migrate_1, migrate_2]


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")
    return db


def init_db(path):
    db = connect(path)
    db.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
    version = db.execute("PRAGMA user_version").fetchone()[0]
    for step in MIGRATIONS[version:]:
        step(db)
    db.close()


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
