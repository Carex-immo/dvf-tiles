# Index IRIS départemental — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produire `stats/iris_index/{DD}.json` (un index spatial léger des IRIS par département) et enrichir, de façon additive, le `stats/manifest.json` existant.

**Architecture:** Deux scripts Python autonomes — `build_iris_index.py` (DuckDB spatial : géométrie CONTOURS-IRIS → tableaux `{code, com, lat, lon, bbox}` par département) et `patch_manifest.py` (merge additif des bits IRIS dans le manifest live, version préservée). Câblage dans `build_france.sh` (build) et `deploy_cli.sh` (upload + patch manifest). Aucune modification du chemin de décodage des tuiles.

**Tech Stack:** Python 3.13, DuckDB 1.5.3 + extension `spatial` (déjà dans `.venv`), pytest 9.1.0, Supabase CLI (`storage cp`).

## Global Constraints

- **Schéma d'une entrée d'index, strict :** `{"code": str(9), "com": str(5), "lat": float, "lon": float, "bbox": [minLon, minLat, maxLon, maxLat]}`. Aucun champ supplémentaire.
- **Point centre :** `ST_PointOnSurface` (jamais `ST_Centroid`). Coordonnées arrondies à **6 décimales**.
- **Clé département `{DD}` :** `code[:3]` si `code[:2] in ("97","98")`, sinon `code[:2]`.
- **JSON :** compact, `separators=(",", ":")`, `ensure_ascii=False`.
- **Manifest :** ne **jamais** minter ni modifier `version`, ni supprimer/altérer un champ existant. Ajouts autorisés uniquement : `millesime_iris`, `layers.iris_index`, `compteurs.iris`.
- **`layers.iris_index` vaut exactement :** `"stats/iris_index/{DD}.json"`.
- **Déploiement additif/non destructif :** ne touche ni `dvf.pmtiles` ni `stats/dep/`.
- Tests : pattern existant (`tests/test_build_iris.py`) — `sys.path.insert` vers `pipeline/`, GeoJSON synthétique via `ST_Read`, `tmp_path`.

---

### Task 1: `pipeline/build_iris_index.py`

**Files:**
- Create: `pipeline/build_iris_index.py`
- Test: `tests/test_build_iris_index.py`

