#!/usr/bin/env python3
"""CAREX — Index IRIS départemental : stats/iris_index/{DD}.json.

Pour chaque IRIS de CONTOURS-IRIS : {code, com, lat, lon (point intérieur via
ST_PointOnSurface), bbox:[minLon,minLat,maxLon,maxLat]}. Un tableau JSON par
département, trié par code. Construit depuis la géométrie seule (aucune mutation)."""
import argparse
import json
import os

import duckdb


def connect():
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    return con


def dep_of(code):
    """Clé département alignée sur manifest.departements : 3 chars pour DOM/COM
    (97x/98x), 2 chars sinon (métropole 01-95 et Corse 2A/2B)."""
    return code[:3] if code[:2] in ("97", "98") else code[:2]


def load_iris(con, iris_path):
    # Schémas hétérogènes (GPKG IGN minuscules / GeoJSON via ST_Read) : on normalise
    # vers code_iris, insee_com, geom. Même approche que build_iris.load_iris.
    desc = con.execute(f"DESCRIBE SELECT * FROM ST_Read('{iris_path}')").fetchall()
    cols = {c[0].lower(): c[0] for c in desc}
    geom = next(c[0] for c in desc if c[1].upper().startswith("GEOMETRY"))

    def pick(*names):
        for n in names:
            if n in cols:
                return cols[n]
        raise KeyError(f"colonne IRIS introuvable parmi {names} ; dispo: {list(cols)}")

    con.execute(f"""
      CREATE OR REPLACE TABLE iris AS
      SELECT "{pick('code_iris')}"               AS code_iris,
             "{pick('code_insee', 'insee_com')}" AS insee_com,
             "{geom}"                            AS geom
      FROM ST_Read('{iris_path}')
    """)


def build_index(con):
    """{dep: [ {code, com, lat, lon, bbox}, ... trié par code ]}.
    PointOnSurface calculé une seule fois (CTE), coordonnées arrondies à 6 décimales."""
    rows = con.execute("""
      WITH pt AS (
        SELECT code_iris, insee_com,
               ST_PointOnSurface(geom) AS p,
               ST_XMin(geom) AS xmin, ST_YMin(geom) AS ymin,
               ST_XMax(geom) AS xmax, ST_YMax(geom) AS ymax
        FROM iris
      )
      SELECT code_iris, insee_com, ST_X(p) AS lon, ST_Y(p) AS lat,
             xmin, ymin, xmax, ymax
      FROM pt ORDER BY code_iris
    """).fetchall()

    def r6(v):
        return round(v, 6)

    by_dep = {}
    for code, com, lon, lat, xmin, ymin, xmax, ymax in rows:
        by_dep.setdefault(dep_of(code), []).append({
            "code": code, "com": com, "lat": r6(lat), "lon": r6(lon),
            "bbox": [r6(xmin), r6(ymin), r6(xmax), r6(ymax)]})
    return by_dep


def write_index(by_dep, out_dir):
    """Écrit out_dir/{DD}.json (tableau compact). Retourne (n_departements, n_iris)."""
    os.makedirs(out_dir, exist_ok=True)
    n_iris = 0
    for dep, entries in by_dep.items():
        with open(os.path.join(out_dir, f"{dep}.json"), "w") as f:
            json.dump(entries, f, separators=(",", ":"), ensure_ascii=False)
        n_iris += len(entries)
    return len(by_dep), n_iris


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iris", default="data/geo/CONTOURS-IRIS.gpkg")  # ST_Read : GPKG ou GeoJSON
    ap.add_argument("--out", default="build")
    args = ap.parse_args()
    con = connect()
    load_iris(con, args.iris)
    by_dep = build_index(con)
    out_dir = os.path.join(args.out, "iris_index")
    n_files, n_iris = write_index(by_dep, out_dir)
    print(f"iris_index : {n_files} départements, {n_iris} IRIS -> {out_dir}/{{DD}}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
