# Spec — Exposition IRIS + mutations DVF par point GPS

**Date :** 2026-06-16
**Projet :** dvf-tiles (CAREX — POC service de tuiles DVF)
**Statut :** Design validé, prêt pour plan d'implémentation

> **Mise à jour (juin 2026) :** le client iOS est passé de **MapKit à MapLibreGL** (déployé, hors de ce repo). Le squelette `client/DvfTileClient.swift` a été retiré et les détails de rendu Swift/MapKit **purgés** de ce document. Les **contrats de données** (schémas `mutations`/`iris`, JSON `stats/iris/{code}.json`, chemins de tuiles) restent la référence ; §8 décrit la consommation côté client de façon neutre.

## 1. Besoin

Dans l'app iOS, à partir d'un **point GPS** (géolocalisation utilisateur), récupérer **toutes les mutations DVF de la zone IRIS** qui contient ce point. Le **filtrage** (année, type de bien, fourchette €/m²…) est réalisé **côté app**, en mémoire, sur la liste retournée.

### Hors périmètre

- Filtrage / requêtage côté serveur (tout est statique).
- Reverse-geocoding externe (la résolution IRIS se fait localement, cf. §3).
- Backend dynamique ou base de données à l'exécution.

## 2. Décisions d'architecture (validées)

| Décision | Choix |
|---|---|
| Mode de service | **Statique précalculé** sur object storage + CDN (cohérent avec `dvf.pmtiles`) |
| Filtrage | **Côté app** (en mémoire), comme le filtre 14 ms existant du POC |
| Résolution `point GPS → CODE_IRIS` | **Via une nouvelle couche tuiles `iris`** dans `dvf.pmtiles` (décodage MVT + point-in-polygon local) |
| Détail mutations | Fichier statique **`/iris/{code_iris}.json`** (contour + stats + mutations) |
| `contour` GeoJSON dans le JSON | **Inclus** (surlignage précis de la zone) |
| `stats` pré-agrégées dans le JSON | **Incluses** (résumé immédiat) |
| Schéma d'une mutation | **14 attributs existants** de la couche `mutations` (réutilisés tels quels) |

## 3. Flux applicatif (bout en bout)

```
Point GPS (lat, lon)
  └─▶ [app] tuile dvf.pmtiles au zoom courant → décodage couche `iris`
        └─▶ point-in-polygon local → CODE_IRIS (ex. 691230101)
              └─▶ GET https://<cdn>/dvf/v1/iris/691230101.json   (statique, gzip, caché)
                    └─▶ { contour + stats + toutes les mutations de l'IRIS }
                          └─▶ [app] filtre en mémoire (année / type / prix) → affichage
```

Deux artefacts produits par le pipeline :
1. la **couche tuiles `iris`** (résolution GPS→IRIS + choroplèthe) intégrée à `dvf.pmtiles` ;
2. les **fichiers `/iris/{code_iris}.json`** (détail mutations), publiés à côté de `dvf.pmtiles`.

## 4. Source de données IRIS

- **Produit :** IGN **CONTOURS-IRIS®** (contours statistiques alignés sur les IRIS INSEE), Licence Ouverte Etalab 2.0 (mention « IGN »).
- **Édition courante (2026-06) :** `CONTOURS-IRIS_3-0__GPKG_WGS84G_FRA_2026-01-01` (~88 Mo, **déjà en WGS84 / EPSG:4326** → aucune reprojection).
- **Récupération :** archive `.7z` via le service de téléchargement Géoplateforme. L'URL réelle est sous `…/telechargement/**download**/CONTOURS-IRIS/{EDITION}/{EDITION}.7z` (et non `/resource/`).
- **Détection de l'édition la plus récente :** flux Atom **paginé** `…/telechargement/resource/CONTOURS-IRIS?page=N` → collecter tous les `<title>`, filtrer le format voulu (`GPKG_WGS84G_FRA`), prendre la date max ; résoudre l'URL `.7z` + taille via le flux de l'édition `…/resource/CONTOURS-IRIS/{EDITION}`. Implémenté et validé dans `pipeline/iris_latest.py`. La matrice format×année est irrégulière (ex. GPKG 2025 absent, GeoParquet 2025 présent) → **toujours lister et filtrer, ne pas sonder une URL par année avec un format fixe**.
- **Figer vs suivre :** épingler l'édition dans le pipeline (reproductibilité) et l'aligner sur le millésime DVF dominant ; `iris_latest.py --current <édition>` signale (code retour 10) qu'une édition plus récente existe.
- **Clé pivot :** `CODE_IRIS` (9 caractères = code INSEE commune sur 5 + n° IRIS sur 4).
- **Volume :** ~49 000 IRIS France entière (édition 3-0) ; pour le POC 69/01, ~1 000–1 500 IRIS.

