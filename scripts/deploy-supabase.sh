#!/bin/bash
# Déploiement des tuiles DVF sur Supabase : archive PMTiles + index + Edge Function.
# Usage: ./scripts/deploy-supabase.sh [project-ref] [pmtiles-file]
#
# Prérequis : supabase CLI authentifié (supabase login), bucket public "tiles"
# existant, build/tiles_index.json régénéré depuis l'archive à uploader
# (node scripts/build-pmtiles-index.mjs) — un index d'une autre archive
# servirait des offsets faux, donc des tuiles corrompues.

set -euo pipefail

PROJECT_REF="${1:-bqwbazolhtwizafxqzlr}"
PMTILES_FILE="${2:-build/dvf.pmtiles}"
INDEX_FILE="build/tiles_index.json"
BUCKET="tiles"

echo "🚀 Déploiement des tuiles DVF — projet Supabase : $PROJECT_REF"

# Étape 1 : lier le projet
echo "📌 Lien au projet Supabase..."
supabase link --project-ref "$PROJECT_REF" --yes

# Étape 2 : le bucket existe ?
# NB : `supabase storage ls` exige --experimental et le schéma ss:///
# (ss:/// liste les buckets) — sans cela la commande échoue silencieusement.
echo "📁 Vérification du bucket '$BUCKET'..."
if ! supabase storage ls ss:/// --experimental | grep -q "$BUCKET"; then
  echo "❌ Bucket '$BUCKET' introuvable. À créer (public) dans le dashboard :"
  echo "   https://supabase.com/dashboard/project/$PROJECT_REF/storage/buckets"
  exit 1
fi

# Étape 3 : cohérence archive/index puis upload (archive d'abord : l'index ne
# doit jamais référencer des offsets que l'archive en ligne n'a pas encore)
[ -f "$PMTILES_FILE" ] || { echo "❌ Archive introuvable : $PMTILES_FILE"; exit 1; }
[ -f "$INDEX_FILE" ]   || { echo "❌ Index introuvable : $INDEX_FILE (node scripts/build-pmtiles-index.mjs)"; exit 1; }

ARCHIVE_SIZE=$(stat -f%z "$PMTILES_FILE" 2>/dev/null || stat -c%s "$PMTILES_FILE")
INDEX_SIZE=$(python3 -c "import json;print(json.load(open('$INDEX_FILE'))['metadata']['pmtilesSize'])" 2>/dev/null || echo 0)
if [ "$INDEX_SIZE" != "$ARCHIVE_SIZE" ]; then
  echo "❌ L'index ($INDEX_SIZE o) ne correspond pas à l'archive ($ARCHIVE_SIZE o)."
  echo "   Régénérer : node scripts/build-pmtiles-index.mjs"
  exit 1
fi

# `storage cp` ne sait pas écraser (409 Duplicate) : on supprime puis on
# re-uploade. Fenêtre sans objet pendant l'upload — assumée au stade POC.
upload() {
  local src="$1" dst="$2"
  if ! supabase storage cp "$src" "$dst" --experimental 2>/dev/null; then
    echo "   (objet existant : suppression puis re-upload)"
    echo y | supabase storage rm "$dst" --experimental || true
    if ! supabase storage cp "$src" "$dst" --experimental; then
      echo "❌ Upload CLI échoué pour $dst. Repli : dashboard (upload résumable)"
      echo "   https://supabase.com/dashboard/project/$PROJECT_REF/storage/buckets/$BUCKET"
      exit 1
    fi
  fi
}

echo "📤 Upload de $PMTILES_FILE ($((ARCHIVE_SIZE / 1024 / 1024)) Mo)..."
upload "$PMTILES_FILE" "ss:///$BUCKET/dvf.pmtiles"

echo "📤 Upload de $INDEX_FILE..."
upload "$INDEX_FILE" "ss:///$BUCKET/tiles_index.json"

