# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Vue d'ensemble

POC CAREX d'un service de tuiles DVF (ventes immobilières, données geo-dvf de la DGFiP). Le pipeline produit `build/dvf.pmtiles`, une archive PMTiles statique à 3 couches vectorielles, servie telle quelle en production (cible spec : R2/S3 + Worker PMTiles, `/{couche}/{z}/{x}/{y}.mvt`, tuile vide → 204). Implémente la spec `spec-service-tuiles-dvf.md` (hors dépôt). POC validé sur les départements 69 et 01 ; le pipeline supporte la France entière (`run_pipeline.sh france`), millésimes 2021–2025.

**Service de production (Supabase)** : `dvf.pmtiles` uploadé sur le bucket Storage public `tiles` (https://bqwbazolhtwizafxqzlr.supabase.co/storage/v1/object/public/tiles/dvf.pmtiles), servi via Edge Function Deno (`supabase/functions/dvf-tiles/`) sur la route `/{couche}/{z}/{x}/{y}.mvt` (validation couche/zoom, 204 si hors plage). **État MVP : l'extraction des tuiles depuis l'archive n'est pas encore implémentée — la fonction répond 204 pour toute tuile** (cf. `DEPLOYMENT.md` § À faire). Déploiement : `./scripts/deploy-supabase.sh` et doc dans `DEPLOYMENT.md`. Alternative en place : le client iOS lit le PMTiles directement par requêtes HTTP Range sur l'URL Storage publique (support natif) et le parse localement.

Tout le projet (code, commentaires, README) est rédigé en français.

## Commandes

Prérequis : venv Python (`.venv/` à la racine) + `tippecanoe` et `tile-join` dans le PATH.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install duckdb mapbox-vector-tile pmtiles
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
python3 pipeline/prepare.py --raw data/raw --geo data/geo --out build # DuckDB → GeoJSON(L)
./pipeline/build_tiles.sh build                                       # tippecanoe (2 passes mutations) + tile-join
python3 pipeline/qa_checks.py build                                   # bloquant : structure, comptages, exhaustivité z13
```

Validation (pas de tests automatisés ni de linter) :

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
        └── pipeline/prepare.py (DuckDB) ──────────┘
              ├─ build/mutations.geojsonl   (1 point par mutation, dédupliqué)
              ├─ build/communes.geojson     (agrégats année×type joints aux contours)
              └─ build/departements.geojson
                        │
              pipeline/build_tiles.sh : tippecanoe par couche
              (mutations en 2 passes : z4–12 échantillonné, z13–14 exhaustif),
              puis tile-join
                        │
              build/dvf.pmtiles  ← artefact de production
```

`prepare.py` fait le travail métier : les CSV DVF répètent chaque mutation par disposition/parcelle/local ; les CTE `locaux`/`parcelles`/`head` reconstruisent 1 ligne par `id_mutation` (surface bâtie sommée, type local dominant par surface, valeur foncière max).

Couches et stratégie de zoom (reprise côté clients) : `departements` z4–6, `communes` z6–10, `mutations` z4–14 — échantillonnées jusqu'à z12 (taille de tuile bornée), **exhaustives dès z13** (passe tippecanoe dédiée `-pk -pf`, contrôle bloquant dans `qa_checks.py`). Côté client : z<7 départements, z7–10 communes, z≥11 points (échantillon d'affichage), stats exactes (comptes, médianes) à z≥13 uniquement ; zoom de données plafonné à 14 ; les filtres s'appliquent en mémoire côté client, jamais par le réseau.

## Encodage compact partagé — à garder synchronisé

Les propriétés des features utilisent des clés courtes et des codes entiers (spec §5). Cet encodage est dupliqué dans **quatre fichiers consommateurs** : `pipeline/prepare.py` (production), `demo/index.html`, `client/simulate_ios.py`, `client/DvfTileClient.swift`. Toute modification doit être propagée aux quatre.

- Mutations : `id, date (YYYYMMDD), annee, nat, type, vf, sb, st, pm2, np, nl, nc, dep, com` — les propriétés nulles/absentes sont omises du GeoJSON.
- `nat` : 1 Vente, 2 VEFA, 3 Adjudication, 4 Échange, 5 Expropriation, 6 Terrain à bâtir, 0 autre.
- `type` (code_type_local) : 0 terrain/sans local, 1 maison, 2 appartement, 3 dépendance, 4 local com./ind.
- `nc` (nature culture dominante) : 0 nul, 1 S, 2 T, 3 P*, 4 VI, 5 B*, 6 J, 7 autre.
- Agrégats communes/départements : `n_{annee}_t{type}` (compte), `p_{annee}_t{type}` (€/m² médian), plus `n_tot`, `pm2_med`, `vf_med`.

## Pièges connus

- **Limite de taille tippecanoe** : la limite par défaut de 500 Ko/tuile déclenche `--drop-densest-as-needed` à *tous* les zooms, même au-dessus de `-B` — c'est ce qui a invalidé l'ancien contrat « exhaustif dès z11 » au passage France entière. L'exhaustivité n'existe que sur la passe z13–14 construite avec `-pk -pf`. Ne pas remettre `--extend-zooms-if-still-dropping` sur la passe z4–12 : elle régénérerait des tuiles z13+ échantillonnées, fusionnées en doublons par tile-join.
- **Arrondissements municipaux** : DVF code les mutations au niveau arrondissement (`751xx`, `6938x`, `132xx`) — `download_geo.sh` récupère automatiquement ceux de Paris/Lyon/Marseille en plus des contours communaux.
- **COG mouvant** : geo-dvf garde le COG d'origine de chaque millésime ; `prepare.py` remappe les communes fusionnées/scindées vers le COG courant (localisation des points dans les polygones + table INSEE `cog_mouvements.csv`), cf. README § gestion du COG. Saint-Barthélemy/Saint-Martin (`97123`/`97127`), absents de geo.api.gouv.fr, viennent d'un contour statique versionné (`pipeline/static/communes_97x.geojson`).
- Les entités sans mutation sont rendues avec `n_tot: 0` dans les couches communes/départements (une commune sans vente n'est pas un trou) ; seule la couche points les ignore faute de coordonnées.
- Lors d'une recomposition d'agrégats multi-tuiles, dédupliquer par `properties.code` (les polygones apparaissent dans plusieurs tuiles).
- `data/` et `build/` sont des artefacts téléchargés/générés : ne pas les éditer à la main, relancer le pipeline.
- Passage France entière : utiliser les `full.csv.gz` (cf. commentaire dans `download.sh`) et fournir des contours nationaux.
