#!/usr/bin/env bash
# CAREX - Pipeline complet de build des tuiles DVF.
#
#   ./pipeline/run_pipeline.sh poc      # departements 69 + 01 (validation)
#   ./pipeline/run_pipeline.sh france   # France entiere (prevoir ~3 Go de CSV,
#                                       # ~8 Go RAM, 30-90 min selon machine)
#
# Etapes : download CSV -> download contours -> prepare (DuckDB) ->
#          tippecanoe/tile-join -> controles qualite -> build/dvf.pmtiles
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-poc}"
YEARS="${YEARS:-2021 2022 2023 2024 2025}"
PREPARE_OPTS="${PREPARE_OPTS:-}"

case "$MODE" in
  poc)    SCOPE_CSV="69 01"; SCOPE_GEO="69 01"
          PATTERN="*_69.csv.gz,*_01.csv.gz" ;;
  france) SCOPE_CSV="full";  SCOPE_GEO="france"
          PATTERN="*_full.csv.gz"
          PREPARE_OPTS="${PREPARE_OPTS:---memory-limit 8GB}" ;;
  *) echo "usage: $0 poc|france" >&2; exit 1 ;;
esac

command -v tippecanoe >/dev/null || { echo "tippecanoe manquant (brew install tippecanoe)" >&2; exit 1; }
command -v tile-join  >/dev/null || { echo "tile-join manquant" >&2; exit 1; }
python3 -c "import duckdb, mapbox_vector_tile, pmtiles" 2>/dev/null \
  || { echo "pip install duckdb mapbox-vector-tile pmtiles" >&2; exit 1; }

echo "==== [1/5] CSV geo-dvf ($MODE) ===="
bash pipeline/download.sh "$YEARS" "$SCOPE_CSV" data/raw

echo "==== [2/5] Contours administratifs ===="
bash pipeline/download_geo.sh "$SCOPE_GEO" data/geo

echo "==== [3/5] Preparation (DuckDB) ===="
# shellcheck disable=SC2086
python3 pipeline/prepare.py --raw data/raw --geo data/geo --out build \
  --pattern "$PATTERN" $PREPARE_OPTS

echo "==== [4/5] Tuiles (tippecanoe) ===="
bash pipeline/build_tiles.sh build

echo "==== [5/5] Controles qualite ===="
python3 pipeline/qa_checks.py build

echo "OK : build/dvf.pmtiles pret a publier (cf. spec §4.3 / §6)."
