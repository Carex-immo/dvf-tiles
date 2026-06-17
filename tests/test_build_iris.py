import json, os, sys, duckdb
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
import build_iris


def _make_iris(path):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"CODE_IRIS": "100000000", "NOM_IRIS": "A",
                        "INSEE_COM": "10000", "NOM_COM": "Ville A"},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}},
        {"type": "Feature",
         "properties": {"CODE_IRIS": "200000000", "NOM_IRIS": "B",
                        "INSEE_COM": "20000", "NOM_COM": "Ville B"},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[1, 0], [1, 1], [2, 1], [2, 0], [1, 0]]]}}]}
    json.dump(fc, open(path, "w"))


def _make_mut(path):
    con = duckdb.connect()
    con.execute("""CREATE TABLE m AS SELECT * FROM (VALUES
      ('a',20240101,2024,1,2,300000,60,0,5000,3,1,0,'10','10000',0.5,0.5),
      ('b',20230601,2023,1,1,200000,80,200,2500,4,1,2,'10','10000',0.2,0.8),
      ('c',20240201,2024,1,2,250000,50,0,5000,2,1,0,'20','20000',1.5,0.5)
    ) AS t(id,date,annee,nat,type,vf,sb,st,pm2,np,nl,nc,dep,com,lon,lat)""")
    con.execute(f"COPY m TO '{path}' (FORMAT parquet)")


def _prepared(tmp_path):
    iris = str(tmp_path / "iris.geojson"); _make_iris(iris)
    mut = str(tmp_path / "mut.parquet"); _make_mut(mut)
    con = build_iris.connect()
    build_iris.load_iris(con, iris)
    build_iris.load_mutations(con, mut)
    build_iris.join(con)
    return con


def test_join_assigns_code_iris(tmp_path):
    con = _prepared(tmp_path)
    rows = dict(con.execute(
        "SELECT id, code_iris FROM mut_iris ORDER BY id").fetchall())
    assert rows == {"a": "100000000", "b": "100000000", "c": "200000000"}


def test_export_iris_json(tmp_path):
    con = _prepared(tmp_path)
    out = str(tmp_path / "iris")
    n = build_iris.export_iris_json(con, out, millesime="2024")
    assert n == 2
    obj = json.load(open(os.path.join(out, "100000000.json")))
    # Métadonnées
    assert obj["code_iris"] == "100000000"
    assert obj["nom_com"] == "Ville A"
    assert obj["millesime_iris"] == "2024"
    # Contour GeoJSON présent
    assert obj["contour"]["type"] in ("Polygon", "MultiPolygon")
    # Stats : 2 mutations dans l'IRIS A, dont 1 appart 2024
    assert obj["stats"]["n_tot"] == 2
    assert obj["stats"]["par_annee_type"]["2024"]["t2"]["n"] == 1
    # Mutations : 14 attributs + lon/lat, liste complète
    assert len(obj["mutations"]) == 2
    m = next(x for x in obj["mutations"] if x["id"] == "a")
    assert m["type"] == 2 and m["vf"] == 300000 and m["pm2"] == 5000
    assert set(m) >= {"id", "date", "annee", "nat", "type", "vf", "sb", "st",
                      "pm2", "np", "nl", "nc", "dep", "com", "lon", "lat"}


def test_export_iris_layer(tmp_path):
    con = _prepared(tmp_path)
    out = str(tmp_path / "iris_layer.geojson")
    n = build_iris.export_iris_layer(con, out)
    assert n == 2
    fc = json.load(open(out))
    assert fc["type"] == "FeatureCollection"
    f = next(x for x in fc["features"]
             if x["properties"]["code_iris"] == "100000000")
    assert f["properties"]["n_tot"] == 2
    assert f["properties"]["pm2_med"] == 3750
    assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
