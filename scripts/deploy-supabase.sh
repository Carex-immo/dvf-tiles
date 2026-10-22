#!/bin/bash
# Déploiement des tuiles DVF sur Supabase : archive PMTiles + index + Edge Function
# + stats (bundles, index IRIS, détail IRIS).
# Usage: ./scripts/deploy-supabase.sh [project-ref] [pmtiles-file]
#   prod    : ./scripts/deploy-supabase.sh                       (bqwbazolhtwizafxqzlr)
#   staging : ./scripts/deploy-supabase.sh uyozmyiunskrapdptqwv
#
# Prérequis :
#  - supabase CLI authentifié (supabase login) — déploiement de l'Edge Function ;
#  - aws CLI (brew install awscli) + clés S3 du projet (Dashboard → Storage →
#    S3 Connection → New access key) dans un profil dédié, jamais committées :
#      aws configure --profile supabase-<project-ref>    (région : eu-west-3)
#    (profil surchargeable par AWS_PROFILE) ;
#  - bucket public "tiles" existant ;
#  - build/tiles_index.json régénéré depuis l'archive à uploader
#    (node scripts/build-pmtiles-index.mjs) — un index d'une autre archive
#    servirait des offsets faux, donc des tuiles corrompues.
#
# Upload par l'API S3 de Supabase Storage : un PutObject (ou multipart pour
# l'archive) remplace l'objet d'un bloc à la fin du transfert — aucune fenêtre
# sans objet, reprise par parties, et sync en masse du détail IRIS (~47 000 fichiers).

set -euo pipefail

PROJECT_REF="${1:-bqwbazolhtwizafxqzlr}"
PMTILES_FILE="${2:-build/dvf.pmtiles}"
INDEX_FILE="build/tiles_index.json"
BUCKET="tiles"
PUBLIC_URL="https://$PROJECT_REF.supabase.co/storage/v1/object/public/$BUCKET"
FN_URL="https://$PROJECT_REF.supabase.co/functions/v1/dvf-tiles"
S3_ENDPOINT="https://$PROJECT_REF.storage.supabase.co/storage/v1/s3"
export AWS_PROFILE="${AWS_PROFILE:-supabase-$PROJECT_REF}"
# aws CLI ≥ 2.23 envoie par défaut des checksums CRC que les S3 compatibles ne
# gèrent pas tous : on se limite à ceux exigés par l'opération.
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required
export AWS_RESPONSE_CHECKSUM_VALIDATION=when_required

s3() { aws --endpoint-url "$S3_ENDPOINT" --region "${S3_REGION:-eu-west-3}" "$@"; }
# Tous les objets sont servis en no-cache (archive sous URL fixe, index
# dé-versionné, stats rafraîchies 2×/an) : comportement du servi actuel.
put() { # src, chemin dans le bucket, content-type
  s3 s3 cp "$1" "s3://$BUCKET/$2" --content-type "$3" --cache-control no-cache --only-show-errors
}

echo "🚀 Déploiement des tuiles DVF — projet Supabase : $PROJECT_REF (profil aws : $AWS_PROFILE)"

# Étape 1 : outils, accès S3, bucket
command -v aws >/dev/null      || { echo "❌ aws CLI manquant (brew install awscli)"; exit 1; }
command -v supabase >/dev/null || { echo "❌ supabase CLI manquant"; exit 1; }
if ! s3 s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  echo "❌ Bucket '$BUCKET' inaccessible en S3 (profil $AWS_PROFILE absent, clés invalides"
  echo "   ou bucket inexistant). Bucket (public) à créer dans le dashboard :"
  echo "   https://supabase.com/dashboard/project/$PROJECT_REF/storage/buckets"
  exit 1
fi

# Étape 2 : cohérence archive/index
[ -f "$PMTILES_FILE" ] || { echo "❌ Archive introuvable : $PMTILES_FILE"; exit 1; }
[ -f "$INDEX_FILE" ]   || { echo "❌ Index introuvable : $INDEX_FILE (node scripts/build-pmtiles-index.mjs)"; exit 1; }

ARCHIVE_SIZE=$(stat -f%z "$PMTILES_FILE" 2>/dev/null || stat -c%s "$PMTILES_FILE")
INDEX_SIZE=$(python3 -c "import json;print(json.load(open('$INDEX_FILE'))['metadata']['pmtilesSize'])" 2>/dev/null || echo 0)
if [ "$INDEX_SIZE" != "$ARCHIVE_SIZE" ]; then
  echo "❌ L'index ($INDEX_SIZE o) ne correspond pas à l'archive ($ARCHIVE_SIZE o)."
  echo "   Régénérer : node scripts/build-pmtiles-index.mjs"
  exit 1
fi

# Étape 3 : archive puis index (l'index ne doit jamais référencer des offsets
# que l'archive en ligne n'a pas encore)
echo "📤 Upload de $PMTILES_FILE ($((ARCHIVE_SIZE / 1024 / 1024)) Mo, multipart)..."
put "$PMTILES_FILE" dvf.pmtiles application/octet-stream
ONLINE_SIZE=$(curl -sI "$PUBLIC_URL/dvf.pmtiles" | awk 'tolower($1)=="content-length:" {print $2}' | tr -d '\r')
if [ "$ONLINE_SIZE" != "$ARCHIVE_SIZE" ]; then
  echo "❌ Archive en ligne : ${ONLINE_SIZE:-?} o, attendu $ARCHIVE_SIZE o (bucket public ?)"
  exit 1
