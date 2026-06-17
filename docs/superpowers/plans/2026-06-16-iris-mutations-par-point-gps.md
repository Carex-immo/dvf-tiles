# IRIS + mutations DVF par point GPS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exposer, pour un point GPS, toutes les mutations DVF de la zone IRIS qui le contient, via une couche tuiles `iris` (résolution locale) + des fichiers statiques `/iris/{code_iris}.json` (contour + stats + mutations).

**Architecture:** Le pipeline DuckDB existant est étendu : `prepare.py` persiste les mutations en Parquet ; un nouveau module `build_iris.py` réalise la **jointure spatiale** `ST_Within(point_mutation, polygone_iris)`, exporte `build/iris_layer.geojson` (source de la couche tuile) et un JSON par IRIS dans `build/iris/`. `build_tiles.sh` ajoute la couche `iris` à `dvf.pmtiles`. Côté app, l'IRIS est résolu par décodage MVT + point-in-polygon, puis le JSON est chargé depuis le CDN. Tout est statique.

**Tech Stack:** Python 3 + DuckDB (extension `spatial`), GDAL/`ogr2ogr`, tippecanoe + tile-join (PMTiles), pytest, shapely (simulateur). Client iOS **MapLibreGL** hors repo.

> **Mise à jour (juin 2026) :** le client iOS est passé de **MapKit à MapLibreGL** (déployé, hors de ce repo). Le squelette `client/DvfTileClient.swift` a été **retiré** et la tâche iOS Swift/MapKit **purgée** de ce plan (cf. Task 9). Les **contrats de données** que l'app consomme (JSON `stats/iris/{code}.json`, couche tuile `iris`) restent définis par `pipeline/build_iris.py` et la spec §7/§8.

**Spec :** [docs/superpowers/specs/2026-06-16-iris-mutations-par-point-gps-design.md](../specs/2026-06-16-iris-mutations-par-point-gps-design.md)

> **Pré-requis git :** le dossier n'est pas sous git. Pour suivre la méthodologie (commits fréquents), exécuter `git init` d'abord ; sinon ignorer les étapes « Commit ».
> **Pré-requis outils :** `pip install duckdb shapely pytest` ; `ogr2ogr` (GDAL) ; `tippecanoe`/`tile-join`. La 1ʳᵉ exécution de DuckDB `INSTALL spatial` nécessite un accès réseau.

---

## File Structure

| Fichier | Responsabilité | Action |
|---|---|---|
| `pipeline/iris_latest.py` | Détecte la dernière édition CONTOURS-IRIS (flux Atom paginé) | **Créé (validé)** |
| `pipeline/download.sh` | Téléchargement sources (DVF + IRIS) | Modifier (ajout IRIS) |
| `pipeline/prepare.py` | Préparation mutations + agrégats commune/dept | Modifier (1 ligne : export Parquet) |
| `pipeline/build_iris.py` | Jointure spatiale + export couche IRIS + JSON par IRIS | **Créer** |
| `pipeline/build_tiles.sh` | Construction PMTiles | Modifier (couche `iris`) |
| `tests/test_build_iris.py` | Tests unitaires de `build_iris.py` | **Créer** |
| `client/simulate_iris.py` | Proxy Python du chemin iOS (GPS→IRIS→JSON) | **Créer** |
| `demo/index.html` | Validation visuelle | Modifier (couche `iris`) |
| `README.md` | Doc | Modifier |

---

## Task 1 : Télécharger et reprojeter les contours IRIS

