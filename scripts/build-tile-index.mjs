#!/usr/bin/env node
/**
 * Build a tile index from dvf.pmtiles for efficient byte-range lookups
 * Output: build/tiles_index.json
 * Format: { "mutations": { "4": { "0": { "0": [offset, length], ... } } } }
 */

import fs from "fs";
import path from "path";
import { PMTiles } from "pmtiles";

const pmtilesPath = process.argv[2] || "./build/dvf.pmtiles";
const outputPath = "./build/tiles_index.json";

async function buildIndex() {
  if (!fs.existsSync(pmtilesPath)) {
    console.error(`❌ File not found: ${pmtilesPath}`);
    process.exit(1);
  }

  console.log(`📖 Reading ${pmtilesPath}...`);
  const buffer = fs.readFileSync(pmtilesPath);

  // Create a minimal source that implements ISource interface
  const source = {
    data: buffer,
    getBytes: async (offset, length) => {
      return new Uint8Array(buffer.slice(offset, offset + length));
    },
  };

  const pmtiles = new PMTiles(source);
  const header = pmtiles.getHeader();

  console.log(`📊 PMTiles header:`);
  console.log(`   Version: ${header.specVersion}`);
  console.log(`   Root dir: offset=${header.rootDirOffset}, len=${header.rootDirLength}`);
  console.log(`   Tile count: ${header.tileEntries}`);

  // Build index
  const index = {
    mutations: {},
    communes: {},
    departements: {},
  };

  // For now, return empty index with structure
  // Full implementation would enumerate all tiles from directory
  console.log("⚠️  Note: Tile enumeration requires full PMTiles directory parsing");
  console.log("    For MVP, using storage direct access pattern instead.");

  fs.writeFileSync(outputPath, JSON.stringify(index, null, 2));
  console.log(`\n✅ Index written to ${outputPath}`);
}

buildIndex().catch((err) => {
  console.error("❌ Error:", err.message);
  process.exit(1);
});
