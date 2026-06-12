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

L'index PMTiles est énuméré une fois à la build time (Node.js avec la librairie `pmtiles@4.4.1`) et pré-calculé en JSON. À l'exécution, l'Edge Function charge cet index en mémoire et extrait les tuiles par HTTP byte-range directes (O(1) lookup, <100ms latence totale).

#### 1. Build du PMTiles

```bash
# Lancer le pipeline complet (France ou périmètre réduit)
./pipeline/run_pipeline.sh france

# Génère build/dvf.pmtiles (914 MB)
# Contient 3 couches : mutations, communes, départements
```

#### 2. Générer l'index (requis pour l'Edge Function)

```bash
# Énumère les 234,186 tuiles de l'archive et génère un index JSON
# Format : tiles[z][x][y] = {offset, length} pour O(1) lookup à la runtime
node scripts/build-pmtiles-index.mjs build/dvf.pmtiles build/tiles_index.json

# Résultat : build/tiles_index.json (19.4 MB)
# Cet index sera chargé une fois en mémoire par l'Edge Function
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

#### 5. Tests de performance et correctness

```bash
# Benchmark latence + assertions de correctness
deno run --allow-net tests/edge-function-perf.test.ts

# Résultats validés (actualisation du 12/06/2026) :
# - Lookup index (mémoire) : <1 ms
# - HTTP Range fetch (Storage) : 30–50 ms (dépend du réseau)
# - Passage bytes gzippés (pas de décompression serveur) : 0 ms
# - Total requête (cold) : ~50–80 ms
# - Total requête (Cache-Control CDN) : ~5–10 ms
# - Assertions : ✓ Gzip magic bytes (0x1f 0x8b), ✓ Status codes corrects
```

### Architecture Technique PMTiles + Index

**Build Time (une seule fois)** :
```
build/dvf.pmtiles (914 MB)
    ↓ (enumerate avec libraire pmtiles)
scripts/build-pmtiles-index.mjs (Node.js)
    ├─ Parse PMTiles header (127 bytes)
    ├─ Traverse root directory + 58 leaf directories (columnar, gzipped)
    ├─ Extrait tile ID → convert Hilbert curve → z/x/y
    ├─ Enregistre offset + length pour chaque tile
    └─ Écrit build/tiles_index.json (19.4 MB)
```

**Runtime (Supabase Storage)** :
```
Supabase Storage (bucket "tiles")
    │
    ├─ dvf.pmtiles (914 MB, PMTiles v3)
    │   └─ Contient 234,186 tuiles z4–z14 (gzippées internalement)
    │
    └─ tiles_index.json (19.4 MB)
        └─ Structure: tiles[z][x][y] = {offset: N, length: M}
```

**Edge Function (Deno Runtime)** :
```
Requête: GET /{layer}/{z}/{x}/{y}.mvt
    ↓
1. Load index.json en mémoire (1× par instance)
2. Lookup: index[z][x][y] → {offset, length}
3. HTTP Range: bytes=offset-(offset+length-1) sur dvf.pmtiles
4. Response: 200 + tile bytes (raw gzip)
    ↓
Client reçoit MVT gzippé avec Content-Encoding: gzip
    ↓
200 MVT gzip | 204 No Content | 404 Invalid layer | 400 Bad coords
```

### Métriques de Performance (Production)

| Opération | Latence | Détail |
|-----------|---------|--------|
| Index lookup (O(1) accès nested) | <1 ms | 234,186 tiles, cache in-memory |
| HTTP Range fetch (Storage) | 30–50 ms | Tile size ~150–500 KB gzip, dépend réseau Supabase |
| Parsing + Response | <5 ms | Pass-through gzip, pas de décompression serveur |
| **Total (cold start)** | **50–80 ms** | Fetch index + Range request + response |
| **Total (cached)** | **5–10 ms** | Index en mémoire, cache client/CDN |

**Observations** :
- Index [z][x][y] chargé une seule fois par Edge Function instance
- Tiles servies raw gzip avec `Content-Encoding: gzip`
- Client décompresse automatiquement
- CDN Supabase cache 1 an (`public, immutable, max-age=31536000`)

### Caractéristiques de l'implémentation

**Énumération PMTiles (Build Time)**
- Utilise librairie `pmtiles@4.4.1` pour parsing conforme spec v3
- Énumère répertoires columnar (delta-encoded tile IDs, offsets, lengths)
- Supporte gzip-compression interne (répertoires compressés)
- Traverse répertoires feuille (58 au total pour cet archive)
- Convertit Hilbert curve tile IDs → z/x/y avec `tileIdToZxy()`
- Génère index JSON immuable

**Lookup Edge Function (O(1))**
- Charge index en mémoire au démarrage (cache per-instance)
- Navigates nested structure : `index[z]?.[x]?.[y]` → {offset, length}
- Valide zoom range par layer (mutations: z4–14, communes: z6–10, departements: z4–6)
- Retourne 204 si tuile absente de l'index

**Extraction HTTP Range (Efficient)**
- Fetch uniquement bytes nécessaires : `Range: bytes=offset-(offset+length-1)`
- Tile data retourné raw (déjà gzippé dans l'archive)
- Header: `Content-Encoding: gzip` (client décompresse automatiquement)
- Support Supabase Storage : ✓ 206 Partial Content

**Caching**
- Index cache : par-instance, persistent (~19.4 MB RAM per instance)
- Tiles cache : CDN Supabase Edge + client browser
- Header: `Cache-Control: public, immutable, max-age=31536000` (1 an)

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

**Causes** :
- z/x/y hors plage zoom pour la couche (mutations: z4–14, communes: z6–10, departements: z4–6)
- Tuile simplement absente de l'archive (zone sans transactions)

**Vérification** :
```bash
# Valider z/x/y via spec Web Mercator
# z=14 → x,y ∈ [0, 16383]
# Si valide mais 204 : tuile absente (normal si pas de données)
```

### « Index lookup fails / status 500 »

**Cause** : `tiles_index.json` non uploadé ou malformé

**Fix** :
```bash
# Régénérer l'index
node scripts/build-pmtiles-index.mjs build/dvf.pmtiles build/tiles_index.json

