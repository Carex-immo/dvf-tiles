#!/usr/bin/env bash
# Telechargement des contours administratifs.
#
# Mode POC :            ./download_geo.sh "69 01" data/geo
# Mode France entiere : ./download_geo.sh france data/geo
#
# Source des communes : geo.api.gouv.fr, departement par departement.
# C'est la seule source alignee sur le COG COURANT, le meme que celui utilise
# par geo-dvf pour code_commune. Un fichier national fige (Etalab/france-geojson)
# cree des trous pour chaque fusion/scission posterieure a son millesime.
# Arrondissements municipaux de Paris/Lyon/Marseille inclus (DVF code les
# mutations au niveau arrondissement : 751xx, 6938x, 132xx).
set -euo pipefail
SCOPE="${1:-69 01}"
DEST="${2:-data/geo}"
MILLESIME_CONTOURS="${MILLESIME_CONTOURS:-2024}"
mkdir -p "$DEST"
ETALAB="https://adresse.data.gouv.fr/data/contours-administratifs/$MILLESIME_CONTOURS/geojson"
GEOAPI="https://geo.api.gouv.fr"

# valide qu'un fichier est un GeoJSON avec >= $2 features, sinon le supprime
check_geojson() {
  python3 - "$1" "${2:-1}" <<'EOF'
import json, os, sys
p, n_min = sys.argv[1], int(sys.argv[2])
try:
    n = len(json.load(open(p)).get("features", []))
except Exception:
    n = -1
if n < n_min:
    if os.path.exists(p):
        os.remove(p)
    sys.exit(1)
EOF
}

fetch_communes_dept() { # $1 = code departement
  local f="$DEST/communes_$1.geojson"
  if [ -s "$f" ] && check_geojson "$f" 1; then echo "skip communes $1"; return 0; fi
  echo "== communes $1 =="
  curl -fsL --retry 3 --retry-delay 2 -o "$f" \
    "$GEOAPI/departements/$1/communes?format=geojson&geometry=contour"
  check_geojson "$f" 1 || { echo "ERREUR: contours $1 invalides" >&2; return 1; }
}

fetch_arrondissements() { # $1 = code departement (75, 69, 13)
  local f="$DEST/communes_arr$1.geojson"
  if [ -s "$f" ] && check_geojson "$f" 1; then echo "skip arrondissements $1"; return 0; fi
  echo "== arrondissements municipaux $1 =="
  curl -fsL --retry 3 --retry-delay 2 -o "$f" \
    "$GEOAPI/communes?codeDepartement=$1&type=arrondissement-municipal&format=geojson&geometry=contour" || true
  check_geojson "$f" 1 || true   # vide/absent -> supprime, sans erreur
}

# table INSEE des mouvements de communes (fusions/scissions depuis 1943) :
# sert au remappage des codes retires sans mutation geolocalisee (cf. prepare.py)
COG_MVT_URL="${COG_MVT_URL:-https://www.insee.fr/fr/statistiques/fichier/8740222/v_mvt_commune_2026.csv}"
if [ ! -s "$DEST/cog_mouvements.csv" ]; then
  echo "== mouvements de communes INSEE =="
  curl -fsL --retry 3 -o "$DEST/cog_mouvements.csv" "$COG_MVT_URL"
fi

if [ "$SCOPE" = "france" ]; then
  # 96 departements metropolitains (20 -> 2A/2B) + DROM couverts par DVF
  DEPTS="$(seq -w 1 19) 2A 2B $(seq 21 95) 971 972 973 974"
  for d in $DEPTS; do fetch_communes_dept "$d"; done
  for d in 75 69 13; do fetch_arrondissements "$d"; done
  # Saint-Barthelemy (97123) et Saint-Martin (97127) : collectivites d'outre-mer
  # depuis 2007, absentes de geo.api/Etalab mais toujours presentes dans DVF.
  # Contours statiques (source ARCEP format Admin Express, reprojetes WGS84,
  # recodes vers les codes commune DVF) versionnes dans le depot.
  cp "$(dirname "$0")/static/communes_97x.geojson" "$DEST/communes_97x.geojson"
  echo "== departements France (Etalab $MILLESIME_CONTOURS, 100 m) =="
  if ! { [ -s "$DEST/dept_france.geojson" ] && check_geojson "$DEST/dept_france.geojson" 90; }; then
    curl -fsL --retry 3 -o "$DEST/dept_france.geojson" "$ETALAB/departements-100m.geojson"
    check_geojson "$DEST/dept_france.geojson" 90
  fi
  # purge des sources nationales figees d'anciens builds (sinon doublons de COG)
  rm -f "$DEST/communes_france.geojson" "$DEST/.communes_france.part"
  n_files=$(ls "$DEST"/communes_*.geojson | wc -l)
  echo "OK : $n_files fichiers communes"
else
  for d in $SCOPE; do
    fetch_communes_dept "$d"
    fetch_arrondissements "$d"
  done
  echo "== contours departements (Etalab $MILLESIME_CONTOURS) =="
  curl -fsL --retry 3 -o "$DEST/.dept_all.geojson" "$ETALAB/departements-100m.geojson"
  python3 - "$DEST" $SCOPE <<'EOF'
import json, sys
dest = sys.argv[1]; keep = set(sys.argv[2:])
d = json.load(open(f"{dest}/.dept_all.geojson"))
feats = [f for f in d["features"] if f["properties"]["code"] in keep]
json.dump({"type": "FeatureCollection", "features": feats},
          open(f"{dest}/dept_poc.geojson", "w"), separators=(",", ":"))
print(f"dept_poc.geojson : {len(feats)} departements")
EOF
  rm -f "$DEST/.dept_all.geojson"
fi
ls "$DEST" | head -20
