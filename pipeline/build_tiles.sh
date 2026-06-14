#!/usr/bin/env bash
# Generation de l'archive PMTiles (3 couches) - cf. spec §4.2 / §4.2bis
# Prerequis : tippecanoe + tile-join dans le PATH, build/ produit par prepare.py
set -euo pipefail
BUILD="${1:-build}"
cd "$BUILD"

# Deux passes : la limite de 500 Ko/tuile de tippecanoe declenche
# --drop-densest-as-needed a TOUS les zooms (y compris au-dessus de -B11),
# donc l'exhaustivite n'est tenable qu'en desactivant toute limite (-pk -pf)
# sur une plage haute dediee. A z11 ce serait intenable (Paris ~6,8 Mo gz) ;
# le contrat est donc : z4-z12 echantillonne, exhaustif des z13.
# Surtout ne pas remettre --extend-zooms-if-still-dropping sur la passe basse :
# elle regenererait des tuiles z13+ echantillonnees, fusionnees en doublons.

echo "== mutations (points, z4-z12, echantillonne taille bornee, sans adresse) =="
# -x adr -x cp : l'adresse n'est garantie qu'a z13+ (liste iOS) — l'option est
# PAR INVOCATION tippecanoe ; surtout pas sur tile-join (purgerait z13-14 aussi).
tippecanoe -o mutations_z4_12.pmtiles -l mutations \
  -Z4 -z12 -B11 -P \
  --drop-densest-as-needed \
  -x adr -x cp \
  --force --quiet \
  mutations.geojsonl

echo "== mutations (points, z13-z14, exhaustif : aucune limite) =="
tippecanoe -o mutations_z13_14.pmtiles -l mutations \
  -Z13 -z14 -B13 -P \
  -pk -pf \
  --force --quiet \
  mutations.geojsonl

echo "== communes (polygones, z6-z10) =="
tippecanoe -o communes.pmtiles -l communes \
  -Z6 -z10 \
  --coalesce-densest-as-needed --detect-shared-borders \
  --force --quiet \
  communes.geojson

echo "== departements (polygones, z4-z6) =="
tippecanoe -o departements.pmtiles -l departements \
  -Z4 -z6 \
  --detect-shared-borders \
  --force --quiet \
  departements.geojson

echo "== fusion =="
tile-join -o dvf.pmtiles --force --no-tile-size-limit \
  mutations_z4_12.pmtiles mutations_z13_14.pmtiles \
  communes.pmtiles departements.pmtiles

ls -la ./*.pmtiles
