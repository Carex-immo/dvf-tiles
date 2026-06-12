# PMTiles Parser avec Index O(1) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implémenter un parser PMTiles complet qui énumère les tuiles, construit un index persistant (layer → z → x → y → {offset, length}), et permet à l'Edge Function de servir les tuiles via byte-range requests ciblés en O(1).

**Architecture:** 
1. Script Node.js (`scripts/build-pmtiles-index.mjs`) : énumère toutes les tuiles du PMTiles avec la librairie pmtiles, génère un index JSON structuré par layer/z/x/y
2. Index uploadé vers Supabase Storage (`tiles/index.json`)
3. Edge Function (`supabase/functions/dvf-tiles/`) : charge l'index en cache, valide les requêtes, fetch le PMTiles via byte-range ciblé, décode et retourne le MVT
4. Tests de latence et taille tuile pour valider les performances

**Tech Stack:** 
- Node.js (pmtiles npm package)
- Deno/TypeScript (Edge Function)
- Supabase Storage (HTTP Range requests)
- Gzip compression (MVT data)

---

## Structure des fichiers

```
scripts/
  ├── build-pmtiles-index.mjs       (CRÉER : énumère PMTiles → index JSON)
  └── upload-index-to-storage.sh    (CRÉER : upload index via CLI)

supabase/functions/dvf-tiles/
  ├── index.ts                       (MODIFIER : parser complet + byte-range)
  ├── pmtiles-parser.ts             (CRÉER : helper parsing)
  └── deno.json                      (MODIFIER si besoin)

build/
  └── tiles_index.json               (GÉNÉRER : index structure)

tests/
  └── edge-function-perf.test.ts    (CRÉER : tests latence/taille)

DEPLOYMENT.md                        (MODIFIER : ajouter section PMTiles)
```

---

## Task 1: Script d'énumération des tuiles PMTiles

**Files:**
- Create: `scripts/build-pmtiles-index.mjs`
- Create: `build/tiles_index.json` (output)

- [ ] **Step 1: Créer le script Node.js d'énumération**

Créer le fichier `scripts/build-pmtiles-index.mjs` avec le contenu complet pour énumérer toutes les tuiles du PMTiles et générer un index JSON structuré.

- [ ] **Step 2: Installer la dépendance pmtiles**

Exécuter `npm install pmtiles` pour ajouter la librairie.

- [ ] **Step 3: Exécuter le script pour générer l'index**

Exécuter `node scripts/build-pmtiles-index.mjs build/dvf.pmtiles build/tiles_index.json` et vérifier que le fichier `build/tiles_index.json` est créé avec la structure correcte.

- [ ] **Step 4: Vérifier la structure du fichier index**

Vérifier que le JSON est valide et contient la structure `{ "mutations": { "4": { ... } }, ... }`.

- [ ] **Step 5: Commit**

Commiter les fichiers avec un message explicite.

---

## Task 2: Upload l'index vers Supabase Storage

**Files:**
- Create: `scripts/upload-index.sh`
- Reference: `build/tiles_index.json` (input)

- [ ] **Step 1: Créer un script d'upload**

Créer `scripts/upload-index.sh` qui upload `build/tiles_index.json` vers Supabase Storage (`tiles/index.json`).

- [ ] **Step 2: Exécuter le script d'upload**

Exécuter `./scripts/upload-index.sh bqwbazolhtwizafxqzlr build/tiles_index.json`.

- [ ] **Step 3: Vérifier que le fichier est accessible**

Vérifier que le fichier est accessible via `curl` depuis l'URL Supabase Storage publique.

- [ ] **Step 4: Commit**

Commiter le script d'upload.

---

## Task 3: Implémenter le parser PMTiles dans l'Edge Function

**Files:**
- Modify: `supabase/functions/dvf-tiles/index.ts`
- Create: `supabase/functions/dvf-tiles/pmtiles-parser.ts`

- [ ] **Step 1: Créer un helper pour parser la structure PMTiles**

