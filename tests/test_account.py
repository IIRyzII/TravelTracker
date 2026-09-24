import json
import sqlite3

from orbit import create_app
from orbit.db import BASE_SCHEMA


def test_export_has_everything(make_user):
    c, _ = make_user("Ann", email="ann@example.com")
    c.post("/api/visited", json={"code": "FRA"})
    c.post("/api/visited_city", json={"name": "Lyon", "iso2": "FR"})
    c.post("/api/wishlist", json={"place": "Crete, Greece"})
    c.post("/api/trips", json={"destination": "Rome", "items": [{"title": "Colosseum"}]})
    resp = c.get("/api/account/export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["Content-Disposition"]
    data = json.loads(resp.data)
    assert data["account"]["email"] == "ann@example.com"
    assert [v["country_code"] for v in data["visited_countries"]] == ["FRA"]
    assert data["visited_places"][0]["name"] == "Lyon"
    assert data["wishlist"][0]["place"] == "Crete, Greece"
    assert data["trips"][0]["items"][0]["title"] == "Colosseum"


def test_delete_account_removes_every_row(app, make_user):
    ann_c, ann = make_user("Ann", password="ann password")
    bo_c, bo = make_user("Bo")
    bo_c.post("/api/friends", json={"share_code": ann["share_code"]})
    ann_c.post("/api/visited", json={"code": "FRA"})
    ann_c.post("/api/visited_city", json={"name": "Lyon", "iso2": "FR"})
    ann_c.post("/api/wishlist", json={"place": "Peru"})
    own = ann_c.post("/api/trips", json={"destination": "Rome", "invite_ids": [bo["id"]],
                                         "items": [{"title": "Colosseum"}]}).json["saved_trip_id"]
    bos = bo_c.post("/api/trips", json={"destination": "Oslo", "invite_ids": [ann["id"]],
                                        "items": [{"title": "Fjord"}]}).json["saved_trip_id"]
    item = ann_c.get(f"/api/trips/{bos}").json["items"][0]["id"]
    ann_c.post(f"/api/trips/{bos}/items/{item}/vote", json={})

    assert ann_c.delete("/api/account", json={"confirm": "DELETE",
                                              "password": "wrong"}).status_code == 403
    assert ann_c.delete("/api/account", json={"password": "ann password"}).status_code == 400
    resp = ann_c.delete("/api/account", json={"confirm": "DELETE", "password": "ann password"})
    assert resp.status_code == 200
    assert ann_c.get("/api/state").status_code == 401

    db = sqlite3.connect(app.config["DATABASE_PATH"])
    uid = ann["id"]
    for table, col in [("users", "id"), ("visited", "user_id"), ("visited_cities", "user_id"),
                       ("wishlist", "user_id"), ("trips", "user_id"), ("trip_members", "user_id"),
                       ("trip_votes", "user_id"), ("friends", "user_id"), ("friends", "friend_id")]:
        assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (uid,)).fetchone()[0] == 0, table
    assert db.execute("SELECT COUNT(*) FROM trip_items WHERE trip_id=?", (own,)).fetchone()[0] == 0
    # Bo's own trip survives, minus Ann
    bo_trip = bo_c.get(f"/api/trips/{bos}").json
    assert bo_trip["members"] == [] and bo_trip["items"][0]["votes"] == 0
    assert bo_c.get("/api/state").json["friends"] == []


def test_rename(make_user):
    c, _ = make_user("Ann")
    assert c.patch("/api/account", json={"username": "  Annie  "}).json["username"] == "Annie"


def test_migrates_a_pre_accounts_database(tmp_path):
    """Databases from the name-only era keep their data after the upgrade."""
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript(BASE_SCHEMA)
    db.execute("INSERT INTO users(username, share_code) VALUES('Ryley', 'ABC234')")
    db.execute("INSERT INTO visited(user_id, country_code, country_name) VALUES(1, 'FRA', 'France')")
    db.execute("INSERT INTO trips(user_id, destination) VALUES(1, 'Rome')")
    db.execute("INSERT INTO trip_items(trip_id, category, title, detail, rating, rating_count, maps_url) "
               "VALUES(1, 'Must-see', 'Colosseum', 'Piazza del Colosseo', 4.7, 90000, 'https://maps.google.com/?cid=9')")
    db.execute("INSERT INTO trip_items(trip_id, category, title, detail) "
               "VALUES(1, 'Night out', 'Trastevere', 'ORBIT curated tip')")
    db.commit()
    db.close()

    app = create_app({"DATABASE_PATH": str(path), "RATELIMIT_ENABLED": False})
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == 4
    row = db.execute("SELECT username, share_code, email, plan, auth_version FROM users").fetchone()
    assert row == ("Ryley", "ABC234", None, "free", 1)
    # old accounts start the inactivity clock at the upgrade, not at 0
    assert db.execute("SELECT last_active_at FROM users").fetchone()[0] is not None
    cols = {r[1] for r in db.execute("PRAGMA table_info(trips)")}
    assert {"flight_number", "start_date", "end_date"} <= cols
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    # Google details saved before migration 4 are cleared; ORBIT's own text stays
    items = db.execute("SELECT title, detail, rating, rating_count FROM trip_items ORDER BY id").fetchall()
    assert items == [("Colosseum", None, None, None), ("Trastevere", "ORBIT curated tip", None, None)]
    db.close()

    # claim the old profile, then sign in with it
    runner = app.test_cli_runner()
    result = runner.invoke(args=["claim-profile", "ryley", "me@example.com",
                                 "--password", "my new password"])
    assert result.exit_code == 0, result.output
    c = app.test_client()
    state = c.post("/api/auth/login", json={"email": "me@example.com",
                                            "password": "my new password"}).json
    assert state["username"] == "Ryley"
    assert [v["code"] for v in state["visited"]] == ["FRA"]
    assert state["trips"][0]["destination"] == "Rome"
