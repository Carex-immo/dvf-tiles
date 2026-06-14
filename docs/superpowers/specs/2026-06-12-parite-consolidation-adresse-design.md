# Spec — Parité de consolidation + adresse dans la couche `mutations`

**Date** : 2026-06-12
**Statut** : validé (suite de la session « articulation tuiles ↔ liste iOS »)
**Périmètre** : repo `dvf-tiles` — pipeline, QA, consommateurs de référence. Met en œuvre le
contrat carex.immo [`docs/specs/2026-06-11-tuiles-mvt-contrat-integration.md`](../../../../carex.immo/docs/specs/2026-06-11-tuiles-mvt-contrat-integration.md)
(commit `4b95f59`) **et** l'étend : adresse + code postal + commune dans les tuiles (amendement
proposé, cf. §7).

## 1. Problème

La liste de mutations de l'app iOS affiche l'adresse complète, fournie aujourd'hui par
l'API dvf-api.data.gouv.fr. Après migration vers les tuiles statiques, le schéma du contrat
(9 attributs) n'a ni adresse ni commune : la liste perdrait son champ principal. Par ailleurs
le contrat acte des **divergences de consolidation** entre `prepare.py` (DuckDB) et l'app
(référence verrouillée par les goldens Swift) : pièces (max vs somme), type (pas de règle
immeuble), fusion des biens, ancrage, surface bâtie, nature, filtre `vf > 0`. Tant qu'elles
subsistent, compteurs et filtres des tuiles divergent de l'app.

## 2. Décisions

| # | Décision | Justification |
|---|---|---|
| D1 | La consolidation mutations passe de SQL DuckDB à **`consolidate.py` (pont de parité carex.immo), importé verbatim** | Décision du contrat ; les règles (fold, half-away, fusion, ancrage) sont impraticables à répliquer fidèlement en SQL ; parité prouvée par les goldens rejoués à chaque build |
| D2 | Nouveau schéma couche `mutations` : `id, date, nat, type, vf, sb, st, np, nl, com` + **`adr`, `cp` (z≥13 uniquement)** ; suppression de `annee, pm2, nc, dep` | 9 attributs du contrat + amendement §7 ; `annee`/`pm2`/`dep` dérivables, `nc` non filtré |
| D3 | `adr`/`cp` exclus de la passe z4-12 (`tippecanoe -x`) | La liste (z≥13) seule en a besoin ; surcoût mesuré +27–41 % sur z13-14 si embarqué partout ; à z4-12 l'attribut ferait dropper plus de points (limite 500 Ko/tuile) |
| D4 | Bandes de zoom **inchangées** : mutations z4-14, échantillonné ≤ z12, exhaustif z13-14 | Le contrat (« exhaustif z11+ ») est resté sur l'état POC, invalidé au passage France entière (cf. CLAUDE.md « Pièges connus ») — amendement à reporter au contrat, cf. §7 |
| D5 | DuckDB reste pour l'aval : remap COG, scissions, agrégats, exports | « DuckDB peut rester pour l'I/O mais plus pour les règles métier » (contrat) |
| D6 | Agrégats communes/départements : clés `n_{annee}_t{type}` / `p_{annee}_t{type}` conservées, codes type app (1-5), **`cx`/`cy` centroïdes ajoutés** | Format POC connu des consommateurs ; codes contractuels ; centroïdes exigés par le contrat (cercles proportionnels MapKit) |

## 3. Sémantique de la couche `mutations` (source de vérité : goldens P1)

Population : une feature par mutation **consolidée par `consolidate_group`** — ancrée par les
coordonnées de la parcelle de la 1ʳᵉ ligne (map fichier-globale parcelle→coords, jamais de
repli ; sans ancre → rejetée + comptée). Conséquences assumées vs POC :

- **Le filtre `valeur_fonciere > 0` disparaît** : une mutation sans vf est présente, l'attribut
  `vf` est simplement omis (règle MVT « pas de sentinelle »).
- **Terrain nu** (`compute_primary_type` → None) : exclu de la couche points, compté
  (`mutations_terrain_nu` dans `prepare_stats.json`), **inclus dans les agrégats** (`n_tot`,
  `vf_med` — une vente de terrain est une vente) ; pas de seau `n_{annee}_t{type}`.
- **Les mutations sans ancre sortent aussi des agrégats** (le POC les y comptait) : la
  population agrégats = population consolidée, seule base cohérente avec les goldens.

