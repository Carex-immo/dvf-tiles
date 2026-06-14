"""Tests de l'extracteur de stats (pipeline/stats_bundles.py) — jeu DuckDB
synthétique déterministe, indépendant d'un build réel."""
import json
import os
import sys

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stats_bundles import years, entity_stats, build_stats_bundles, _dept_of  # noqa: E402


def _con():
    """Connexion DuckDB avec une vue stats_src synthétique.
    Commune 01001 (dense pour seuil=4) : 1 vente t1 2023 + 5 ventes t1 2024 (Q1)
    + 1 terrain nu (type NULL) 2024 Q2. Commune 01002 : 2 ventes t2 2024 (creux)."""
    con = duckdb.connect()
    con.execute("""
    CREATE VIEW stats_src AS SELECT * FROM (VALUES
      ('01001','01', 1,    200000, 100,  500,    4, 20230615, 2000.0, 2023),
      ('01001','01', 1,    300000,  50, NULL,    3, 20240115, 1000.0, 2024),
      ('01001','01', 1,    300000,  50, NULL,    3, 20240115, 2000.0, 2024),
      ('01001','01', 1,    300000,  50, NULL,    3, 20240115, 3000.0, 2024),
      ('01001','01', 1,    300000,  50, NULL,    3, 20240115, 4000.0, 2024),
      ('01001','01', 1,    300000,  50, NULL,    3, 20240115, 5000.0, 2024),
      ('01001','01', NULL,  50000, NULL, 800, NULL, 20240515,   NULL, 2024),
      ('01002','01', 2,    240000,  60, NULL,    3, 20240715, 4000.0, 2024),
      ('01002','01', 2,    360000,  80, NULL,    3, 20240715, 6000.0, 2024)
    ) AS t(com, dep, type, vf, sb, st, np, date, pm2, annee)
    """)
    return con


def test_years_tries():
    assert years(_con()) == [2023, 2024]


def test_entity_stats_commune_dense():
    con = _con()
    out = entity_stats(con, "com", {"01001": "A", "01002": "B"},
                       years(con), dense_threshold=4)
    a = out["01001"]
    assert a["nom"] == "A"
    assert a["n_tot"] == 7
    assert a["pm2_med"] == 2500
    assert a["vf_med"] == 300000
    assert a["years"] == [2023, 2024]
    assert a["overall"]["n"] == [1, 6]
    assert a["overall"]["pm2_med"] == [2000, 3000]
    t1 = a["byType"]["1"]
    assert t1["n"] == [1, 5]
    assert t1["pm2_med"] == [2000, 3000]
    assert t1["vf_med"] == [200000, 300000]
    assert t1["sb_med"] == [100, 50]
    assert t1["st_med"] == [500, None]
    assert t1["np_med"] == [4, 3]
    # dense (n_tot 7 >= 4) : seul 2024Q1 atteint n>=5
    assert a["quarters"] == [{"p": "2024Q1", "n": 5, "pm2_med": 3000}]


def test_entity_stats_commune_creuse_alignee():
    con = _con()
    out = entity_stats(con, "com", {"01001": "A", "01002": "B"},
                       years(con), dense_threshold=4)
    b = out["01002"]
    assert b["n_tot"] == 2
    assert b["pm2_med"] == 5000
    assert "quarters" not in b              # n_tot 2 < 4 : pas de trimestriel
    assert b["overall"]["n"] == [0, 2]      # 2023 absent -> 0, aligné sur years
    assert b["overall"]["pm2_med"] == [None, 5000]
    t2 = b["byType"]["2"]
    assert t2["n"] == [0, 2]
    assert t2["pm2_med"] == [None, 5000]
    assert t2["sb_med"] == [None, 70]
    assert t2["np_med"] == [None, 3]


def test_build_stats_bundles_ecrit_arbre(tmp_path):
    con = _con()
    out = str(tmp_path)
    compteurs = build_stats_bundles(
        con, {"01001": "A", "01002": "B"}, {"01": "Ain"},
        out, version="V1", dense_threshold=4)

    man = json.load(open(os.path.join(out, "stats", "manifest.json")))
    assert man["version"] == "V1"
    assert man["years"] == [2023, 2024]
    assert man["dense_threshold"] == 4
    assert man["departements"] == ["01"]
    assert compteurs == {"departements": 1, "communes": 2, "bundles_dep": 1}

    dep = json.load(open(os.path.join(out, "stats", "departements.json")))
    assert dep["version"] == "V1"
    assert {e["code"] for e in dep["entities"]} == {"01"}
    assert dep["entities"][0]["n_tot"] == 9          # toutes les ventes du dépt

    com = json.load(open(os.path.join(out, "stats", "dep", "01.json")))
    assert com["version"] == "V1"
    assert {e["code"] for e in com["entities"]} == {"01001", "01002"}


def test_dept_of():
    assert _dept_of("01001") == "01"
    assert _dept_of("2A004") == "2A"
    assert _dept_of("97123") == "971"


def _ecrire_geojson(path, ntot_par_code):
    feats = [{"type": "Feature",
              "properties": {"code": c, "nom": c, "n_tot": n},
              "geometry": None} for c, n in ntot_par_code.items()]
    json.dump({"type": "FeatureCollection", "features": feats}, open(path, "w"))


def _build_dir_coherent(tmp_path):
    """Génère un build/ minimal cohérent : bundles + geojson aux mêmes n_tot."""
    con = _con()
    out = str(tmp_path)
    build_stats_bundles(con, {"01001": "A", "01002": "B"}, {"01": "Ain"},
                        out, version="V1", dense_threshold=4)
    # geojson alignés sur les n_tot des bundles (01001=7, 01002=2, dépt 01=9)
    _ecrire_geojson(os.path.join(out, "communes.geojson"),
                    {"01001": 7, "01002": 2})
    _ecrire_geojson(os.path.join(out, "departements.geojson"), {"01": 9})
    return out


def test_check_stats_bundles_ok(tmp_path):
    from qa_checks import check_stats_bundles
    out = _build_dir_coherent(tmp_path)
    errors, warnings = [], []
    report = check_stats_bundles(out, errors, warnings)
    assert errors == []
    assert report["version"] == "V1"
    assert report["communes"] == 2


def test_check_stats_bundles_detecte_divergence_ntot(tmp_path):
    from qa_checks import check_stats_bundles
    out = _build_dir_coherent(tmp_path)
    # casser la parité : n_tot geojson != bundle pour 01001
    _ecrire_geojson(os.path.join(out, "communes.geojson"),
                    {"01001": 999, "01002": 2})
    errors, warnings = [], []
    check_stats_bundles(out, errors, warnings)
    assert any("01001" in e and "n_tot" in e for e in errors)


def test_check_stats_bundles_detecte_version_incoherente(tmp_path):
    from qa_checks import check_stats_bundles
    out = _build_dir_coherent(tmp_path)
    p = os.path.join(out, "stats", "dep", "01.json")
    b = json.load(open(p))
    b["version"] = "AUTRE"
    json.dump(b, open(p, "w"))
    errors, warnings = [], []
    check_stats_bundles(out, errors, warnings)
    assert any("version" in e for e in errors)
