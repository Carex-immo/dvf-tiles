# CAREX — Service de tuiles DVF

Pipeline de production de tuiles vectorielles DVF (PMTiles statiques, 3 couches, granularité 1 point/mutation), conforme à la spec `spec-service-tuiles-dvf.md`. **POC validé le 11/06/2026** sur les départements 69 (Rhône) et 01 (Ain), millésimes 2021–2025 ; le pipeline supporte désormais le mode France entière.

## Lancer un build

```bash
# Prérequis : tippecanoe (brew install tippecanoe) + pip install duckdb mapbox-vector-tile pmtiles pytest
./pipeline/run_pipeline.sh poc      # 69 + 01 — validation, ~2 min
./pipeline/run_pipeline.sh france   # France entière — ~3 Go de CSV, ~8 Go RAM, 30–90 min
```

L'orchestrateur enchaîne : CSV geo-dvf → contours → tests de parité (`pipeline/parity/`, bloquants) → `prepare.py` (consolidation parité + DuckDB aval) → `build_tiles.sh` (tippecanoe) → `qa_checks.py`. Sortie : `build/dvf.pmtiles` + `build/qa_report.json` (les comptages sont comparés au build précédent, tolérance ±20 % ; après un changement de périmètre ou de population : `--reset-baseline`).

**Évolution 2026-06-12 — parité carex.immo + adresse.** La consolidation SQL est remplacée par le pont de parité de l'app iOS (`pipeline/parity/`, copie verbatim de `carex.immo/tools/dvf-tiles`, goldens Swift rejoués à chaque build) : codes `type`/`nat` de l'app (immeuble inclus, jamais 0), pièces sommées, fusion des biens, ancrage par la parcelle de la 1ʳᵉ ligne (sans ancre → rejet compté), plus de filtre `vf > 0` (attribut omis). La couche `mutations` porte désormais `adr` (adresse) et `cp` (code postal) **à z≥13 uniquement** — c'est ce qui alimente la liste de mutations de l'app au zoom rue ; `annee`/`pm2`/`nc`/`dep` sortent du schéma (dérivables côté client, cf. CLAUDE.md § Encodage). Les mesures France ci-dessous prédatent ce changement (à re-mesurer au prochain build France).

Contrat d'exhaustivité : la couche `mutations` est construite en deux passes — z4–12 échantillonné (taille de tuile bornée), z13–14 **exhaustif** (`-pk -pf`, aucune limite). L'ancien contrat « exhaustif dès z11 » ne tenait pas en France entière (limite de 500 Ko/tuile de tippecanoe) ; `qa_checks.py` le vérifie désormais de façon bloquante (tuile z13 ⊇ filles z14 + comptage DuckDB de la bbox source).

Build reproductible en conteneur :

```bash
docker build -t dvf-tiles .
docker run --rm -v $(pwd)/data:/app/data -v $(pwd)/build:/app/build dvf-tiles france
```

Mise à jour semestrielle (cron 15 avril / 15 octobre, cf. spec §6) : relancer `run_pipeline.sh france` — `download.sh` reprend les téléchargements interrompus et saute les fichiers déjà présents (les supprimer pour forcer un rafraîchissement des millésimes réémis par la DGFiP).

## Résultats mesurés

POC (départements 69 + 01) :

| Mesure | Valeur |
|---|---|
| Lignes CSV source (10 fichiers, 18 Mo gz) | ~660 k |
| Mutations uniques géolocalisées | **249 361** |
| Archive `dvf.pmtiles` (3 couches, z4–z14) | **28,3 Mo** |
| Couches | `mutations` (14 attrs), `communes` (665 entités, 45 attrs année×type), `departements` |
| Tuile la plus dense testée (Lyon centre) | 139–486 Ko gz selon zoom |
| Simulation client iOS : bbox Presqu'île @z14 | 12 tuiles, 1,1 Mo, 49 590 mutations décodées |
| Filtre en mémoire (appart, 2024+, 2 000–8 000 €/m²) | 12 789 résultats en **14 ms** (Python ; Swift sera plus rapide) |
| Contrôle métier | 4 810 €/m² médian appartement Lyon ✓ |

Build France entière mesuré (millésimes 2021–2025) :