| Attribut | Règle (consolidate.py) | Omission |
|---|---|---|
| `id` | `id_mutation` (1ʳᵉ ligne) | jamais |
| `date` | `date_mutation` 1ʳᵉ ligne → int `YYYYMMDD` | jamais |
| `nat` | `MUTATION_TYPE_CODE` 1-5, repli vente=1, jamais 0 (« Vente terrain à bâtir » → 1) | jamais |
| `type` | `compute_primary_type` : 1 maison, 2 appartement, **3 immeuble**, 4 local, **5 dépendance** ; None → feature exclue | — |
| `vf` | `round_half_away(valeur_fonciere)` 1ʳᵉ ligne | si absente |
| `sb` | Σ bâti des biens **post-fusion, hors dépendances**, half-away | jamais (0 si aucun) |
| `st` | Σ par parcelle du max, sinon Σ terrains des biens, half-away | jamais (0 si aucun) |
| `np` | **somme** des pièces de tous les biens | jamais (0 si aucun) |
| `nl` | nb de **biens post-fusion** (≠ locaux distincts POC) | jamais |
| `com` | `code_commune` 1ʳᵉ ligne, **après remap COG/scissions** | jamais |
| `adr` | 1ʳᵉ ligne : `adresse_numero` ⌴ `adresse_suffixe` ⌴ `adresse_nom_voie`, champs vides sautés, casse source (l'app applique `titleCaseFR`) | si vide ; **z≥13 seulement** |
| `cp` | `code_postal` 1ʳᵉ ligne (chaîne, zéros de tête) | si vide ; **z≥13 seulement** |

Coordonnées : ancre arrondie à 5 décimales (`round5`, half-away — aligne le geojsonl sur les
goldens, le POC écrivait 6 décimales).

Notes adresse (règle **non** couverte par les goldens — fixée ici) :
- Le suffixe (`B` = bis…) est inclus : donnée réelle distinguant deux biens, coût ~2 o ;
  l'app l'ignorait (son modèle ne le parse pas) — divergence d'affichage assumée, le chemin
  API disparaissant avec la migration.
- Le nom de commune n'est pas embarqué : dérivable de `com` via table COG embarquée côté app ;
  `adresseComplete` = `titleCaseFR(adr)`, `cp`, nom de commune.
- ~99,4 % des mutations ont une voie non vide (mesure 2024) : la couverture `adr` est un
  indicateur QA (§6).

## 4. Architecture de `prepare.py`

```
pipeline/parity/                     ← copie versionnée carex.immo@4b95f59 (NE PAS MODIFIER,
  consolidate.py                       toute évolution part du Swift + goldens régénérés)
  tests/test_parity.py + goldens/ + fixtures/
pipeline/prepare.py
  1. par fichier CSV : read_rows_extended()   ← réplique read_rows + adr/cp/com/dep composés
     → build_coords_map / contiguous_groups / consolidate_group  (importés VERBATIM)
     → écrit build/mutations_consolidees.jsonl (tous attributs + lon/lat + type nullable)
  2. DuckDB : charge le jsonl → remap_cog + reassign_scissions (inchangés, sur com/dep/lon/lat)
     → export build/mutations.geojsonl (props non nulles, type NOT NULL, round5)
     → agrégats communes/departements (annee = date//10000, pm2 = vf/sb si les deux > 0)
     → build_layer + centroïde (cx/cy, shoelace sur le plus grand anneau extérieur)
  3. prepare_stats.json : compteurs consolidate (rows_read, malformed, skipped, rejets sans
     ancre, terrain nu) + compteurs existants (par_annee, communes…)
```

- `read_rows_extended` est la **seule** logique dupliquée (lecture CSV + 4 champs annexes) ;
  un test dédié (`pipeline/parity/test_parity_extended.py`, propre à dvf-tiles) rejoue les
  goldens à travers elle pour prouver la non-déviation, et vérifie l'extraction `adr`/`cp`
  sur fixture.
- DuckDB ne lit plus les CSV : les stats source viennent des compteurs de consolidation.
- `--layers-only` survit (reconstruction agrégats depuis le geojsonl).
- RAM : un fichier à la fois (`rows` libérés entre fichiers). France entière : ~4-5 M lignes
  par `full.csv.gz` ≈ 3-5 Go de pics Python, +15-25 min vs SQL — accepté pour un build batch ;
  si insoluble, v2 streaming (2 passes) sans toucher aux règles.

## 5. Tuilage

- Passe mutations z4-12 : + `-x adr -x cp` (option **par invocation tippecanoe** — surtout pas
  sur `tile-join`, qui purgerait les attributs de toutes les tuiles).
- Passes z13-14, communes, départements, tile-join : inchangées.
- Effet attendu : tuiles z4-12 plus légères qu'avant (4 attributs supprimés) donc moins de
  drop ; z13-14 : +27–41 % mesuré pour adr seul, partiellement compensé par les suppressions.
- La metadata fusionnée listera `adr`/`cp` pour toute la couche sans mention de zoom : les
  clients ne doivent jamais supposer leur présence sous z13 (documenté CLAUDE.md).

## 6. QA (bloquant au build)

1. **Parité** : `pytest pipeline/parity/` (goldens officiels + chemin étendu) — nouvelle étape
   de `run_pipeline.sh`, prérequis `pytest` ajouté.
2. `qa_checks.py` (durci après revue adversariale) :
   - `REQUIRED_ATTRS` = `{id, date, nat, type, sb, st, np, nl, com}` — vérifiés sur **toutes**
     les features de la tuile (`com` « jamais omis » est aussi garanti par une garde dure dans
     `prepare.py` : échec si une mutation a `com` NULL) ;
   - écart de plage de zoom d'une couche : **erreur** (plages déterministes `-Z/-z`) ; au moins
     un échantillon décodé exigé par palier z12/z13/z14 (sinon les contrôles de palier ne
     prouvent rien) ;
   - couverture `vf` : erreur si 0 feature ne le porte, warning < 90 % ; bornes sur les
     features qui le portent ;
   - `adr` **et `cp`** : à z≥13 couverture ≥ 80 % (erreur si 0, warning sous le seuil) ; à z12
     **erreur si la clé est présente** (l'exclusion -x a sauté) ;
   - `ko_gz` z13/14 : warning > 800 Ko (tuiles construites sans limite) ;
   - baseline de comptage : un build en échec écrit `qa_report_echec.json` et ne remplace pas
     `qa_report.json`. Premier build post-migration : `--reset-baseline`.

## 7. Amendement du contrat carex.immo (à reporter, pas d'édition croisée)

1. Schéma mutations : **+ `com`** (string, COG courant — nom de commune et `adresseComplete`
   côté app via table COG ; clé du matching « reventes ») ; **+ `adr`, `cp`** garantis
   uniquement à z≥13, omis si vides, casse source.
2. Zooms : mutations **z4-14, exhaustif z13+** (z9-z10 « drop-densest » du contrat ne reflète
   plus le pipeline post-France ; les bandes app restent libres d'ignorer z<9).
3. Stratégie liste : la liste se nourrit des tuiles à z≥13 (adresse incluse) ; l'API
   `dvf_get_mutation` reste le chemin du **détail** (lots, biens, parcelles).
4. Agrégats : clés `n_{annee}_t{type}`/`p_{annee}_t{type}` (POC) avec codes type app —
   le contrat écrivait `n_{annee}_{type}`/`pm2med_…` ; population = mutations consolidées
   (terrain nu inclus dans `n_tot`, sans ancre exclues).

## 8. Synchronisation des consommateurs (même lot)

- `demo/index.html` : sélecteur et couleurs type 1-5 (immeuble, dépendance recodés), filtre
  année via `["floor",["/",["get","date"],10000]]`, `pm2` dérivé `vf/sb`, `adr`/`cp` dans la
  popup (ternaire — couche visible dès z11), vf omissible.
- `client/simulate_ios.py` : filtres sur dérivés (`date//10000`, `vf/sb`), affichage d'un
  échantillon `adr`, agrégat `n_2025_t2` inchangé (appartement reste 2).
- `client/DvfTileClient.swift` : struct `Mutation` = nouveau schéma (`vf: Int?`, `adr/cp:
  String?`, `com: String`, sans `annee/pm2/nc`), commentaires de contrat (z≥13, dérivations).
- `CLAUDE.md` : section « Encodage compact partagé » réécrite, pièges ajoutés (parité
  verbatim, -x par passe, population des agrégats).

## 8bis. Correctif embarqué — parents PLM vs arrondissements

Découvert au premier run : `reassign_scissions` traitait le polygone parent (69123 Lyon,
75056 Paris, 13055 Marseille — présent dans les contours sans jamais porter de stats
propres, DVF codant par arrondissement) comme une commune rétablie par scission, et lui
réaffectait par localisation les mutations de ses arrondissements (50 000 à Lyon,
arrondissements à `n_tot=0`). Bug pré-existant, aggravé par ce lot (`com` part dans les
tuiles). Correctif : constante `PLM_PARENTS` exclue de `reassign_scissions`, du vote de
`remap_cog` et de la couche communes (les arrondissements couvrent le territoire).

Confirmé en revue adversariale (même mécanique, cas général) : toute commune sans vente
aspirait les points frontaliers (7 mutations 69/01 réaffectées vers 5 communes des
départements 39/42/71 dont 3 sans aucun mouvement COG). Correctif : seules les communes
**rétablies par scission (MOD 21 de la table INSEE)** sont candidates, et seules les
mutations encore **codées sous leur commune parente** sont capturées ; `dep` est ensuite
réaligné sur `com` (cohérence des agrégats départements et du chemin `--layers-only`).

## 9. Risques

- **Comptages en mouvement** : suppression du filtre vf>0 (+), rejets sans ancre (−), terrain
  nu hors couche points (−) — le premier build casse la tolérance ±20 % → `--reset-baseline`
  documenté ; les compteurs de rejets sont exposés pour suivi.
- **Performance France** : consolidation pure Python ~20 M lignes ; mesurer au premier run
  France, v2 streaming si besoin (les règles ne bougent pas).
- **Dérive de la copie parité** : interdiction de modifier `pipeline/parity/consolidate.py`
  (en-tête + CLAUDE.md) ; resynchronisation = recopie depuis carex.immo + commit dédié.
- **RGPD/produit** : l'adresse passe d'un service au tap à des tuiles statiques publiques
  téléchargeables en masse. DVF est open data adresses comprises (dvf-api les sert déjà) ;
  arbitrage explicite à acter côté produit.
