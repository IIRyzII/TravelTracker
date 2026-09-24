"""JSON shapes the frontend renders: the signed-in user's world, and one trip."""

from flask import current_app

from .plans import entitlements, live_lookups_left


def user_payload(db, user):
    uid = user["id"]
    visited = [dict(r) for r in db.execute(
        "SELECT country_code AS code, country_name AS name FROM visited "
        "WHERE user_id=? ORDER BY country_name", (uid,))]
    wishlist = [dict(r) for r in db.execute(
        "SELECT id, place, country_code AS code, country_name AS country "
        "FROM wishlist WHERE user_id=? ORDER BY id DESC", (uid,))]
    visited_cities = [dict(r) for r in db.execute(
        "SELECT name, iso2, lat, lng FROM visited_cities WHERE user_id=? ORDER BY name", (uid,))]
    friends = [dict(r) for r in db.execute(
        "SELECT u.id, u.username, "
        "(SELECT COUNT(*) FROM visited v WHERE v.user_id=u.id) AS visited_count, "
        "(SELECT COUNT(*) FROM visited v JOIN visited mine "
        "   ON mine.country_code=v.country_code AND mine.user_id=? "
        " WHERE v.user_id=u.id) AS overlap "
        "FROM friends f JOIN users u ON u.id=f.friend_id WHERE f.user_id=? "
        "ORDER BY u.username COLLATE NOCASE", (uid, uid))]

    trip_rows = db.execute(
        "SELECT t.*, u.username AS owner_name, "
        "(SELECT COUNT(*) FROM trip_items i WHERE i.trip_id=t.id) AS item_count, "
        "(SELECT COALESCE(SUM(done), 0) FROM trip_items i WHERE i.trip_id=t.id) AS done_count "
        "FROM trips t JOIN users u ON u.id=t.user_id "
        "WHERE t.user_id=? OR t.id IN (SELECT trip_id FROM trip_members WHERE user_id=?) "
        "ORDER BY t.id DESC", (uid, uid)).fetchall()
    members = {}
    if trip_rows:
        marks = ",".join("?" * len(trip_rows))
        for r in db.execute(
                f"SELECT m.trip_id, u.username FROM trip_members m JOIN users u ON u.id=m.user_id "
                f"WHERE m.trip_id IN ({marks}) ORDER BY u.username COLLATE NOCASE",
                [t["id"] for t in trip_rows]):
            members.setdefault(r["trip_id"], []).append(r["username"])
    trips = [{
        "id": t["id"], "destination": t["destination"], "country": t["country"],
        "created_at": t["created_at"], "flight_number": t["flight_number"],
        "start_date": t["start_date"], "end_date": t["end_date"],
        "item_count": t["item_count"], "done_count": t["done_count"],
        "owner": t["owner_name"], "is_owner": t["user_id"] == uid,
        "members": members.get(t["id"], []),
    } for t in trip_rows]

    live = bool(current_app.config["GOOGLE_MAPS_API_KEY"])
    return {
        "id": uid,
        "username": user["username"],
        "email": user["email"],
        "has_password": bool(user["password_hash"]),
        "google_linked": bool(user["google_sub"]),
        "share_code": user["share_code"],
        "plan": entitlements(user)["plan"],
        "visited": visited,
        "visited_cities": visited_cities,
        "wishlist": wishlist,
        "friends": friends,
        "trips": trips,
        "live_places": live,
        "live_left": live_lookups_left(db, user) if live else 0,
    }


def trip_payload(db, trip, user):
    items = [dict(r) for r in db.execute(
        "SELECT i.id, i.category, i.title, i.detail, i.rating, i.rating_count, "
        "i.address, i.maps_url, i.open_days, i.done, (i.place_id IS NOT NULL) AS from_google, "
        "(SELECT COUNT(*) FROM trip_votes v WHERE v.item_id=i.id) AS votes, "
        "EXISTS(SELECT 1 FROM trip_votes v WHERE v.item_id=i.id AND v.user_id=?) AS my_vote "
        "FROM trip_items i WHERE i.trip_id=? ORDER BY i.id", (user["id"], trip["id"]))]
    owner = db.execute("SELECT id, username FROM users WHERE id=?", (trip["user_id"],)).fetchone()
    members = [dict(r) for r in db.execute(
        "SELECT u.id, u.username FROM trip_members m JOIN users u ON u.id=m.user_id "
        "WHERE m.trip_id=? ORDER BY u.username COLLATE NOCASE", (trip["id"],))]
    return {"id": trip["id"], "destination": trip["destination"], "country": trip["country"],
            "tagline": trip["tagline"], "created_at": trip["created_at"],
            "flight_number": trip["flight_number"], "start_date": trip["start_date"],
            "end_date": trip["end_date"], "items": items,
            "owner": dict(owner), "members": members,
            "is_owner": trip["user_id"] == user["id"]}
