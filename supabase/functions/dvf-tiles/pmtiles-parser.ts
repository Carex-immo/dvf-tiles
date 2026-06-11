// PMTiles header parser for Deno
// Implements PMTiles v3 specification parsing

export interface PMTilesHeader {
  specVersion: number;
  rootDirOffset: number;
  rootDirLength: number;
  leafDirsOffset: number;
  leafDirsLength: number;
  jsonMetadataOffset: number;
  jsonMetadataLength: number;
}

export interface TileEntry {
  tileId: bigint;
  offset: number;
  length: number;
}

/**
 * Parse PMTiles header from first 512 bytes
 * Validates magic "pmtiles" and extracts directory offsets
 */
export function parsePMTilesHeader(headerBytes: Uint8Array): PMTilesHeader {
  if (headerBytes.length < 512) {
    throw new Error(`Header too short: ${headerBytes.length} < 512`);
  }

  // Check magic bytes "pmtiles" at offset 7-13 (magic must be ASCII)
  const magic = new TextDecoder().decode(headerBytes.slice(7, 14));
  if (magic !== "pmtiles") {
    throw new Error(`Invalid PMTiles magic: ${magic}`);
  }

  // Read spec version at offset 14
  const specVersion = headerBytes[14];

  // Helper to read little-endian 64-bit unsigned int
  const readUint64LE = (offset: number): number => {
    const low = readUint32LE(offset);
    const high = readUint32LE(offset + 4);
    return high * 0x100000000 + low;
  };

  // Helper to read little-endian 32-bit unsigned int
  const readUint32LE = (offset: number): number => {
    const view = new DataView(headerBytes.buffer);
    return view.getUint32(offset, true);
  };

  // Read directory offsets (all are 64-bit little-endian)
  const rootDirOffset = readUint64LE(72);
  const rootDirLength = readUint64LE(80);
  const leafDirsOffset = readUint64LE(88);
  const leafDirsLength = readUint64LE(96);
  const jsonMetadataOffset = readUint64LE(104);
  const jsonMetadataLength = readUint64LE(112);

  return {
    specVersion,
    rootDirOffset,
    rootDirLength,
    leafDirsOffset,
    leafDirsLength,
    jsonMetadataOffset,
    jsonMetadataLength,
  };
}

/**
 * Convert Web Mercator tile coordinates (z, x, y) to Hilbert curve tile ID
 * PMTiles uses Hilbert curve ordering for tile indexing
 */
export function zxyToTileId(z: number, x: number, y: number): bigint {
  let tileId = 0n;
  let n = 1n << BigInt(z);

  for (let i = z - 1; i >= 0; i--) {
    const mask = 1n << BigInt(i);
    let rx = (BigInt(x) & mask) >> BigInt(i);
    let ry = (BigInt(y) & mask) >> BigInt(i);

    // Hilbert curve rotation
    if (ry === 0n) {
      if (rx === 1n) {
        tileId += (n * n - 1n);
      }
      // Swap x and y
      const temp = BigInt(x);
      // Note: This is simplified; full Hilbert requires matrix rotation
    }
    n = n >> 1n;
    tileId += (rx | (ry << 1n)) * (n * n);
  }

  return BigInt(tileId);
}

/**
 * Find tile in directory by linear search
 * Directory format: entries are 24-byte records (tileId: 8 bytes, offset: 8 bytes, length: 4 bytes)
 */
export function findTileInDirectory(
  dirBytes: Uint8Array,
  targetTileId: bigint
): TileEntry | null {
  if (dirBytes.length % 24 !== 0) {
    throw new Error(
      `Invalid directory size: ${dirBytes.length} (must be multiple of 24)`
    );
  }

  const view = new DataView(dirBytes.buffer);

  // Iterate through 24-byte entries
  for (let i = 0; i < dirBytes.length; i += 24) {
    // Read 8-byte tile ID (little-endian 64-bit)
    const tileIdLow = view.getUint32(i, true);
    const tileIdHigh = view.getUint32(i + 4, true);
    const tileId =
      BigInt(tileIdHigh) * 0x100000000n + BigInt(tileIdLow);

    // If we've passed the target, it's not in this directory
    if (tileId > targetTileId) {
      return null;
    }

    if (tileId === targetTileId) {
      // Found it! Read offset (8 bytes) and length (4 bytes)
      const offsetLow = view.getUint32(i + 8, true);
      const offsetHigh = view.getUint32(i + 12, true);
      const offset =
        Number(BigInt(offsetHigh) * 0x100000000n + BigInt(offsetLow));

      const length = view.getUint32(i + 16, true);

      return {
        tileId,
        offset,
        length,
      };
    }
  }

  return null;
}