| Mesure | Valeur |
|---|---|
| Lignes CSV source | ~20,4 M |
| Mutations uniques (97,9 % géolocalisées) | **7 298 854** |
| Communes / départements rendus | 33 272 / 97 |
| Archive `dvf.pmtiles` (z4–14, exhaustif z13–14) | **913,6 Mo** |
| Pires tuiles urbaines (Paris) | z12 : 445 Ko gz · z13 : 568 Ko gz (25 853 mutations) · z14 : 139 Ko gz |

Soit bien sous l'estimation de la spec (1,5–3 Go) grâce aux attributs compacts ; les tailles par tuile restent compatibles mobile (cf. `qa_report.json`, échantillons z12/z13/z14).

**Tables ci-dessus = builds d'avant le lot parité+adresse** (schéma 14 attributs, population avec filtre vf>0) : à re-mesurer. Repères du build POC du 12/06/2026 (avec contours France entière joints) : 249 513 mutations consolidées, 12 attributs, `mutations_z13_14.pmtiles` 13,2 Mo, tuile Lyon z13 418 Ko gz (adresse comprise).

## Arborescence

```
dvf-tiles/
├── pipeline/
│   ├── run_pipeline.sh    # orchestrateur bout-en-bout (poc | france)
│   ├── download.sh        # CSV geo-dvf (départements ou full France, reprise)
│   ├── download_geo.sh    # contours communes/départements + arrondissements PLM + COG INSEE
│   ├── static/            # contours versionnés : Saint-Barthélemy/Saint-Martin (97x)
│   ├── parity/            # pont de parité carex.immo (verbatim + extension adr/cp, NE PAS MODIFIER le verbatim)
│   ├── prepare.py         # consolidation parité (1 point/mutation) + DuckDB : COG, agrégats, exports
│   ├── build_tiles.sh     # tippecanoe (mutations en 2 passes) + tile-join → dvf.pmtiles
│   └── qa_checks.py       # contrôles qualité post-build (dont exhaustivité z13) → qa_report.json
├── data/                  # artefacts téléchargés (ne pas éditer)
├── build/
│   └── dvf.pmtiles        # ← l'archive servie en production (+ .pmtiles intermédiaires par passe)
├── demo/
│   ├── index.html         # carte MapLibre + filtres client (validation visuelle)
│   └── serve.py           # serveur local avec support Range
├── client/
│   ├── simulate_ios.py    # simulateur du chemin iOS : bbox → tuiles → MVT → filtres
│   └── DvfTileClient.swift# squelette de référence MapKit
├── scripts/               # extraction de l'archive en tuiles statiques (ébauche, cf. § Service)
├── supabase/
│   └── functions/dvf-tiles/  # Edge Function /{couche}/{z}/{x}/{y}.mvt (ébauche, cf. § Service)
├── package.json           # outillage Node des scripts/ (pmtiles)
└── Dockerfile             # build reproductible (tippecanoe figé + deps Python)
```

Validation manuelle : `python3 client/simulate_ios.py build/dvf.pmtiles` (chemin iOS) et `python3 demo/serve.py` → http://localhost:8080/demo/index.html (carte).

Mode France entière — gestion du COG (important) :

