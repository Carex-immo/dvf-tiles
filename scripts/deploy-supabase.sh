#!/bin/bash
# Deploy DVF tiles to Supabase
# Usage: ./scripts/deploy-supabase.sh <project-ref> [pmtiles-file]

set -euo pipefail

PROJECT_REF="${1:-bqwbazolhtwizafxqzlr}"
PMTILES_FILE="${2:-build/dvf.pmtiles}"
BUCKET="tiles"

echo "🚀 Deploying DVF tiles to Supabase project: $PROJECT_REF"

# Step 1: Link to project
echo "📌 Linking to Supabase project..."
supabase link --project-ref "$PROJECT_REF" --yes

# Step 2: Verify bucket exists
echo "📁 Checking bucket 'tiles'..."
if ! supabase storage ls tiles 2>/dev/null | grep -q "tiles"; then
  echo "❌ Bucket 'tiles' not found. Create it in dashboard:"
  echo "   https://supabase.com/dashboard/project/$PROJECT_REF/storage/buckets"
  echo "   Then re-run this script."
  exit 1
fi

# Step 3: Upload PMTiles file
if [ -f "$PMTILES_FILE" ]; then
  FILE_SIZE=$(stat -f%z "$PMTILES_FILE" 2>/dev/null || stat -c%s "$PMTILES_FILE")
  FILE_SIZE_MB=$((FILE_SIZE / 1024 / 1024))

  echo "📤 Uploading $PMTILES_FILE ($FILE_SIZE_MB MB)..."
  echo "   Note: For files > 500 MB, upload manually via dashboard:"
  echo "   https://supabase.com/dashboard/project/$PROJECT_REF/storage/buckets/tiles"

  # Use web upload for large files
  if [ $FILE_SIZE_MB -gt 500 ]; then
    echo "⚠️  File too large for CLI. Please upload via dashboard."
    exit 1
  fi

  # supabase storage cp requires --experimental and special syntax
  supabase storage cp "$PMTILES_FILE" "ss:///tiles/dvf.pmtiles" --experimental 2>/dev/null || {
    echo "❌ CLI upload failed. Upload manually to https://supabase.com/dashboard/project/$PROJECT_REF/storage/buckets/tiles"
    exit 1
  }
else
  echo "❌ PMTiles file not found: $PMTILES_FILE"
  exit 1
fi

# Step 4: Deploy Edge Function
echo "⚙️  Deploying Edge Function..."
supabase functions deploy dvf-tiles --project-ref "$PROJECT_REF"

# Step 5: Verify deployment
echo "✅ Deployment complete!"
echo ""
echo "📍 URLs:"
echo "   PMTiles: https://$PROJECT_REF.supabase.co/storage/v1/object/public/$BUCKET/dvf.pmtiles"
echo "   API: https://$PROJECT_REF.supabase.co/functions/v1/dvf-tiles"
echo ""
echo "🧪 Test:"
echo "   curl https://$PROJECT_REF.supabase.co/functions/v1/dvf-tiles/mutations/14/8000/5900.mvt"
echo ""
echo "📱 iOS Client config:"
echo '   static let baseURL = URL(string: "https://'$PROJECT_REF'.supabase.co/functions/v1/dvf-tiles")!'
