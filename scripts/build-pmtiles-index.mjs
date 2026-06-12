#!/usr/bin/env node
/**
 * Build a minimal tile metadata index from dvf.pmtiles
 * The Edge Function will use the pmtiles library for actual tile lookup
 */

import fs from "fs";
import { bytesToHeader } from "pmtiles";

const pmtilesPath = process.argv[2] || "./build/dvf.pmtiles";
const outputPath = process.argv[3] || "./build/tiles_index.json";

async function buildIndex() {
  if (!fs.existsSync(pmtilesPath)) {
    console.error(`❌ File not found: ${pmtilesPath}`);
    process.exit(1);
  }

  console.log(`📖 Reading ${pmtilesPath}...`);
  const fileBuffer = fs.readFileSync(pmtilesPath);
  const fileSize = fileBuffer.length;

  // Parse header
  const headerAB = fileBuffer.buffer.slice(fileBuffer.byteOffset, fileBuffer.byteOffset + 127);
  const header = bytesToHeader(headerAB);

  console.log(`\n📊 PMTiles Archive Info:`);
  console.log(`   Spec version: ${header.specVersion}`);
  console.log(`   File size: ${(fileSize / 1024 / 1024).toFixed(1)} MB`);
  console.log(`   Min zoom: ${header.minZoom}, Max zoom: ${header.maxZoom}`);
  console.log(`   Addressed tiles: ${header.numAddressedTiles}`);
  console.log(`   Bounds: [${header.minLon}, ${header.minLat}, ${header.maxLon}, ${header.maxLat}]`);

  // Create metadata-only index
  // The Edge Function will use the pmtiles library for actual tile lookups
  const indexContent = {
    metadata: {
      timestamp: new Date().toISOString(),
      pmtilesPath: pmtilesPath,
      pmtilesSize: fileSize,
      archivedTiles: header.numAddressedTiles,
      headerInfo: {
        specVersion: header.specVersion,
        minZoom: header.minZoom,
        maxZoom: header.maxZoom,
        numAddressedTiles: header.numAddressedTiles,
        bounds: {
          minLon: header.minLon,
          minLat: header.minLat,
          maxLon: header.maxLon,
          maxLat: header.maxLat,
        },
      },
    },
    // The Edge Function will perform lookups using the PMTiles library
    // No pre-indexed tile list is provided
  };

  fs.writeFileSync(outputPath, JSON.stringify(indexContent, null, 2));

  console.log(`\n✅ Metadata index created`);
  console.log(`📄 Written to: ${outputPath}`);

  const fileSize2 = fs.statSync(outputPath).size;
  console.log(`📊 Index size: ${(fileSize2 / 1024).toFixed(1)} KB`);
  console.log(`\n📝 Note: The Edge Function will use the pmtiles library to look up tiles at runtime.`);
}

buildIndex().catch((e) => {
  console.error("Fatal error:", e.message);
  process.exit(1);
});
