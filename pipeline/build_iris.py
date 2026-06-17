#!/usr/bin/env python3
"""CAREX — Jointure spatiale mutations DVF → IRIS, export couche tuile + JSON par IRIS."""
import argparse
import json
import os
from decimal import Decimal

import duckdb

COLS = ["id", "date", "annee", "nat", "type", "vf", "sb", "st",
        "pm2", "np", "nl", "nc", "dep", "com", "lon", "lat"]


def connect():
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    return con


def load_iris(con, iris_path):
    # Schémas hétérogènes : le GPKG IGN v3.0 expose code_iris/nom_iris/code_insee/
    # nom_commune/geometrie (minuscules, géom = 'geometrie') ; un GeoJSON via ST_Read
    # expose les propriétés telles quelles + géom nommée 'geom'. On normalise :
    desc = con.execute(
        f"DESCRIBE SELECT * FROM ST_Read('{iris_path}')").fetchall()
    cols = {c[0].lower(): c[0] for c in desc}
    # DuckDB spatial >= 1.5 expose le type géométrie sous la forme
    # "GEOMETRY('EPSG:4326')" (SRID inclus) ; on matche donc le préfixe
    # plutôt qu'une égalité stricte à "GEOMETRY".
    geom = next(c[0] for c in desc if c[1].upper().startswith("GEOMETRY"))

    def pick(*names):
        for n in names:
            if n in cols:
                return cols[n]
        raise KeyError(f"colonne IRIS introuvable parmi {names} ; dispo: {list(cols)}")

    con.execute(f"""
      CREATE OR REPLACE TABLE iris AS
      SELECT "{pick('code_iris')}"   AS code_iris,
             "{pick('nom_iris')}"    AS nom_iris,
             "{pick('code_insee', 'insee_com')}"  AS insee_com,
             "{pick('nom_commune', 'nom_com')}"   AS nom_com,
             "{geom}"                AS geom
      FROM ST_Read('{iris_path}')
    """)


def load_mutations(con, mutations_parquet):
    con.execute(f"""
      CREATE OR REPLACE TABLE mut AS
      SELECT *, ST_Point(lon, lat) AS pt
      FROM read_parquet('{mutations_parquet}')
    """)


def join(con):
    con.execute("""
      CREATE OR REPLACE TABLE mut_iris AS
      SELECT m.* EXCLUDE (pt),
             i.code_iris, i.nom_iris, i.insee_com, i.nom_com
      FROM mut m JOIN iris i
        ON m.com = i.insee_com AND ST_Within(m.pt, i.geom)
    """)


