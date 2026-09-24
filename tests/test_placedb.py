"""The server's database of every populated place (orbit/placedb.py)."""

import io
import zipfile

import pytest

from orbit import placedb

REGIONS = ["GR.43\tCrete\tCrete\t1", "CH.25\tZuerich\tZurich\t2", "FJ.03\tNorthern\tNorthern\t3"]


def line(gid, name, lat, lng, pop, cc="GR", code="PPL", cls="P", utf8=None, alts="", admin1="43"):
    return (f"{gid}\t{utf8 or name}\t{name}\t{alts}\t{lat}\t{lng}\t{cls}\t{code}\t{cc}\t\t{admin1}"
            f"\t\t\t\t{pop}\t\t\tEurope/Athens\t2024-01-01")


DUMP = [
    line(1, "Chania", 35.511, 24.029, 53910, alts="Hania,Xania,Χανιά,CHQ"),
    line(2, "Kolymvari", 35.54, 23.78, 900),                    # a village near Chania
    line(3, "Orbitville", 35.37, 24.2, 0),                      # a hamlet, no population figure
    line(4, "Sfakia", 35.2, 24.14, 0),
    line(5, "Zurich", 47.367, 8.55, 415367, cc="CH", admin1="25", utf8="Zürich", alts="Zurigo,ZRH"),
    line(6, "Old Knossos", 35.3, 25.16, 5000, code="PPLH"),    # historical: skipped
    line(7, "Souda Bay", 35.49, 24.07, 0, cls="S"),             # not a populated place: skipped
    line(8, "Nadi", -17.8, 179.95, 800, cc="FJ", admin1="03"),  # just west of the date line
    line(9, "Labasa", -16.43, -179.61, 600, cc="FJ", admin1="03"),  # just east of it
]


@pytest.fixture
def built(tmp_path):
    path = str(tmp_path / "places.db")
    placedb.build_database(path, iter(DUMP), placedb.read_regions(REGIONS), log=lambda m: None)
    return placedb.PlaceDatabase(path), path


def test_only_populated_places_are_kept(built):
    db, _ = built
    names = {r["name"] for r in db._db().execute("SELECT name FROM places")}
    assert names == {"Chania", "Kolymvari", "Orbitville", "Sfakia", "Zurich", "Nadi", "Labasa"}


def test_search_finds_towns_villages_and_other_names(built):
    db, _ = built
    assert db.search("Chania")[0]["name"] == "Chania"
    assert db.search("Hania")[0]["name"] == "Chania"             # alternate name
    assert db.search("Zürich")[0]["name"] == "Zurich"            # accented form
    assert db.search("Zurigo")[0]["admin"] == "Zurich"           # region comes along
    assert db.search("orbitv")[0]["name"] == "Orbitville"        # a hamlet
    assert db.search("or") == []                                 # 2 letters: towns only
    assert db.search("kolymvari")[0]["country"] == "Greece"
    assert db.search("CHQ") == [] and db.search("Χανιά") == []   # codes and other scripts dropped


def test_find_and_the_bundled_fallback_agree(built):
    db, _ = built
    assert db.find("Chania, Greece")["name"] == "Chania"
    assert db.find("Zurich, Switzerland")["iso2"] == "CH"


def test_villages_near(built):
    db, _ = built
    near = db.villages_near(35.45, 24.1, 1.0)
    assert {v["name"] for v in near} <= {"Kolymvari", "Orbitville", "Sfakia"}
    assert "Kolymvari" in {v["name"] for v in near}             # biggest village in its cell
    assert all(v["pop"] < placedb.BIG for v in near)             # towns ship with the app
    assert db.villages_near(0, 0, 1.0) == []
    # across the date line, both sides come back
    assert {v["name"] for v in db.villages_near(-17.0, 180.0, 2.0)} == {"Nadi", "Labasa"}


def test_endpoints_use_the_database(app, make_user, built):
    _, path = built
    client, _ = make_user()
    assert client.get("/api/config").json["villages"] is False
    assert client.get("/api/places/near?lat=35.45&lng=24.1&radius=1").json == []  # not built yet
    assert client.get("/api/cities?q=orbitv").json == []           # bundled list: towns only

    app.config["PLACES_DB_PATH"] = path
    assert client.get("/api/config").json["villages"] is True
    near = client.get("/api/places/near?lat=35.45&lng=24.1&radius=1").json
    assert "Kolymvari" in {v["name"] for v in near}
    assert client.get("/api/cities?q=orbitv").json[0]["name"] == "Orbitville"
    assert client.get("/api/places/near?lat=x&lng=1").status_code == 400


def test_villages_need_sign_in(client):
    assert client.get("/api/places/near?lat=1&lng=1&radius=1").status_code == 401


def test_build_from_geonames_downloads_and_cleans_up(tmp_path, monkeypatch):
    files = {"admin1CodesASCII.txt": "\n".join(REGIONS).encode()}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("allCountries.txt", "\n".join(DUMP))
    files["allCountries.zip"] = archive.getvalue()

    def fake_download(name, dest_dir):
        dest = tmp_path / name
        dest.write_bytes(files[name])
        return str(dest)

    monkeypatch.setattr(placedb, "download", fake_download)
    path = str(tmp_path / "places.db")
    assert placedb.build_from_geonames(path, log=lambda m: None) == 7
    assert sorted(p.name for p in tmp_path.iterdir()) == ["places.db"]  # downloads removed
    assert placedb.PlaceDatabase(path).search("Chania")[0]["pop"] == 53910