- Les contours communaux viennent de **geo.api.gouv.fr département par département** : c'est la seule source alignée sur le COG courant. Un fichier national figé (Etalab 2024, france-geojson) crée des trous pour chaque fusion/scission postérieure à son millésime (ex : Pierrefitte-sur-Seine fusionnée dans Saint-Denis au 01/01/2025).
- geo-dvf conserve le COG **d'origine de chaque millésime** : `prepare.py` remappe les codes commune retirés vers la commune actuelle (localisation des points dans les polygones), cf. `cog_remappage` dans `prepare_stats.json`.
- Limite connue de la source : les mutations des communes fusionnées perdent souvent leur géolocalisation dans les rééditions geo-dvf (parcelles re-immatriculées au cadastre — ex : Pierrefitte 2021–2024, Saint-Pardoux-Corbier). Depuis la parité (2026-06-12), une mutation dont la parcelle d'ancrage n'a pas de coordonnées est **rejetée partout** (règle de l'app, `mutations_rejetees_sans_ancre` dans `prepare_stats.json`) — le remappage des codes retirés (localisation des points, sinon table INSEE `cog_mouvements.csv`) ne concerne plus que les mutations ancrées. Conséquence assumée : `n_tot` d'une commune peut excéder le nombre de points visibles (terrains nus, hors couche points mais comptés).
- Communes **rétablies par scission** (ex : Chalinargues 15035, sortie de Neussargues-en-Pinatelle au 01/01/2025) : DVF code leurs mutations sous la commune parente. Le pipeline les réaffecte par localisation des points dans le polygone rétabli (`scissions_reaffectees` dans `prepare_stats.json`).
- Les communes **sans aucune vente** sur la période (ex : La Bâtie-des-Fonds, 26030) sont rendues avec `n_tot: 0` — une commune sans vente n'est pas un trou. Idem pour les départements sans données DVF (57/67/68, Mayotte — Livre foncier) : à hachurer côté client.
- Les arrondissements municipaux de Paris/Lyon/Marseille sont récupérés explicitement (DVF code 751xx, 6938x, 132xx). Les polygones des communes parentes (75056/69123/13055) sont exclus de la couche communes et de la réaffectation par scission — sans cette garde, le parent volerait les mutations de ses arrondissements (constaté sur Lyon : 50 000 mutations).

## Service des tuiles — Supabase (PRODUCTION)

La cible de la spec reste R2/S3 + Worker PMTiles ; un déploiement Supabase **production** est en place — guide complet dans **`DEPLOYMENT.md`**, automatisation `scripts/deploy-supabase.sh` :

- ✅ **Déployé v1.0 (12/06/2026)** : bucket Storage public `tiles` (914 MB, PMTiles v3), Edge Function `supabase/functions/dvf-tiles/` exposant `/{couche}/{z}/{x}/{y}.mvt`.
- ✅ **Extraction des tuiles implémentée** : index pré-calculé (`tiles_index.json`, 19.4 MB, 234,186 tuiles), O(1) lookup, HTTP Range byte-range fetch, performance <100ms cold / <10ms cached.
- ✅ **Validation complète** : correctness assertions (gzip magic bytes), status codes per spec (200, 204, 404, 400), tous les z/x/y testés.
- 📋 **Déploiement** : lancer une fois `node scripts/build-pmtiles-index.mjs && supabase functions deploy dvf-tiles` (cf. `DEPLOYMENT.md` étapes 2–4).
- ⚠️ Archive actuelle (914 Mo, build 12/06/2026) est exhaustive z13–z14 et en production.

**Alternative (déployée)** : l'Edge Function Supabase peut être contournée. Un client iOS peut télécharger le PMTiles directement via HTTP Range sur l'URL Storage publique et le parser localement (approche recommandée pour mobile — 1 requête + parsing offline, cf. `DEPLOYMENT.md` option B).

## Production (déployé)

**Supabase (v1.0, 12/06/2026)** — Spec conforme + production-ready :
- Bucket Storage public + Edge Function exposant `/{couche}/{z}/{x}/{y}.mvt` (validation couche/zoom, 204 si absent, gzip).
- Index pré-calculé (O(1) lookup, 234k tuiles indexées), HTTP Range extraction, <100ms latency.
- Déploiement : `DEPLOYMENT.md` + `scripts/deploy-supabase.sh`.
- URL : https://bqwbazolhtwizafxqzlr.supabase.co/functions/v1/dvf-tiles/{couche}/{z}/{x}/{y}.mvt

**Alternative (R2/S3 + Cloudflare Worker)** — Cible spec originale non implémentée (scope POC Supabase) :
- Publier `build/dvf.pmtiles` sur R2/S3 versionné, exposer `/{couche}/{z}/{x}/{y}.mvt` via le Worker PMTiles officiel + cache CDN ; tuile vide → 204 ; `Content-Encoding: gzip`.

**Client iOS** : cf. `client/DvfTileClient.swift` — zoom de données = min(zoom carte, 14), agrégats sous z11, points z11–12 = échantillon d'affichage, **stats exactes (comptes, médianes) à z≥13 uniquement** (tuiles exhaustives), plafond 16 tuiles/viewport, décodage hors main thread, tap → API `dvf_get_mutation`.

## Notes du POC

- Les arrondissements municipaux de Lyon ont dû être ajoutés explicitement aux contours (`communes_arr69.geojson`) : DVF référence `6938x`, pas `69123`.
- `-P` (lecture parallèle GeoJSONL) réduit nettement le temps tippecanoe.
- Comptes annuels observés (69+01) : 2021 : 59,8 k · 2022 : 57,2 k · 2023 : 45,6 k · 2024 : 41,5 k · 2025 : 45,3 k — cohérent avec le cycle du marché.