def _json_default(o):
    # DuckDB renvoie les colonnes DECIMAL (ex. lon/lat) sous forme de Decimal,
    # non sérialisable par json ; on les convertit en float.
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def export_iris_json(con, out_dir, millesime):
    """Un JSON par IRIS. Conçu pour l'échelle France (~49k IRIS, millions de
    mutations) : agrégats chargés en 3 requêtes globales (petits, ~49k entrées),
    puis mutations streamées triées par code_iris et écrites IRIS par IRIS
    (mémoire bornée à une seule zone à la fois)."""
    os.makedirs(out_dir, exist_ok=True)

    meta = {}
    for code, nom_iris, insee, nom_com, n_tot, pm2 in con.execute("""
          SELECT code_iris, any_value(nom_iris), any_value(insee_com),
                 any_value(nom_com), count(*)::INT, CAST(median(pm2) AS INT)
          FROM mut_iris GROUP BY code_iris""").fetchall():
        meta[code] = (nom_iris, insee, nom_com, n_tot, pm2)

    par = {}
    for code, annee, typ, n, p in con.execute("""
          SELECT code_iris, annee, type, count(*)::INT, CAST(median(pm2) AS INT)
          FROM mut_iris GROUP BY code_iris, annee, type""").fetchall():
        entry = {"n": n}
        if p is not None:
            entry["pm2_med"] = p
        par.setdefault(code, {}).setdefault(str(annee), {})[f"t{typ}"] = entry

    contour = dict(con.execute("""
          SELECT i.code_iris, ST_AsGeoJSON(any_value(i.geom))
          FROM iris i
          WHERE i.code_iris IN (SELECT code_iris FROM mut_iris)
          GROUP BY i.code_iris""").fetchall())

    def write(code, muts):
        nom_iris, insee, nom_com, n_tot, pm2 = meta[code]
        stats = {"n_tot": n_tot}
        if pm2 is not None:
            stats["pm2_med"] = pm2
        stats["par_annee_type"] = par.get(code, {})
        obj = {"code_iris": code, "nom_iris": nom_iris, "insee_com": insee,
               "nom_com": nom_com, "millesime_iris": millesime,
               "contour": json.loads(contour[code]), "stats": stats,
               "mutations": muts}
        with open(os.path.join(out_dir, f"{code}.json"), "w") as f:
            json.dump(obj, f, separators=(",", ":"), ensure_ascii=False,
                      default=_json_default)

    n_files, cur, buf = 0, None, []
    reader = con.execute(
        f"SELECT code_iris, {', '.join(COLS)} FROM mut_iris ORDER BY code_iris")
    while True:
        rows = reader.fetchmany(50000)
        if not rows:
            break
        for r in rows:
            code = r[0]
            if code != cur:
                if cur is not None:
                    write(cur, buf)
                    n_files += 1
                cur, buf = code, []
            buf.append({k: v for k, v in zip(COLS, r[1:]) if v is not None})
    if cur is not None:
        write(cur, buf)
        n_files += 1
    return n_files


def export_iris_layer(con, out_path):
    rows = con.execute("""
      WITH agg AS (
        SELECT code_iris,
               any_value(nom_iris) AS nom_iris,
               any_value(insee_com) AS insee_com,
               any_value(nom_com) AS nom_com,
               count(*)::INT AS n_tot,
               CAST(median(pm2) AS INT) AS pm2_med
        FROM mut_iris GROUP BY code_iris
      )
      SELECT a.code_iris, a.nom_iris, a.insee_com, a.nom_com,
             a.n_tot, a.pm2_med, ST_AsGeoJSON(any_value(i.geom)) AS geojson
      FROM agg a JOIN iris i USING (code_iris)
      GROUP BY 1, 2, 3, 4, 5, 6
    """).fetchall()
    feats = []
    for code_iris, nom_iris, insee_com, nom_com, n_tot, pm2_med, geojson in rows:
        props = {"code_iris": code_iris, "nom_iris": nom_iris,
                 "insee_com": insee_com, "nom_com": nom_com, "n_tot": n_tot}
        if pm2_med is not None:
            props["pm2_med"] = pm2_med
        feats.append({"type": "Feature",
                      "geometry": json.loads(geojson), "properties": props})
    with open(out_path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f,
                  separators=(",", ":"), ensure_ascii=False)
    return len(feats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutations", default="build/mutations.parquet")
    ap.add_argument("--iris", default="data/geo/CONTOURS-IRIS.gpkg")  # ST_Read lit GPKG ou GeoJSON
    ap.add_argument("--out", default="build")
    ap.add_argument("--millesime", default="2026")
    args = ap.parse_args()
    con = connect()
    load_iris(con, args.iris)
    load_mutations(con, args.mutations)
    join(con)
    # Sanity : mutations non rattachées à un IRIS (commune absente du millésime IRIS,
    # ou code commune DVF ≠ insee_com IRIS — cas Paris/Lyon/Marseille à surveiller).
    n_mut, n_joined = (con.execute("SELECT count(*) FROM mut").fetchone()[0],
                       con.execute("SELECT count(*) FROM mut_iris").fetchone()[0])
    if n_joined < n_mut:
        print(f"⚠ {n_mut - n_joined}/{n_mut} mutations non rattachées à un IRIS")
    n_layer = export_iris_layer(con, os.path.join(args.out, "iris_layer.geojson"))
    n_json = export_iris_json(con, os.path.join(args.out, "iris"), args.millesime)
    print(f"iris_layer: {n_layer} entités | iris/*.json: {n_json} fichiers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
