# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Vue d'ensemble

POC CAREX d'un service de tuiles DVF (ventes immobilières, données geo-dvf de la DGFiP). Le pipeline produit `build/dvf.pmtiles`, une archive PMTiles statique à 3 couches vectorielles, servie telle quelle en production (cible spec : R2/S3 + Worker PMTiles, `/{couche}/{z}/{x}/{y}.mvt`, tuile vide → 204). Implémente la spec `spec-service-tuiles-dvf.md` (hors dépôt). POC validé sur les départements 69 et 01 ; le pipeline supporte la France entière (`run_pipeline.sh france`), millésimes 2021–2025.

**Service de production (Supabase)** : `dvf.pmtiles` uploadé sur le bucket Storage public `tiles` (https://bqwbazolhtwizafxqzlr.supabase.co/storage/v1/object/public/tiles/dvf.pmtiles), servi via Edge Function Deno (`supabase/functions/dvf-tiles/`) sur la route `/{couche}/{z}/{x}/{y}.mvt` (validation couche/zoom, 204 si hors plage). **Extraction des tuiles implémentée (v1.0)** : index pré-calculé `tiles_index.json` (généré par `scripts/build-tile-index.mjs`, uploadé sur le bucket) → lookup O(1) `tiles[z][x][y]` → lecture HTTP Range dans l'archive ; 200 MVT gzip, 204 si tuile absente (cf. `DEPLOYMENT.md` § État actuel). Déploiement : `./scripts/deploy-supabase.sh` et doc dans `DEPLOYMENT.md`. Alternative en place : le client iOS lit le PMTiles directement par requêtes HTTP Range sur l'URL Storage publique (support natif) et le parse localement.

Tout le projet (code, commentaires, README) est rédigé en français.

## Commandes

Prérequis : venv Python (`.venv/` à la racine) + `tippecanoe` et `tile-join` dans le PATH.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install duckdb mapbox-vector-tile pmtiles pytest
```

Pipeline complet via l'orchestrateur (venv activé) :

```bash
./pipeline/run_pipeline.sh poc      # 69 + 01 — validation, ~2 min
./pipeline/run_pipeline.sh france   # France entière — ~3 Go CSV, ~8 Go RAM, 30–90 min
```

Étapes individuelles, dans l'ordre :

```bash
./pipeline/download.sh "2021 2022 2023 2024 2025" "69 01" data/raw   # CSV geo-dvf (skip si déjà présents)
./pipeline/download_geo.sh "69 01" data/geo                          # contours + arrondissements + COG INSEE
python3 -m pytest -q pipeline/parity                                  # bloquant : parité goldens carex.immo
python3 pipeline/prepare.py --raw data/raw --geo data/geo --out build # consolidation parité + DuckDB → GeoJSON(L)
./pipeline/build_tiles.sh build                                       # tippecanoe (2 passes mutations) + tile-join
python3 pipeline/qa_checks.py build                                   # bloquant : structure, comptages, exhaustivité z13, adr
```

Validation (pas de linter ; les seuls tests automatisés sont ceux de `pipeline/parity/`) :

```bash
python3 client/simulate_ios.py build/dvf.pmtiles   # simule le chemin iOS : bbox → tuiles → MVT → filtres → stats
python3 demo/serve.py                              # → http://localhost:8080/demo/index.html (carte MapLibre)
```

`demo/serve.py` est indispensable pour la démo : PMTiles exige les requêtes HTTP Range, que le serveur Python standard ne gère pas.

## Architecture

Chaîne de données :

```
CSV geo-dvf (data/raw/)                 contours geo.api.gouv.fr (data/geo/)
        │                                          │
        └── pipeline/prepare.py ───────────────────┘
            consolidation = pipeline/parity/ (pont de parité carex.immo,
            règles goldens Swift, NE PAS MODIFIER) ; DuckDB pour l'aval
            (remap COG, agrégats, exports)
              ├─ build/mutations_consolidees.jsonl (intermédiaire, 1 ligne/mutation)
              ├─ build/mutations.geojsonl   (points ; terrain nu exclu, compté)
              ├─ build/communes.geojson     (agrégats année×type + centroïdes cx/cy)
              └─ build/departements.geojson
                        │
              pipeline/build_tiles.sh : tippecanoe par couche
              (mutations en 2 passes : z4–12 échantillonné SANS adr/cp,
              z13–14 exhaustif avec adresse), puis tile-join
                        │
              build/dvf.pmtiles  ← artefact de production
```

Le travail métier (1 mutation par `id_mutation` : fusion des biens, type dominant avec règle immeuble, sommes, ancrage par la parcelle de la 1ʳᵉ ligne) vit dans `pipeline/parity/consolidate.py`, **copie verbatim de `carex.immo/tools/dvf-tiles/`** verrouillée par les goldens Swift et rejouée à chaque build (`pytest pipeline/parity`). Toute évolution de règle part du Swift côté carex.immo puis se propage par recopie (cf. `pipeline/parity/README.md`). `pipeline/parity/extended.py` (propre à dvf-tiles) ajoute seulement la lecture des champs annexes `adr`/`cp`/`com`/`dep` et le support gzip.

Couches et stratégie de zoom (reprise côté clients) : `departements` z4–6, `communes` z6–10, `mutations` z4–14 — échantillonnées jusqu'à z12 (taille de tuile bornée), **exhaustives dès z13** (passe tippecanoe dédiée `-pk -pf`, contrôle bloquant dans `qa_checks.py`). Côté client : z<7 départements, z7–10 communes, z≥11 points (échantillon d'affichage), stats exactes (comptes, médianes) à z≥13 uniquement ; zoom de données plafonné à 14 ; les filtres s'appliquent en mémoire côté client, jamais par le réseau.

## Encodage compact partagé — à garder synchronisé

Les propriétés des features utilisent des clés courtes et des codes entiers (contrat carex.immo `docs/specs/2026-06-11-tuiles-mvt-contrat-integration.md` + spec locale `docs/superpowers/specs/2026-06-12-parite-consolidation-adresse-design.md`). Cet encodage est dupliqué dans **quatre fichiers consommateurs** : `pipeline/prepare.py` (production, `TILE_PROPS`), `demo/index.html`, `client/simulate_ios.py`, `client/DvfTileClient.swift`. Toute modification doit être propagée aux quatre.

- Mutations : `id, date (YYYYMMDD), nat, type, vf, sb, st, np, nl, com, adr, cp` — les propriétés nulles/absentes sont omises (jamais de sentinelle). **`adr`/`cp` n'existent qu'à z≥13** (exclus de la passe z4–12 par `-x`). `annee` (= `date // 10000`), `pm2` (= `vf/sb` si les deux > 0) et `dep` (préfixe de `com`) sont des dérivés côté client.
- `nat` (`MutationType` app) : 1 Vente (et terrain à bâtir, et repli), 2 VEFA, 3 Adjudication, 4 Échange, 5 Expropriation — jamais 0.
- `type` (`PropertyType` app, via `compute_primary_type`) : 1 maison, 2 appartement, 3 immeuble (≥ 3 apparts ou appart+local), 4 local com./ind., 5 dépendance — le terrain nu (type nul) est **exclu de la couche points** et compté dans `prepare_stats.json`.
- `sb` : Σ bâti des biens post-fusion hors dépendances ; `np` : somme des pièces ; `nl` : nb de biens post-fusion ; `vf` : valeur de la 1ʳᵉ ligne, arrondi half-away.
- Agrégats communes/départements : `n_{annee}_t{type}` (compte), `p_{annee}_t{type}` (€/m² médian), plus `n_tot`, `pm2_med`, `vf_med`, et `cx`/`cy` (centroïde du plus grand anneau, pour cercles proportionnels). Population = mutations consolidées (terrain nu inclus dans `n_tot`, mutations sans ancre exclues).

## Pièges connus

- **Limite de taille tippecanoe** : la limite par défaut de 500 Ko/tuile déclenche `--drop-densest-as-needed` à *tous* les zooms, même au-dessus de `-B` — c'est ce qui a invalidé l'ancien contrat « exhaustif dès z11 » au passage France entière. L'exhaustivité n'existe que sur la passe z13–14 construite avec `-pk -pf`. Ne pas remettre `--extend-zooms-if-still-dropping` sur la passe z4–12 : elle régénérerait des tuiles z13+ échantillonnées, fusionnées en doublons par tile-join.
- **Arrondissements municipaux** : DVF code les mutations au niveau arrondissement (`751xx`, `6938x`, `132xx`) — `download_geo.sh` récupère automatiquement ceux de Paris/Lyon/Marseille en plus des contours communaux. Les polygones des communes parentes (`75056`/`69123`/`13055`, constante `PLM_PARENTS`) sont exclus de la couche communes ET de `reassign_scissions` : sans cette garde, le parent — jamais porteur de stats propres — « volerait » les mutations de ses arrondissements par localisation (constaté : 50 000 mutations lyonnaises réaffectées à 69123, arrondissements à `n_tot=0`).
- **Pont de parité** : ne jamais « corriger » `pipeline/parity/consolidate.py` ni ses tests/goldens — copie verbatim de carex.immo (cf. `pipeline/parity/README.md`) ; les règles évoluent côté Swift, goldens régénérés, puis recopie. `extended.py` et `test_parity_extended.py` sont les seuls fichiers modifiables du répertoire.
- **`-x adr -x cp` est une option tippecanoe par invocation** (passe z4–12 uniquement) : posée sur `tile-join`, elle purgerait l'adresse de TOUTES les tuiles, z13–14 comprises.
- **Population des comptages** : depuis la parité, les mutations sans ancre (parcelle de la 1ʳᵉ ligne sans coordonnées) sont rejetées partout, le filtre `vf > 0` a disparu (vf simplement omise) et le terrain nu sort de la couche points — premier build après un tel changement : `qa_checks.py --reset-baseline`.
- **COG mouvant** : geo-dvf garde le COG d'origine de chaque millésime ; `prepare.py` remappe les communes fusionnées/scindées vers le COG courant (localisation des points dans les polygones + table INSEE `cog_mouvements.csv`), cf. README § gestion du COG. Saint-Barthélemy/Saint-Martin (`97123`/`97127`), absents de geo.api.gouv.fr, viennent d'un contour statique versionné (`pipeline/static/communes_97x.geojson`).
- Les entités sans mutation sont rendues avec `n_tot: 0` dans les couches communes/départements (une commune sans vente n'est pas un trou).
- Lors d'une recomposition d'agrégats multi-tuiles, dédupliquer par `properties.code` (les polygones apparaissent dans plusieurs tuiles).
- `data/` et `build/` sont des artefacts téléchargés/générés : ne pas les éditer à la main, relancer le pipeline.
- Passage France entière : utiliser les `full.csv.gz` (cf. commentaire dans `download.sh`) et fournir des contours nationaux.
