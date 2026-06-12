#!/usr/bin/env node
/**
 * Build a complete tile enumeration index from dvf.pmtiles
 * Traverses the PMTiles v3 directory structure to enumerate all ~234,000 tiles
 * and record their z/x/y coordinates and byte offsets in the archive.
 */

import fs from "fs";
import zlib from "zlib";
import { bytesToHeader, tileIdToZxy } from "pmtiles";

const pmtilesPath = process.argv[2] || "./build/dvf.pmtiles";
const outputPath = process.argv[3] || "./build/tiles_index.json";

/**
 * Read a varint from buffer at offset
 * Returns [value, newOffset]
 */
function readVarint(buffer, offset) {
  let value = 0;
  let shift = 0;
  let i = offset;

  while (i < buffer.length) {
    const byte = buffer[i];
    value |= ((byte & 0x7f) << shift);
    i++;
    if ((byte & 0x80) === 0) break;
    shift += 7;
  }

  return [value, i];
}

/**
 * Decompress gzip data synchronously
 */
function gunzipSync(data) {
  return zlib.gunzipSync(data);
}

/**
 * Parse a directory buffer and extract tile entries
 * Returns array of { tileId, offset, length, runLength }
 *
 * Structure (after decompression if needed):
 * 1. numEntries (varint)
 * 2. Delta-encoded tileIds (numEntries varints)
 * 3. runLengths (numEntries varints)
 * 4. lengths (numEntries varints)
 * 5. offsets (numEntries varints, with delta encoding logic)
 */
function parseDirectory(buffer) {
  let offset = 0;

  // Read number of entries
  const [numEntries, nextOffset] = readVarint(buffer, offset);
  offset = nextOffset;

  if (numEntries === 0) {
    return [];
  }

  const entries = [];
  const tileIds = [];
  const runLengths = [];
  const lengths = [];
  const offsets = [];

  // 1. Read delta-encoded tile IDs
  let prevTileId = 0;
  for (let i = 0; i < numEntries; i++) {
    const [delta, nextOffset] = readVarint(buffer, offset);
    offset = nextOffset;
    const tileId = prevTileId + delta;
    tileIds.push(tileId);
    prevTileId = tileId;
  }

  // 2. Read run lengths
  for (let i = 0; i < numEntries; i++) {
    const [value, nextOffset] = readVarint(buffer, offset);
    offset = nextOffset;
    runLengths.push(value);
  }

  // 3. Read lengths
  for (let i = 0; i < numEntries; i++) {
    const [value, nextOffset] = readVarint(buffer, offset);
    offset = nextOffset;
    lengths.push(value);
  }

  // 4. Read offsets with delta encoding logic
  // If value == 0 and i > 0: offset = previous_offset + previous_length
  // Otherwise: offset = value - 1
  for (let i = 0; i < numEntries; i++) {
    const [value, nextOffset] = readVarint(buffer, offset);
    offset = nextOffset;

    if (value === 0 && i > 0) {
      // Delta-encoded: use previous offset + previous length
      offsets.push(offsets[i - 1] + lengths[i - 1]);
    } else {
      // Explicit offset (minus 1)
      offsets.push(value - 1);
    }
  }

  // Build entry objects
  for (let i = 0; i < numEntries; i++) {
    entries.push({
      tileId: tileIds[i],
      offset: offsets[i],
      length: lengths[i],
      runLength: runLengths[i],
    });
  }

  return entries;
}

/**
 * Recursively traverse directory structure and collect all tile entries
 */
function traverseDirectories(
  fileBuffer,
  header,
  dirOffset,
  dirLength,
  isLeaf = false
) {
  const dirBuffer = fileBuffer.slice(dirOffset, dirOffset + dirLength);

  let decompressed = dirBuffer;
  if (header.internalCompression === 2) {
    // Gzip compression
    try {
      decompressed = gunzipSync(dirBuffer);
    } catch (e) {
      console.error(`Failed to decompress directory at offset ${dirOffset}:`, e.message);
      return [];
    }
  }

  const entries = parseDirectory(decompressed);
  const tiles = [];

  for (const entry of entries) {
    if (entry.runLength > 0) {
      // Regular tile data
      const [z, x, y] = tileIdToZxy(entry.tileId);
      tiles.push({
        z,
        x,
        y,
        tileId: entry.tileId,
        offset: header.tileDataOffset + entry.offset,
        length: entry.length,
      });
    } else if (entry.runLength === 0) {
      // Leaf directory pointer
      const leafDirStart = header.leafDirectoryOffset + entry.offset;
      const leafDirLength = entry.length;
      const leafTiles = traverseDirectories(
        fileBuffer,
        header,
        leafDirStart,
        leafDirLength,
        true
      );
      tiles.push(...leafTiles);
    }
  }

  return tiles;
}

