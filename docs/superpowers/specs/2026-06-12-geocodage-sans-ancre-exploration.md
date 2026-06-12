# Exploration — géocoder les mutations « sans ancre » via data.geopf.fr

Date : 2026-06-12. Statut : **exploration close, pas d'implémentation** (décision : « juste explorer »). Rien n'a été modifié dans le pipeline.

## Question

~2,2–2,7 % des mutations geo-dvf sont rejetées « sans ancre » (la parcelle de la 1ʳᵉ ligne n'a pas de coordonnées). Peut-on les récupérer en interrogeant l'API de géocodage de la Géoplateforme (`https://data.geopf.fr/geocodage/search`), par la parcelle ou par l'adresse ?

## Protocole

Script ponctuel (non versionné, `/tmp/explore_sans_ancre.py`) : rejoue la détection « sans ancre » sur `2021_full.csv.gz` (1 726 304 mutations, 45 097 sans ancre soit 2,61 %, 35 326 parcelles uniques), tire 400 parcelles au hasard (seed 42), interroge l'index `parcel` (`q=<id_parcelle>`), puis en repli l'index `address` (`q="numéro voie ville"` + `postcode`) quand la ligne a un numéro **et** une voie.

Note de syntaxe API : sur l'index `parcel`, `q=<id_parcelle complet>` (14 caractères) fonctionne ; la forme structurée (`departmentcode`/`municipalitycode`/`section`/`number`) échoue dès que le préfixe `oldmunicipalitycode` est non nul.

## Résultats

| Voie | Récupération | Remarques |
|---|---|---|
| Index `parcel` | **0 / 400 (0 %)** | Voie morte par construction |
| Repli `address` | 232 / 400 (58 %) | Scores 0,31–0,98, médiane 0,77 |
| Irrécupérable | 168 / 400 (42 %) | Lieu-dit sans numéro de voie |

- **Parcelle : 0 %.** geo-dvf géocode déjà en croisant DVF avec le cadastre actuel (PCI). Une parcelle « sans ancre » est une parcelle qui n'existe plus au cadastre (remembrement, fusion, renumérotation) ; l'index `parcel` de la Géoplateforme interroge ce même cadastre, donc ne peut rien retrouver de plus.
- **Adresse : ~58 % brut, ~40–50 % réaliste.** Quasi toutes les lignes avec numéro+voie obtiennent un résultat BAN, mais la qualité est hétérogène : matchs `housenumber` excellents (score 0,97) côtoient des `locality` (centre de lieu-dit) et des numéros DVF suspects (`6017`, `6153` — artefacts cadastraux ruraux). Avec un seuil sérieux (score ≥ 0,7 et type `housenumber`/`street`), on retombe vers 40–50 % des sans-ancre, soit **~1 à 1,3 % des mutations totales**.
- Les 42 % restants n'ont qu'un lieu-dit (` LE VILLAGE`, ` LES AULNETTES`…) : toute récupération serait un point approximatif, incompatible avec une couche de points exacte à z13+.

## Conclusion et conditions d'une reprise éventuelle

Gain modeste (~1 % de mutations) pour un coût réel : ~150 000 géocodages par millésime France, une sémantique d'ancre différente (point BAN ≈ entrée de voie, vs centroïde de parcelle), et surtout une **divergence de parité avec carex.immo** (l'app rejette ces mutations ; les tuiles en montreraient plus).

Si le sujet est repris un jour :

1. **Swift d'abord** : implémenter côté carex.immo, régénérer les goldens, recopier le pont de parité (processus de `pipeline/parity/README.md`) — jamais d'enrichissement unilatéral côté tuiles.
2. Seuil strict : score ≥ 0,7 **et** type `housenumber`/`street` ; ignorer les `locality` et les numéros de voie > 5000.
3. Utiliser le géocodeur CSV par lots de la Géoplateforme, pas du requête-par-requête.