# Manifest IRIS (additif, AVANT l'upload des stats) : si l'index IRIS a été
# produit (WITH_IRIS=1), patch_manifest.py enrichit build/stats/manifest.json
# avec millesime_iris + layers.iris_index + compteurs.iris (idempotent, préserve
# la version mintée par le pipeline stats). Le manifest patché est uploadé juste
# après par le bloc STATS_DIR.
IRIS_MILLESIME="${IRIS_MILLESIME:-2026}"
if [ -d "build/iris_index" ] && [ -f "build/stats/manifest.json" ]; then
  echo "🧩 Patch du manifest stats (bits IRIS)..."
  python3 pipeline/patch_manifest.py \
    --manifest-file build/stats/manifest.json \
    --iris-index-dir build/iris_index \
    --millesime "$IRIS_MILLESIME" \
    --out build/stats/manifest.json
fi

# Bundles de stats par département (panneau iOS au tap) — fichiers statiques publics
STATS_DIR="build/stats"
if [ -d "$STATS_DIR" ]; then
  COUNT=$(find "$STATS_DIR" -type f -name '*.json' | wc -l | tr -d ' ')
  echo "📤 Upload des bundles de stats ($COUNT fichiers depuis $STATS_DIR)..."
  while IFS= read -r f; do
    rel="${f#build/}"                       # ex: stats/manifest.json, stats/dep/69.json
    upload "$f" "ss:///$BUCKET/$rel"
  done < <(find "$STATS_DIR" -type f -name '*.json')
else
  echo "ℹ️  $STATS_DIR absent : aucun bundle de stats à uploader (relancer prepare.py)"
fi

# Index IRIS départemental (résolution GPS→IRIS côté client) : stats/iris_index/{DD}.json
if [ -d "build/iris_index" ]; then
  N=$(find build/iris_index -name '*.json' | wc -l | tr -d ' ')
  echo "📤 Upload de l'index IRIS départemental ($N fichiers → stats/iris_index/)..."
  while IFS= read -r f; do
    upload "$f" "ss:///$BUCKET/stats/iris_index/$(basename "$f")"
  done < <(find build/iris_index -name '*.json')
fi

# Détail par IRIS (contour + stats + mutations, chargé au tap) : stats/iris/{code_iris}.json
if [ -d "build/iris" ]; then
  N=$(find build/iris -name '*.json' | wc -l | tr -d ' ')
  if [ "$N" -gt 5000 ]; then
    # À l'échelle France (~49 000 IRIS) l'upload CLI un-par-un est impraticable.
    echo "ℹ️  Détail IRIS : $N fichiers — trop nombreux pour l'upload CLI un-par-un."
    echo "    Pousser en bulk (S3, méthode éprouvée ; nécessite des clés S3 Supabase) :"
    echo "      aws s3 sync build/iris s3://$BUCKET/stats/iris \\"
    echo "        --endpoint-url https://$PROJECT_REF.storage.supabase.co/storage/v1/s3 \\"
    echo "        --content-type application/json --cache-control 'public, max-age=86400'"
  else
    echo "📤 Upload du détail IRIS ($N fichiers → stats/iris/)..."
    while IFS= read -r f; do
      upload "$f" "ss:///$BUCKET/stats/iris/$(basename "$f")"
    done < <(find build/iris -name '*.json')
  fi
fi

# Étape 4 : Edge Function — tuiles open data, servies sans JWT
echo "⚙️  Déploiement de l'Edge Function (--no-verify-jwt : service public)..."
supabase functions deploy dvf-tiles --project-ref "$PROJECT_REF" --no-verify-jwt

# Étape 5 : vérification
echo "✅ Déploiement terminé."
echo ""
echo "📍 URLs :"
echo "   PMTiles : https://$PROJECT_REF.supabase.co/storage/v1/object/public/$BUCKET/dvf.pmtiles"
echo "   Index   : https://$PROJECT_REF.supabase.co/storage/v1/object/public/$BUCKET/tiles_index.json"
echo "   Stats   : https://$PROJECT_REF.supabase.co/storage/v1/object/public/$BUCKET/stats/manifest.json"
[ -d "build/iris_index" ] && echo "   IRIS idx: https://$PROJECT_REF.supabase.co/storage/v1/object/public/$BUCKET/stats/iris_index/{DD}.json"
echo "   API     : https://$PROJECT_REF.supabase.co/functions/v1/dvf-tiles/{couche}/{z}/{x}/{y}.mvt"
echo ""
echo "🧪 Test :"
echo "   curl -sI https://$PROJECT_REF.supabase.co/functions/v1/dvf-tiles/mutations/13/4206/2922.mvt"