**Interfaces:**
- Consumes: rien (point d'entrée pipeline).
- Produces (utilisé par Task 3 et les tests) :
  - `connect() -> duckdb.DuckDBPyConnection` (spatial chargé)
  - `dep_of(code: str) -> str`
  - `load_iris(con, iris_path: str) -> None` (crée la table `iris(code_iris, insee_com, geom)`)
  - `build_index(con) -> dict[str, list[dict]]` (dept → entrées triées par `code`)
  - `write_index(by_dep: dict, out_dir: str) -> tuple[int, int]` (`(n_departements, n_iris)`)

- [ ] **Step 1: Écrire le fichier de test**

`tests/test_build_iris_index.py` :

```python
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
```

- [ ] **Step 2: Lancer les tests → échec attendu**

Run: `cd "$(git rev-parse --show-toplevel)" && .venv/bin/python -m pytest tests/test_build_iris_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'build_iris_index'`.

- [ ] **Step 3: Écrire l'implémentation**

`pipeline/build_iris_index.py` :

```python
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
```

- [ ] **Step 4: Lancer les tests → succès attendu**

Run: `cd "$(git rev-parse --show-toplevel)" && .venv/bin/python -m pytest tests/test_build_iris_index.py -v`
Expected: PASS — 4 tests verts.

- [ ] **Step 5: Commit**

```bash
git add pipeline/build_iris_index.py tests/test_build_iris_index.py
git commit -m "feat(iris-index): build_iris_index.py — stats/iris_index/{DD}.json"
```

---

### Task 2: `pipeline/patch_manifest.py`

**Files:**
- Create: `pipeline/patch_manifest.py`
- Test: `tests/test_patch_manifest.py`

**Interfaces:**
- Consumes: répertoire produit par Task 1 (`{out}/iris_index/*.json`).
- Produces (utilisé par Task 3 et les tests) :
  - `load_manifest(url: str | None = None, file: str | None = None) -> dict`
  - `count_iris(iris_index_dir: str) -> tuple[int, list[str]]` (`(n_iris, [departements triés])`)
  - `merge(manifest: dict, millesime: str, n_iris: int) -> dict` (mute et retourne `manifest`)
  - `extra_deps(index_deps: list[str], manifest: dict) -> list[str]` (départements de l'index absents de `manifest["departements"]`, triés)
  - Constante `IRIS_INDEX_LAYER = "stats/iris_index/{DD}.json"`

- [ ] **Step 1: Écrire le fichier de test**

`tests/test_patch_manifest.py` :

```python
import copy, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
import patch_manifest as pm

LIVE = {"version": "20260614T102335Z", "generated": "20260614T102335Z",
        "dense_threshold": 200, "years": [2021, 2022, 2023, 2024, 2025],
        "layers": {"departements": "stats/departements.json",
                   "communes": "stats/dep/{DD}.json"},
        "departements": ["01", "2A", "974"],
        "compteurs": {"departements": 109, "communes": 34902, "bundles_dep": 100}}


def _index_dir(tmp_path):
    d = tmp_path / "iris_index"; d.mkdir()
    json.dump([{"code": "010010000"}, {"code": "010010001"}], open(d / "01.json", "w"))
    json.dump([{"code": "2A0040000"}], open(d / "2A.json", "w"))
    return str(d)


def test_count_iris(tmp_path):
    n, deps = pm.count_iris(_index_dir(tmp_path))
    assert n == 3
    assert deps == ["01", "2A"]


def test_merge_adds_iris_bits():
    m = pm.merge(copy.deepcopy(LIVE), "2026", 48000)
    assert m["millesime_iris"] == "2026"
    assert m["layers"]["iris_index"] == "stats/iris_index/{DD}.json"
    assert m["compteurs"]["iris"] == 48000


def test_merge_preserves_existing():
    m = pm.merge(copy.deepcopy(LIVE), "2026", 48000)
    assert m["version"] == "20260614T102335Z"          # version jamais touchée
    assert m["generated"] == "20260614T102335Z"
    assert m["dense_threshold"] == 200
    assert m["years"] == [2021, 2022, 2023, 2024, 2025]
    assert m["layers"]["communes"] == "stats/dep/{DD}.json"
    assert m["compteurs"]["bundles_dep"] == 100
    assert m["departements"] == ["01", "2A", "974"]


def test_merge_idempotent():
    m1 = pm.merge(copy.deepcopy(LIVE), "2026", 48000)
    m2 = pm.merge(copy.deepcopy(m1), "2026", 48000)
    assert m1 == m2


def test_load_manifest_file(tmp_path):
    p = tmp_path / "manifest.json"; json.dump(LIVE, open(p, "w"))
    assert pm.load_manifest(file=str(p))["version"] == "20260614T102335Z"


def test_extra_deps():
    # 975/977 sont dans l'index mais pas dans manifest.departements (cas réel DOM).
    assert pm.extra_deps(["01", "974", "975", "977"], LIVE) == ["975", "977"]
    assert pm.extra_deps(["01", "2A"], LIVE) == []
```

- [ ] **Step 2: Lancer les tests → échec attendu**

Run: `cd "$(git rev-parse --show-toplevel)" && .venv/bin/python -m pytest tests/test_patch_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'patch_manifest'`.

- [ ] **Step 3: Écrire l'implémentation**

`pipeline/patch_manifest.py` :

```python
#!/usr/bin/env python3
"""CAREX — Enrichit le manifest stats existant avec les bits IRIS (additif).

⚠️ stats/manifest.json est généré par un pipeline externe (communes/départements
+ version). Ce script NE mint PAS de version : il charge le manifest live, AJOUTE
millesime_iris + layers.iris_index + compteurs.iris, et préserve tout le reste.
Idempotent. Une seule source de version (le pipeline stats)."""
import argparse
import glob
import json
import os
import urllib.request

IRIS_INDEX_LAYER = "stats/iris_index/{DD}.json"


def load_manifest(url=None, file=None):
    if url:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read())
    with open(file) as f:
        return json.load(f)


def count_iris(iris_index_dir):
    """(n_iris_total, [departements triés]) depuis iris_index/*.json."""
    deps, n = [], 0
    for path in sorted(glob.glob(os.path.join(iris_index_dir, "*.json"))):
        deps.append(os.path.splitext(os.path.basename(path))[0])
        n += len(json.load(open(path)))
    return n, deps


def merge(manifest, millesime, n_iris):
    """Ajoute/maj les 3 clés IRIS ; ne supprime ni n'altère aucune autre clé.
    Idempotent."""
    manifest["millesime_iris"] = millesime
    manifest.setdefault("layers", {})["iris_index"] = IRIS_INDEX_LAYER
    manifest.setdefault("compteurs", {})["iris"] = n_iris
    return manifest


def extra_deps(index_deps, manifest):
    """Départements présents dans l'index mais absents de manifest.departements
    (triés). Le client n'itère que manifest.departements : ces fichiers sont posés
    mais jamais demandés — on les signale (cas réel : 975-978)."""
    listed = set(manifest.get("departements", []))
    return sorted(d for d in index_deps if d not in listed)


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest-url")
    src.add_argument("--manifest-file")
    ap.add_argument("--iris-index-dir", default="build/iris_index")
    ap.add_argument("--millesime", default="2026")
    ap.add_argument("--out", default="build/manifest.json")
    args = ap.parse_args()

    manifest = load_manifest(url=args.manifest_url, file=args.manifest_file)
    n_iris, deps = count_iris(args.iris_index_dir)
    extra = extra_deps(deps, manifest)
    merge(manifest, args.millesime, n_iris)
    with open(args.out, "w") as f:
        json.dump(manifest, f, separators=(",", ":"), ensure_ascii=False)
    print(f"manifest enrichi -> {args.out} : version={manifest.get('version')} "
          f"(préservée), millesime_iris={args.millesime}, iris={n_iris}, "
          f"{len(deps)} dépt iris_index")
    if extra:
        print(f"  ⚠ {len(extra)} dépt dans l'index absents de manifest.departements "
              f"(non demandés par le client) : {', '.join(extra)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Lancer les tests → succès attendu**

Run: `cd "$(git rev-parse --show-toplevel)" && .venv/bin/python -m pytest tests/test_patch_manifest.py -v`
Expected: PASS — 6 tests verts.

- [ ] **Step 5: Commit**

```bash
git add pipeline/patch_manifest.py tests/test_patch_manifest.py
git commit -m "feat(iris-index): patch_manifest.py — merge additif des bits IRIS"
```

---

### Task 3: Câblage build + deploy

**Files:**
- Modify: `pipeline/build_france.sh` (insérer une étape après l'étape 2)
- Modify: `deploy/deploy_cli.sh` (insérer après la boucle de chunks `stats/iris`)

**Interfaces:**
- Consumes: `build_iris_index.py` (Task 1), `patch_manifest.py` (Task 2).
- Produces: rien de programmatique (scripts d'orchestration).

- [ ] **Step 1: Étape build dans `build_france.sh`**

Insérer **entre** le bloc `== 2) build_iris.py …` et le bloc `== 3) tippecanoe …` le texte suivant :

```bash
echo "== 2b) build_iris_index.py France (stats/iris_index/{DD}.json) =="
$PY pipeline/build_iris_index.py --iris "$GPKG" --out "$OUT"
```

Puis, dans le bloc `== 6) résumé ==`, ajouter après la ligne `echo "stats/iris : …"` :

```bash
echo "iris_index : $(ls "$OUT/iris_index" 2>/dev/null | wc -l | tr -d ' ') départements"
```

- [ ] **Step 2: Upload + patch manifest dans `deploy_cli.sh`**

Insérer, **juste avant** le bloc `if [ "${1:-}" = "--pmtiles" ]; then`, le texte suivant :

```bash
echo "== stats/iris_index -> tiles/stats/iris_index/{DD}.json (cache long, busté par ?v=) =="
IDX_SRC="${IRIS_INDEX_SRC:-build_fr/iris_index}"
if [ -d "$IDX_SRC" ]; then
  "${SB[@]}" "$IDX_SRC" ss:///tiles/stats --recursive --jobs "$JOBS" \
    --content-type application/json --cache-control "max-age=31536000, immutable" >/dev/null 2>&1
  echo "  $(find "$IDX_SRC" -name '*.json' | wc -l | tr -d ' ') départements déployés"
