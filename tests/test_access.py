"""Nobody can read or change another traveller's data."""

import pytest


PROTECTED = [
    ("get", "/api/state"),
    ("post", "/api/visited"),
    ("delete", "/api/visited"),
    ("post", "/api/visited_city"),
    ("post", "/api/wishlist"),
    ("post", "/api/friends"),
    ("get", "/api/compare/1"),
    ("post", "/api/trips"),
    ("get", "/api/trips/1"),
    ("get", "/api/itinerary?place=Rome"),
    ("patch", "/api/account"),
    ("get", "/api/account/export"),
    ("delete", "/api/account"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_signed_out_gets_401(client, method, path):
    resp = getattr(client, method)(path, json={}) if method != "get" else client.get(path)
    assert resp.status_code == 401
    assert resp.json["error"]


def test_user_id_from_the_browser_is_ignored(make_user):
    ann_c, ann = make_user("Ann")
    bo_c, bo = make_user("Bo")
    ann_c.post("/api/visited", json={"code": "FRA"})

    # the old API let you pick any profile by id — now the session decides
    resp = bo_c.get(f"/api/state?user_id={ann['id']}")
    assert resp.json["id"] == bo["id"] and resp.json["visited"] == []
    bo_c.post("/api/visited", json={"code": "JPN", "user_id": ann["id"]})
    ann_state = ann_c.get("/api/state").json
    assert [v["code"] for v in ann_state["visited"]] == ["FRA"]


def test_wishlist_items_are_private(make_user):
    ann_c, _ = make_user("Ann")
    bo_c, _ = make_user("Bo")
    item = ann_c.post("/api/wishlist", json={"place": "Crete, Greece"}).json["wishlist"][0]
    assert item["code"] == "GRC"
    bo_c.delete(f"/api/wishlist/{item['id']}", json={})
    assert len(ann_c.get("/api/state").json["wishlist"]) == 1


def test_compare_needs_friendship(make_user):
    ann_c, ann = make_user("Ann")
    bo_c, bo = make_user("Bo")
    assert bo_c.get(f"/api/compare/{ann['id']}").status_code == 403
    bo_c.post("/api/friends", json={"share_code": ann["share_code"]})
    ann_c.post("/api/visited", json={"code": "ITA"})
    data = bo_c.get(f"/api/compare/{ann['id']}").json
    assert [v["code"] for v in data["visited"]] == ["ITA"]
    # friendship is mutual
    assert [f["username"] for f in ann_c.get("/api/state").json["friends"]] == ["Bo"]


def test_friend_code_errors(make_user):
    ann_c, ann = make_user("Ann")
    assert ann_c.post("/api/friends", json={"share_code": "ZZZZZZ"}).status_code == 404
    assert ann_c.post("/api/friends", json={"share_code": ann["share_code"]}).status_code == 400


def test_rotating_share_code_keeps_friends(make_user):
    ann_c, ann = make_user("Ann")
    bo_c, _ = make_user("Bo")
    bo_c.post("/api/friends", json={"share_code": ann["share_code"]})
    new = ann_c.post("/api/share_code/rotate", json={}).json
    assert new["share_code"] != ann["share_code"] and len(new["friends"]) == 1
    carl_c, _ = make_user("Carl")
    assert carl_c.post("/api/friends", json={"share_code": ann["share_code"]}).status_code == 404


def _trip(client, invite=None):
    body = {"destination": "Rome, Italy", "country": "Italy",
            "items": [{"category": "Must-see", "title": "Colosseum", "desc": "Old",
                       "maps_url": "https://maps.google.com/?q=colosseum", "open_days": "0111111"},
                      {"category": "Night out", "title": "Trastevere",
                       "maps_url": "javascript:alert(1)", "open_days": "nonsense"}]}
    if invite:
        body["invite_ids"] = invite
    return client.post("/api/trips", json=body).json


def test_trip_permissions(make_user):
    ann_c, ann = make_user("Ann")
    bo_c, bo = make_user("Bo")
    eve_c, _ = make_user("Eve")
    bo_c.post("/api/friends", json={"share_code": ann["share_code"]})
    trip_id = _trip(ann_c, invite=[bo["id"]])["saved_trip_id"]

    trip = ann_c.get(f"/api/trips/{trip_id}").json
    assert [m["username"] for m in trip["members"]] == ["Bo"]
    item_id = trip["items"][0]["id"]

    # strangers see nothing and change nothing
    assert eve_c.get(f"/api/trips/{trip_id}").status_code == 404
    assert eve_c.post(f"/api/trips/{trip_id}/items/{item_id}/toggle", json={}).status_code == 404
    assert eve_c.post(f"/api/trips/{trip_id}/items/{item_id}/vote", json={}).status_code == 404
    eve_c.delete(f"/api/trips/{trip_id}", json={})
    assert ann_c.get(f"/api/trips/{trip_id}").status_code == 200

    # members can tick and vote, but not delete items or invite
    assert bo_c.post(f"/api/trips/{trip_id}/items/{item_id}/toggle", json={}).json["items"][0]["done"] == 1
    assert bo_c.post(f"/api/trips/{trip_id}/items/{item_id}/vote", json={}).json["items"][0]["votes"] == 1
    assert bo_c.delete(f"/api/trips/{trip_id}/items/{item_id}", json={}).status_code == 403
    assert bo_c.post(f"/api/trips/{trip_id}/members", json={"friend_id": ann["id"]}).status_code == 403

    # only friends can be invited
    carl_c, carl = make_user("Carl")
    resp = ann_c.post(f"/api/trips/{trip_id}/members", json={"friend_id": carl["id"]})
    assert resp.status_code == 400

    # a member can leave; the trip leaves their list
    left = bo_c.delete(f"/api/trips/{trip_id}/members/{bo['id']}", json={}).json
    assert left["trips"] == []


def test_trip_item_urls_are_sanitised(make_user):
    ann_c, _ = make_user("Ann")
    trip_id = _trip(ann_c)["saved_trip_id"]
    items = ann_c.get(f"/api/trips/{trip_id}").json["items"]
    assert items[0]["maps_url"].startswith("https://")
    assert items[1]["maps_url"] is None  # javascript: links are dropped
    # opening days only ever came from Google, which saved trips no longer keep
    assert items[0]["open_days"] is None and items[1]["open_days"] is None


def test_visiting_a_city_marks_its_country(make_user):
    c, _ = make_user()
    state = c.post("/api/visited_city", json={"name": "Kyoto", "iso2": "JP", "lat": 35, "lng": 135.7}).json
    assert [v["code"] for v in state["visited"]] == ["JPN"]
    state = c.delete("/api/visited", json={"code": "JPN"}).json
    assert state["visited_cities"] == []
