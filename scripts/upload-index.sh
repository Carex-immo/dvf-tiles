#!/bin/bash
# Upload tiles index to Supabase Storage
# Usage: ./scripts/upload-index.sh [project-ref] [index-file]

set -euo pipefail

PROJECT_REF="${1:-bqwbazolhtwizafxqzlr}"
INDEX_FILE="${2:-build/tiles_index.json}"
BUCKET="tiles"
OBJECT_NAME="index.json"

echo "📤 Uploading index to Supabase Storage..."

# Step 1: Check that index file exists
if [ ! -f "$INDEX_FILE" ]; then
  echo "❌ Index file not found: $INDEX_FILE"
  exit 1
fi

FILE_SIZE=$(stat -f%z "$INDEX_FILE" 2>/dev/null || stat -c%s "$INDEX_FILE")
FILE_SIZE_KB=$((FILE_SIZE / 1024))

echo "   File: $INDEX_FILE ($FILE_SIZE_KB KB)"

# Step 2: Try supabase CLI first
echo "   Attempting upload via Supabase CLI..."
if supabase storage cp "$INDEX_FILE" "ss:///$BUCKET/$OBJECT_NAME" --experimental 2>/dev/null; then
  echo "✅ Index uploaded successfully via CLI"
else
  # Step 3: Fallback to curl with REST API
  echo "   CLI failed, attempting REST API upload..."

  # Get auth token from environment (required for upload)
  if [ -z "${SUPABASE_TOKEN:-}" ]; then
    echo "❌ Error: SUPABASE_TOKEN environment variable not set"
    echo "   Please set SUPABASE_TOKEN to your Supabase JWT before running this script"
    exit 1
  fi
  AUTH_TOKEN="$SUPABASE_TOKEN"

  BASE_URL="https://$PROJECT_REF.supabase.co/storage/v1"

  if curl -s \
    -X POST \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    --data-binary @"$INDEX_FILE" \
    "$BASE_URL/object/$BUCKET/$OBJECT_NAME" > /dev/null 2>&1; then
    echo "✅ Index uploaded successfully via REST API"
  else
    echo "❌ Upload failed via both CLI and REST API"
    echo "   Try uploading manually via:"
    echo "   https://supabase.com/dashboard/project/$PROJECT_REF/storage/buckets/$BUCKET"
    exit 1
  fi
fi

# Step 4: Verify the file is accessible
PUBLIC_URL="https://$PROJECT_REF.supabase.co/storage/v1/object/public/$BUCKET/$OBJECT_NAME"

echo ""
echo "🔍 Verifying accessibility..."
if curl -s -I "$PUBLIC_URL" | grep -q "200\|304"; then
  echo "✅ Index is publicly accessible"
  echo ""
  echo "📍 Public URL:"
  echo "   $PUBLIC_URL"
else
  echo "⚠️  Could not verify public access (file may still be uploading)"
  echo ""
  echo "📍 Expected URL:"
  echo "   $PUBLIC_URL"
fi
