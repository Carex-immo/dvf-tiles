# Spec — Index IRIS départemental `stats/iris_index/{DD}.json`

**Date :** 2026-06-17
**Projet :** dvf-tiles (CAREX — service de tuiles DVF)
**Statut :** Design validé, prêt pour plan d'implémentation

## 1. Besoin

Fournir un **index spatial léger des IRIS, un fichier par département**, que l'app iOS
peut charger sans décoder de tuile ni télécharger de géométrie : pour chaque IRIS, son
**code**, sa **commune**, un **point centre** (lat/lon) et sa **bbox**. Versionné via la
clé `version` du manifest existant (mécanisme `?v=` déjà en place).

Usages côté app : localiser/lister les IRIS d'un département, tri « IRIS le plus proche »,
poser un repère/label, pré-cadrage de carte — **sans** charger les contours ni les tuiles.

### Hors périmètre

- Toute géométrie de contour (le contour vit déjà dans `stats/iris/{code}.json`, couche `iris` des tuiles).
- Tout filtrage/agrégat (mutations) : l'index ne porte que de la donnée de localisation.
- Génération du `manifest.json` complet (communes/départements) : **produite par un pipeline externe**
  à ce repo (cf. §5) ; ce repo ne fait qu'**ajouter** les bits IRIS de façon additive.

## 2. Décisions d'architecture (validées)

