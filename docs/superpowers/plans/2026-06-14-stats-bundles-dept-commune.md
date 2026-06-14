# Extracteur de stats par département/commune — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Générer, dans le pipeline dvf-tiles, des stats riches par département/commune (médianes par année × type, tendance annuelle + trimestrielle si dense) livrées en bundles JSON par département sur le bucket public, directement exploitables par l'app iOS au tap.

**Architecture:** Un module `pipeline/stats_bundles.py` interroge la vue DuckDB `stats_src` de `prepare.py` (même source remappée que les agrégats des tuiles → parité garantie) et écrit `build/stats/{manifest.json, departements.json, dep/{DD}.json}`. `prepare.py` l'appelle après `build_layer`. `qa_checks.py` valide structure + parité `n_tot` bundle ⟷ geojson. `deploy-supabase.sh` uploade l'arbre `build/stats/`. Un doc de contrat aval décrit la consommation iOS (UI hors périmètre).

**Tech Stack:** Python 3 + DuckDB (médianes natives), pytest, bash + Supabase CLI.

**Spec de référence:** [docs/superpowers/specs/2026-06-14-stats-bundles-dept-commune-design.md](../specs/2026-06-14-stats-bundles-dept-commune-design.md)

---

## File Structure

- **Create** `pipeline/stats_bundles.py` — `years()`, `entity_stats()`, `_dept_of()`, `build_stats_bundles()`. Tout le calcul SQL + l'assemblage du schéma `EntityStats` + l'écriture des bundles. Aucune règle métier (réutilise `stats_src`).
- **Create** `pipeline/test_stats_bundles.py` — tests unitaires (jeu DuckDB synthétique déterministe) de `entity_stats`, `build_stats_bundles`, et `check_stats_bundles`.
- **Modify** `pipeline/prepare.py` — imports (`datetime`, `stats_bundles`) ; `build_layer` renvoie aussi `{code: nom}` ; pose `qa["version"]` ; appelle `build_stats_bundles` (hors `--layers-only`, qui n'a pas les colonnes `st`/`np`).
- **Modify** `pipeline/qa_checks.py` — `_geo_ntot()` + `check_stats_bundles()` (structure, alignement des arrays, seuil de densité, parité `n_tot`), appelée dans `main()`.
- **Modify** `pipeline/run_pipeline.sh` — l'étape parité joue aussi `pipeline/test_stats_bundles.py`.
- **Modify** `scripts/deploy-supabase.sh` — boucle d'upload de `build/stats/**` + URLs dans le récap.
- **Modify** `CLAUDE.md` — artefact `build/stats/`, son rôle, le seuil, schéma distinct des tuiles.
- **Create** `docs/specs/2026-06-14-stats-bundles-contrat-aval-ios.md` — contrat de consommation iOS.

**Conventions du repo à respecter :** commentaires en français ; `json.dump(..., separators=(",", ":"), ensure_ascii=False)` pour les artefacts ; pas de dépendance nouvelle ; ne pas toucher `pipeline/parity/` (verrouillé, hors `extended.py`/`test_parity_extended.py`).

---

## Task 1: `stats_bundles.py` — `years()` + `entity_stats()` (cœur du calcul)

**Files:**
- Create: `pipeline/stats_bundles.py`
- Test: `pipeline/test_stats_bundles.py`

- [ ] **Step 1: Écrire le test qui échoue**

Créer `pipeline/test_stats_bundles.py` :

```python
"""Tests de l'extracteur de stats (pipeline/stats_bundles.py) — jeu DuckDB
synthétique déterministe, indépendant d'un build réel."""
import json
import os
import sys

import duckdb
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stats_bundles import years, entity_stats, build_stats_bundles, _dept_of  # noqa: E402


def _con():
    """Connexion DuckDB avec une vue stats_src synthétique.
    Commune 01001 (dense pour seuil=4) : 1 vente t1 2023 + 5 ventes t1 2024 (Q1)
    + 1 terrain nu (type NULL) 2024 Q2. Commune 01002 : 2 ventes t2 2024 (creux).
    Colonnes = celles que stats_src expose en prod : pm2 et annee dérivés."""
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `python3 -m pytest pipeline/test_stats_bundles.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'stats_bundles'`.

- [ ] **Step 3: Implémenter `stats_bundles.py` (parties `years` + `entity_stats` + `_dept_of`)**

Créer `pipeline/stats_bundles.py` :

```python
#!/usr/bin/env python3
"""Extracteur de stats riches par entité (commune/département) — artefact
build/stats/ consommé directement par l'app iOS (panneau au tap).

Source : la vue DuckDB `stats_src` de prepare.py (post remap COG/scissions),
même base que les agrégats des tuiles -> parité garantie. Tout en MÉDIANES
(robuste, précalculable ; les médianes ne se recombinent pas -> on précalcule
à la granularité d'affichage : année puis année x type).

Schéma EntityStats : cf.
docs/superpowers/specs/2026-06-14-stats-bundles-dept-commune-design.md
"""
import json
import os


def years(con):
    """Millésimes présents dans stats_src, triés (axe commun à tous les arrays)."""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT annee FROM stats_src ORDER BY 1").fetchall()]


def _dept_of(code):
    """Département d'un code commune (préfixe), même règle que prepare.py :
    97x -> 3 caractères, sinon 2 (couvre la Corse 2A/2B)."""
    return code[:3] if code.startswith("97") else code[:2]


def entity_stats(con, key, names, yrs, dense_threshold=200):
    """Retourne {code: EntityStats} pour la dimension `key` ('com' ou 'dep').

    names : {code: nom} des entités à émettre (géométrie connue) ; une entité
    sans vente sort avec n_tot=0. yrs : axe années commun (cf. years()).
    Trimestriel (clé 'quarters') seulement si n_tot >= dense_threshold, point
    omis si n < 5."""
    idx = {y: i for i, y in enumerate(yrs)}
    n = len(yrs)
    out = {code: {"code": code, "nom": nom, "n_tot": 0,
                  "pm2_med": None, "vf_med": None, "years": yrs,
                  "overall": {"n": [0] * n, "pm2_med": [None] * n},
                  "byType": {}}
           for code, nom in names.items()}

    # totaux toute période (terrain nu inclus dans n_tot ; pm2/vf ignorent les NULL)
    for code, n_tot, pm2_med, vf_med in con.execute(f"""
        SELECT {key}, count(*)::INT, CAST(median(pm2) AS INT),
               CAST(median(vf) AS BIGINT)
        FROM stats_src WHERE {key} IS NOT NULL GROUP BY 1""").fetchall():
        e = out.get(code)
        if e is not None:
            e["n_tot"], e["pm2_med"], e["vf_med"] = n_tot, pm2_med, vf_med

    # tendance annuelle, tous types confondus
    for code, annee, cnt, p in con.execute(f"""
        SELECT {key}, annee, count(*)::INT, CAST(median(pm2) AS INT)
        FROM stats_src WHERE {key} IS NOT NULL GROUP BY 1, 2""").fetchall():
        e = out.get(code)
        if e is not None and annee in idx:
            e["overall"]["n"][idx[annee]] = cnt
            e["overall"]["pm2_med"][idx[annee]] = p

    # détail par type (1-5) x année
    for code, typ, annee, cnt, pm2, vf, sb, st, np_ in con.execute(f"""
        SELECT {key}, type, annee, count(*)::INT,
               CAST(median(pm2) AS INT), CAST(median(vf) AS BIGINT),
               CAST(median(sb) AS INT), CAST(median(st) AS INT),
               CAST(median(np) AS INT)
        FROM stats_src WHERE {key} IS NOT NULL AND type IS NOT NULL
        GROUP BY 1, 2, 3""").fetchall():
        e = out.get(code)
        if e is None or annee not in idx:
            continue
        i = idx[annee]
        bt = e["byType"].setdefault(str(typ), {
            "n": [0] * n, "pm2_med": [None] * n, "vf_med": [None] * n,
            "sb_med": [None] * n, "st_med": [None] * n, "np_med": [None] * n})
        bt["n"][i] = cnt
        bt["pm2_med"][i] = pm2
        bt["vf_med"][i] = vf
        bt["sb_med"][i] = sb
        bt["st_med"][i] = st
        bt["np_med"][i] = np_

    # tendance trimestrielle : entités denses, point omis si n < 5
    dense = {c for c, e in out.items() if e["n_tot"] >= dense_threshold}
    if dense:
        for code, annee, q, cnt, p in con.execute(f"""
            SELECT {key}, annee, ((((date // 100) % 100) - 1) // 3 + 1) AS q,
                   count(*)::INT, CAST(median(pm2) AS INT)
            FROM stats_src WHERE {key} IS NOT NULL
            GROUP BY 1, 2, 3 HAVING count(*) >= 5 ORDER BY 2, 3""").fetchall():
            if code in dense:
                out[code].setdefault("quarters", []).append(
                    {"p": f"{annee}Q{q}", "n": cnt, "pm2_med": p})
    return out
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `python3 -m pytest pipeline/test_stats_bundles.py -q -k "years or entity_stats"`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/stats_bundles.py pipeline/test_stats_bundles.py
git commit -m "feat(stats): entity_stats — médianes par année×type + trimestriel si dense"
```

---

## Task 2: `stats_bundles.py` — `build_stats_bundles()` (écriture des bundles)

**Files:**
- Modify: `pipeline/stats_bundles.py`
- Test: `pipeline/test_stats_bundles.py`

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à la fin de `pipeline/test_stats_bundles.py` :

```python
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `python3 -m pytest pipeline/test_stats_bundles.py -q -k "build_stats_bundles"`
Expected: FAIL — `ImportError: cannot import name 'build_stats_bundles'` (ou `AttributeError`).

- [ ] **Step 3: Implémenter `build_stats_bundles` (à ajouter à la fin de `stats_bundles.py`)**

```python
def build_stats_bundles(con, com_names, dep_names, out_dir, version,
                        dense_threshold=200):
    """Écrit out_dir/stats/{manifest.json, departements.json, dep/{DD}.json}.
    Retourne les compteurs (pour prepare_stats.json / QA)."""
    yrs = years(con)
    stats_dir = os.path.join(out_dir, "stats")
    dep_dir = os.path.join(stats_dir, "dep")
    os.makedirs(dep_dir, exist_ok=True)

    dep_stats = entity_stats(con, "dep", dep_names, yrs, dense_threshold)
    com_stats = entity_stats(con, "com", com_names, yrs, dense_threshold)

    def _write(path, entities):
        json.dump({"version": version, "entities": entities},
                  open(path, "w"), separators=(",", ":"), ensure_ascii=False)

    _write(os.path.join(stats_dir, "departements.json"), list(dep_stats.values()))

    # communes regroupées par département -> un fichier par département
    by_dep = {}
    for code, e in com_stats.items():
        by_dep.setdefault(_dept_of(code), []).append(e)
    for dd, entities in by_dep.items():
        _write(os.path.join(dep_dir, f"{dd}.json"), entities)

    compteurs = {"departements": len(dep_stats), "communes": len(com_stats),
                 "bundles_dep": len(by_dep)}
    manifest = {"version": version, "generated": version,
                "dense_threshold": dense_threshold, "years": yrs,
                "layers": {"departements": "stats/departements.json",
                           "communes": "stats/dep/{DD}.json"},
                "departements": sorted(by_dep), "compteurs": compteurs}
    json.dump(manifest, open(os.path.join(stats_dir, "manifest.json"), "w"),
              separators=(",", ":"), ensure_ascii=False)
    return compteurs
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `python3 -m pytest pipeline/test_stats_bundles.py -q`
Expected: PASS (tous, dont `build_stats_bundles` et `dept_of`).

- [ ] **Step 5: Commit**

```bash
git add pipeline/stats_bundles.py pipeline/test_stats_bundles.py
git commit -m "feat(stats): build_stats_bundles — bundles par département + manifest versionné"
```

---

## Task 3: Brancher l'extracteur dans `prepare.py`

**Files:**
- Modify: `pipeline/prepare.py` (imports ~ligne 19-31 ; `build_layer` ~480-505 ; section agrégats ~476 ; appels ~507-514)

- [ ] **Step 1: Ajouter les imports**

Dans le bloc d'imports en tête de [pipeline/prepare.py](../../../pipeline/prepare.py), après `import argparse` ajouter `import datetime` ; après la ligne `from extended import consolidate_file_extended  # regles : parity/consolidate.py (verbatim)` ajouter :

```python
from stats_bundles import build_stats_bundles  # extracteur stats par entité
```

(Le répertoire `pipeline/` est `sys.path[0]` quand `prepare.py` est lancé comme script — l'import direct fonctionne, comme `extended`.)

- [ ] **Step 2: Faire renvoyer `{code: nom}` par `build_layer`**

Dans `build_layer`, remplacer l'initialisation et la construction des propriétés. Remplacer :

```python
        feats, seen = [], set()
```
par :
```python
        feats, seen, names = [], set(), {}
```

Puis remplacer le bloc qui construit `ft["properties"]` :

```python
                seen.add(code)
                centroid = feature_centroid(ft["geometry"])
                ft["properties"] = {"code": code,
                                    "nom": ft.get("properties", {}).get("nom", ""),
                                    **({"cx": centroid[0], "cy": centroid[1]}
                                       if centroid else {}),
                                    **st}
                feats.append(ft)
```
par :
```python
                seen.add(code)
                nom = ft.get("properties", {}).get("nom", "")
                names[code] = nom
                centroid = feature_centroid(ft["geometry"])
                ft["properties"] = {"code": code, "nom": nom,
                                    **({"cx": centroid[0], "cy": centroid[1]}
                                       if centroid else {}),
                                    **st}
                feats.append(ft)
```

Et la fin de la fonction, remplacer `return seen` par `return seen, names`.

- [ ] **Step 3: Poser `qa["version"]` et appeler l'extracteur**

Juste avant la ligne `com_stats = agg_stats("com")`, insérer :

```python
    # version du build : horodatage UTC, repris par le manifest des bundles
    # et le cache-busting iOS (mêmes URLs entre deux builds).
    qa["version"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
```

Remplacer les deux appels `build_layer` et l'affectation des compteurs :

```python
    seen_com = build_layer("communes_*.geojson",
                           lambda ft: ft["properties"].get("code"),
                           "communes.geojson", com_stats, exclude=PLM_PARENTS)
    seen_dep = build_layer("dept_*.geojson",
                           lambda ft: ft["properties"].get("code"),
                           "departements.geojson", dep_stats)
    qa["communes"] = len(seen_com)
    qa["departements"] = len(seen_dep)
```
par :
```python
    seen_com, com_names = build_layer("communes_*.geojson",
                                      lambda ft: ft["properties"].get("code"),
                                      "communes.geojson", com_stats, exclude=PLM_PARENTS)
    seen_dep, dep_names = build_layer("dept_*.geojson",
                                      lambda ft: ft["properties"].get("code"),
                                      "departements.geojson", dep_stats)
    qa["communes"] = len(seen_com)
    qa["departements"] = len(seen_dep)
    # Bundles de stats par entité (panneau iOS au tap). Hors --layers-only :
    # la table mutations reconstruite depuis les points ne porte pas st/np.
    if not args.layers_only:
        qa["stats_bundles"] = build_stats_bundles(
            con, com_names, dep_names, args.out, qa["version"])
        print("->", os.path.join(args.out, "stats"), qa["stats_bundles"])
```

- [ ] **Step 4: Vérifier la non-régression parité + nouveaux tests**

Run: `python3 -m pytest -q pipeline/parity pipeline/test_stats_bundles.py`
Expected: PASS (parité inchangée + tests stats).

- [ ] **Step 5: Build POC de bout en bout (vérifie l'écriture réelle des bundles)**

Run (venv activé, après un build POC existant ou frais) :
```bash
python3 pipeline/prepare.py --raw data/raw --geo data/geo --out build --pattern "*_69.csv.gz,*_01.csv.gz"
ls build/stats build/stats/dep | head
python3 -c "import json;m=json.load(open('build/stats/manifest.json'));print(m['version'],m['compteurs'],m['departements'][:5])"
```
Expected : `build/stats/manifest.json`, `departements.json`, `dep/69.json`, `dep/01.json` présents ; `compteurs` cohérents (communes ≈ celles de `communes.geojson`).

> Si `data/raw`/`data/geo` ne sont pas présents, exécuter d'abord `./pipeline/run_pipeline.sh poc` une fois (cf. CLAUDE.md), puis relancer cette étape.

- [ ] **Step 6: Commit**

```bash
git add pipeline/prepare.py
git commit -m "feat(stats): prepare.py génère build/stats via stats_bundles"
```

---

## Task 4: Contrôles QA dans `qa_checks.py`

**Files:**
- Modify: `pipeline/qa_checks.py`
- Test: `pipeline/test_stats_bundles.py`

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à la fin de `pipeline/test_stats_bundles.py` :

```python
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `python3 -m pytest pipeline/test_stats_bundles.py -q -k "check_stats_bundles"`
Expected: FAIL — `ImportError: cannot import name 'check_stats_bundles' from 'qa_checks'`.

- [ ] **Step 3: Implémenter `_geo_ntot` + `check_stats_bundles` dans `qa_checks.py`**

Ajouter ces deux fonctions juste avant `def main()` dans [pipeline/qa_checks.py](../../../pipeline/qa_checks.py) :

```python
def _geo_ntot(path):
    """Map {code: n_tot} d'une couche geojson (communes/départements)."""
    if not os.path.exists(path):
        return {}
    data = json.load(open(path))
    return {f["properties"]["code"]: f["properties"].get("n_tot", 0)
            for f in data.get("features", [])}


def check_stats_bundles(build, errors, warnings):
    """Valide build/stats/ : structure, alignement des arrays sur years, seuil
    de densité (quarters), parité n_tot bundle <-> geojson. Renvoie un récap."""
    sdir = os.path.join(build, "stats")
    man_path = os.path.join(sdir, "manifest.json")
    if not os.path.exists(man_path):
        errors.append("stats/manifest.json absent")
        return {}
    man = json.load(open(man_path))
    version, yrs, thr = man.get("version"), man.get("years"), man.get("dense_threshold")
    ny = len(yrs or [])
    report = {"version": version, "departements_attendus": len(man.get("departements", []))}

    def check_entities(entities, geo_ntot, label):
        for e in entities:
            ov = e.get("overall", {})
            if len(ov.get("n", [])) != ny or len(ov.get("pm2_med", [])) != ny:
                errors.append(f"{label} {e['code']} : overall non aligné sur years ({ny})")
            for t, bt in e.get("byType", {}).items():
                for mkey in ("n", "pm2_med", "vf_med", "sb_med", "st_med", "np_med"):
                    if len(bt.get(mkey, [])) != ny:
                        errors.append(f"{label} {e['code']} byType[{t}].{mkey} non aligné")
            if "quarters" in e and e.get("n_tot", 0) < thr:
                errors.append(f"{label} {e['code']} : quarters présent sous le seuil {thr}")
            exp = geo_ntot.get(e["code"])
            if exp is not None and exp != e.get("n_tot"):
                errors.append(f"{label} {e['code']} : n_tot {e.get('n_tot')} != geojson {exp}")

    # départements (couche légère)
    dep_path = os.path.join(sdir, "departements.json")
    if not os.path.exists(dep_path):
        errors.append("stats/departements.json absent")
    else:
        dj = json.load(open(dep_path))
        if dj.get("version") != version:
            errors.append("departements.json : version != manifest")
        check_entities(dj.get("entities", []), _geo_ntot(
            os.path.join(build, "departements.geojson")), "dept")

    # communes (un bundle par département)
    com_geo = _geo_ntot(os.path.join(build, "communes.geojson"))
    vus = 0
    for dd in man.get("departements", []):
        p = os.path.join(sdir, "dep", f"{dd}.json")
        if not os.path.exists(p):
            errors.append(f"bundle département manquant : dep/{dd}.json")
            continue
        b = json.load(open(p))
        if b.get("version") != version:
            errors.append(f"dep/{dd}.json : version != manifest")
        check_entities(b.get("entities", []), com_geo, "commune")
        vus += len(b.get("entities", []))
    report["communes"] = vus
    return report
```

- [ ] **Step 4: Appeler le contrôle dans `main()`**

Dans `qa_checks.py`, juste après le bloc de la section 4 (exhaustivité) et **avant** `report["erreurs"] = errors`, insérer :

```python
    # 5. bundles de stats par entité (panneau iOS au tap)
    report["stats"] = check_stats_bundles(build, errors, warnings)
```

- [ ] **Step 5: Lancer les tests pour vérifier qu'ils passent**

Run: `python3 -m pytest pipeline/test_stats_bundles.py -q`
Expected: PASS (tous, dont les 3 `check_stats_bundles`).

- [ ] **Step 6: Vérifier la QA sur un build POC réel**

Run: `python3 pipeline/qa_checks.py build`
Expected: `QA : OK (...)` ; le rapport `build/qa_report.json` contient une clé `stats` avec `version`/`communes`.

- [ ] **Step 7: Commit**

```bash
git add pipeline/qa_checks.py pipeline/test_stats_bundles.py
git commit -m "test(stats): QA structure + parité n_tot bundle⟷geojson"
```

---

## Task 5: Orchestration (`run_pipeline.sh`) + livraison (`deploy-supabase.sh`)

**Files:**
- Modify: `pipeline/run_pipeline.sh` (étape [3/6])
- Modify: `scripts/deploy-supabase.sh`

- [ ] **Step 1: Jouer le nouveau test dans l'étape parité**

Dans [pipeline/run_pipeline.sh](../../../pipeline/run_pipeline.sh), remplacer :

```bash
echo "==== [3/6] Parite de consolidation (goldens carex.immo) ===="
python3 -m pytest -q pipeline/parity
```
par :
```bash
echo "==== [3/6] Parite de consolidation (goldens) + extracteur de stats ===="
python3 -m pytest -q pipeline/parity pipeline/test_stats_bundles.py
```

- [ ] **Step 2: Vérifier l'étape de tests**

Run: `python3 -m pytest -q pipeline/parity pipeline/test_stats_bundles.py`
Expected: PASS (parité + stats).

- [ ] **Step 3: Ajouter l'upload des bundles dans le script de déploiement**

Dans [scripts/deploy-supabase.sh](../../../scripts/deploy-supabase.sh), juste après le bloc `echo "📤 Upload de $INDEX_FILE..."` / `upload "$INDEX_FILE" "ss:///$BUCKET/tiles_index.json"`, insérer :

```bash
# Bundles de stats par département (panneau iOS au tap) — fichiers statiques publics
STATS_DIR="build/stats"
if [ -d "$STATS_DIR" ]; then
  COUNT=$(find "$STATS_DIR" -type f -name '*.json' | wc -l | tr -d ' ')
  echo "📤 Upload des bundles de stats ($COUNT fichiers depuis $STATS_DIR)..."
  while IFS= read -r f; do
    rel="${f#build/}"                       # ex: stats/manifest.json, stats/dep/69.json
    upload "$f" "ss:///$BUCKET/$rel"
  done < <(find "$STATS_DIR" -type f -name '*.json')
else
  echo "ℹ️  $STATS_DIR absent : aucun bundle de stats à uploader (relancer prepare.py)"
fi
```

Puis, dans le bloc `echo "📍 URLs :"`, ajouter une ligne après celle de l'index :

```bash
echo "   Stats   : https://$PROJECT_REF.supabase.co/storage/v1/object/public/$BUCKET/stats/manifest.json"
```

- [ ] **Step 4: Vérifier la syntaxe bash**

Run: `bash -n scripts/deploy-supabase.sh && bash -n pipeline/run_pipeline.sh`
Expected: aucune sortie (syntaxe OK).

- [ ] **Step 5: Commit**

```bash
git add pipeline/run_pipeline.sh scripts/deploy-supabase.sh
git commit -m "build(stats): run_pipeline joue les tests stats ; deploy uploade build/stats"
```

---

## Task 6: Documentation — `CLAUDE.md` + contrat aval iOS

**Files:**
- Modify: `CLAUDE.md`
- Create: `docs/specs/2026-06-14-stats-bundles-contrat-aval-ios.md`

- [ ] **Step 1: Mettre à jour `CLAUDE.md` (section Architecture)**

Dans [CLAUDE.md](../../../CLAUDE.md), dans le schéma de la chaîne de données (bloc « Chaîne de données »), après la ligne `build/dvf.pmtiles  ← artefact de production`, ajouter :

```
              pipeline/stats_bundles.py (depuis stats_src, après build_layer)
                        │
              build/stats/{manifest.json, departements.json, dep/{DD}.json}
              ← stats riches par entité (médianes année×type + trimestriel
                si dense), bundles par département pour le panneau iOS au tap
```

- [ ] **Step 2: Mettre à jour `CLAUDE.md` (section « Encodage compact partagé »)**

À la fin de la section « Encodage compact partagé — à garder synchronisé », ajouter ce paragraphe :

```markdown
**Bundles de stats par entité (`build/stats/`)** — artefact DISTINCT des tuiles
(schéma propre, cf. [docs/specs/2026-06-14-stats-bundles-contrat-aval-ios.md](docs/specs/2026-06-14-stats-bundles-contrat-aval-ios.md)) :
médianes par année × type (`pm2_med, vf_med, sb_med, st_med, np_med`) + comptes,
tendance annuelle (`overall`) et trimestrielle si `n_tot ≥ 200` (`quarters`).
Produit par `pipeline/stats_bundles.py` depuis `stats_src` (mêmes données que
les agrégats des tuiles → parité vérifiée en QA). **N'entre pas** dans le contrat
des « 4 fichiers consommateurs » des tuiles ; lu directement par iOS au tap d'un
département/commune.
```

- [ ] **Step 3: Créer le contrat aval iOS**

Créer `docs/specs/2026-06-14-stats-bundles-contrat-aval-ios.md` :

```markdown
# Contrat aval — bundles de stats par département/commune (consommation iOS)

**Date** : 2026-06-14 · **Producteur** : dvf-tiles (`pipeline/stats_bundles.py`) ·
**Consommateur** : app iOS carex.immo (panneau au tap d'un département/commune).
Conception : [../superpowers/specs/2026-06-14-stats-bundles-dept-commune-design.md](../superpowers/specs/2026-06-14-stats-bundles-dept-commune-design.md).

## URLs (bucket public Supabase `tiles`)

Base : `https://bqwbazolhtwizafxqzlr.supabase.co/storage/v1/object/public/tiles`
- `…/stats/manifest.json` — version, années, seuil de densité, liste des départements.
- `…/stats/departements.json` — tous les départements (~109).
- `…/stats/dep/{DD}.json` — communes d'un département. `{DD}` = code département.

## Résolution du fichier au tap

L'app connaît déjà, depuis la tuile, le `code` INSEE et la couche de l'entité.
- Tap **département** → charger `stats/departements.json` (une fois, caché) → entité par `code`.
- Tap **commune** (code INSEE `C`) → `DD = C[:3] si C commence par "97", sinon C[:2]`
  (couvre Corse `2A`/`2B` et DOM `97x`) → charger `stats/dep/{DD}.json?v={manifest.version}`
  → entité par `code`. Communes voisines = même bundle (cache par zone).

## Schéma d'une entité (`EntityStats`)

Tableaux parallèles indexés par `years` ; `null` = pas de donnée. Codes type :
`1` maison, `2` appartement, `3` immeuble, `4` local com./ind., `5` dépendance.

| Champ | Type | Sens |
|---|---|---|
| `code` | String | code INSEE (commune) ou code département |
| `nom` | String | libellé |
| `n_tot` | Int | total mutations (terrain nu inclus) |
| `pm2_med` | Int? | médiane €/m² toute période |
| `vf_med` | Int? | médiane valeur foncière toute période |
| `years` | [Int] | millésimes, axe commun des arrays |
| `overall.n` | [Int] | nb ventes/an, tous types (terrain nu inclus) |
| `overall.pm2_med` | [Int?] | médiane €/m²/an, tous types |
| `byType` | {code type → métriques} | présent par type observé |
| `byType[t].n` | [Int] | nb ventes/an (0 si aucune) |
| `byType[t].{pm2_med,vf_med,sb_med,st_med,np_med}` | [Int?] | médianes/an (€/m², valeur, surface bâtie, terrain, pièces) |
| `quarters` | [{p,n,pm2_med}]? | tendance trimestrielle si `n_tot ≥ dense_threshold` ; `p="{annee}Q{1..4}"` |

## Règles de consommation

- **Tendance** : `quarters` si présent (fin), sinon `overall.pm2_med` (annuel) — toujours traçable.
- **Répartition par type** : `byType` directement ; filtre type/année = sélection d'arrays.
  Les comptes annuels se somment ; **les médianes s'affichent par année, jamais fusionnées
  entre années** (une médiane de plage n'est pas la médiane des médianes).
- **Cache-busting** : suffixer les bundles de `?v={manifest.version}` ; lire le manifest avec
  un cache court. Les URLs sont stables entre builds (archive remplacée en place).
- **Absence** : un `404` sur `dep/{DD}.json` = pas de données pour ce département (traiter comme
  vide, pas comme une erreur). Une entité absente du bundle = hors périmètre géométrique (rare,
  cf. communes sans géométrie côté pipeline).

## Garanties de cohérence (vérifiées en QA côté pipeline)

- `byType[t].n[i] == n_{years[i]}_t{t}` des agrégats portés par les tuiles.
- `Σ overall.n == n_tot` ; `n_tot` identique à celui des couches `communes`/`departements`.
- `version` identique entre `manifest.json` et chaque bundle.
```

- [ ] **Step 4: Vérifier les liens/chemins**

Run: `test -f docs/specs/2026-06-14-stats-bundles-contrat-aval-ios.md && rg -n "stats-bundles-contrat-aval-ios" CLAUDE.md`
Expected: le fichier existe et `CLAUDE.md` le référence.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/specs/2026-06-14-stats-bundles-contrat-aval-ios.md
git commit -m "docs(stats): CLAUDE.md + contrat aval iOS des bundles de stats"
```

---

## Définition de terminé

- `python3 -m pytest -q pipeline/parity pipeline/test_stats_bundles.py` : vert.
- `./pipeline/run_pipeline.sh poc` : produit `build/stats/{manifest.json, departements.json, dep/69.json, dep/01.json}` et `qa_checks.py` passe (rapport avec clé `stats`).
- `bash -n scripts/deploy-supabase.sh` : OK ; l'upload de `build/stats/**` est présent.
- Contrat aval iOS écrit et référencé depuis `CLAUDE.md`.
- UI iOS : **hors périmètre** (lot carex.immo, guidé par le contrat aval).
