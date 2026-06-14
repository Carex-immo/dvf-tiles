"""Tests de l'extracteur de stats (pipeline/stats_bundles.py) — jeu DuckDB
synthétique déterministe, indépendant d'un build réel."""
import json
import os
import sys

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stats_bundles import years, entity_stats, _dept_of  # noqa: E402


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