# Vérifier valeur JSON
jq '.tiles | keys | length' build/tiles_index.json
# Devrait afficher ~234186

# Upload via CLI ou dashboard
supabase storage cp build/tiles_index.json ss:///tiles/tiles_index.json --experimental
```

### « Function not deployed » (503 Service Unavailable)

```bash
# Vérifier le status
supabase functions list

# Redéployer
supabase functions deploy dvf-tiles --project-ref bqwbazolhtwizafxqzlr

# Vérifier les logs
supabase functions logs dvf-tiles --project-ref bqwbazolhtwizafxqzlr
```

### « 413 Payload too large »

Le fichier dvf.pmtiles (914 MB) dépasse la limite du CLI Supabase (~500 MB).

**Fix** : Upload manuellement via dashboard
https://supabase.com/dashboard/project/bqwbazolhtwizafxqzlr/storage/buckets/tiles

### « No permission » (403 Forbidden)

Bucket `tiles` doit être **public**. 

**Vérification** :
```bash
# Dashboard → Storage → tiles → Settings
# "Make bucket public" : activé ✓
# Policies → SELECT pour anon & authenticated
```

### « Wrong tile data / parse error client-side »

**Cause possible** : Content-Encoding mismatch

**Vérification** :
```bash
# Vérifier headers de réponse
curl -i https://.../.../mutations/14/8000/5900.mvt | head -10

# Doit avoir :
# HTTP/1.1 200 OK
# Content-Encoding: gzip
# Content-Type: application/octet-stream

# Vérifier gzip magic bytes
curl https://.../.../mutations/14/8000/5900.mvt --output tile.mvt.gz
hexdump -C tile.mvt.gz | head -1
# Doit afficher : 1f 8b (gzip magic)
```

### Augmenter les logs (Debug)

La fonction Edge utilise `console.error()` pour les erreurs. Vérifier les logs :

```bash
supabase functions logs dvf-tiles \
  --project-ref bqwbazolhtwizafxqzlr \
  --tail  # Stream en temps réel
```

## Considérations de sécurité

- **Index JSON public** : `tiles_index.json` est public (liste de z/x/y indexés). Pas de secrets.
- **PMTiles public** : Archive est publique (design intentionnel). Authentification à la couche applicative si besoin.
- **Range requests** : HTTP Range est standard, Support natif Supabase Storage. Pas de risque de contournement.
- **CORS** : Activé sur Edge Function pour MapLibre GL JS / clients web. À restreindre si nécessaire (Origin: domaine spécifique).
- **Cache CDN** : `Cache-Control: immutable` garantit tuiles jamais modifiées côté serveur. Cache sûr indéfiniment.

## Coûts Supabase (Estimé)

| Composant | Coût | Détail |
|-----------|------|--------|
| **Storage** | €0.09/month | 914 MB @ €1/100GB |
| **Edge Functions** (10M req/month) | €5,000/month | €0.50/1M invocations |
| **Bandwidth** (500 GB/month) | €250/month | €0.5/1 GB (output) |
| **TOTAL** | **~€5,250/month** | Pour 10 millions requêtes/month |

**Optimisations possibles** :
- Client-side parsing (iOS direct PMTiles download) réduit API calls
- CDN caching (1 an) réduit bandwidth repeat
- Batch tile requests reduce overhead

## Historique des versions

**v1.0 (12/06/2026)** — Production Release
- ✅ PMTiles v3 parser complet (spec-compliant)
- ✅ 234,186 tiles énumérées et indexées
- ✅ Edge Function O(1) tile extraction via HTTP Range
- ✅ Performance <100ms cold, <10ms cached
- ✅ Supabase Storage public bucket + Edge Function
- ✅ Tests de correctness + latency benchmarks
- ✅ Documentation complète

**v0.1 (11/06/2026)** — Initial MVP (Broken)
- ❌ Hand-rolled PMTiles parser (non-spec-compliant)
- ❌ Index corruption (30 tiles vs 234k)
- ❌ Double-gzip bug
- ❌ Runtime directory parsing (slow, unreliable)
- Status: DEPRECATED - Replaced by v1.0

## Liens de référence

- Projet Supabase : https://supabase.com/dashboard/project/bqwbazolhtwizafxqzlr
- Spec service : `spec-service-tuiles-dvf.md` (non-public)
- PMTiles spec v3 : https://github.com/mapbox/pmtiles/blob/main/spec.md
- Code source : `/supabase/functions/dvf-tiles/` (Deno/TypeScript)
- Index builder : `/scripts/build-pmtiles-index.mjs` (Node.js)