else
  echo "  (pas de $IDX_SRC — étape ignorée)"
fi

echo "== manifest : merge additif des bits IRIS dans le manifest live (version préservée) =="
MANIFEST_URL="https://bqwbazolhtwizafxqzlr.supabase.co/storage/v1/object/public/tiles/stats/manifest.json"
if "${PY:-.venv/bin/python}" pipeline/patch_manifest.py \
     --manifest-url "$MANIFEST_URL" --iris-index-dir "$IDX_SRC" \
     --millesime "${MILLESIME:-2026}" --out /tmp/manifest_iris.json; then
  supabase storage rm ss:///tiles/stats/manifest.json --experimental --linked --yes >/dev/null 2>&1
  "${SB[@]}" /tmp/manifest_iris.json ss:///tiles/stats/manifest.json \
    --content-type application/json --cache-control "no-cache"
  echo "  manifest mis à jour"
else
  echo "  ⚠ patch_manifest a échoué (manifest live indisponible ?) — manifest INCHANGÉ"
fi

echo "== ⚠ orchestration =="
echo "   iris_index est posé immutable, busté par ?v={version} ; version n'est PAS bumpée ici."
echo "   Ne pas déployer l'IRIS en isolation : co-déployer avec un run stats qui bumpe version"
echo "   (sinon les clients en cache restent sur l'ancien index jusqu'à 1 an)."
```

> Rappel mapping CLI : `cp <dir> ss:///tiles/stats` ajoute le basename du dir → `iris_index/` atterrit en `tiles/stats/iris_index/`. `cp` ne fait pas d'upsert → `rm` avant le manifest (qui change à chaque déploiement).

