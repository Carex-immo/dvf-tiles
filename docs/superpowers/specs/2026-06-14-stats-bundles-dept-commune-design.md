# Spec — Extracteur de stats par département/commune (panneau « tap »)

**Date** : 2026-06-14
**Statut** : validé (session « stats au tap d'un département/commune »)
**Périmètre** : repo `dvf-tiles` — pipeline (nouvel artefact `build/stats/`), QA, livraison Supabase,
et **contrat aval** pour l'app iOS `carex.immo`. L'UI iOS (vue SwiftUI, fetch, cache) est un **lot
distinct côté carex.immo** : cette spec en fige le contrat, pas l'implémentation.

## 1. Problème

Côté app iOS, le **bouton stat** de la barre du haut ([`MapHeader.swift:67-80`](../../../../carex.immo/carex.immo/Views/MapHeader.swift#L67-L80))
n'apparaît qu'au **niveau ville** (`isExactCountZone && filteredMutations.count >= 2`,
[`MapRootView.swift:822`](../../../../carex.immo/carex.immo/Views/MapRootView.swift#L822)) : il ouvre
`StatsView`, qui calcule **tout côté client à partir des mutations individuelles chargées**
(tendance trimestrielle du €/m² médian + répartition par type : compte, prix moyen rogné, €/m²,
surfaces, pièces).

Quand l'utilisateur **tape un département ou une commune** (zooms bas/moyens), les mutations
individuelles ne sont pas chargées. L'app n'a alors qu'un petit callout
([`MapRootView.swift:796-808`](../../../../carex.immo/carex.immo/Views/MapRootView.swift#L796-L808),
`AggregateEntity`) : code, nom, compte filtré, €/m² médian — lus des agrégats déjà portés par les
tuiles (`n_{annee}_t{type}`, `p_{annee}_t{type}`, `n_tot`, `pm2_med`, `vf_med`).

**Objectif** : un panneau riche (esprit `StatsView`) au tap d'un département/commune. Les métriques
nécessaires (médianes de prix/surfaces/pièces par type, tendance) n'existent **pas** dans les
agrégats actuels. Il faut **les générer** et les livrer dans un format **directement exploitable**
par iOS.

## 2. Décisions

| # | Décision | Justification |
|---|---|---|
| D1 | Un **extracteur** dans `dvf-tiles` produit des stats riches par entité ; l'UI iOS est un lot aval | « préparer un extracteur de données exploitable facilement par l'app iOS » ; même schéma de division que le lot décodeur MVT |
| D2 | **Médianes** (pas de moyennes rognées) pour prix/surfaces/pièces | Tout le pipeline raisonne en médianes (`pm2_med`, `vf_med`, `p_…`) ; robuste sans rognage (queues lourdes immobilier) ; précalculable proprement ; les médianes **ne se recombinent pas** → on précalcule à la granularité d'affichage |
| D3 | Granularité **annuelle partout** (2021–2025) **+ trimestrielle si dense** | Annuel robuste même pour les petites communes ; trimestriel pertinent surtout grandes villes/départements ; l'app affiche le plus fin disponible |
| D4 | Livraison en **bundles par département** sur le bucket public `tiles` : `stats/dep/{DD}.json` + `stats/departements.json` + `stats/manifest.json` | ~102 petits fichiers ; localité de cache (communes voisines = même bundle) ; pas d'infra nouvelle ; lecture directe iOS (comme la lecture directe du PMTiles) |
| D5 | Nouveau module **`pipeline/stats_bundles.py`** accroché à `prepare.py` sur la vue `stats_src` | Même source remappée (COG/scissions) que `agg_stats` → cohérence garantie tuiles ⟷ bundles ; séparé pour ne pas coupler le contrat des tuiles ni les gonfler |
| D6 | Trimestriel émis si **`n_tot ≥ 200`** ; point trimestriel omis si `n < 5` ; `quarters` **tous types confondus** | ~10 ventes/trimestre en moyenne → médianes stables ; évite l'explosion 5 types × 20 trimestres ; seuil paramétrable d'un seul endroit |
| D7 | Cache-busting par **`manifest.version`** + suffixe `?v={version}` sur les bundles | L'archive est remplacée en place sous la même URL ; sans version, le `URLCache` iOS servirait du périmé |

## 3. Schéma des données (`EntityStats`)

Une entité (commune ou département), tableaux parallèles indexés par `years` ; `null` = pas de
donnée. Codes type identiques aux tuiles : `1` maison, `2` appartement, `3` immeuble, `4` local
com./ind., `5` dépendance.

```jsonc
{
  "code": "69123",
  "nom": "Lyon",
  "n_tot": 50234,            // toutes mutations consolidées (terrain nu inclus)
  "pm2_med": 4200,           // médiane €/m² toute période, tous types
  "vf_med": 285000,          // médiane valeur foncière toute période
  "years": [2021,2022,2023,2024,2025],   // millésimes présents dans les données, triés
                                          // (pas codé en dur : dérivé de stats_src)

  // tendance annuelle, tous types confondus → courbe principale
  // n = toutes mutations de l'année (terrain nu inclus) ; pm2_med ignore les pm2 nuls
  "overall": { "n":[5800,6100,5400,4900,5100], "pm2_med":[3900,4050,4200,4250,4300] },

  // détail par type (clé = code type, présente seulement si l'entité a ce type)
  "byType": {
    "2": {
      "n":      [3100,3300,2900,2600,2700],
      "pm2_med":[4300,4450,4600,4650,4700],
      "vf_med": [240000,250000,255000,258000,262000],
      "sb_med": [62,61,60,60,59],            // surface bâtie médiane (m²)
      "st_med": [null,null,null,null,null],  // terrain médian (pertinent t1/t4)
      "np_med": [3,3,3,3,3]                   // nb pièces médian
    }
    // "1","3","4","5" idem
  },

  // tendance trimestrielle (tous types), présente seulement si n_tot >= 200
  // point omis si n < 5 ; "p" = "{annee}Q{1..4}"
  "quarters": [ {"p":"2021Q1","n":1450,"pm2_med":3850}, … ]
}
```

**Invariants** : `Σ overall.n == n_tot` ; `byType[t].n[i] == n_{years[i]}_t{t}` des agrégats des
tuiles ; les arrays de `byType[t]` et de `overall` ont la longueur de `years`.

## 4. Architecture de l'extracteur

`pipeline/stats_bundles.py`, fonction pure et testable :

```python
def build_stats_bundles(con, names: dict[str, str], out_dir: str, version: str,
                        dense_threshold: int = 200) -> dict:
    """con : connexion DuckDB avec la vue stats_src déjà créée (post remap COG/scissions).
       names : {code commune/dept -> nom}, capté pendant build_layer.
       version : id de build (ex. timestamp) écrit dans manifest + chaque bundle.
       Écrit out_dir/stats/{manifest.json, departements.json, dep/{DD}.json}.
       Retourne un récap (compteurs) pour prepare_stats.json / QA."""
```

Calcul en SQL DuckDB sur `stats_src` (`median()` natif) :
- `overall` : `GROUP BY <key>, annee` → `n=count(*)`, `pm2_med=median(pm2)`.
- `byType` : `GROUP BY <key>, annee, type` (type non nul) → `n`, `median(pm2|vf|sb|st|np)`.
- `quarters` : `GROUP BY <key>, annee, (date//100%100-1)//3+1` filtré aux entités `n_tot ≥ seuil`,
  points `n ≥ 5`.
- `<key>` = `com` (communes) puis `dep` (départements).

`nom` provient des fichiers de contours : **`build_layer` renvoie désormais aussi son
`{code: nom}`**. Les entités sans vente sortent avec `n_tot: 0` (cohérent avec les couches
communes/départements — une commune sans vente n'est pas un trou).

**Point d'accroche** dans [`prepare.py`](../../../pipeline/prepare.py) (après les `build_layer`, ~ligne 512) :

```python
# version : horodatage UTC du build, posé tôt dans main() (qa["version"])
com_names = build_layer("communes_*.geojson", …)   # renvoie {code: nom}
dep_names = build_layer("dept_*.geojson", …)
if not args.layers_only:
    qa["stats_bundles"] = build_stats_bundles(
        con, {**com_names, **dep_names}, args.out, version=qa["version"])
```

`years` n'est **pas** codé en dur : `build_stats_bundles` lit les millésimes distincts présents
dans `stats_src` (triés) et aligne tous les arrays dessus — l'invariant `Σ overall.n == n_tot`
reste exact même si l'éventail de millésimes évolue.

Tourne dans le pipeline normal (`prepare.py`) → couvert par `run_pipeline.sh`, pas de commande
manuelle nouvelle. La dérivation du dépt depuis un code commune suit `prepare.py` : `97x` → 3
caractères, Corse `2A/2B`, sinon 2 caractères.

## 5. Disposition & livraison

```
build/stats/
├── manifest.json        # { version, generated, layers, departements:[...], compteurs }
├── departements.json    # { version, entities:[ ~109 départements ] }
└── dep/
    ├── 01.json … 95.json, 2A.json, 2B.json, 971.json … 976.json   # ~101 fichiers
    └──                   # { version, entities:[ communes du département ] }
```

**Chemin iOS au tap** (URLs publiques `…/storage/v1/object/public/tiles/<chemin>`) :
- tap **département** → `stats/departements.json` (caché une fois) → lookup par `code`.
- tap **commune** → dérive `{DD}` du code INSEE → `stats/dep/{DD}.json?v={version}` → lookup par
  `code`. Localité : communes voisines = même bundle déjà caché.

**Ordres de grandeur** : ~345 communes/dépt → bundle ~0,3–0,7 Mo brut (~100–200 Ko gzip).
Gzip à l'upload = optimisation optionnelle (post-POC).

**Upload** : extension de [`scripts/deploy-supabase.sh`](../../../scripts/deploy-supabase.sh) —
après l'archive + l'index, boucle `cp` de tout `build/stats/**` vers `ss:///tiles/stats/**` (même
`upload()` delete-then-recopy). Pas de nouvelle Edge Function : fichiers statiques publics.

## 6. Contrat aval iOS (livré, non implémenté ici)

- URLs stables : `…/public/tiles/stats/{manifest.json, departements.json, dep/{DD}.json}`.
- `EntityStats` (§3) → type `Codable` Swift ; arrays alignés sur `years` ; `null` = absence.
- Résolution du fichier dépt depuis un code INSEE commune (`97x` → 3 car., `2A`/`2B`, sinon 2 car.).
- Branchement : au tap, l'app a déjà l'`AggregateEntity` (code, nom) depuis la tuile → fetch bundle
  → vue type `AggregateStatsView` réutilisant `PriceTrendChart` (`overall`/`quarters` pour la
  courbe, `byType` pour la répartition). Les chips année/type filtrent l'affichage (comptes annuels
  sommables ; médianes affichées par année, jamais fusionnées).

## 7. Tests & QA

**Tests (bloquants, `pytest`)** :
1. **Unitaire `stats_bundles`** sur un mini-jeu DuckDB synthétique déterministe : forme (arrays
   alignés, `null`), médianes/comptes sur valeurs connues, application du seuil de densité (entité
   `< 200` → pas de `quarters` ; point `< 5` omis).
2. **Parité tuiles ⟷ bundles** : `byType[t].n[i] == n_{years[i]}_t{t}` et `Σ overall.n == n_tot`
   (mêmes sources `stats_src` → invariante figée).

**QA (`pipeline/qa_checks.py`, bloquant)** :
- Tout dépt du `manifest` a son fichier ; tout `code` de `communes.geojson`/`departements.geojson`
  apparaît dans un bundle (y compris `n_tot:0`).
- Recoupement `n_tot` bundle ⟷ `n_tot` des couches geojson (échec dur si divergence).
- `version` cohérente entre `manifest.json` et chaque bundle.

**Doc** : mettre à jour `CLAUDE.md` (§ commandes/architecture) — nouvel artefact `build/stats/`,
son rôle, le seuil — et préciser que ce schéma est **distinct** du contrat « 4 fichiers
consommateurs » des tuiles (artefact à part, son propre cycle de vie).

## 8. Hors périmètre (YAGNI)

- UI iOS (vue, fetch, cache, branchement tap) — lot aval carex.immo.
- Moyennes rognées P2–P98 (remplacées par médianes, D2).
- Trimestriel par type (D6) ; granularité infra-communale (quartiers/IRIS) ; gzip à l'upload.
- Endpoint Edge Function dynamique pour les stats (écarté au profit du statique, D4).