## 5. Composant A — Couche tuiles `iris` (dans `dvf.pmtiles`)

- **Géométrie :** contours CONTOURS-IRIS généralisés (suffisants pour le PIP « dans quelle zone »).
- **Zooms :** **z10–z14** (z14 indispensable pour résoudre sous le point GPS ; z10–13 pour la choroplèthe).
- **Attributs par polygone :**

| Attribut | Type | Usage |
|---|---|---|
| `code_iris` | string(9) | **clé** de fetch `/iris/{code_iris}.json` |
| `nom_iris` | string | affichage |
| `insee_com` | string(5) | rattachement commune |
| `nom_com` | string | affichage |
| `n_tot` | int | volume mutations (toutes années) |
| `pm2_med` | int | médiane €/m² (choroplèthe) |

> Les agrégats portés par la tuile servent la coloration **sans** charger le JSON. La granularité année×type complète vit dans le JSON (§6).

## 6. Composant B — Fichier statique `/iris/{code_iris}.json`

```jsonc
{
  "code_iris": "691230101",
  "nom_iris": "Part-Dieu Nord",
  "insee_com": "69123",
  "nom_com": "Lyon 3e Arrondissement",
  "millesime_iris": "2024",

  // Contour GeoJSON WGS84 (Polygon|MultiPolygon), géométrie propre pour surlignage
  "contour": { "type": "Polygon", "coordinates": [ /* … */ ] },

  // Stats pré-agrégées année × type (type: 0 terrain,1 maison,2 appart,3 dep,4 local)
  "stats": {
    "n_tot": 412,
    "pm2_med": 4810,
    "par_annee_type": {
      "2024": { "t2": { "n": 123, "pm2_med": 4810 }, "t1": { "n": 8, "pm2_med": 3950 } },
      "2023": { "t2": { "n": 140, "pm2_med": 4760 } }
      // …
    }
  },

  // Toutes les mutations de l'IRIS — 14 attributs de la couche `mutations` + lon/lat
  "mutations": [
    {
      "id": "2024-123456",      // id_mutation
      "date": 20240312,         // YYYYMMDD
      "annee": 2024,
      "nat": 1,                 // 1 Vente,2 VEFA,3 Adjud,4 Echange,5 Exprop,6 Terrain à bâtir
      "type": 2,                // 0 terrain,1 maison,2 appart,3 dépendance,4 local
      "vf": 285000,             // valeur foncière (€)
      "sb": 62,                 // surface bâtie (m²)
      "st": 0,                  // surface terrain (m²)
      "pm2": 4596,              // €/m² bâti (null si sb=0)
      "np": 3,                  // pièces principales
      "nl": 1,                  // nb locaux
      "nc": 0,                  // nature culture dominante (code compact)
      "dep": "69",
      "com": "69123",
      "lon": 4.8512,
      "lat": 45.7601
    }
    // …
  ]
}
```

- **Schéma `mutations` identique** à `cols` de `prepare.py` (`id, date, annee, nat, type, vf, sb, st, pm2, np, nl, nc, dep, com`) + `lon, lat`. Encodages compacts inchangés.
- **Taille attendue :** ~30–80 Ko gzip même pour un IRIS dense (>1000 mutations).
- **Encodage :** UTF-8, JSON compact, servi `Content-Encoding: gzip`, cache long (immutable + millésime dans le chemin de version).

## 7. Pipeline (modifications)

Réutilise la chaîne existante (`download.sh` → `prepare.py` → `build_tiles.sh`).

### 7.1 `download.sh`
Ajout : télécharger + décompresser l'archive CONTOURS-IRIS (GPKG) dans `data/geo/`.

### 7.2 Préparation géométrie IRIS (WGS84)
`ogr2ogr` reprojette l'archive (Lambert-93 EPSG:2154) en **GeoJSON WGS84** restreint aux champs utiles :
```bash
ogr2ogr -f GeoJSON data/geo/iris.geojson -t_srs EPSG:4326 \
  -select CODE_IRIS,NOM_IRIS,INSEE_COM,NOM_COM \
  data/geo/CONTOURS-IRIS.gpkg CONTOURS_IRIS
```

