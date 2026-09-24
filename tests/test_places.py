"""City search on ORBIT's own place data, and the script that enriches it."""

import os
import sys

import pytest

from orbit.places import PlaceIndex, fold, index

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
import build_places  # noqa: E402


@pytest.mark.parametrize("a,b", [
    ("Zürich", "Zuerich"), ("Zurich", "Zuerich"), ("Kraków", "Krakow"), ("São Paulo", "Sao Paulo"),
    ("St. Ives", "Saint Ives"), ("Straße", "Strasse"), ("Tromsø", "Tromso"), ("KÖLN", "Koeln"),
])
def test_fold_treats_spellings_alike(a, b):
    assert fold(a) == fold(b)


def names(query, **kw):
    return [(r["name"], r["iso2"]) for r in index().search(query, **kw)]


def test_search_the_bundled_places():
    assert names("Paris")[0] == ("Paris", "FR")          # biggest exact match first
    assert names("Zürich")[0] == ("Zuerich", "CH")       # accents and ü/ue don't matter
    assert names("krakow")[0] == ("Krakow", "PL")
    assert names("São Paulo")[0] == ("Sao Paulo", "BR")
    assert ("Saint Ives", "GB") in names("St Ives")
    assert names("Ho Chi")[0] == ("Ho Chi Minh City", "VN")   # prefix
    assert ("New York City", "US") in names("york", limit=40)  # a later word, after exact Yorks
    assert names("x") == [] and names("") == []


def test_results_carry_country_names():
    top = index().search("Kyoto")[0]
    assert top["country"] == "Japan" and top["lat"] == pytest.approx(35.02, abs=0.1)


def test_find_uses_the_country_hint():
    assert index().find("Paris, United States of America")["iso2"] == "US"
    assert index().find("Paris")["iso2"] == "FR"
    assert index().find("Chania, Greece")["name"] == "Chania"


def test_cities_endpoint(client):
    res = client.get("/api/cities?q=Reykjav%C3%ADk").json
    assert res[0]["name"] == "Reykjavik" and res[0]["country"] == "Iceland"
    assert set(res[0]) == {"name", "country", "iso2", "admin", "lat", "lng", "pop"}
    assert client.get("/api/cities?q=a").json == []


def test_other_names_and_regions_are_searchable():
    """What scripts/build_places.py adds: München finds Munich, regions tell
    same-named places apart."""
    idx = PlaceIndex([
        ["Munich", "DE", 48.137, 11.575, 1505005, "Bavaria", ["München", "Monaco di Baviera"]],
        ["Portland", "US", 45.523, -122.676, 652503, "Oregon", []],
        ["Portland", "US", 43.661, -70.255, 68408, "Maine", []],
    ])
    assert idx.search("München")[0]["name"] == "Munich"
    assert idx.search("monaco di")[0]["name"] == "Munich"
    assert [r["admin"] for r in idx.search("Portland")] == ["Oregon", "Maine"]
    assert idx.find("Portland, Maine")["lat"] == 43.661


GEONAMES_LINES = [
    # id, name, asciiname, alternatenames, lat, lng, class, code, cc, cc2, admin1, …, population
    "2657896\tZürich\tZurich\tZRH,Zuerich,Zurigo,Цюрих,https://en.wikipedia.org/wiki/Zurich,Zürich"
    "\t47.36667\t8.55\tP\tPPLA\tCH\t\t25\t\t\t\t341730\t\t\tEurope/Zurich\t2024-01-01",
    "1\tSmallville\tSmallville\t\t10\t10\tP\tPPL\tUS\t\tKS\t\t\t\t400\t\t\t\t",
    "2\tOld Town\tOld Town\t\t10\t10\tP\tPPLH\tGB\t\tENG\t\t\t\t50000\t\t\t\t",
]
ADMIN1_LINES = ["CH.25\tZürich\tZurich\t2657895"]


def test_build_places_parses_geonames():
    rows = build_places.parse_rows(GEONAMES_LINES, ADMIN1_LINES)
    assert len(rows) == 1  # under 1,000 people and historical places are dropped
    name, iso2, lat, lng, pop, region, others = rows[0]
    assert (name, iso2, lat, lng, pop, region) == ("Zurich", "CH", 47.367, 8.55, 341730, "Zurich")
    # the accented name and Latin alternates become search terms; codes, links,
    # other scripts and duplicates of the main name don't
    assert others == ["Zurigo"]