- [ ] **Step 3: Smoke test build réel (France) + vérif schéma**

Run :
```bash
cd "$(git rev-parse --show-toplevel)" && \
.venv/bin/python pipeline/build_iris_index.py --iris data/geo/CONTOURS-IRIS.gpkg --out build && \
.venv/bin/python - <<'PY'
import json, glob, os
files = glob.glob("build/iris_index/*.json")
print(f"{len(files)} fichiers iris_index")
# Échantillon : un département métropole et la structure d'une entrée
arr = json.load(open("build/iris_index/01.json"))
e = arr[0]
assert set(e) == {"code", "com", "lat", "lon", "bbox"}, set(e)
assert len(e["code"]) == 9 and len(e["com"]) == 5
assert len(e["bbox"]) == 4
assert e["bbox"][0] <= e["lon"] <= e["bbox"][2]
assert e["bbox"][1] <= e["lat"] <= e["bbox"][3]
assert arr == sorted(arr, key=lambda x: x["code"])  # trié par code
# dep_of : DOM en 3 chars, Corse en 2A/2B
names = {os.path.basename(f)[:-5] for f in files}
assert any(n.startswith("97") and len(n) == 3 for n in names), "DOM 3 chars manquant"
print("OK — schéma, tri, bbox⊇point, clés DOM/Corse")
PY
```
Expected : **104** fichiers `iris_index` (104 départements, 49 386 IRIS ; clés DOM `971`–`978`), puis `OK — …`.

> Note : `build/iris_index/` est un artefact de build (comme `build/iris/`). Ne pas committer ces fichiers de données. Vérifier qu'ils sont ignorés (`git status` ne doit pas les lister) ; sinon ajouter `build/iris_index/` au `.gitignore` dans ce commit.

- [ ] **Step 4: Lancer toute la suite de tests**

Run: `cd "$(git rev-parse --show-toplevel)" && .venv/bin/python -m pytest -q`
Expected: PASS — l'ensemble des tests du repo (existants + 10 nouveaux : 4 + 6) verts.

- [ ] **Step 5: Commit**

```bash
git add pipeline/build_france.sh deploy/deploy_cli.sh
git status --short    # confirmer qu'aucun build/iris_index/*.json n'est stagé
git commit -m "feat(iris-index): câblage build_france + deploy (upload iris_index + patch manifest)"
```

---

## Self-Review

**1. Spec coverage :**
- §3 index schema/keys → Task 1 (`build_index`, tests schéma/tri/bbox/dep_of). ✓
- §3 PointOnSurface intérieur → Task 1 `test_point_on_surface_inside_concave`. ✓
- §4 manifest additif (millesime_iris, layers.iris_index, compteurs.iris) + version préservée → Task 2 (`merge`, tests préservation/idempotence). ✓
- §5.1 build_iris_index.py → Task 1. §5.2 patch_manifest.py → Task 2. §5.3 build_france.sh → Task 3 Step 1. §5.4 deploy_cli.sh (upload iris_index cache immutable + rm/cp manifest no-cache) → Task 3 Step 2. ✓
- §6 tests → Task 1 (4) + Task 2 (6, dont `test_extra_deps`). ✓
- §7 cas limites : IRIS sans mutation (couverture géométrie seule — pas de jointure mutations dans `build_index`) ✓ ; concave/multipart (PointOnSurface) ✓ ; Corse/DOM `971`–`978` (`dep_of` testé) ✓ ; dépt index hors `manifest.departements` (`extra_deps` loggué, `test_extra_deps`) ✓ ; manifest live indisponible (Task 3 Step 2 : échec explicite, manifest inchangé) ✓ ; orchestration version (warning echo Task 3 Step 2) ✓.
- §8 critères d'acceptation → couverts par Task 1/2 + smoke test Task 3 Step 3. ✓

**2. Placeholder scan :** aucun TBD/TODO ; chaque step de code montre le code complet ; commandes exactes avec sortie attendue. ✓

**3. Type consistency :** `connect/dep_of/load_iris/build_index/write_index` (Task 1) et `load_manifest/count_iris/merge` + `IRIS_INDEX_LAYER` (Task 2) sont nommés identiquement dans les interfaces, l'implémentation et les tests. `IRIS_INDEX_LAYER == "stats/iris_index/{DD}.json"` cohérent avec le test et la spec. ✓
