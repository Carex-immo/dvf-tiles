# CI GitHub Actions + verrou du contrat d'encodage — design

**Date** : 2026-06-18
**Statut** : design validé, à implémenter
**Auteur** : brainstorming Claude Code + Laurent

## Problème

Les tests existent (parité `pipeline/parity`, suite IRIS `tests/`, `swift test`
sur `client/DvfTileKit`, bench Deno `tests/edge-function-perf.test.ts`) mais
**rien ne les lance automatiquement**. Aucune Action GitHub n'est en place
(`.github/` absent). Le risque principal est l'**encodage compact partagé** :
les clés courtes + codes entiers des features MVT sont **dupliqués à la main**
dans quatre fichiers consommateurs (`pipeline/prepare.py` via `TILE_PROPS`,
`demo/index.html`, `client/simulate_ios.py`, `client/DvfTileClient.swift`) sans
source de vérité commune. Une modification dans un fichier non propagée aux
autres passe aujourd'hui inaperçue.

Objectif : une Action GitHub sur PR qui (1) joue les suites déterministes
existantes et (2) **verrouille le contrat des 4 fichiers** contre la dérive
silencieuse.

## Décisions de cadrage (validées)

- **Approche du test de contrat** : source de vérité unique + drift check
  (vs parité comportementale headless, plus lourde ; vs « juste lancer
  l'existant », qui ne traite pas le cœur du besoin).
- **Bench Deno** : exclu de la CI PR (frappe l'endpoint Supabase **live**,
  c'est une mesure de latence, pas un pass/fail — source de flakiness).
  Reste une commande manuelle.
- **Runner Swift** : container `swift:6` sur `ubuntu-latest` (DvfTileKit est
  zéro-dépendance, Foundation seul → ~10× moins cher que macOS).
- **DvfTileKit** : conservé en CI comme référence de parité / verrou de spec
  de l'encodage MVT, indépendamment du moteur carto (iOS est passé de MapKit à
  **MapLibreGL**).
- **`client/DvfTileClient.swift`** : conservé comme déclaration Swift canonique
  de l'encodage (le `struct Mutation` liste les 12 clés + codes `nat`/`type`).
  Son commentaire d'en-tête MapKit, périmé, sera corrigé (MapLibreGL).

## Architecture

Un seul workflow `.github/workflows/ci.yml`.

- **Déclencheurs** : `pull_request` (vers `main`) + `push` sur `main`.
- **Concurrency** : groupe par ref, `cancel-in-progress: true` (annule les runs
  obsolètes d'une même PR).
- **Deux jobs indépendants**, tous deux requis :

| Job | Runner | Commande |
|-----|--------|----------|
| `python` | `ubuntu-latest` | `pytest pipeline/parity tests/` |
| `swift` | `ubuntu-latest`, `container: swift:6` | `cd client/DvfTileKit && swift test` |

Tout ce qui tourne en CI est **déterministe et hors-ligne**. Hors périmètre :
run du pipeline complet (Go de CSV à télécharger), `simulate_ios.py` (exige
`build/dvf.pmtiles`), bench Deno (endpoint live).

### Job `python`

1. `actions/checkout`
2. `actions/setup-python` (3.12)
3. `pip install pytest duckdb shapely`
   - Footprint minimal vérifié : `consolidate.py`/`extended.py` (pont de parité)
     sont **stdlib pur** ; `duckdb` pour la suite IRIS (`test_build_iris`,
     `build_iris_index`) ; `shapely` pour `build_iris_index`/`simulate_iris`
     (`from shapely.geometry import shape, Point`).
   - `mapbox-vector-tile`/`pmtiles` **non requis** (uniquement pour
     `simulate_ios.py`, qui n'est pas un test unitaire CI).
4. `pytest pipeline/parity tests/` — une seule invocation ; `tests/` inclut le
   nouveau `test_tile_encoding_contract.py`.

### Job `swift`

1. `actions/checkout`
2. `swift test --package-path client/DvfTileKit` (ou `cd` + `swift test`)
   - Container `swift:6` : toolchain fournie, pas de setup. Fixtures MVT +
     goldens déjà committés.

## Test de contrat — composant central (nouveau)

### Source de vérité : `pipeline/tile_encoding.json`

Fichier déclaratif unique, à côté du producteur (`prepare.py`) :

```json
{
  "mutation_keys": ["id","date","nat","type","vf","sb","st","np","nl","com","adr","cp"],
  "nat":  {"1":"Vente","2":"VEFA","3":"Adjudication","4":"Echange","5":"Expropriation"},
  "type": {"1":"maison","2":"appartement","3":"immeuble","4":"local","5":"dependance"}
}
```

**Pourquoi ce JSON ne devient pas une 5ᵉ copie qui dérive** : le test force
`JSON == TILE_PROPS == struct Swift`. Il ne peut pas diverger silencieusement —
c'est le point d'ancrage *vérifié* et la référence lisible pour les
consommateurs souples, pas une nouvelle autorité concurrente.

### Test : `tests/test_tile_encoding_contract.py`

Placé dans `tests/` → joué par le job `python`. Stdlib seule (`json`, `re`,
`ast`, `pathlib`). **Ne pas importer `prepare.py`** (il importe `duckdb` et a
des effets de bord au niveau module) : lire `TILE_PROPS` par parsing `ast` du
source.

Trois niveaux de vérification, du plus fort au best-effort :

1. **Verrou exact des clés (3 voies)** — backbone du contrat :
   - `TILE_PROPS` extrait par `ast` de `pipeline/prepare.py`
   - `mutation_keys` de `tile_encoding.json`
   - champs `let <clé>:` du `struct Mutation` de `DvfTileClient.swift`
     (regex sur le bloc struct ; `coordinate` exclu = géométrie, pas une
     propriété)

   Les trois doivent être **égaux, ordre compris**. Renommer/ajouter/retirer
   une clé sans aligner les trois casse le test.

2. **Verrou des codes là où ils sont machine-lisibles** :
   - table `types[...]` de `demo/index.html` (mapping code→label déjà présent
     dans le JS) **==** bloc `type` du JSON.
   - codes `nat`/`type` documentés dans les commentaires du `struct Swift`
     (lignes `// 1 Vente, 2 VEFA, …`) parsés et comparés au JSON.

3. **Présence best-effort sur les consommateurs souples** :
   - les clés lues par `demo/index.html` et `client/simulate_ios.py` doivent
     être **⊆ `mutation_keys`** (détecte une clé périmée après renommage).
   - extraction par motifs spécifiques au langage (`p["…"]`, `["get","…"]`,
     `p.<clé>` pour JS ; `p["…"]`/`p.get("…")` pour Python) afin d'éviter les
     faux positifs type `type:"vector"` (clé MapLibre, pas la clé mutation).

### Limite assumée (explicite dans le test et la doc)

Seules les **clés** ont un verrou exact 3 voies (renforcé côté Swift par les
goldens DvfTileKit). Sur `demo`/`simulate`, les vérifs sont des regex
best-effort : elles attrapent le mode de panne réel — *renommer/ajouter une clé
et oublier un fichier* — pas une dérive sémantique profonde (ex. inverser le
sens du code 2). C'est le bon curseur pour la fragilité « dupliqué à la main »
sans sur-ingénierie. Si la dérive récidive malgré ça, l'étape suivante serait
le codegen des consommateurs depuis le JSON (hors périmètre v1).

## Périmètre exclu (YAGNI v1)

- Verrou des clés d'agrégats communes/départements (`n_{annee}_t{type}`,
  `p_{annee}_t{type}`, `cx`/`cy`, …) — extensible plus tard.
- Codegen des consommateurs depuis le JSON.
- Job Deno (bench live) ; run pipeline complet ; `simulate_ios.py`.

## Documentation à mettre à jour

- `CLAUDE.md` § « Encodage compact partagé » : pointer vers
  `pipeline/tile_encoding.json` + `tests/test_tile_encoding_contract.py` comme
  garde-fou désormais **enforced** (la mention « propager aux quatre » devient
  vérifiée).
- `README.md` § Validation : mentionner la CI (`.github/workflows/ci.yml`) et ce
  qu'elle joue.
- `client/DvfTileClient.swift` en-tête : corriger le commentaire MapKit →
  MapLibreGL.

## Critères de succès

- Une PR ouverte déclenche les deux jobs ; les deux passent sur l'état actuel
  de `main` (les suites existantes sont déjà vertes localement).
- Renommer une clé dans `prepare.py` (ou le struct Swift, ou le JSON) sans
  aligner les autres fait **échouer** `test_tile_encoding_contract.py`.
- Le job `python` n'installe que `pytest duckdb shapely` et tourne hors-ligne.
- Le job `swift` joue `swift test` dans le container `swift:6`.
```