async function buildIndex() {
  if (!fs.existsSync(pmtilesPath)) {
    console.error(`❌ File not found: ${pmtilesPath}`);
    process.exit(1);
  }

  console.log(`📖 Reading ${pmtilesPath}...`);
  const fileBuffer = fs.readFileSync(pmtilesPath);
  const fileSize = fileBuffer.length;

  // Parse header
  const headerAB = fileBuffer.buffer.slice(
    fileBuffer.byteOffset,
    fileBuffer.byteOffset + 127
  );
  const header = bytesToHeader(headerAB);

  console.log(`\n📊 PMTiles Archive Info:`);
  console.log(`   Spec version: ${header.specVersion}`);
  console.log(`   File size: ${(fileSize / 1024 / 1024).toFixed(1)} MB`);
  console.log(`   Min zoom: ${header.minZoom}, Max zoom: ${header.maxZoom}`);
  console.log(`   Addressed tiles: ${header.numAddressedTiles}`);
  console.log(`   Root directory offset: ${header.rootDirectoryOffset}, length: ${header.rootDirectoryLength}`);
  console.log(`   Leaf directory offset: ${header.leafDirectoryOffset}`);
  console.log(`   Tile data offset: ${header.tileDataOffset}`);
  console.log(`   Internal compression: ${header.internalCompression === 2 ? "gzip" : "none"}`);

  console.log(`\n🔍 Traversing directory structure...`);
  const tiles = traverseDirectories(
    fileBuffer,
    header,
    header.rootDirectoryOffset,
    header.rootDirectoryLength,
    false
  );

  console.log(`\n📊 Collected ${tiles.length} tiles`);

  // Organize tiles by zoom level for efficient lookup
  // Each tile can belong to multiple layers (z4-6: departments + communes + mutations, etc.)
  const index = {};

  for (const tile of tiles) {
    if (!index[tile.z]) {
      index[tile.z] = {};
    }
    if (!index[tile.z][tile.x]) {
      index[tile.z][tile.x] = {};
    }

    index[tile.z][tile.x][tile.y] = {
      offset: tile.offset,
      length: tile.length,
    };
  }

  // Count tiles per zoom
  const zoomStats = {};
  for (const [z, xData] of Object.entries(index)) {
    let zoomCount = 0;
    for (const yData of Object.values(xData)) {
      zoomCount += Object.keys(yData).length;
    }
    zoomStats[z] = zoomCount;
  }

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
      layers: {
        description:
          "All tiles are stored in a single PMTiles archive. Layer selection is determined at read time by examining MVT layer content, not by pre-computed indices.",
        departements: "z4-6",
        communes: "z6-10",
        mutations: "z4-14",
      },
    },
    stats: {
      totalTiles: tiles.length,
      byZoom: zoomStats,
    },
    tiles: index,
  };

  fs.writeFileSync(outputPath, JSON.stringify(indexContent, null, 2));

  console.log(`\n✅ Full tile enumeration index created`);
  console.log(`📄 Written to: ${outputPath}`);

  const fileSizeKb = fs.statSync(outputPath).size;
  console.log(`📊 Index size: ${(fileSizeKb / 1024).toFixed(1)} KB`);

  console.log(`\n📈 Tile Summary by Zoom:`);
  const sortedZooms = Object.entries(zoomStats)
    .sort(([z1], [z2]) => parseInt(z1) - parseInt(z2));
  const zoomSummary = sortedZooms
    .map(([z, count]) => `z${z}:${count}`)
    .join(", ");
  console.log(`   ${zoomSummary}`);
  console.log(`\n   Total indexed tiles: ${tiles.length} of ${header.numAddressedTiles}`);
}

buildIndex().catch((e) => {
  console.error("Fatal error:", e.message);
  console.error(e.stack);
  process.exit(1);
});
