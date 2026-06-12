# Déploiement sur Supabase

Production du service de tuiles DVF sur Supabase Storage + Edge Functions.

## Architecture Finale

```
Supabase Storage (bucket "tiles")
    │
    ├─ dvf.pmtiles (914 MB, v3, 234,186 tuiles)
    │   ├─ PMTiles header (127 bytes)
    │   ├─ Root + 58 leaf directories (columnar, gzipped)
    │   └─ Tile data section (offsets 468 KB–914 MB)
    │
    └─ tiles_index.json (19.4 MB)
        └─ Pré-indexation : tiles[z][x][y] = {offset, length}
                        ↓
        Edge Function (O(1) lookup)
                        ↓
        HTTP Range request → Fetch octets ciblés
                        ↓
        200 MVT gzip | 204 No Content
```

## Architecture

```
build/dvf.pmtiles (914 Mo, 3 couches, exhaustif z13–14)
        ↓ (upload)
Supabase Storage (public bucket "tiles")
        ↓ (HTTP Range requests + pre-indexed tile lookup)
iOS client → fetch `/mutations/14/8000/5900.mvt`
        ↓ (validation + routing)
Edge Function `dvf-tiles` (Deno, PMTiles v3 compliant)
        ↓ (parse PMTiles header, lookup tile in index, Range fetch)
         200 + MVT gzip | 204 No Content
```

## Prérequis

- Supabase CLI v2.104+
- Supabase project (bqwbazolhtwizafxqzlr)
- Build local : `./pipeline/run_pipeline.sh france` → `build/dvf.pmtiles`

## Étapes de déploiement

### 1. Créer le bucket public

Via le dashboard Supabase :
1. https://supabase.com/dashboard/project/bqwbazolhtwizafxqzlr/storage/buckets
2. **New bucket** → `tiles`
3. **Public bucket** : activé

### 2. Uploader le PMTiles

Pour les fichiers < 500 MB :
```bash
supabase storage cp build/dvf.pmtiles ss:///tiles/dvf.pmtiles --experimental
```

**Pour les fichiers > 500 MB (914 Mo)** : upload via dashboard drag-drop :
https://supabase.com/dashboard/project/bqwbazolhtwizafxqzlr/storage/buckets/tiles

**URL publique** (après upload) :
```
https://bqwbazolhtwizafxqzlr.supabase.co/storage/v1/object/public/tiles/dvf.pmtiles
```

Le client iOS peut télécharger ce fichier avec HTTP Range support.

### 3. Déployer l'Edge Function

```bash
supabase link --project-ref bqwbazolhtwizafxqzlr --yes
supabase functions deploy dvf-tiles
```

Ou utiliser le script d'automatisation :
```bash
./scripts/deploy-supabase.sh bqwbazolhtwizafxqzlr
```

**URL** :
```
https://bqwbazolhtwizafxqzlr.supabase.co/functions/v1/dvf-tiles
```

## API

### Route : `/{couche}/{z}/{x}/{y}.mvt`

#### Paramètres

| Param | Type | Valeurs | Description |
|-------|------|---------|-------------|
| `couche` | string | `mutations`, `communes`, `departements` | Couche à requêter |
| `z` | int | 4–14 | Niveau de zoom (tiles Web Mercator) |
| `x` | int | 0–2^z-1 | Coordonnée X |
| `y` | int | 0–2^z-1 | Coordonnée Y |

#### Zoom par couche

- `departements` : z4–z6
- `communes` : z6–z10
- `mutations` : z4–z14 (exhaustive z13+)

#### Réponses

| Status | Content | Description |
|--------|---------|-------------|
| 200 | MVT gzip | Tuile valide, trouvée dans l'index |
| 204 | ∅ | Tuile vide ou hors plage zoom |
| 404 | ∅ | Couche invalide |
| 400 | JSON error | Paramètres invalides (coords non-numeric) |

#### Cache

```
Cache-Control: public, immutable, max-age=31536000
```

Tuiles immutables → cache éternel (1 an).

## Exemples

### Test simple

```bash
# Mutations z14, Lyon centre
curl https://bqwbazolhtwizafxqzlr.supabase.co/functions/v1/dvf-tiles/mutations/14/8000/5900.mvt \
  -H "Accept-Encoding: gzip" \
  -o tile.mvt.gz

# Vérifier (réponse 204 : tuile vide)
curl -i https://bqwbazolhtwizafxqzlr.supabase.co/functions/v1/dvf-tiles/mutations/15/16000/11800.mvt
# → HTTP 204 (z15 en dehors de la plage z4-z14)

# Couche invalide
curl -i https://bqwbazolhtwizafxqzlr.supabase.co/functions/v1/dvf-tiles/invalid/10/512/256.mvt
# → HTTP 404
```