Créer `supabase/functions/dvf-tiles/pmtiles-parser.ts` avec les fonctions :
- `parsePMTilesHeader()` : extrait les offsets du répertoire
- `zxyToTileId()` : conversion z/x/y → Hilbert tile ID
- `findTileInDirectory()` : cherche une tuile dans le répertoire

- [ ] **Step 2: Modifier la fonction principal pour charger l'index**

Modifier `supabase/functions/dvf-tiles/index.ts` pour :
- Implémenter `loadTileIndex()` qui fetch `tiles/index.json` depuis Storage et cache en mémoire
- Implémenter `fetchTile()` qui valide l'existence de la tuile via l'index
- Retourner 204 pour les tuiles n'existant pas, 200 pour les tuiles valides

- [ ] **Step 3: Déployer la fonction mise à jour**

Exécuter `supabase functions deploy dvf-tiles --project-ref bqwbazolhtwizafxqzlr`.

- [ ] **Step 4: Vérifier que la fonction charge l'index**

Tester avec `curl` que la fonction retourne les bons codes HTTP.

- [ ] **Step 5: Commit**

Commiter les modifications.

---

## Task 4: Implémenter l'extraction des tuiles via byte-range

**Files:**
- Modify: `supabase/functions/dvf-tiles/index.ts`
- Modify: `supabase/functions/dvf-tiles/pmtiles-parser.ts`

- [ ] **Step 1: Enrichir le parser PMTiles pour extraire les offsets**

Modifier `pmtiles-parser.ts` pour :
- Parser la structure complète du répertoire PMTiles
- Retourner offset + length pour chaque tuile

- [ ] **Step 2: Implémenter le fetching via byte-range**

Modifier la fonction `fetchTile()` dans `index.ts` pour :
- Utiliser l'index pour obtenir l'offset et la longueur
- Faire un HTTP Range request ciblé (`Range: bytes=offset-end`)
- Décompresser si nécessaire
- Retourner les données MVT

- [ ] **Step 3: Tester l'extraction**

Vérifier que la fonction retourne des données valides (status 200) pour les tuiles existantes.

- [ ] **Step 4: Commit**

Commiter les modifications.

---

## Task 5: Tester les performances de l'Edge Function

**Files:**
- Create: `tests/edge-function-perf.test.ts`

- [ ] **Step 1: Créer un test de latence**

Créer `tests/edge-function-perf.test.ts` avec des tests qui mesurent :
- Latence des requêtes
- Tailles des réponses
- Cache hit rates

- [ ] **Step 2: Exécuter le test de performance**

Exécuter `deno run --allow-net tests/edge-function-perf.test.ts`.

- [ ] **Step 3: Vérifier la latence avec cache**

Exécuter à nouveau pour observer les améliorations avec le cache en place.

- [ ] **Step 4: Commit**

Commiter les tests.

---

## Task 6: Documentation du déploiement complet

**Files:**
- Modify: `DEPLOYMENT.md`

- [ ] **Step 1: Ajouter une section au guide de déploiement**

Ajouter une section "Déploiement avec Parser PMTiles Complet" qui documente :
- Processus complet (build → index → upload → deploy)
- Architecture PMTiles + Index
- Performances observées
- Cas d'usage clients

- [ ] **Step 2: Commit**

Commiter la mise à jour de la documentation.

---

## Contexte partagé pour tous les subagents

**Projet:** dvf-tiles (service de tuiles DVF pour Supabase)
**Stack:** Node.js (scripts) + Deno/TypeScript (Edge Functions) + Supabase Storage
**Supabase Project:** bqwbazolhtwizafxqzlr
**PMTiles File:** `build/dvf.pmtiles` (914 MB, exhaustif z13-z14)
**Bucket:** `tiles` (public)

**Spec refs:**
- CLAUDE.md : architecture et encodage compact
- DEPLOYMENT.md : guide de déploiement current
- PMTiles spec : https://github.com/mapbox/pmtiles/blob/main/spec.md
