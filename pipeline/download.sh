#!/usr/bin/env bash
# Telechargement des CSV geo-dvf.
#
# Mode departements : ./download.sh "2021 2022 2023 2024 2025" "69 01" data/raw
# Mode France entiere : ./download.sh "2021 2022 2023 2024 2025" full data/raw
#   (full.csv.gz ~ 300-500 Mo par millesime ; reprise automatique avec curl -C -)
set -euo pipefail
YEARS="${1:-2021 2022 2023 2024 2025}"
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