### 7.3 `prepare.py` (extension DuckDB spatial)
- `INSTALL spatial; LOAD spatial;`
- Charger `iris.geojson` (`ST_Read`), table `iris(code_iris, nom_iris, insee_com, nom_com, geom)`.
- **Jointure spatiale** : `ST_Within(ST_Point(lon, lat), geom)` pour attribuer `code_iris` à chaque ligne de la table `mutations` (DVF ne porte pas `code_iris`, contrairement aux communes jointes par attribut). Optimiser via index spatial / `ST_Intersects` sur bbox.
- Produire :
  - **Agrégats IRIS** (`GROUP BY code_iris`, année×type) → écrit `build/iris_layer.geojson` (FeatureCollection contours + agrégats, même logique que `build_layer`/`agg_stats` pour communes).
  - **Un JSON par `code_iris`** dans `build/iris/{code_iris}.json` (contour + stats + mutations), via itération sur les IRIS ayant ≥1 mutation.
- IRIS sans mutation : pas de JSON émis (la tuile peut rester non colorée / grisée).

### 7.4 `build_tiles.sh`
```bash
tippecanoe -L iris:build/iris_layer.geojson \
  -Z10 -z14 --simplification=10 --coalesce-densest-as-needed \
  -o build/iris.pmtiles
tile-join -o build/dvf.pmtiles \
  build/mutations.pmtiles build/iris.pmtiles build/communes.pmtiles build/departements.pmtiles
```

### 7.5 Publication
`build/iris/*.json` synchronisés sur R2/S3 sous `dvf/v1/iris/`, à côté de `dvf.pmtiles`. CDN, gzip, cache long.

## 8. Côté client (MapLibreGL, hors repo)

- **Détail IRIS** : `code_iris, nom_iris, insee_com, nom_com, millesime_iris, contour (GeoJSON), stats, mutations[]` — schéma du JSON `stats/iris/{code_iris}.json` (cf. §7 et `pipeline/build_iris.py`).
- **Résolution GPS→IRIS** : décoder la couche `iris` de la tuile couvrant le point, point-in-polygon sur les polygones → `code_iris`.
- **Fetch** : `GET <baseURL>/stats/iris/{code_iris}.json`, décodage **hors thread principal**.
- **Filtrage** : en mémoire sur `mutations` (même pattern que le filtre existant).
- **Surlignage** : tracer le `contour` GeoJSON de l'IRIS sur la carte.

## 9. Cas limites

| Cas | Traitement |
|---|---|
| Point GPS hors IRIS (mer, gap, étranger) | PIP ne renvoie rien → état **« pas de données »** (pas de fallback IRIS le plus proche) |
| Point sur une frontière d'IRIS (tuile simplifiée) | Tolérance acceptable : précision « bonne zone » suffit (pas de précision cadastrale requise) |
| Commune non irisée | `code_iris = INSEE+0000`, un seul fichier — comportement normal |
| Paris / Lyon / Marseille (DVF à l'arrondissement) | Vérifier que le PIP tombe dans le bon IRIS ; codes `751xx`, `6938x`, `132xx` |
| Millésime IRIS ≠ millésime mutation | Les `code_iris` évoluent ; figer une édition CONTOURS-IRIS et la documenter dans la sortie |
| IRIS très dense (>1000 mutations) | JSON reste < ~80 Ko gzip ; pas de pagination nécessaire au POC |

## 10. Critères d'acceptation

1. `dvf.pmtiles` contient une couche `iris` (z10–14) avec `code_iris` + agrégats, vérifiable via `tippecanoe-decode` / la démo MapLibre.
2. Pour un `code_iris` donné, `build/iris/{code_iris}.json` existe, valide, contient `contour`, `stats`, et la liste `mutations` aux 14 attributs.
3. Sur le POC 69/01 : un point GPS au centre de Lyon résout vers son IRIS et renvoie un nombre de mutations cohérent avec la couche `mutations` filtrée sur le même polygone.
4. Contrôle métier : la médiane €/m² appartement d'un IRIS central de Lyon reste dans l'ordre de grandeur connu (~4 000–6 000 €/m²).
5. La démo (`demo/index.html`) peut afficher la couche `iris` en choroplèthe et, au clic, charger le JSON correspondant.

## 11. Estimation de volume (extrapolation)

- POC 69/01 : ~1 000–1 500 fichiers JSON, couche `iris` ajoutant quelques Mo à `dvf.pmtiles`.
- France entière : jusqu'à ~49 000 fichiers JSON (1 par IRIS ayant ≥1 mutation ; object storage : trivial) ; couche `iris` z10–14 estimée +20–40 Mo sur l'archive.
