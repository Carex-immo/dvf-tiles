import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
import build_iris_index as bi


def _make_iris(path):
    # 01 : un IRIS concave en L (le centroïde tomberait HORS du polygone), + un carré.
    # 2A (Corse) et 974 (DOM) pour vérifier dep_of. INSEE_COM porté pour `com`.
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"CODE_IRIS": "010010000", "INSEE_COM": "01001"},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[0, 0], [4, 0], [4, 1], [1, 1], [1, 4], [0, 4], [0, 0]]]}},
        {"type": "Feature",
         "properties": {"CODE_IRIS": "010010001", "INSEE_COM": "01001"},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[5, 5], [6, 5], [6, 6], [5, 6], [5, 5]]]}},
        {"type": "Feature",
         "properties": {"CODE_IRIS": "2A0040000", "INSEE_COM": "2A004"},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]]}},
        {"type": "Feature",
         "properties": {"CODE_IRIS": "974010000", "INSEE_COM": "97401"},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[55, -21], [56, -21], [56, -20], [55, -20], [55, -21]]]}}]}
    json.dump(fc, open(path, "w"))


def test_dep_of():
    assert bi.dep_of("010010000") == "01"
    assert bi.dep_of("2A0040000") == "2A"
    assert bi.dep_of("974010000") == "974"
    assert bi.dep_of("971234567") == "971"


def test_build_index_grouping_schema_and_sort(tmp_path):
    p = str(tmp_path / "iris.geojson"); _make_iris(p)
    con = bi.connect(); bi.load_iris(con, p)
    by_dep = bi.build_index(con)
    assert set(by_dep) == {"01", "2A", "974"}
    assert [e["code"] for e in by_dep["01"]] == ["010010000", "010010001"]  # trié
    e = by_dep["01"][0]
    assert set(e) == {"code", "com", "lat", "lon", "bbox"}                  # schéma strict
    assert e["com"] == "01001"
    assert e["bbox"] == [0.0, 0.0, 4.0, 4.0]                                # bbox du L


def test_point_on_surface_inside_concave(tmp_path):
    p = str(tmp_path / "iris.geojson"); _make_iris(p)
    con = bi.connect(); bi.load_iris(con, p)
    e = bi.build_index(con)["01"][0]   # le L concave
    inside = con.execute(
        "SELECT ST_Within(ST_Point(?, ?), "
        "ST_GeomFromText('POLYGON((0 0,4 0,4 1,1 1,1 4,0 4,0 0))'))",
        [e["lon"], e["lat"]]).fetchone()[0]
    assert inside is True


def test_write_index(tmp_path):
    p = str(tmp_path / "iris.geojson"); _make_iris(p)
    con = bi.connect(); bi.load_iris(con, p)
    by_dep = bi.build_index(con)
    out_dir = str(tmp_path / "iris_index")
    n_files, n_iris = bi.write_index(by_dep, out_dir)
    assert (n_files, n_iris) == (3, 4)
    arr = json.load(open(os.path.join(out_dir, "01.json")))
    assert isinstance(arr, list)
    assert [x["code"] for x in arr] == ["010010000", "010010001"]