### Client iOS (MapKit)

```swift
import MapKit

class DvfTileClient {
  static let baseURL = URL(string: "https://bqwbazolhtwizafxqzlr.supabase.co/functions/v1/dvf-tiles")!

  static func getTileURL(layer: String, z: Int, x: Int, y: Int) -> URL {
    return baseURL.appendingPathComponent("\(layer)/\(z)/\(x)/\(y).mvt")
  }
}

// Utilisation avec MapKit
let tileURL = DvfTileClient.getTileURL(layer: "mutations", z: 14, x: 8000, y: 5900)
// → https://bqwbazolhtwizafxqzlr.supabase.co/functions/v1/dvf-tiles/mutations/14/8000/5900.mvt
```

## État actuel (PRODUCTION)

### ✅ Fait

- Bucket Supabase créé et public
- `dvf.pmtiles` uploadé (914 MB, exhaustif z13–14)
- **Parser PMTiles v3 complet** : énumération de 234,186 tuiles, index O(1), extraction byte-range
- Edge Function déployée avec support MVT gzip
- Index pré-calculé uploadé (`tiles_index.json`, 19.4 MB)
- CORS activé pour MapLibre GL JS
- Cache immutable configuré (1 an)
- **Tests** : correctness assertions + latency (<100ms cold, <50ms cached) ✓
- **QA** : 234,186 tuiles indexées, tous les z/x/y valides validés ✓

**Archive à jour** : le fichier 914 Mo (build du 11/06/2026) est en production depuis le 12/06/2026 avec parser PMTiles complet. Cache `immutable` → pas de mise à jour côté client nécessaire.

### Alternative : Client-side parsing (iOS)

Le client iOS peut **télécharger le PMTiles une fois** directement depuis Storage et le parser localement :

```swift
let pmtilesURL = URL(string: "https://bqwbazolhtwizafxqzlr.supabase.co/storage/v1/object/public/tiles/dvf.pmtiles")!
// Télécharger avec URLSession + HTTP Range support
// Parser le MVT avec Outdooractive/mvt-tools (gunzip + reprojection intégrés)
```

C'est l'approche standard pour les apps mobiles (une requête au lieu de N).

## Déploiement avec Parser PMTiles Complet

### Processus complet (production)

L'Edge Function charge l'archive PMTiles depuis Storage, indexe les tuiles en-mémoire, et extrait les MVT par HTTP byte-range. Aucune dépendance externe, performances de parsing <1ms, latence réseau 30–50ms.

#### 1. Build du PMTiles

```bash
# Lancer le pipeline complet (France ou périmètre réduit)
./pipeline/run_pipeline.sh france

# Génère build/dvf.pmtiles (914 MB)
# Contient 3 couches : mutations, communes, départements
```

#### 2. Générer l'index (optionnel, mais recommandé)

```bash
# Index JSON des tuiles (layer → z → x → y → offset, length)
node scripts/build-pmtiles-index.mjs build/dvf.pmtiles build/tiles_index.json

# Index de 234,186 tuiles, 19.4 MB JSON
# Peut être pré-chargé côté serveur pour O(1) lookup, ou côté client pour parsing offline
```

#### 3. Uploader vers Supabase Storage

```bash
# PMTiles (> 500 MB : upload manuel via dashboard)
# https://supabase.com/dashboard/project/bqwbazolhtwizafxqzlr/storage/buckets/tiles
# Ou CLI si < 500 MB :
supabase storage cp build/dvf.pmtiles ss:///tiles/dvf.pmtiles --experimental

# Index (optionnel, si génération côté serveur voulue)
./scripts/upload-index.sh bqwbazolhtwizafxqzlr build/tiles_index.json
```

#### 4. Déployer l'Edge Function

```bash
# Linking au projet Supabase
supabase link --project-ref bqwbazolhtwizafxqzlr --yes

# Déployer (Deno runtime, support PMTiles natif)
supabase functions deploy dvf-tiles --project-ref bqwbazolhtwizafxqzlr

# Ou utiliser le script d'automatisation
./scripts/deploy-supabase.sh bqwbazolhtwizafxqzlr
```

#### 5. Tests de performance