| Décision | Choix |
|---|---|
| Couverture | **Tous les IRIS** de CONTOURS-IRIS (y compris ceux sans mutation) — construit depuis la géométrie seule |
| Point « centre » | **`ST_PointOnSurface`** (toujours à l'intérieur du polygone, même concave/multipart) |
| Clé département `{DD}` | `code[:3]` si le code commence par `97`/`98` (DOM/COM → `971`…`976`), sinon `code[:2]` (couvre `01`…`95` **et** la Corse `2A`/`2B`) — **identique** à la convention du manifest existant |
| Manifest | **Un seul** : le `stats/manifest.json` existant, **enrichi de façon additive** (pas de 2ᵉ manifest, pas de manifest racine) |
| Source de version | **Inchangée** : `version` est minté par le pipeline stats externe ; ce repo **préserve** `version` et n'en mint jamais |
| Service des fichiers | Objets statiques publics (comme `stats/iris/*.json`), fetch avec `?v={version}`, cache long/immutable |

## 3. Artefact A — `stats/iris_index/{DD}.json`

Un **tableau JSON** par département, trié par `code` (sortie déterministe) :

```json
[
  {"code":"010010000","com":"01001","lat":46.1763,"lon":4.9261,"bbox":[4.901,46.158,4.951,46.195]},
  {"code":"010040000","com":"01004","lat":45.9612,"lon":5.3505,"bbox":[5.31,45.93,5.39,45.99]}
]
```

| Champ | Source | Détail |
|---|---|---|
| `code` | `CODE_IRIS` | 9 caractères (INSEE commune 5 + IRIS 4) |
| `com` | `INSEE_COM` | 5 caractères |
| `lat`, `lon` | `ST_Y/ST_X(ST_PointOnSurface(geom))` | point intérieur garanti, arrondi à 6 décimales |
| `bbox` | `[ST_XMin, ST_YMin, ST_XMax, ST_YMax](geom)` | `[minLon, minLat, maxLon, maxLat]`, 6 décimales |

- **Encodage :** UTF-8, JSON compact (`separators=(",",":")`, `ensure_ascii=False`).
- **Nom de fichier :** `{DD}.json` où `{DD}` = clé département (cf. §2). Ex. `01.json`, `2A.json`, `974.json`.
- **Note couverture :** l'index liste *tous* les IRIS ; certains `code` n'ont **pas** de
  `stats/iris/{code}.json` (zéro mutation). Le client traite un 404/204 sur le fetch détail
  comme « pas de données » (cohérent avec la spec IRIS §9, pas de fallback IRIS le plus proche).
  Le schéma reste **strict** (`code, com, lat, lon, bbox`) — pas d'indicateur de présence de données.
- **Couverture réelle CONTOURS-IRIS 3-0 (2026-01-01), mesurée :** **104 départements, 49 386 IRIS**.
  Clés DOM/COM produites : `971`…`978` (incl. St-Barthélemy `977`, St-Martin `978`) ; Corse `2A`/`2B` ;
  **aucun `98x`** (Polynésie / N.-Calédonie / Wallis / TAAF non couverts). Conséquence : la branche
  `98` de `dep_of` est inerte sur la donnée réelle.
- **Alignement clé pipeline ↔ app (validé iOS) :** tous les codes à 3 caractères commencent par
  `97`, donc `dep_of` ≡ `EntityStats.departement(forInsee:)` de l'app
  (`hasPrefix("97") ? prefix(3) : prefix(2)`) sur **100 % des IRIS réels**. ⚠️ **Point d'action
  côté app** (hors de ce repo) : la spec app utilise encore `communeCode.prefix(2)` → un bien DOM
  (`97411`) chercherait `iris_index/97.json` (404, repli commune silencieux) au lieu de `974.json`.
  À corriger côté app pour utiliser `EntityStats.departement(forInsee:)` **avant l'implémentation app**.

## 4. Artefact B — `stats/manifest.json` (enrichi, additif)

Forme **actuelle** (millésime 2026-06, pipeline externe) :

```json
{"version":"20260614T102335Z","generated":"20260614T102335Z","dense_threshold":200,
 "years":[2021,2022,2023,2024,2025],
 "layers":{"departements":"stats/departements.json","communes":"stats/dep/{DD}.json"},
 "departements":["01","02","…","2A","2B","…","971","972","973","974"],
 "compteurs":{"departements":109,"communes":34902,"bundles_dep":100}}
```

Ce repo **ajoute trois choses** et **préserve tout le reste** (`version`, `generated`,
`dense_threshold`, `years`, `departements`, les autres entrées de `layers`/`compteurs`) :

```jsonc
{
  // … tous les champs existants intacts, dont version …
  "millesime_iris": "2026",                         // NOUVEAU, top-level (à côté de "years")
  "layers": {
    "departements": "stats/departements.json",
    "communes": "stats/dep/{DD}.json",
    "iris_index": "stats/iris_index/{DD}.json"      // NOUVEAU hint
  },
  "compteurs": { "departements": 109, "communes": 34902, "bundles_dep": 100, "iris": 48000 }  // + iris
}
```

- **`version` jamais minté ici.** Une seule source de version (pipeline stats externe).
  L'IRIS hérite gratuitement du `?v={version}` courant. **Zéro casse de décodage** : aucun
  champ existant n'est modifié.
- **Contrainte d'orchestration (validée iOS) :** `iris_index` est posé `immutable` mais son
  `?v=` vient de `version`, que ce repo ne bumpe pas. **Toujours co-déployer l'IRIS avec un
  run qui bumpe `version`** (run stats complet) ; **ne jamais déployer `iris_index` en
  isolation** — sinon les clients déjà en cache restent sur l'ancien index jusqu'à 1 an. La
  géométrie IRIS ne change qu'avec `millesime_iris` (≈ annuel), donc la contrainte est rare
  mais stricte.
- **Fenêtre `rm`→`cp` du manifest :** bref 404 entre suppression et upload (toutes couches) ;
  l'app dégrade en `version = nil` → requêtes sans `?v=`, fonctionnel. Pattern pré-existant
  (tout update de manifest), non spécifique à l'IRIS.

## 5. Composants & intégration pipeline

> Le `manifest.json`, `stats/departements.json` et `stats/dep/{DD}.json` sont **générés par
> un pipeline externe** à ce repo. Le déploiement de ce repo est **additif et non destructif**
> (ne touche ni `dvf.pmtiles` ni `stats/dep/`) — cf. `deploy/README.md`.

### 5.1 `pipeline/build_iris_index.py` (nouveau)
- DuckDB + `INSTALL spatial; LOAD spatial;`.
- Charge les IRIS via `ST_Read` (GPKG ou GeoJSON), normalisation des colonnes
  (`code_iris`, `insee_com`, `geom`) sur le modèle de `build_iris.load_iris`.
- Calcule `ST_PointOnSurface` (une seule fois, via CTE) + bornes bbox ; arrondit à 6 décimales.
- Groupe par département (`dep_of(code)`), trie chaque liste par `code`, écrit
  `{out}/iris_index/{DD}.json`.
- Fonctions testables : `connect()`, `dep_of(code)`, `load_iris(con, path)`,
  `build_index(con) -> {dep: [entries]}`, `write_index(by_dep, out_dir) -> (n_files, n_iris)`.
- CLI : `--iris data/geo/CONTOURS-IRIS.gpkg --out build`.

### 5.2 `pipeline/patch_manifest.py` (nouveau)
- Charge le manifest **live** (`--manifest-url`) ou local (`--manifest-file`).
- Compte les IRIS et les départements depuis `--iris-index-dir` (somme des longueurs des
  tableaux `iris_index/*.json`).
- **Merge additif idempotent** : pose `millesime_iris`, `layers.iris_index`,
  `compteurs.iris` ; ne supprime/altère **aucune** autre clé (dont `version`).
- Écrit `--out` en JSON compact (mêmes `separators` que l'existant).
- Fonctions testables : `load_manifest(...)`, `count_iris(dir) -> (n_iris, deps)`,
  `merge(manifest, millesime, n_iris) -> manifest`, `main()`.
- CLI : `--manifest-url <url> | --manifest-file <path>`, `--iris-index-dir build/iris_index`,
  `--millesime 2026`, `--out build/manifest.json`.

### 5.3 `pipeline/build_france.sh` (modif)
Ajouter, après l'étape `build_iris.py` :
```bash
echo "== 2b) build_iris_index.py France (stats/iris_index/{DD}.json) =="
$PY pipeline/build_iris_index.py --iris "$GPKG" --out "$OUT"
```
(Le patch du manifest se fait au **déploiement**, contre le manifest *live*, pas au build.)

### 5.4 `deploy/deploy_cli.sh` (modif, additif)
Deux ajouts, fidèles à la philosophie non destructive existante :
1. **Upload `iris_index/`** → `tiles/stats/iris_index/{DD}.json`
   (`--content-type application/json`, cache **long/immutable** : `max-age=31536000, immutable`
   — sûr car `?v=` busté ; ~101 fichiers, pas de chunk anti-GOAWAY nécessaire).
2. **Patch + upload manifest** : `patch_manifest.py --manifest-url <live>` puis
   `rm` + `cp` de `stats/manifest.json` (cp ne fait pas d'upsert) avec `cache-control: no-cache`
   (header actuel conservé).
3. **Garde d'orchestration** : un `echo` d'avertissement rappelle de ne pas déployer l'IRIS en
   isolation (co-déployer avec un run qui bumpe `version`, cf. §4).

> **Sanity infra :** le ref Supabase `bqwbazolhtwizafxqzlr` est hardcodé dans `deploy_cli.sh`
> et l'Edge Function. Le manifest live a été récupéré avec succès sur
> `bqwbazolhtwizafxqzlr.supabase.co` → les bundles stats y sont **bien déployés et servis**.
> Reste à confirmer côté app que son `SUPABASE_URL` (obfusqué dans les Secrets) pointe le même
> projet — quasi certain, mais invérifiable depuis le pipeline.

## 6. Tests

### 6.1 `tests/test_build_iris_index.py`
GeoJSON IRIS synthétique (sur le modèle de `tests/test_build_iris.py`) :
- groupement par département incl. un IRIS Corse `2A…` et un DOM `974…` (vérifie `dep_of`) ;
- bbox exacte sur un polygone connu ;
- `ST_PointOnSurface` **à l'intérieur** d'un polygone concave/multipart (point-in-polygon) ;
- schéma strict (`code, com, lat, lon, bbox`) et tableau **trié par `code`**.

### 6.2 `tests/test_patch_manifest.py`
- merge préserve **tous** les champs existants, dont `version` (valeur inchangée) ;
- ajoute `millesime_iris`, `layers.iris_index`, `compteurs.iris` ;
- **idempotent** : un 2ᵉ passage ne duplique ni ne corrompt rien.

## 7. Cas limites

| Cas | Traitement |
|---|---|
| IRIS sans mutation | Présent dans l'index (couverture « tous IRIS ») ; pas de `stats/iris/{code}.json` → 404/204 côté client = « pas de données » |
| Polygone concave / MultiPolygon | `ST_PointOnSurface` garantit un centre intérieur |
| Corse / DOM | `dep_of` : `2A`/`2B` via `code[:2]`, `971`…`976` via `code[:3]` — aligné sur `manifest.departements` |
| Département dans l'index mais absent de `manifest.departements` (constaté : `975`–`978`) | `patch_manifest` **logue l'écart** ; le client n'itère que `manifest.departements` → fichiers extra inoffensifs (non demandés). Ne pas modifier la liste (owned externe). |
| Expansion « limitrophe » inter-départements côté app | Hors périmètre pipeline : chaque `iris_index/{DD}.json` ne contient qu'un seul département, donc aucun voisin n'y est découvrable. Nécessiterait une **table d'adjacence** — décision app, non traitée ici. |
| Manifest live momentanément indisponible au déploiement | `patch_manifest` échoue explicitement (pas d'écrasement d'un manifest vide) ; relancer |

## 8. Critères d'acceptation

1. `build_iris_index.py` produit un `{out}/iris_index/{DD}.json` par département, tableau trié
   par `code`, chaque entrée au schéma `{code, com, lat, lon, bbox}`.
2. Pour chaque entrée, le point `(lat, lon)` est **dans** le polygone de l'IRIS et la `bbox`
   contient le polygone.
3. `patch_manifest.py` produit un manifest qui contient **tous** les champs d'origine (dont
   `version` à l'identique) plus `millesime_iris`, `layers.iris_index`, `compteurs.iris`, et
   est idempotent.
4. `build_france.sh` enchaîne la génération de l'index ; `deploy_cli.sh` pousse `iris_index/`
   et le manifest enrichi sans toucher `dvf.pmtiles` ni `stats/dep/`.
5. Vérif publique : `GET stats/iris_index/{DD}.json?v={version}` renvoie le tableau attendu ;
   `GET stats/manifest.json` expose `layers.iris_index` + `millesime_iris`.
6. Les tests `test_build_iris_index.py` et `test_patch_manifest.py` passent.

## 9. Estimation de volume

- ~101 fichiers `iris_index/{DD}.json` (un par département) ; ~48 000 entrées au total France.
- Chaque entrée ≈ 90–110 octets ; un département dense (Paris/Rhône) reste de l'ordre de
  quelques dizaines à centaines de Ko (≪ les `stats/iris/{code}.json`). Gzip côté CDN.
