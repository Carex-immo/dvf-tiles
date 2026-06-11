#!/usr/bin/env node
/**
 * Build a tile index from dvf.pmtiles for efficient O(1) tile lookups
 * Output: build/tiles_index.json
 * Format: { "mutations": { "4": { "0": { "0": { "present": true } } } } }
 */

import fs from "fs";
import path from "path";
import { decompressSync } from "fflate";

const pmtilesPath = process.argv[2] || "./build/dvf.pmtiles";
const outputPath = process.argv[3] || "./build/tiles_index.json";

const LAYER_RANGES = {
  departements: { minZ: 4, maxZ: 6 },
  communes: { minZ: 6, maxZ: 10 },
  mutations: { minZ: 4, maxZ: 14 },
};

/**
 * Decompose a Hilbert tileId to find which zoom level it belongs to
 * by checking if it falls within each level's range
 */
function tileIdToZXY(tileId) {
  // The tileId space is organized by zoom levels
  // z=0: 1 tile (ids 0)
  // z=1: 4 tiles (ids 1-4)
  // z=2: 16 tiles (ids 5-20)
  // etc.
  // Range for z: start = (4^z - 1) / 3, count = 4^z

  let cumulativeTiles = 0;
  for (let z = 0; z <= 28; z++) {
    const tilesAtZ = 1 << (2 * z); // 4^z = 2^(2z)
    if (tileId < cumulativeTiles + tilesAtZ) {
      // Found the zoom level
      const indexInZ = tileId - cumulativeTiles;
      const [x, y] = decomposeHilbert(indexInZ, z);
      return [z, x, y];
    }
    cumulativeTiles += tilesAtZ;
  }

  return [0, 0, 0];
}

/**
 * Decompose a Hilbert index within a zoom level to x, y coordinates
 */
function decomposeHilbert(n, z) {
  let x = 0;
  let y = 0;
  let s = 1;

  while (s < (1 << z)) {
    const rx = 1 & (n >> 1);
    const ry = 1 & (n ^ rx);

    // Rotate
    if (ry === 0) {
      if (rx === 1) {
        x = s - 1 - x;
        y = s - 1 - y;
      }
      // Swap x and y
      [x, y] = [y, x];
    }

    x += s * rx;
    y += s * ry;
    n >>= 2;
    s <<= 1;
  }

  return [x, y];
}

/**
 * Parse a varint from a buffer at a given offset
 * Returns [value, newOffset]
 */
function parseVarint(buffer, offset) {
  let value = 0;
  let shift = 0;
  let byte;

  do {
    if (offset >= buffer.byteLength) break;
    byte = buffer[offset++];
    value |= (byte & 0x7f) << shift;
    shift += 7;
  } while (byte & 0x80);

  return [value, offset];
}

/**
 * Get a 64-bit little-endian uint from DataView
 */
function getUint64LE(view, offset) {
  const low = view.getUint32(offset, true);
  const high = view.getUint32(offset + 4, true);
  return BigInt(high) * (BigInt(1) << BigInt(32)) + BigInt(low);
}

/**
 * Read and parse the header from a PMTiles file buffer
 * Spec: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md
 */