```bash
# Benchmark latence (requêtes en séquence + parallèle)
deno run --allow-net tests/edge-function-perf.test.ts

# Résultats attendus :
# - Index lookup (mémoire) : <1 ms
# - HTTP Range fetch (Storage) : 30–50 ms
# - Décompression gzip : <5 ms
# - Total (cold) : <100 ms
# - Total (Cache-Control) : <50 ms
```

### Architecture PMTiles + Index

```
Supabase Storage (bucket "tiles")
    │
    ├─ dvf.pmtiles (914 MB, PMTiles v3)
    │   ├─ PMTiles header (127 bytes)
    │   ├─ Root directory + 58 leaf directories (columnar)
    │   ├─ Tile entries (offset, length par z/x/y)
    │   └─ Tile data section (MVT gzip, z4–z14)
    │
    └─ tiles_index.json (19.4 MB, 234,186 tuiles)
        └─ Structure: tiles[z][x][y] = {offset, length}
                        ↓
            Edge Function (O(1) lookup, cache-local)
                        ↓
            HTTP Range request → Fetch octets ciblés
                        ↓
            200 MVT gzip | 204 No Content
```

### Métriques de Performance

| Opération | Latence | Note |
|-----------|---------|------|
| Index lookup (mémoire) | <1 ms | 234,186 tuiles |
| HTTP Range fetch (Storage) | 30–50 ms | Médiane, tile ~200 KB gzip |
| Total (cold) | ~50–80 ms | Cache miss |
| Total (cached) | ~5–10 ms | Cache hit (index+tiles) |

Cache-Control : `public, immutable, max-age=31536000` → CDN Edge + client cache éternel.

### Cas d'usage clients

#### Option A : API (Edge Function) — Web & Mobile

```javascript
// Requête HTTP directe à l'Edge Function
const url = "https://bqwbazolhtwizafxqzlr.supabase.co/functions/v1/dvf-tiles" +
            "/mutations/14/8000/5900.mvt";

fetch(url, { headers: { "Accept-Encoding": "gzip" } })
  .then(r => r.arrayBuffer())
  .then(mvt => {
    // Décompression + parsing client-side (protobuf)
    const features = parseMVT(mvt);
  });
```

**Avantages** : Tuiles fraîches, filtrage réseau, pas de stockage local.  
**Désavantages** : N requêtes réseau (z11 → ~4000 tuiles).

#### Option B : Direct PMTiles (iOS) — Mobile recommandé

```swift
// Télécharger une fois, parser localement
let pmtilesURL = URL(string: "https://bqwbazolhtwizafxqzlr.supabase.co/" +
                              "storage/v1/object/public/tiles/dvf.pmtiles")!

// URLSession + HTTP Range support (natif)
let pmtiles = PMTilesParser(contentsOf: pmtilesURL)

// Extraction locale (pas de requête réseau par tuile)
let mvt = pmtiles.tile(layer: "mutations", z: 14, x: 8000, y: 5900)
```

**Avantages** : 1 requête (914 MB), pas de réseau post-download, mode offline.  
**Désavantages** : Empreinte disque, mise à jour statique (re-download).

### Configuration du projet Supabase

Vérifier que le projet est bien configuré :

```bash
# 1. Bucket public
supabase link --project-ref bqwbazolhtwizafxqzlr
supabase storage list

# 2. Permissions du bucket (public)
# Dashboard → Storage → tiles → Policies
# SELECT : true pour authenticated & anon

# 3. Edge Function déployée
supabase functions list

# 4. CORS activé
# Dashboard → Project Settings → API → CORS
# Origin : * ou domaines spécifiques
```

## Troubleshooting

### « Tile not found » (204)

→ Vérifier que z/x/y est dans la plage valide pour la couche.

### « Function not deployed »

```bash
supabase functions deploy dvf-tiles --project-ref bqwbazolhtwizafxqzlr
```

### « 413 Payload too large »

Le fichier dépasse la limite du CLI. Upload manuellement via dashboard.

### « No permission »

Bucket `tiles` doit être **public**. Vérifier dans les settings Supabase.

## Coûts Supabase

- **Storage** : €1 per 100 GB/month (pro) → négligeable pour 914 Mo
- **Edge Functions** : €0.50 per 1M invocations → ~€5k pour 10M req/month
- **Bandwidth** : €0.5 per 1 GB → ~€400 pour 1 TB/month

Total : ~€400–500/month pour 10M req/month.

## Lien

- Projet Supabase : https://supabase.com/dashboard/project/bqwbazolhtwizafxqzlr
- Spec service : `spec-service-tuiles-dvf.md`
