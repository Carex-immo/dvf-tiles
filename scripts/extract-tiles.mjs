#!/usr/bin/env node
/**
 * Extract all MVT tiles from dvf.pmtiles into build/tiles/layer/z/x/y.mvt
 * npm install pmtiles
 */

import fs from "fs";
import path from "path";
import { readFileSync } from "fs";
import { PMTiles } from "pmtiles";

const pmtilesPath = process.argv[2] || "./build/dvf.pmtiles";
const outputDir = "./build/tiles";

const LAYER_RANGES = {
  departements: { minZ: 4, maxZ: 6 },
  communes: { minZ: 6, maxZ: 10 },
  mutations: { minZ: 4, maxZ: 14 },
};

async function extractTiles() {
  if (!fs.existsSync(pmtilesPath)) {
    console.error(`❌ File not found: ${pmtilesPath}`);
    process.exit(1);
  }

  console.log(`📖 Reading ${pmtilesPath}...`);
  const buffer = readFileSync(pmtilesPath);
  const pmtiles = new PMTiles(new (Buffer.from(buffer).constructor)(buffer));

  const stats = { departements: 0, communes: 0, mutations: 0 };
  let total = 0;

  console.log(`📁 Extracting to ${outputDir}/`);

  // Iterate all tiles
  for await (const tile of pmtiles.getAll()) {
    const { z, x, y, data } = tile;

    // Determine layer based on zoom level
    let layer = "mutations";
    if (z >= LAYER_RANGES.departements.minZ && z <= LAYER_RANGES.departements.maxZ) {
      layer = "departements";
    }
    if (z >= LAYER_RANGES.communes.minZ && z <= LAYER_RANGES.communes.maxZ) {
      layer = "communes";
    }

    // Create directory structure
    const tileDir = path.join(outputDir, layer, String(z), String(x));
    fs.mkdirSync(tileDir, { recursive: true });

    // Write MVT tile
    const tilePath = path.join(tileDir, `${y}.mvt`);
    fs.writeFileSync(tilePath, data);

    stats[layer]++;
    total++;

    if (total % 1000 === 0) {
      const pct = ((total / pmtiles.getNumTiles?.()) * 100).toFixed(1);
      console.log(
        `  ✓ ${total} tiles | ${stats.departements} dept, ${stats.communes} communes, ${stats.mutations} mutations`
      );
    }
  }

  console.log(`\n✅ Extracted ${total} tiles:`);
  console.log(`   • Mutations: ${stats.mutations}`);
  console.log(`   • Communes: ${stats.communes}`);
  console.log(`   • Départements: ${stats.departements}`);

  // Show disk usage
  const dirSize = await getDirSize(outputDir);
  console.log(`\n📊 Directory size: ${(dirSize / 1024 / 1024).toFixed(1)} MB`);
}

async function getDirSize(dirPath) {
  let size = 0;
  const files = fs.readdirSync(dirPath, { recursive: true });
  for (const file of files) {
    const stat = fs.statSync(path.join(dirPath, file));
    if (stat.isFile()) size += stat.size;
  }
  return size;
}

extractTiles().catch((err) => {
  console.error("❌ Extraction failed:", err.message);
  process.exit(1);
});
