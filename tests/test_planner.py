import pytest

from orbit import planner


@pytest.fixture
def live(app, monkeypatch):
    """Google Maps 'on', with the network calls faked and counted."""
    app.config.update(GOOGLE_MAPS_API_KEY="fake-key", PLACES_FREE_DAILY=2,
                      PLACES_GLOBAL_DAILY_CAP=100)
    calls = []

    def fake_search(query, bias=None, limit=10):
        calls.append(query)
        return [{"id": f"ChIJplace{i:04d}", "displayName": {"text": f"{query} #{i}"},
                 "rating": 4.5, "userRatingCount": 500, "formattedAddress": "1 Harbour St",
                 "googleMapsUri": "https://maps.google.com/?cid=1"} for i in range(2)]

    monkeypatch.setattr(planner, "places_text_search", fake_search)
    monkeypatch.setattr(planner, "geocode_place", lambda place: (38.0, 23.7))
    return calls


def test_live_results_use_the_daily_allowance(make_user, live):
    c, user = make_user()
    assert user["live_left"] == 2

    first = c.get("/api/itinerary?place=Chania").json
    assert first["live"] and first["live_left"] == 1
    assert len(live) == 4  # one Places query per category
    item = first["items"][0]
    assert item["source"] == "google" and item["place_id"] == "ChIJplace0000"
    assert "query_place_id=ChIJplace0000" in item["maps_url"]

    # nothing is cached (Google's terms), so a repeat search is a fresh lookup
    again = c.get("/api/itinerary?place=Chania").json
    assert again["live"] and again["live_left"] == 0 and len(live) == 8

    capped = c.get("/api/itinerary?place=Heraklion").json
    assert not capped["live"] and capped["live_limited"]
    assert capped["curated"]  # Heraklion falls back to the curated Crete list
    assert len(live) == 8


def test_saved_trips_keep_only_what_google_allows(app, make_user, live):
    c, _ = make_user()
    plan = c.get("/api/itinerary?place=Chania").json
    live_item = plan["items"][0]
    assert live_item["rating"] and live_item["desc"] is not None
    trip_id = c.post("/api/trips", json={"destination": "Chania", "items": [
        live_item,
        {"category": "Must-see", "title": "Our own tip", "desc": "ORBIT's curated text",
         "maps_url": "https://www.google.com/maps/search/?api=1&query=tip"},
    ]}).json["saved_trip_id"]
    google, curated = c.get(f"/api/trips/{trip_id}").json["items"]
    assert google["title"] == live_item["title"] and google["from_google"]
    assert "query_place_id=ChIJplace0000" in google["maps_url"]
    assert google["rating"] is None and google["rating_count"] is None
    assert google["detail"] is None and google["open_days"] is None and google["address"] is None
    assert curated["detail"] == "ORBIT's curated text" and not curated["from_google"]


def test_geocoding_uses_local_places(app):
    with app.app_context():
        assert planner.geocode_place("Chania, Greece") == pytest.approx((35.511, 24.029), abs=0.01)
        assert planner.geocode_place("Nowhere-at-all-ville") is None


def test_pro_plan_gets_more(app, make_user, live):
    import sqlite3
    c, user = make_user()
    db = sqlite3.connect(app.config["DATABASE_PATH"])
    db.execute("UPDATE users SET plan='pro' WHERE id=?", (user["id"],))
    db.commit()
    state = c.get("/api/state").json
    assert state["plan"] == "pro" and state["live_left"] == app.config["PLACES_PRO_DAILY"]


def test_global_budget_stops_everyone(app, make_user, live):
    app.config["PLACES_GLOBAL_DAILY_CAP"] = 1
    a, _ = make_user("A")
    b, _ = make_user("B")
    assert a.get("/api/itinerary?place=Chania").json["live"]
    resp = b.get("/api/itinerary?place=Tokyo").json
    assert not resp["live"] and resp["live_limited"]


def test_curated_and_starter_lists_without_google(client, make_user):
    c, user = make_user()
    assert user["live_places"] is False
    crete = c.get("/api/itinerary?place=Crete").json
    assert crete["curated"] and crete["destination"] == "Crete, Greece"
    starter = c.get("/api/itinerary?place=Nowhereville").json
    assert not starter["curated"] and len(starter["items"]) == 8
    assert c.get("/api/itinerary").status_code == 400


def test_destinations_are_public(client):
    dests = client.get("/api/destinations").json
    assert len(dests) >= 20 and {"destination", "country", "tagline"} <= set(dests[0])
