#!/usr/bin/env bash
# Telechargement des CSV geo-dvf.
#
# Mode departements : ./download.sh "2021 2022 2023 2024 2025" "69 01" data/raw
# Mode France entiere : ./download.sh "2021 2022 2023 2024 2025" full data/raw
#   (full.csv.gz ~ 300-500 Mo par millesime ; reprise automatique avec curl -C -)
#
# Livraison DVF courante (2021-S2 -> 2026-S1) + 1er semestre 2021 conserve de
# l'ancienne livraison. Fichiers semestriels poses a la main (non telecharges) :
#   2021s1_full.csv.gz  pipeline/extract_semestre.py data/raw/archive/2021_full.csv.gz
#                       data/raw/2021s1_full.csv.gz --avant 2021-07-01 --decalage 2000000
#                       (ids 2021-N -> 2021-(N+2000000) : la nouvelle livraison
#                       renumerote 2021-S2 a partir de 2021-1)
#   2021s2_full.csv.gz, 2026s1_full.csv.gz  livres tels quels
# Ne jamais melanger deux livraisons pour une meme periode : les id_mutation
# sont renumerotes d'une livraison a l'autre.
set -euo pipefail
YEARS="${1:-2022 2023 2024 2025}"
DEPTS="${2:-69 01}"
DEST="${3:-data/raw}"
BASE="https://files.data.gouv.fr/geo-dvf/latest/csv"
mkdir -p "$DEST"

fetch() { # url, dest
  echo "GET $1"
  curl -fL --retry 3 -C - -o "$2" "$1" || curl -fL --retry 3 -o "$2" "$1"
  gzip -t "$2" || { echo "ERREUR: $2 corrompu" >&2; rm -f "$2"; exit 1; }
}

for y in $YEARS; do
  if [ "$DEPTS" = "full" ]; then
    f="$DEST/${y}_full.csv.gz"
    [ -s "$f" ] && gzip -t "$f" 2>/dev/null && { echo "skip $f"; continue; }
    fetch "$BASE/${y}/full.csv.gz" "$f"
  else
    for d in $DEPTS; do
      f="$DEST/${y}_${d}.csv.gz"
      [ -s "$f" ] && gzip -t "$f" 2>/dev/null && { echo "skip $f"; continue; }
      fetch "$BASE/${y}/departements/${d}.csv.gz" "$f"
    done
  fi
done
ls -la "$DEST"

# --- Contours IRIS (opt-in WITH_IRIS=1) : derniere edition GPKG WGS84 --------
# Source unique France entiere (~49 000 IRIS) publiee sur la Geoplateforme.
# iris_latest.py resout l'URL .7z de la derniere edition ; 7z (p7zip) extrait
# le GPKG. WGS84G = deja EPSG:4326, aucune reprojection. Pose dans data/geo car
# c'est un contour, au meme titre que communes_*/dept_* (cf. download_geo.sh).
if [ "${WITH_IRIS:-0}" = "1" ]; then
  GEO_DIR="${GEO_DIR:-data/geo}"
  mkdir -p "$GEO_DIR"
  if [ ! -f "$GEO_DIR/CONTOURS-IRIS.gpkg" ]; then
    command -v 7z >/dev/null || { echo "ERREUR: 7z manquant (brew install p7zip) — requis pour CONTOURS-IRIS" >&2; exit 1; }
    IRIS_URL=$(python3 pipeline/iris_latest.py | awk '/^url/ {print $3}')
    [ -n "$IRIS_URL" ] || { echo "ERREUR: URL CONTOURS-IRIS introuvable (iris_latest.py)" >&2; exit 1; }
    echo "== CONTOURS-IRIS : $IRIS_URL =="
    curl -fL --retry 3 -o "$GEO_DIR/iris.7z" "$IRIS_URL"
    7z x -y -o"$GEO_DIR/iris_extract" "$GEO_DIR/iris.7z" >/dev/null
    GPKG=$(find "$GEO_DIR/iris_extract" -iname '*.gpkg' | head -n1)
    [ -n "$GPKG" ] || { echo "ERREUR: aucun .gpkg dans l'archive IRIS" >&2; exit 1; }
    cp "$GPKG" "$GEO_DIR/CONTOURS-IRIS.gpkg"
    rm -rf "$GEO_DIR/iris.7z" "$GEO_DIR/iris_extract"
    echo "-> $GEO_DIR/CONTOURS-IRIS.gpkg"
  else
    echo "skip CONTOURS-IRIS (deja present)"
  fi
fi
