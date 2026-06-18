# CI GitHub Actions + verrou du contrat d'encodage — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mettre en place une Action GitHub qui joue les suites de tests déterministes sur chaque PR et verrouille le contrat d'encodage dupliqué dans les « 4 fichiers consommateurs ».

**Architecture:** Un workflow `.github/workflows/ci.yml` à deux jobs (`python` sur ubuntu, `swift` sur container `swift:6`). Un nouveau fichier source-de-vérité `pipeline/tile_encoding.json` et un test `tests/test_tile_encoding_contract.py` (joué par le job python) cross-vérifient les clés et codes entre `prepare.py`, le struct Swift, `demo/index.html` et `simulate_ios.py`.

**Tech Stack:** GitHub Actions, Python 3.12 + pytest, `ast`/`re` pour le parsing des sources, conteneur Docker `swift:6` pour `swift test`.

## Global Constraints

- Tout le projet (code, commentaires, doc) est rédigé **en français**.
- La CI doit être **déterministe et hors-ligne** : aucun run du pipeline complet (Go de CSV), aucun appel réseau (donc **pas** le bench Deno `tests/edge-function-perf.test.ts` qui frappe l'endpoint Supabase live, **pas** `client/simulate_ios.py` qui exige `build/dvf.pmtiles`).
- Footprint pip du job python limité à `pytest duckdb shapely` (rien d'autre).
- Runner Swift = `ubuntu-latest` + `container: swift:6` (DvfTileKit est zéro-dépendance, Foundation seul).
- **Ne jamais modifier** `pipeline/parity/consolidate.py`, ses goldens, ni `pipeline/parity/tests/` (pont de parité verbatim carex.immo).
- Le test de contrat ne doit **pas importer** `pipeline/prepare.py` (il importe `duckdb` et exécute du code au niveau module) : lire `TILE_PROPS` par parsing `ast` du source.
- Source de vérité de l'encodage : `pipeline/tile_encoding.json`. Les clés/codes des autres fichiers sont vérifiés contre lui, jamais l'inverse.

**Valeurs verbatim de l'encodage (spec 2026-06-18) :**
- `mutation_keys` (ordre exact) : `["id","date","nat","type","vf","sb","st","np","nl","com","adr","cp"]`
- codes `nat` : `1`=Vente, `2`=VEFA, `3`=Adjudication, `4`=Echange, `5`=Expropriation
- codes `type` : `1`=maison, `2`=appartement, `3`=immeuble, `4`=local, `5`=dependance
- demo lit (clés mutations) : `id, date, type, vf, sb, st, nl, adr, cp`
- `simulate_ios.py` lit (clés mutations) : `type, date, vf, sb, adr, cp, com`

## File Structure

- **Create** `pipeline/tile_encoding.json` — source de vérité de l'encodage (clés mutations, codes nat/type, clés lues par les consommateurs souples).
- **Create** `tests/test_tile_encoding_contract.py` — verrou du contrat (joué par le job python via `pytest tests/`).
- **Create** `.github/workflows/ci.yml` — workflow à deux jobs.
- **Modify** `client/DvfTileClient.swift:1-3` — recadrer le commentaire d'en-tête (MapKit → rôle de référence d'encodage, rendu via MapLibreGL).
- **Modify** `CLAUDE.md` — § « Encodage compact partagé » : pointer vers le garde-fou désormais *enforced*.
- **Modify** `README.md:90` — ajouter la mention de la validation automatique (CI).

Branche de travail : `ci/github-actions` (déjà créée, contient le commit du design).

---

## Task 1 : Source de vérité + verrou exact des clés (3 voies)

Le backbone du contrat : `prepare.py` `TILE_PROPS` == `tile_encoding.json` `mutation_keys` == champs `let` du struct Swift.

**Files:**
- Create: `pipeline/tile_encoding.json`
- Create: `tests/test_tile_encoding_contract.py`

**Interfaces:**
- Produces (helpers réutilisés Tasks 2-3, dans `tests/test_tile_encoding_contract.py`) :
  - `ROOT: Path` — racine du dépôt.
  - `SPEC: dict` — contenu parsé de `tile_encoding.json`.
  - `_tile_props_from_prepare() -> list[str]`
  - `_swift_struct_fields() -> list[str]`

- [ ] **Step 1: Écrire le test de verrou des clés (qui échoue)**

Create `tests/test_tile_encoding_contract.py` :

```python
"""Verrou du contrat d'encodage compact (les « 4 fichiers consommateurs »).

Source de vérité : pipeline/tile_encoding.json. Ce test garantit que les clés
de propriétés des features mutations et les codes nat/type ne dérivent pas
silencieusement entre les fichiers qui dupliquent l'encodage à la main.

Backbone (verrou exact) : prepare.py TILE_PROPS == JSON mutation_keys ==
champs `let` du struct Mutation (DvfTileClient.swift). Cf. design
docs/superpowers/specs/2026-06-18-ci-github-actions-design.md.
"""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "pipeline" / "tile_encoding.json").read_text())


def _tile_props_from_prepare():
    """Lit TILE_PROPS par AST (sans importer prepare.py : il charge duckdb)."""
    src = (ROOT / "pipeline" / "prepare.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TILE_PROPS" for t in node.targets
        ):
            return [el.value for el in node.value.elts]
    raise AssertionError("TILE_PROPS introuvable dans pipeline/prepare.py")


def _swift_struct_fields():
    """Champs `let <clé>:` du struct Mutation, hors `coordinate` (géométrie)."""
    lines = (ROOT / "client" / "DvfTileClient.swift").read_text().splitlines()
    fields, inside = [], False
    for line in lines:
        if line.startswith("struct Mutation"):
            inside = True
            continue
        if inside:
            if line.startswith("}"):
                break
            m = re.match(r"\s*let (\w+)\s*:", line)
            if m and m.group(1) != "coordinate":
                fields.append(m.group(1))
    return fields


def test_tile_props_match_spec():
    assert _tile_props_from_prepare() == SPEC["mutation_keys"]


def test_swift_struct_matches_spec():
    assert _swift_struct_fields() == SPEC["mutation_keys"]
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `python3 -m pytest tests/test_tile_encoding_contract.py -v`
Expected: FAIL au chargement (`FileNotFoundError` sur `pipeline/tile_encoding.json`) — le fichier source-de-vérité n'existe pas encore.

- [ ] **Step 3: Créer le fichier source de vérité**

Create `pipeline/tile_encoding.json` :

```json
{
  "_doc": "Source de vérité de l'encodage compact des tuiles DVF. Verrouillé par tests/test_tile_encoding_contract.py. Toute évolution se propage ici ET dans prepare.py (TILE_PROPS), client/DvfTileClient.swift (struct Mutation), demo/index.html, client/simulate_ios.py.",
  "mutation_keys": ["id", "date", "nat", "type", "vf", "sb", "st", "np", "nl", "com", "adr", "cp"],
  "nat":  {"1": "Vente", "2": "VEFA", "3": "Adjudication", "4": "Echange", "5": "Expropriation"},
  "type": {"1": "maison", "2": "appartement", "3": "immeuble", "4": "local", "5": "dependance"},
  "soft_consumers": {
    "demo/index.html":        ["id", "date", "type", "vf", "sb", "st", "nl", "adr", "cp"],
    "client/simulate_ios.py": ["type", "date", "vf", "sb", "adr", "cp", "com"]
  }
}
```

- [ ] **Step 4: Lancer le test, vérifier qu'il passe**

Run: `python3 -m pytest tests/test_tile_encoding_contract.py -v`
Expected: PASS (`test_tile_props_match_spec`, `test_swift_struct_matches_spec`).

- [ ] **Step 5: Prouver que le garde-fou attrape une dérive**

Vérifier que le verrou échoue bien si une clé n'est pas propagée. Modifier temporairement `pipeline/tile_encoding.json` (remplacer `"vf"` par `"value"` dans `mutation_keys`), puis :

Run: `python3 -m pytest tests/test_tile_encoding_contract.py -v`
Expected: FAIL sur `test_tile_props_match_spec` ET `test_swift_struct_matches_spec` (le JSON dit `value`, prepare.py et Swift disent `vf`).

Puis **annuler la modification** (`git checkout pipeline/tile_encoding.json`) et relancer :

Run: `python3 -m pytest tests/test_tile_encoding_contract.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/tile_encoding.json tests/test_tile_encoding_contract.py
git commit -m "test(contrat): verrou exact des clés d'encodage (prepare.py == JSON == struct Swift)"
```

---

## Task 2 : Verrou des codes nat/type (code-set {1..5})

Les labels diffèrent légitimement entre fichiers (demo affiche « Maison »/« Dépendance » UI, Swift commente « maison »/« dependance »). On verrouille donc l'**ensemble des codes** `{1,2,3,4,5}`, pas les labels.

**Files:**
- Modify: `tests/test_tile_encoding_contract.py` (ajout de tests, réutilise `ROOT`/`SPEC`)

**Interfaces:**
- Consumes: `ROOT`, `SPEC` (Task 1).

- [ ] **Step 1: Écrire les tests de code-set (qui échouent si absents)**

Ajouter à la fin de `tests/test_tile_encoding_contract.py` :

```python
EXPECTED_CODES = {"1", "2", "3", "4", "5"}


def test_spec_code_sets():
    assert set(SPEC["nat"]) == EXPECTED_CODES
    assert set(SPEC["type"]) == EXPECTED_CODES


def test_demo_type_codes_match_spec():
    """Le mapping `const types = {…}` du JS couvre exactement les codes type 1..5."""
    src = (ROOT / "demo" / "index.html").read_text()
    m = re.search(r"const types\s*=\s*\{([^}]*)\}", src)
    assert m, "objet `const types` introuvable dans demo/index.html"
    codes = set(re.findall(r"(\d+)\s*:", m.group(1)))
    assert codes == set(SPEC["type"]), f"codes type demo={codes}"


def test_swift_comment_codes_match_spec():
    """Les commentaires `// 1 …, 2 …` du struct listent exactement les codes 1..5."""
    src = (ROOT / "client" / "DvfTileClient.swift").read_text()
    for key in ("nat", "type"):
        m = re.search(rf"let {key}\s*:[^/]*//(.*)", src)
        assert m, f"commentaire de `let {key}` introuvable dans le struct"
        codes = set(re.findall(r"\b([1-5])\b", m.group(1)))
        assert codes == set(SPEC[key]), f"codes {key} Swift={codes}"
```

- [ ] **Step 2: Lancer les nouveaux tests, vérifier qu'ils passent**

Run: `python3 -m pytest tests/test_tile_encoding_contract.py -v -k "code"`
Expected: PASS (`test_spec_code_sets`, `test_demo_type_codes_match_spec`, `test_swift_comment_codes_match_spec`).

Note : si un test échoue, c'est un signal réel — vérifier que `demo/index.html` contient bien `const types = {1:"Maison",2:"Appartement",3:"Immeuble",4:"Local com./ind.",5:"Dépendance"};` et que les commentaires `let nat:` / `let type:` du struct listent 1..5. Ne pas affaiblir l'assertion pour la faire passer.

- [ ] **Step 3: Commit**

```bash
git add tests/test_tile_encoding_contract.py
git commit -m "test(contrat): verrou du jeu de codes nat/type {1..5} (JSON, demo, Swift)"
```

---

## Task 3 : Présence best-effort dans les consommateurs souples

Pour `demo/index.html` et `client/simulate_ios.py`, vérifier que chaque clé mutation qu'ils sont censés lire (listée dans `soft_consumers`) apparaît bien sous forme d'**accès de propriété** — via des motifs spécifiques au langage qui évitent les collisions de mots-clés (ex. `type:"vector"` de MapLibre ne doit pas valider la clé `type`).

**Files:**
- Modify: `tests/test_tile_encoding_contract.py` (ajout d'un helper + un test)

**Interfaces:**
- Consumes: `ROOT`, `SPEC` (Task 1).

- [ ] **Step 1: Écrire le helper de présence + le test (qui échoue si absent)**

Ajouter à la fin de `tests/test_tile_encoding_contract.py` :

```python
def _key_present(text, key):
    """Vrai si `key` apparaît comme accès de propriété (JS ou Python).
    Les motifs sont assez stricts pour ne pas matcher `type:"vector"` (clé
    MapLibre) ni les appels de méthode `map.on(...)`.
    """
    patterns = [
        rf'\bp\.{key}\b',                 # JS    p.vf
        rf'\["get"\s*,\s*"{key}"\]',      # JS    ["get","vf"]
        rf'''\[\s*["']{key}["']\s*\]''',  # subscript  p["vf"] / ex['adr']
        rf'''\.get\(\s*["']{key}["']''',  # Python .get("vf" / .get('com'
    ]
    return any(re.search(p, text) for p in patterns)


def test_soft_consumers_reference_declared_keys():
    spec_keys = set(SPEC["mutation_keys"])
    for rel, keys in SPEC["soft_consumers"].items():
        text = (ROOT / rel).read_text()
        for key in keys:
            assert key in spec_keys, f"{rel}: clé déclarée {key!r} hors mutation_keys"
            assert _key_present(text, key), (
                f"{rel}: clé {key!r} déclarée mais absente du fichier "
                f"(renommée sans propager ?)")
```

- [ ] **Step 2: Lancer le test, vérifier qu'il passe**

Run: `python3 -m pytest tests/test_tile_encoding_contract.py::test_soft_consumers_reference_declared_keys -v`
Expected: PASS — toutes les clés déclarées (`demo` : id, date, type, vf, sb, st, nl, adr, cp ; `simulate_ios.py` : type, date, vf, sb, adr, cp, com) sont présentes via leurs motifs d'accès.

- [ ] **Step 3: Prouver que le garde-fou attrape une clé oubliée**

Ajouter temporairement une clé inexistante dans `soft_consumers["demo/index.html"]` du JSON (ex. ajouter `"zzz"`), puis :

Run: `python3 -m pytest tests/test_tile_encoding_contract.py::test_soft_consumers_reference_declared_keys -v`
Expected: FAIL avec `demo/index.html: clé 'zzz' hors mutation_keys`.

Annuler (`git checkout pipeline/tile_encoding.json`) et relancer → PASS.

- [ ] **Step 4: Lancer la suite complète du job python en local**

Reproduire exactement ce que lancera la CI (depuis la racine, venv actif) :

Run: `python3 -m pytest pipeline/parity tests/ -q`
Expected: PASS — parité + suite IRIS + les 6 tests de contrat. Aucun test ne nécessite de réseau ni `build/`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_tile_encoding_contract.py
git commit -m "test(contrat): présence best-effort des clés lues par demo et simulate_ios"
```

---

## Task 4 : Workflow GitHub Actions

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: la suite de tests jouable par `pytest pipeline/parity tests/` (Tasks 1-3) et `swift test` sur `client/DvfTileKit`.

- [ ] **Step 1: Créer le workflow**

Create `.github/workflows/ci.yml` :

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  python:
    name: Tests Python (parité + IRIS + contrat)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Installer les dépendances de test
        run: pip install pytest duckdb shapely
      - name: pytest (parité + IRIS + contrat d'encodage)
        run: python -m pytest pipeline/parity tests/ -q

  swift:
    name: Tests Swift (DvfTileKit)
    runs-on: ubuntu-latest
    container: swift:6
    steps:
      - uses: actions/checkout@v4
      - name: swift test (décodeur MVT + parité goldens)
        run: swift test --package-path client/DvfTileKit
```

- [ ] **Step 2: Valider la syntaxe YAML en local**

Run: `python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('YAML OK')"`
Expected: `YAML OK`.
(Si PyYAML n'est pas installé : `pip install pyyaml` d'abord, ou utiliser `ruby -ryaml -e "YAML.load_file('.github/workflows/ci.yml'); puts 'YAML OK'"`.)

- [ ] **Step 3: (Optionnel) Reproduire le job swift en local si une toolchain Swift est disponible**

Run: `swift test --package-path client/DvfTileKit`
Expected: PASS (sur macOS via Xcode ; sinon ce job n'est validé qu'en CT, ce qui est attendu — le container `swift:6` fait foi).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: workflow GitHub Actions (job python parité+IRIS+contrat, job swift DvfTileKit)"
```

---

## Task 5 : Documentation

Recadrer l'en-tête Swift et signaler le garde-fou dans CLAUDE.md / README.

**Files:**
- Modify: `client/DvfTileClient.swift:1-3`
- Modify: `CLAUDE.md` (§ « Encodage compact partagé — à garder synchronisé »)
- Modify: `README.md:90`

- [ ] **Step 1: Recadrer l'en-tête de DvfTileClient.swift**

Remplacer les 3 premières lignes de `client/DvfTileClient.swift` :

Old:
```swift
// CAREX - Client de tuiles DVF pour iOS (MapKit natif) - squelette de reference
// Le decodage MVT est fourni par le package DvfTileKit (client/DvfTileKit/,
// zero dependance : ProtobufReader + MVTTile + MVTDecoder) - `swift test` pour la parite.
```

New:
```swift
// CAREX - Reference d'encodage des tuiles DVF cote Swift.
// Le struct Mutation ci-dessous est la declaration canonique de l'encodage
// (verrouillee par tests/test_tile_encoding_contract.py). L'app iOS rend les
// tuiles via MapLibreGL ; le TileMath/fetch MapKit plus bas reste un squelette
// illustratif. Le decodage MVT est fourni par DvfTileKit (`swift test`).
```

- [ ] **Step 2: Vérifier que le verrou Swift tient toujours après l'édition**

Run: `python3 -m pytest tests/test_tile_encoding_contract.py -q`
Expected: PASS (l'édition ne touche pas le struct ni ses commentaires de codes).

- [ ] **Step 3: Mettre à jour CLAUDE.md**

Dans le § « Encodage compact partagé — à garder synchronisé », après la phrase qui se termine par « Toute modification doit être propagée aux quatre. », ajouter :

```markdown
 **Garde-fou CI (enforced)** : `pipeline/tile_encoding.json` est la source de vérité (clés mutations + codes nat/type) ; `tests/test_tile_encoding_contract.py` (joué par `.github/workflows/ci.yml`) verrouille à l'exact `TILE_PROPS` ↔ JSON ↔ struct Swift et vérifie codes/présence dans `demo/index.html` et `simulate_ios.py`. Une clé renommée/ajoutée non propagée fait échouer la PR.
```

- [ ] **Step 4: Mettre à jour README.md**

Après la ligne 90 (`Validation manuelle : ...`), ajouter :

```markdown

Validation automatique (CI) : `.github/workflows/ci.yml` joue sur chaque PR les tests Python (`pytest pipeline/parity tests/` — parité, suite IRIS, contrat d'encodage) et Swift (`swift test` sur `client/DvfTileKit`, container `swift:6`). Le bench Deno et le pipeline complet restent manuels.
```

- [ ] **Step 5: Commit**

```bash
git add client/DvfTileClient.swift CLAUDE.md README.md
git commit -m "docs(ci): recadre l'en-tête DvfTileClient (MapLibreGL) + documente le garde-fou CI"
```

---

## Task 6 : Validation live (avec accord utilisateur)

La correction réelle du YAML et des deux jobs ne se vérifie qu'en exécution GitHub Actions.

- [ ] **Step 1: Pousser la branche et ouvrir la PR (demander l'accord avant de pousser)**

```bash
git push -u origin ci/github-actions
gh pr create --base main --title "ci: GitHub Actions + verrou du contrat d'encodage" \
  --body "Met en place la CI sur PR (job python parité+IRIS+contrat, job swift DvfTileKit) et un garde-fou des « 4 fichiers consommateurs » via pipeline/tile_encoding.json + tests/test_tile_encoding_contract.py. Design : docs/superpowers/specs/2026-06-18-ci-github-actions-design.md."
```

- [ ] **Step 2: Vérifier que les deux jobs passent**

Run: `gh pr checks --watch`
Expected: `python` ✓ et `swift` ✓ verts.
Si un job échoue : lire les logs (`gh run view --log-failed`), corriger, recommit, repush.

---

## Self-Review (relecture du plan vs spec)

**1. Couverture de la spec :**
- Workflow PR à deux jobs (python ubuntu, swift container `swift:6`) → Task 4. ✓
- Déclencheurs PR + push main + concurrency → Task 4. ✓
- Footprint pip `pytest duckdb shapely` → Task 4 + Global Constraints. ✓
- Bench Deno / pipeline / simulate exclus → Global Constraints + README (Task 5). ✓
- Source de vérité `pipeline/tile_encoding.json` → Task 1. ✓
- Verrou exact 3 voies des clés → Task 1. ✓
- Codes machine-lisibles (demo `types`, commentaires Swift) → Task 2. ✓
- Présence best-effort demo + simulate → Task 3. ✓
- DvfTileKit conservé en CI → Task 4. ✓
- DvfTileClient.swift conservé comme fichier de contrat + commentaire MapKit corrigé → Task 1 (verrou struct) + Task 5 (en-tête). ✓
- Docs CLAUDE.md + README → Task 5. ✓
- Hors périmètre v1 (agrégats, codegen) → non implémenté, conforme. ✓

**2. Placeholders :** aucun « TBD »/« TODO »/code manquant — tout le code (JSON, test, YAML, éditions) est explicite.

**3. Cohérence des types/noms :** `ROOT`/`SPEC`/`_tile_props_from_prepare`/`_swift_struct_fields`/`_key_present`/`EXPECTED_CODES` définis en Task 1-3 et réutilisés sous les mêmes noms. Clés `soft_consumers` cohérentes avec les chemins lus. Commandes pytest cohérentes (`pipeline/parity tests/`).