fi

echo "📤 Upload de $INDEX_FILE..."
put "$INDEX_FILE" tiles_index.json application/json

# Étape 4 : Edge Function, AUSSITÔT après l'index — chaque instance garde
# tiles_index.json en mémoire sans expiration : une instance chaude servirait
# la nouvelle archive avec les offsets de l'ancien index (tuiles corrompues).
# Le redéploiement recycle les instances.
echo "⚙️  Déploiement de l'Edge Function (--no-verify-jwt : service public)..."
supabase functions deploy dvf-tiles --project-ref "$PROJECT_REF" --no-verify-jwt

# Étape 5 : test de fumée — une tuile dense (Lyon z13) doit sortir en MVT
# lisible, couche mutations en tête. La passerelle Supabase peut décompresser
# le gzip de l'archive (constaté : corps MVT brut) : on accepte les deux.
echo "🧪 Test de fumée..."
SMOKE=$(mktemp)
CODE=000
for _ in 1 2 3 4 5 6; do
  CODE=$(curl -s -o "$SMOKE" -w '%{http_code}' "$FN_URL/mutations/13/4206/2922.mvt")
  [ "$CODE" = "200" ] && break
  sleep 5
done
if [ "$CODE" != "200" ] || ! python3 - "$SMOKE" <<'EOF'
import gzip, sys
b = open(sys.argv[1], "rb").read()
if b[:2] == b"\x1f\x8b":
    b = gzip.decompress(b)
sys.exit(0 if b[:1] == b"\x1a" and b"mutations" in b[:64] else 1)
EOF
then
  echo "❌ Tuile de contrôle : HTTP $CODE ou MVT illisible — ne pas poursuivre"
  echo "   (l'archive et l'index en ligne sont peut-être incohérents)."
  rm -f "$SMOKE"; exit 1
fi
echo "   OK ($(wc -c < "$SMOKE" | tr -d ' ') o)"
rm -f "$SMOKE"

# Étape 6 : stats. Manifest IRIS (additif) : si l'index IRIS a été produit
# (WITH_IRIS=1), patch_manifest.py enrichit build/stats/manifest.json avec
# millesime_iris + layers.iris_index + compteurs.iris (idempotent, préserve la
# version mintée par le pipeline stats).
IRIS_MILLESIME="${IRIS_MILLESIME:-2026}"
if [ -d "build/iris_index" ] && [ -f "build/stats/manifest.json" ]; then
  echo "🧩 Patch du manifest stats (bits IRIS)..."
  python3 pipeline/patch_manifest.py \
    --manifest-file build/stats/manifest.json \
    --iris-index-dir build/iris_index \
    --millesime "$IRIS_MILLESIME" \
    --out build/stats/manifest.json
fi

# Le manifest part en DERNIER : il annonce les années et couches disponibles,
# il ne doit pas précéder les fichiers qu'il référence.
STATS_DIR="build/stats"
if [ -d "$STATS_DIR" ]; then
  COUNT=$(find "$STATS_DIR" -type f -name '*.json' | wc -l | tr -d ' ')
  echo "📤 Upload des bundles de stats ($COUNT fichiers, manifest en dernier)..."
  s3 s3 cp "$STATS_DIR" "s3://$BUCKET/stats" --recursive \
    --exclude "*" --include "*.json" --exclude "manifest.json" \
    --content-type application/json --cache-control no-cache --only-show-errors
else
  echo "ℹ️  $STATS_DIR absent : aucun bundle de stats à uploader (relancer prepare.py)"
fi

# Index IRIS départemental (résolution GPS→IRIS côté client) : stats/iris_index/{DD}.json
if [ -d "build/iris_index" ]; then
  N=$(find build/iris_index -name '*.json' | wc -l | tr -d ' ')
  echo "📤 Upload de l'index IRIS départemental ($N fichiers → stats/iris_index/)..."
  s3 s3 cp build/iris_index "s3://$BUCKET/stats/iris_index" --recursive \
    --exclude "*" --include "*.json" \
    --content-type application/json --cache-control no-cache --only-show-errors
fi

# Détail par IRIS (contour + stats + mutations, chargé au tap) : stats/iris/{code_iris}.json
# sync sans --delete : un IRIS disparu garde son ancien fichier (inoffensif,
# plus référencé par l'index) plutôt que de risquer une suppression en masse.
if [ -d "build/iris" ]; then
  N=$(find build/iris -name '*.json' | wc -l | tr -d ' ')
  echo "📤 Sync du détail IRIS ($N fichiers → stats/iris/)..."
  s3 s3 sync build/iris "s3://$BUCKET/stats/iris" \
    --exclude "*" --include "*.json" \
    --content-type application/json --cache-control no-cache --only-show-errors
fi

if [ -f "$STATS_DIR/manifest.json" ]; then
  echo "📤 Upload du manifest stats..."
  put "$STATS_DIR/manifest.json" stats/manifest.json application/json
fi

echo "✅ Déploiement terminé."
echo ""
echo "📍 URLs :"
echo "   PMTiles : $PUBLIC_URL/dvf.pmtiles"
echo "   Index   : $PUBLIC_URL/tiles_index.json"
echo "   Stats   : $PUBLIC_URL/stats/manifest.json"
[ -d "build/iris_index" ] && echo "   IRIS idx: $PUBLIC_URL/stats/iris_index/{DD}.json"
echo "   API     : $FN_URL/{couche}/{z}/{x}/{y}.mvt"