**Files:**
- Existe déjà: `pipeline/iris_latest.py` (détecteur d'édition, validé)
- Modify: `pipeline/download.sh`
- Produit: `data/geo/CONTOURS-IRIS.gpkg` (déjà en WGS84 — **aucune reprojection**)

> **Pas de reprojection :** l'édition GPKG **WGS84G** est déjà en EPSG:4326 (lon/lat). DuckDB `ST_Read` lit le `.gpkg` directement (Task 3), donc `ogr2ogr` n'est plus nécessaire.
> **URL réelle :** le lien de téléchargement est `…/telechargement/**download**/CONTOURS-IRIS/{EDITION}/{EDITION}.7z` (et non `/resource/`). On ne le code pas en dur : `iris_latest.py` le résout.

- [ ] **Step 1 : Câbler la détection + téléchargement dans `download.sh`**

Ajouter à la fin de `pipeline/download.sh` :

```bash
# --- Contours IRIS : résout la dernière édition GPKG WGS84 puis télécharge ---
# (GEO_DIR fixé : le 3e arg du script est déjà le dossier raw)
GEO_DIR="data/geo"
mkdir -p "$GEO_DIR"
if [ ! -f "$GEO_DIR/CONTOURS-IRIS.gpkg" ]; then
  IRIS_URL=$(python3 pipeline/iris_latest.py | awk '/^url/ {print $3}')
  echo "Téléchargement IRIS : $IRIS_URL"
  curl -fL -o "$GEO_DIR/iris.7z" "$IRIS_URL"
  7z x -y -o"$GEO_DIR/iris_extract" "$GEO_DIR/iris.7z"
  GPKG=$(find "$GEO_DIR/iris_extract" -iname '*.gpkg' | head -n1)
  cp "$GPKG" "$GEO_DIR/CONTOURS-IRIS.gpkg"
fi
```

> Pour **figer** un millésime, remplacer la résolution par une variable épinglée
> `IRIS_URL="https://data.geopf.fr/telechargement/download/CONTOURS-IRIS/CONTOURS-IRIS_3-0__GPKG_WGS84G_FRA_2026-01-01/CONTOURS-IRIS_3-0__GPKG_WGS84G_FRA_2026-01-01.7z"`.

- [ ] **Step 2 : Exécuter et vérifier le contenu du GPKG**

Run :
```bash
./pipeline/download.sh "2021 2022 2023 2024 2025" "69 01" data/raw
python3 -c "
import duckdb
con=duckdb.connect(); con.execute('INSTALL spatial; LOAD spatial;')
print(con.execute(\"SELECT count(*) FROM ST_Read('data/geo/CONTOURS-IRIS.gpkg')\").fetchone()[0], 'IRIS')
print([c[0] for c in con.execute(\"DESCRIBE SELECT * FROM ST_Read('data/geo/CONTOURS-IRIS.gpkg')\").fetchall()])
"
```
Expected : ~49 000 IRIS (France entière) ; colonnes incluant `CODE_IRIS`, `NOM_IRIS`, `INSEE_COM`, `NOM_COM`, `geom`. Si les noms diffèrent (casse/accents), adapter le `SELECT` de `load_iris` en Task 3.

- [ ] **Step 3 : Commit**

```bash
git add pipeline/download.sh pipeline/iris_latest.py
git commit -m "feat(pipeline): détecte et télécharge la dernière édition CONTOURS-IRIS (GPKG WGS84)"
```

---

## Task 2 : Persister les mutations en Parquet depuis `prepare.py`

**Files:**
- Modify: `pipeline/prepare.py` (après l'export GeoJSONL des mutations, ~ligne 155)

- [ ] **Step 1 : Ajouter l'export Parquet**

Dans `pipeline/prepare.py`, juste après le bloc qui écrit `mutations.geojsonl` (après la ligne `print("->", out_pts, ...)`), insérer :

```python
    # Export Parquet (réutilisé par build_iris.py pour la jointure spatiale IRIS)
    out_parquet = os.path.join(args.out, "mutations.parquet")
    con.execute(f"COPY (SELECT {', '.join(cols)}, lon, lat FROM mutations) "
                f"TO '{out_parquet}' (FORMAT parquet)")
    print("->", out_parquet)
```

> `cols` est déjà défini juste au-dessus : `["id","date","annee","nat","type","vf","sb","st","pm2","np","nl","nc","dep","com"]`. Le Parquet contient donc les 14 attributs + `lon`,`lat`.

- [ ] **Step 2 : Exécuter `prepare.py` et vérifier la cohérence**

Run :
```bash
python3 pipeline/prepare.py --raw data/raw --geo data/geo --out build
python3 -c "import duckdb; print('parquet:', duckdb.sql(\"SELECT count(*) FROM 'build/mutations.parquet'\").fetchone()[0])"
wc -l build/mutations.geojsonl
```
Expected : le nombre de lignes du Parquet == nombre de lignes du `.geojsonl` (mutations uniques géolocalisées, ~249 361 sur le POC 69/01).

- [ ] **Step 3 : Commit**

```bash
git add pipeline/prepare.py
git commit -m "feat(pipeline): persiste les mutations en Parquet pour la jointure IRIS"
```

---

## Task 3 : `build_iris.py` — jointure spatiale mutation→IRIS (TDD)

**Files:**
- Create: `pipeline/build_iris.py`
- Test: `tests/test_build_iris.py`

- [ ] **Step 1 : Écrire le test de jointure (échoue)**

Créer `tests/test_build_iris.py` :

```python
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
```

- [ ] **Step 2 : Lancer le test (échec attendu)**

Run : `pytest tests/test_build_iris.py::test_join_assigns_code_iris -v`
Expected : FAIL (`ModuleNotFoundError: build_iris` ou `AttributeError`).

- [ ] **Step 3 : Implémenter le socle de `build_iris.py`**

Créer `pipeline/build_iris.py` :

```python
#!/usr/bin/env python3
"""CAREX — Jointure spatiale mutations DVF → IRIS, export couche tuile + JSON par IRIS."""
import argparse
import json
import os

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
    # duckdb 1.5+ : le type peut inclure le SRID, ex. GEOMETRY('EPSG:4326')
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
      FROM mut m JOIN iris i ON ST_Within(m.pt, i.geom)
    """)
```

- [ ] **Step 4 : Lancer le test (succès attendu)**

Run : `pytest tests/test_build_iris.py::test_join_assigns_code_iris -v`
Expected : PASS.

- [ ] **Step 5 : Commit**

```bash
git add pipeline/build_iris.py tests/test_build_iris.py
git commit -m "feat(pipeline): jointure spatiale mutations→IRIS (DuckDB ST_Within)"
```

---

## Task 4 : `build_iris.py` — JSON par IRIS (TDD)

**Files:**
- Modify: `pipeline/build_iris.py`
- Test: `tests/test_build_iris.py`

- [ ] **Step 1 : Écrire le test de schéma JSON (échoue)**

Ajouter à `tests/test_build_iris.py` :

```python
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
    assert "lon" in m and "lat" in m
```

- [ ] **Step 2 : Lancer le test (échec attendu)**

Run : `pytest tests/test_build_iris.py::test_export_iris_json -v`
Expected : FAIL (`AttributeError: module 'build_iris' has no attribute 'export_iris_json'`).

- [ ] **Step 3 : Implémenter `export_iris_json`**

Ajouter à `pipeline/build_iris.py` :

```python
def export_iris_json(con, out_dir, millesime):
    os.makedirs(out_dir, exist_ok=True)
    codes = [r[0] for r in con.execute(
        "SELECT DISTINCT code_iris FROM mut_iris").fetchall()]
    for code in codes:
        meta = con.execute("""
          SELECT any_value(nom_iris), any_value(insee_com), any_value(nom_com),
                 count(*)::INT, CAST(median(pm2) AS INT)
          FROM mut_iris WHERE code_iris = ?
        """, [code]).fetchone()
        contour = con.execute(
            "SELECT ST_AsGeoJSON(any_value(geom)) FROM iris WHERE code_iris = ?",
            [code]).fetchone()[0]
        par = {}
        for annee, typ, n, p in con.execute("""
              SELECT annee, type, count(*)::INT, CAST(median(pm2) AS INT)
              FROM mut_iris WHERE code_iris = ? GROUP BY annee, type
            """, [code]).fetchall():
            entry = {"n": n}
            if p is not None:
                entry["pm2_med"] = p
            par.setdefault(str(annee), {})[f"t{typ}"] = entry
        muts = []
        for r in con.execute(
                f"SELECT {', '.join(COLS)} FROM mut_iris WHERE code_iris = ?",
                [code]).fetchall():
            muts.append({k: v for k, v in zip(COLS, r) if v is not None})
        stats = {"n_tot": meta[3]}
        if meta[4] is not None:
            stats["pm2_med"] = meta[4]
        stats["par_annee_type"] = par
        obj = {"code_iris": code, "nom_iris": meta[0], "insee_com": meta[1],
               "nom_com": meta[2], "millesime_iris": millesime,
               "contour": json.loads(contour), "stats": stats, "mutations": muts}
        with open(os.path.join(out_dir, f"{code}.json"), "w") as f:
            json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    return len(codes)
```

- [ ] **Step 4 : Lancer le test (succès attendu)**

Run : `pytest tests/test_build_iris.py::test_export_iris_json -v`
Expected : PASS.

- [ ] **Step 5 : Commit**

```bash
git add pipeline/build_iris.py tests/test_build_iris.py
git commit -m "feat(pipeline): export JSON par IRIS (contour + stats + mutations)"
```

---

## Task 5 : `build_iris.py` — couche tuile `iris_layer.geojson` (TDD)

**Files:**
- Modify: `pipeline/build_iris.py`
- Test: `tests/test_build_iris.py`

- [ ] **Step 1 : Écrire le test de la couche (échoue)**

Ajouter à `tests/test_build_iris.py` :

```python
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
    assert f["properties"]["pm2_med"] == 5000   # médiane de 5000 et 2500 -> 3750 ? non
    assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
```

> Note : pour l'IRIS A, `pm2` vaut 5000 (a) et 2500 (b) → `median` = 3750. Corriger l'assertion en `== 3750` avant de lancer (laisser volontairement vérifier le comportement de `median`).

- [ ] **Step 2 : Corriger l'assertion puis lancer (échec attendu)**

Remplacer la ligne d'assertion par : `assert f["properties"]["pm2_med"] == 3750`.
Run : `pytest tests/test_build_iris.py::test_export_iris_layer -v`
Expected : FAIL (`AttributeError: ... 'export_iris_layer'`).

- [ ] **Step 3 : Implémenter `export_iris_layer`**

Ajouter à `pipeline/build_iris.py` :

```python
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
```

- [ ] **Step 4 : Lancer tous les tests (succès attendu)**

Run : `pytest tests/test_build_iris.py -v`
Expected : 3 PASS.

- [ ] **Step 5 : Commit**

```bash
git add pipeline/build_iris.py tests/test_build_iris.py
git commit -m "feat(pipeline): export couche tuile iris_layer.geojson (agrégats)"
```

---

## Task 6 : CLI `build_iris.py` + exécution sur le POC

**Files:**
- Modify: `pipeline/build_iris.py` (ajout `main`)

- [ ] **Step 1 : Ajouter le `main` CLI**

Ajouter à la fin de `pipeline/build_iris.py` :

```python
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutations", default="build/mutations.parquet")
    ap.add_argument("--iris", default="data/geo/CONTOURS-IRIS.gpkg")  # ST_Read lit GPKG ou GeoJSON
    ap.add_argument("--out", default="build")
    ap.add_argument("--millesime", default="2024")
    args = ap.parse_args()
    con = connect()
    load_iris(con, args.iris)
    load_mutations(con, args.mutations)
    join(con)
    n_layer = export_iris_layer(con, os.path.join(args.out, "iris_layer.geojson"))
    n_json = export_iris_json(con, os.path.join(args.out, "iris"), args.millesime)
    print(f"iris_layer: {n_layer} entités | iris/*.json: {n_json} fichiers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2 : Exécuter sur les données du POC**

Run :
```bash
python3 pipeline/build_iris.py --millesime 2024
ls build/iris/*.json | wc -l
python3 -c "import json; o=json.load(open(sorted(__import__('glob').glob('build/iris/*.json'))[0])); print(o['code_iris'], len(o['mutations']), 'mut'); assert 'contour' in o and 'stats' in o"
```
Expected : ~1 000–1 500 fichiers ; chaque JSON contient `contour`, `stats`, `mutations`.

- [ ] **Step 3 : Contrôle métier (médiane Lyon centre)**

Run :
```bash
python3 -c "
import glob, json
best=None
for p in glob.glob('build/iris/691*.json'):       # IRIS de Lyon (INSEE 6938x/69123)
    o=json.load(open(p))
    t2=o['stats'].get('pm2_med')
    n=o['stats']['n_tot']
    if t2 and n>50 and (best is None or n>best[2]): best=(o['code_iris'],t2,n)
print('IRIS Lyon le plus dense:', best)
"
```
Expected : médiane €/m² dans l'ordre de grandeur ~3 500–6 500 (cohérent avec ~4 810 €/m² du POC).

- [ ] **Step 4 : Commit**

```bash
git add pipeline/build_iris.py
git commit -m "feat(pipeline): CLI build_iris + génération IRIS sur le POC 69/01"
```

---

## Task 7 : Ajouter la couche `iris` à `dvf.pmtiles`

**Files:**
- Modify: `pipeline/build_tiles.sh`

- [ ] **Step 1 : Construire la couche `iris` et la joindre**

Le script fait `cd "$BUILD"` (chemins relatifs, un fichier par couche, style `-l <couche>`). Avant le bloc `== fusion ==`, ajouter (cohérent avec le bloc `communes`) :

```bash
echo "== iris (polygones, z10-14 : résolution GPS→IRIS + choroplèthe) =="
tippecanoe -o iris.pmtiles -l iris \
  -Z10 -z14 \
  --coalesce-densest-as-needed --detect-shared-borders \
  --force --quiet \
  iris_layer.geojson
```

Puis ajouter `iris.pmtiles` à la commande `tile-join` finale :

```bash
tile-join -o dvf.pmtiles --force --no-tile-size-limit \
  mutations.pmtiles iris.pmtiles communes.pmtiles departements.pmtiles
```

- [ ] **Step 2 : Reconstruire et vérifier la présence de la couche**

Run :
```bash
./pipeline/build_tiles.sh build
pmtiles show build/dvf.pmtiles | grep -i iris || \
  tippecanoe-decode build/dvf.pmtiles 12 2065 1420 2>/dev/null | grep -o '"iris"' | head -n1
```
Expected : la couche `iris` apparaît dans les métadonnées vecteur de `dvf.pmtiles`.

- [ ] **Step 3 : Commit**

```bash
git add pipeline/build_tiles.sh
git commit -m "feat(pipeline): ajoute la couche tuile iris (z10-14) à dvf.pmtiles"
```

---

## Task 8 : Simulateur Python du chemin iOS (GPS→IRIS→JSON)

**Files:**
- Create: `client/simulate_iris.py`
- Test: `tests/test_simulate_iris.py`

- [ ] **Step 1 : Écrire le test (échoue)**

Créer `tests/test_simulate_iris.py` :

```python
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
import simulate_iris


def _layer(path):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"code_iris": "100000000"},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}}]}
    json.dump(fc, open(path, "w"))


def test_resolve_iris_at(tmp_path):
    layer = str(tmp_path / "iris_layer.geojson"); _layer(layer)
    assert simulate_iris.resolve_iris_at(layer, lon=0.5, lat=0.5) == "100000000"
    assert simulate_iris.resolve_iris_at(layer, lon=9.0, lat=9.0) is None
```

- [ ] **Step 2 : Lancer le test (échec attendu)**

Run : `pytest tests/test_simulate_iris.py -v`
Expected : FAIL (`ModuleNotFoundError: simulate_iris`).

- [ ] **Step 3 : Implémenter `simulate_iris.py`**

Créer `client/simulate_iris.py` :

```python
#!/usr/bin/env python3
"""Proxy Python du chemin iOS : point GPS -> IRIS -> mutations.

Côté iOS, la résolution GPS->IRIS se fait par décodage MVT de la couche `iris`
puis point-in-polygon ; ici on valide la même logique sur iris_layer.geojson.
"""
import argparse
import json
import os

from shapely.geometry import shape, Point


def resolve_iris_at(layer_geojson, lon, lat):
    """Retourne le code_iris contenant (lon, lat), ou None."""
    pt = Point(lon, lat)
    fc = json.load(open(layer_geojson))
    for ft in fc["features"]:
        if shape(ft["geometry"]).contains(pt):
            return ft["properties"]["code_iris"]
    return None


def mutations_at(layer_geojson, iris_dir, lon, lat):
    """Résout l'IRIS puis charge ses mutations depuis iris/{code}.json."""
    code = resolve_iris_at(layer_geojson, lon, lat)
    if code is None:
        return None, []
    path = os.path.join(iris_dir, f"{code}.json")
    if not os.path.exists(path):
        return code, []
    return code, json.load(open(path))["mutations"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", default="build/iris_layer.geojson")
    ap.add_argument("--iris-dir", default="build/iris")
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--lat", type=float, required=True)
    args = ap.parse_args()
    code, muts = mutations_at(args.layer, args.iris_dir, args.lon, args.lat)
    print(f"IRIS = {code} | {len(muts)} mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4 : Lancer le test (succès attendu)**

Run : `pytest tests/test_simulate_iris.py -v`
Expected : PASS.

- [ ] **Step 5 : Valider bout-en-bout sur le POC (point dans Lyon)**

Run :
```bash
python3 client/simulate_iris.py --lon 4.8512 --lat 45.7601
```
Expected : `IRIS = 6938x...` avec un nombre de mutations > 0.

- [ ] **Step 6 : Commit**

```bash
git add client/simulate_iris.py tests/test_simulate_iris.py
git commit -m "feat(client): simulateur Python GPS→IRIS→mutations (proxy iOS)"
```

---

## Task 9 : Client iOS — consommation IRIS (hors repo)

> Le client iOS est désormais **MapLibreGL** et vit **hors de ce repo** ; le squelette MapKit `client/DvfTileClient.swift` et tout son code Swift ont été **retirés**. Tâche conservée pour la mémoire de structure du plan.
>
> **Contrat consommé par l'app** (référence canonique : `pipeline/build_iris.py` + spec §7/§8) :
> - **Résolution GPS→IRIS** : décoder la couche tuile `iris` couvrant le point, point-in-polygon sur les polygones → `code_iris`.
> - **Fetch détail** : `GET {baseURL}/stats/iris/{code_iris}.json` → `{ code_iris, nom_iris, insee_com, nom_com, millesime_iris, contour (GeoJSON), stats, mutations[] }`.
> - **Filtrage** des `mutations` en mémoire ; **surlignage** du `contour` GeoJSON sur la carte.

---

## Task 10 : Démo + documentation

**Files:**
- Modify: `demo/index.html`, `README.md`

- [ ] **Step 1 : Ajouter la couche `iris` à la démo MapLibre**

Dans `demo/index.html`, après l'ajout de la source PMTiles, ajouter une couche de remplissage `iris` colorée par `pm2_med`, et un handler de clic qui charge `build/iris/{code_iris}.json` et affiche le nombre de mutations. Exemple de couche :

```javascript
map.addLayer({
  id: 'iris-fill', type: 'fill', source: 'dvf', 'source-layer': 'iris',
  minzoom: 10, maxzoom: 14,
  paint: {
    'fill-opacity': 0.5,
    'fill-color': ['interpolate', ['linear'], ['get', 'pm2_med'],
      1000, '#2c7bb6', 4000, '#ffffbf', 8000, '#d7191c']
  }
});
map.on('click', 'iris-fill', async (e) => {
  const code = e.features[0].properties.code_iris;
  const r = await fetch(`/build/iris/${code}.json`);
  const o = await r.json();
  alert(`IRIS ${code} — ${o.stats.n_tot} mutations`);
});
```

- [ ] **Step 2 : Vérifier visuellement**

Run : `python3 demo/serve.py` puis ouvrir `http://localhost:8080/demo/index.html`, zoomer ≥10, cliquer un IRIS.
Expected : zones IRIS colorées ; le clic affiche le nombre de mutations.

- [ ] **Step 3 : Documenter dans le README**

Dans `README.md`, ajouter à la section « Reproduire » la commande IRIS et décrire la couche/les fichiers :

```bash
python3 pipeline/build_iris.py --millesime 2024   # couche iris + build/iris/*.json
```

Et ajouter à l'arborescence : `build/iris/{code_iris}.json` (contour + stats + mutations) et `pipeline/build_iris.py`. Mentionner la couche `iris` (z10–14) dans la liste des couches de `dvf.pmtiles`.

- [ ] **Step 4 : Lancer toute la suite de tests**

Run : `pytest tests/ -v`
Expected : tous les tests PASS (test_build_iris : 3, test_simulate_iris : 1).

- [ ] **Step 5 : Commit**

```bash
git add demo/index.html README.md
git commit -m "docs: démo couche IRIS + documentation du flux GPS→IRIS→mutations"
```

---

## Self-Review (couverture du spec)

- **§3 flux GPS→IRIS→JSON** → Tasks 7 (couche tuile), 9 (résolution iOS), 8 (proxy Python). ✓
- **§4 source CONTOURS-IRIS** → Task 1. ✓
- **§5 couche tuile `iris` (z10–14, attributs)** → Tasks 5 (geojson), 7 (tippecanoe). ✓
- **§6 JSON `/iris/{code_iris}.json` (contour + stats + 14 attrs)** → Task 4. ✓
- **§7 pipeline (Parquet, ST_Within, exports, build_tiles, publication)** → Tasks 2, 3, 4, 5, 6, 7. ✓
- **§8 côté iOS** → Task 9. ✓
- **§9 cas limites (hors IRIS = pas de données)** → Task 8 (`resolve_iris_at` → None), Task 9 (détail IRIS absent). ✓
- **§10 critères d'acceptation** → couverts par les vérifications des Tasks 6, 7, 8 + démo Task 10. ✓

Cohérence des types : `code_iris`, `nom_iris`, `insee_com`, `nom_com`, `n_tot`, `pm2_med`, `par_annee_type[année][t{type}] = {n, pm2_med}`, `COLS` (14 attrs + lon/lat) — identiques entre spec, `build_iris.py` et JSON. ✓

> **Publication (spec §7.5)** non couverte par une tâche de code (opération d'infra : `rsync`/`aws s3 sync build/iris/ s3://.../dvf/v1/iris/` + `dvf.pmtiles`). À traiter au déploiement, hors plan d'implémentation.