function readHeader(buffer) {
  // PMTiles header is 127 bytes
  if (buffer.byteLength < 127) {
    throw new Error("File too small to be a valid PMTiles");
  }

  // Check magic number (7 bytes: "PMTiles")
  const magic = buffer.slice(0, 7).toString("ascii");
  if (magic !== "PMTiles") {
    throw new Error(`Invalid PMTiles magic number: "${magic}"`);
  }

  // Convert Buffer to ArrayBuffer if needed
  const arrayBuffer = buffer instanceof ArrayBuffer
    ? buffer
    : buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);

  const view = new DataView(arrayBuffer);

  // Header spec (v3):
  // 0-6: "PMTiles"
  // 7: Spec version
  // 8-15: Root directory offset (uint64 LE)
  // 16-23: Root directory length (uint64 LE)
  // 24-31: JSON metadata offset (uint64 LE)
  // 32-39: JSON metadata length (uint64 LE)
  // 40-47: Leaf directory offset (uint64 LE)
  // 48-55: Leaf directory length (uint64 LE)
  // 56-63: Tile data offset (uint64 LE)
  // 64-71: Tile data length (uint64 LE)
  // ...
  // 100: minZoom
  // 101: maxZoom
  // 102-105: minLon (int32 LE, value * 1e-7)
  // 106-109: minLat (int32 LE, value * 1e-7)
  // 110-113: maxLon (int32 LE, value * 1e-7)
  // 114-117: maxLat (int32 LE, value * 1e-7)

  const specVersion = view.getUint8(7);
  const rootDirOffset = Number(getUint64LE(view, 8));
  const rootDirLength = Number(getUint64LE(view, 16));
  const minZoom = view.getUint8(100);
  const maxZoom = view.getUint8(101);
  const internalCompression = view.getUint8(97);

  const minLonE7 = view.getInt32(102, true);
  const minLatE7 = view.getInt32(106, true);
  const maxLonE7 = view.getInt32(110, true);
  const maxLatE7 = view.getInt32(114, true);

  return {
    specVersion,
    rootDirOffset,
    rootDirLength,
    minZoom,
    maxZoom,
    internalCompression,
    minLon: minLonE7 / 1e7,
    minLat: minLatE7 / 1e7,
    maxLon: maxLonE7 / 1e7,
    maxLat: maxLatE7 / 1e7,
  };
}

/**
 * Parse directory entries from a raw directory buffer
 */
function parseDirectoryBuffer(dirBuffer) {
  const entries = [];
  let offset = 0;
  const maxEntries = 1000000; // Safety limit

  while (offset < dirBuffer.byteLength && entries.length < maxEntries) {
    // Parse varint for tileId
    const [tileId, nextOffset1] = parseVarint(dirBuffer, offset);
    if (nextOffset1 === offset) break; // No progress made, stop
    offset = nextOffset1;

    // Parse varint for offset
    const [blockOffset, nextOffset2] = parseVarint(dirBuffer, offset);
    if (nextOffset2 === offset) break; // No progress made, stop
    offset = nextOffset2;

    // Parse varint for length
    const [blockLength, nextOffset3] = parseVarint(dirBuffer, offset);
    if (nextOffset3 === offset) break; // No progress made, stop
    offset = nextOffset3;

    // Parse varint for runLength
    const [runLength, nextOffset4] = parseVarint(dirBuffer, offset);
    if (nextOffset4 === offset) break; // No progress made, stop
    offset = nextOffset4;

    // Sanity checks
    if (tileId < 0 || blockOffset < 0 || blockLength < 0 || runLength < 0) break;
    if (blockLength > 1000000000) break; // Max 1GB per block
    if (blockOffset > 900000000000) break; // Max realistic file size

    if (tileId > 0) {
      entries.push({
        tileId,
        blockOffset,
        blockLength,
        runLength,
      });
    }
  }

  return entries;
}

/**
 * Decompress a buffer if it's gzip (starts with gzip magic)
 */
function decompressIfNeeded(buffer) {
  // Check for gzip magic number
  if (buffer.length >= 2 && buffer[0] === 0x1f && buffer[1] === 0x8b) {
    try {
      const decompressed = decompressSync(new Uint8Array(buffer));
      return Buffer.from(decompressed);
    } catch (e) {
      // If decompression fails, return the raw buffer
      return buffer;
    }
  }
  // Not compressed, return as-is
  return buffer;
}

/**
 * Recursively read all directory entries from a PMTiles file
 */
