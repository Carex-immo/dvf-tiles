#!/usr/bin/env bash
# CAREX - Pipeline complet de build des tuiles DVF.
#
#   ./pipeline/run_pipeline.sh poc      # departements 69 + 01 (validation)
#   ./pipeline/run_pipeline.sh france   # France entiere (prevoir ~3 Go de CSV,
#                                       # ~8 Go RAM, 30-90 min selon machine)
#
# Etapes : download CSV -> download contours -> parite (goldens) ->
#          prepare (consolidation parite + DuckDB aval) ->
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
python3 -c "import duckdb, mapbox_vector_tile, pmtiles, pytest" 2>/dev/null \
  || { echo "pip install duckdb mapbox-vector-tile pmtiles pytest" >&2; exit 1; }

echo "==== [1/6] CSV geo-dvf ($MODE) ===="
bash pipeline/download.sh "$YEARS" "$SCOPE_CSV" data/raw

echo "==== [2/6] Contours administratifs ===="
bash pipeline/download_geo.sh "$SCOPE_GEO" data/geo

echo "==== [3/6] Parite de consolidation (goldens) + extracteur de stats ===="
python3 -m pytest -q pipeline/parity pipeline/test_stats_bundles.py

echo "==== [4/6] Preparation (consolidation parite + DuckDB aval) ===="
# shellcheck disable=SC2086
python3 pipeline/prepare.py --raw data/raw --geo data/geo --out build \
  --pattern "$PATTERN" $PREPARE_OPTS

echo "==== [5/6] Tuiles (tippecanoe) ===="
bash pipeline/build_tiles.sh build

echo "==== [6/6] Controles qualite ===="
python3 pipeline/qa_checks.py build

echo "OK : build/dvf.pmtiles pret a publier (cf. spec §4.3 / §6)."
