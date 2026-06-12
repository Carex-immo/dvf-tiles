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

# Étape 4 : Edge Function — tuiles open data, servies sans JWT
echo "⚙️  Déploiement de l'Edge Function (--no-verify-jwt : service public)..."
supabase functions deploy dvf-tiles --project-ref "$PROJECT_REF" --no-verify-jwt

# Étape 5 : vérification
echo "✅ Déploiement terminé."
echo ""
echo "📍 URLs :"
echo "   PMTiles : https://$PROJECT_REF.supabase.co/storage/v1/object/public/$BUCKET/dvf.pmtiles"
echo "   Index   : https://$PROJECT_REF.supabase.co/storage/v1/object/public/$BUCKET/tiles_index.json"
echo "   API     : https://$PROJECT_REF.supabase.co/functions/v1/dvf-tiles/{couche}/{z}/{x}/{y}.mvt"
echo ""
echo "🧪 Test :"
echo "   curl -sI https://$PROJECT_REF.supabase.co/functions/v1/dvf-tiles/mutations/13/4206/2922.mvt"