function readDirectoryEntries(buffer, header) {
  const entries = [];
  const visited = new Set();

  function traverseDirectory(offset, length, depth = 0) {
    const key = `${offset}:${length}`;
    if (visited.has(key)) {
      return; // Avoid infinite loops
    }
    visited.add(key);

    const dirStart = offset;
    const dirEnd = offset + length;
    let dirBuffer = buffer.slice(dirStart, dirEnd);

    // Decompress if needed (auto-detect gzip)
    dirBuffer = decompressIfNeeded(dirBuffer);

    const dirEntries = parseDirectoryBuffer(dirBuffer);

    for (const entry of dirEntries) {
      // If runLength == 0, this is a pointer to a subdirectory
      if (entry.runLength === 0) {
        // Recursively traverse the subdirectory
        traverseDirectory(entry.blockOffset, entry.blockLength, depth + 1);
      } else {
        // This is a tile entry - add it to our results
        entries.push(entry);
      }
    }
  }

  // Start with the root directory
  traverseDirectory(header.rootDirOffset, header.rootDirLength);

  return entries;
}

function buildIndex() {
  if (!fs.existsSync(pmtilesPath)) {
    console.error(`❌ File not found: ${pmtilesPath}`);
    process.exit(1);
  }

  console.log(`📖 Reading ${pmtilesPath}...`);

  // Read the file buffer
  const buffer = fs.readFileSync(pmtilesPath);

  // Parse the header
  const header = readHeader(buffer);

  console.log(`\n📊 PMTiles Info:`);
  console.log(`   Root dir: offset=${header.rootDirOffset}, len=${header.rootDirLength}`);
  console.log(`   Min zoom: ${header.minZoom}, Max zoom: ${header.maxZoom}`);

  // Build index structure: layer -> z -> x -> y -> { present: true }
  const index = {
    mutations: {},
    communes: {},
    departements: {},
  };

  const stats = { mutations: 0, communes: 0, departements: 0 };
  let total = 0;
  const startTime = Date.now();

  // Enumerate all tiles by reading directory entries
  console.log(`\n📝 Enumerating tiles...`);
  const entries = readDirectoryEntries(buffer, header);

  for (const entry of entries) {
    // Convert tileId to z, x, y using Hilbert curve decomposition
    const [z, x, y] = tileIdToZXY(entry.tileId);

    // Determine layer based on zoom level
    let layer = "mutations";
    if (z >= LAYER_RANGES.departements.minZ && z <= LAYER_RANGES.departements.maxZ) {
      layer = "departements";
    }
    if (z >= LAYER_RANGES.communes.minZ && z <= LAYER_RANGES.communes.maxZ) {
      layer = "communes";
    }

    // Build nested structure
    if (!index[layer][z]) {
      index[layer][z] = {};
    }
    if (!index[layer][z][x]) {
      index[layer][z][x] = {};
    }
    index[layer][z][x][y] = { present: true };

    stats[layer]++;
    total++;

    if (total % 1000 === 0) {
      console.log(`  ✓ ${total} tiles indexed...`);
    }
  }

  const elapsed = Date.now() - startTime;

  // Write index to file
  const indexContent = {
    metadata: {
      timestamp: new Date().toISOString(),
      pmtilesPath: pmtilesPath,
      pmtilesSize: buffer.byteLength,
      tileCount: total,
      layers: {
        mutations: stats.mutations,
        communes: stats.communes,
        departements: stats.departements,
      },
      elapsedMs: elapsed,
    },
    index: index,
  };

  fs.writeFileSync(outputPath, JSON.stringify(indexContent, null, 2));

  console.log(`\n✅ Index built: ${total} tiles`);
  console.log(`   • Mutations: ${stats.mutations}`);
  console.log(`   • Communes: ${stats.communes}`);
  console.log(`   • Départements: ${stats.departements}`);

  const fileSize = fs.statSync(outputPath).size;
  console.log(`\n📄 Written to: ${outputPath}`);
  console.log(`📊 Size: ${(fileSize / 1024).toFixed(1)} KB`);
  console.log(`⏱️  Time: ${(elapsed / 1000).toFixed(2)}s`);
}

buildIndex();
