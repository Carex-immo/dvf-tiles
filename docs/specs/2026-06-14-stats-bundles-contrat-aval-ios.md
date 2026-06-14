# Contrat aval — bundles de stats par département/commune (consommation iOS)

**Date** : 2026-06-14 · **Producteur** : dvf-tiles (`pipeline/stats_bundles.py`) ·
**Consommateur** : app iOS carex.immo (panneau au tap d'un département/commune).
Conception : [../superpowers/specs/2026-06-14-stats-bundles-dept-commune-design.md](../superpowers/specs/2026-06-14-stats-bundles-dept-commune-design.md).

## URLs (bucket public Supabase `tiles`)

Base : `https://bqwbazolhtwizafxqzlr.supabase.co/storage/v1/object/public/tiles`
- `…/stats/manifest.json` — version, années, seuil de densité, liste des départements.
- `…/stats/departements.json` — tous les départements (~109).
- `…/stats/dep/{DD}.json` — communes d'un département. `{DD}` = code département.

## Résolution du fichier au tap

L'app connaît déjà, depuis la tuile, le `code` INSEE et la couche de l'entité.
- Tap **département** → charger `stats/departements.json` (une fois, caché) → entité par `code`.
- Tap **commune** (code INSEE `C`) → `DD = C[:3] si C commence par "97", sinon C[:2]`
  (couvre Corse `2A`/`2B` et DOM `97x`) → charger `stats/dep/{DD}.json?v={manifest.version}`
  → entité par `code`. Communes voisines = même bundle (cache par zone).

## Schéma d'une entité (`EntityStats`)

Tableaux parallèles indexés par `years` ; `null` = pas de donnée. Codes type :
`1` maison, `2` appartement, `3` immeuble, `4` local com./ind., `5` dépendance.

| Champ | Type | Sens |
|---|---|---|
| `code` | String | code INSEE (commune) ou code département |
| `nom` | String | libellé |
| `n_tot` | Int | total mutations (terrain nu inclus) |
| `pm2_med` | Int? | médiane €/m² toute période |
| `vf_med` | Int? | médiane valeur foncière toute période |
| `years` | [Int] | millésimes, axe commun des arrays |
| `overall.n` | [Int] | nb ventes/an, tous types (terrain nu inclus) |
| `overall.pm2_med` | [Int?] | médiane €/m²/an, tous types |
| `byType` | {code type → métriques} | présent par type observé |
| `byType[t].n` | [Int] | nb ventes/an (0 si aucune) |
| `byType[t].{pm2_med,vf_med,sb_med,st_med,np_med}` | [Int?] | médianes/an (€/m², valeur, surface bâtie, terrain, pièces) |
| `quarters` | [{p,n,pm2_med}]? | tendance trimestrielle si `n_tot ≥ dense_threshold` ; `p="{annee}Q{1..4}"` |

## Règles de consommation

- **Tendance** : `quarters` si présent (fin), sinon `overall.pm2_med` (annuel) — toujours traçable.
- **Répartition par type** : `byType` directement ; filtre type/année = sélection d'arrays.
  Les comptes annuels se somment ; **les médianes s'affichent par année, jamais fusionnées
  entre années** (une médiane de plage n'est pas la médiane des médianes).
- **Cache-busting** : suffixer les bundles de `?v={manifest.version}` ; lire le manifest avec
  un cache court. Les URLs sont stables entre builds (archive remplacée en place).
- **Absence** : un `404` sur `dep/{DD}.json` = pas de données pour ce département (traiter comme
  vide, pas comme une erreur). Une entité absente du bundle = hors périmètre géométrique (rare,
  cf. communes sans géométrie côté pipeline).

## Garanties de cohérence

Par construction (extracteur et agrégats des tuiles partagent la même source `stats_src`) :
- `byType[t].n[i] == n_{years[i]}_t{t}` des agrégats portés par les tuiles.
- `Σ overall.n == n_tot`.

Vérifié mécaniquement en QA (`check_stats_bundles`, build bloqué en cas d'écart) :
- `n_tot` du bundle identique à celui des couches `communes`/`departements` (parité bundle ⟷ geojson).
- arrays alignés sur `years` ; `quarters` présent seulement si `n_tot ≥ dense_threshold`.
- `version` identique entre `manifest.json` et chaque bundle.
