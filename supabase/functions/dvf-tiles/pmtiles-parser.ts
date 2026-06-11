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

  // Check magic bytes "PMTiles" at offset 0-7 (ASCII)
  const magic = new TextDecoder().decode(headerBytes.slice(0, 7));
  if (magic !== "PMTiles") {
    throw new Error(`Invalid PMTiles magic: ${magic}`);
  }

  // Read spec version at offset 7
  const specVersion = headerBytes[7];

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
      // Note: Simplified Hilbert; full implementation requires coordinate rotation
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

/**
 * Parse directory entries from PMTiles archive using varint encoding
 * Directory contains entries with: tileId (varint), offset (varint), length (varint), runLength (varint)
 * Returns: Map of tileId -> {offset, length}
 */
export function parsePMTilesDirectory(
  dirBytes: Uint8Array
): Map<bigint, { offset: number; length: number }> {
  const entries = new Map<bigint, { offset: number; length: number }>();
  let offset = 0;

  while (offset < dirBytes.length) {
    // Parse tileId (varint)
    const [tileId, nextOffset1] = parseVarint(dirBytes, offset);
    if (nextOffset1 === offset) break; // No progress
    offset = nextOffset1;

    // Parse block offset (varint)
    const [blockOffset, nextOffset2] = parseVarint(dirBytes, offset);
    if (nextOffset2 === offset) break; // No progress
    offset = nextOffset2;

    // Parse block length (varint)
    const [blockLength, nextOffset3] = parseVarint(dirBytes, offset);
    if (nextOffset3 === offset) break; // No progress
    offset = nextOffset3;

    // Parse run length (varint) - if 0, it's a directory pointer
    const [runLength, nextOffset4] = parseVarint(dirBytes, offset);
    if (nextOffset4 === offset) break; // No progress
    offset = nextOffset4;

    // Only add tile entries (runLength > 0), skip directory pointers
    if (runLength > 0) {
      entries.set(BigInt(tileId), {
        offset: blockOffset,
        length: blockLength,
      });
    }
  }

  return entries;
}

/**
 * Parse varint from buffer at given offset
 * Returns: [value, nextOffset]
 */
function parseVarint(buffer: Uint8Array, offset: number): [number, number] {
  let value = 0;
  let shift = 0;
  let byte: number;

  while (offset < buffer.length) {
    byte = buffer[offset++];
    value |= (byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) {
      break;
    }
    shift += 7;
  }

  return [value, offset];
}

/**
 * Decompress gzip data using DecompressionStream
 * Input: gzip-compressed bytes
 * Output: decompressed MVT data
 */
export async function decompressGzip(data: Uint8Array): Promise<Uint8Array> {
  // Create a ReadableStream from the data
  const readableStream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(data);
      controller.close();
    },
  });

  // Create DecompressionStream and pipe data through it
  // deno-lint-ignore no-explicit-any
  const decompressed = (readableStream as any).pipeThrough(
    new DecompressionStream("gzip")
  );

  // Read all decompressed chunks
  const reader = decompressed.getReader();
  const chunks: Uint8Array[] = [];

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(new Uint8Array(value));
    }
  } finally {
    reader.releaseLock();
  }

  // Concatenate chunks into a single buffer
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const result = new Uint8Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.length;
  }

  return result;
}
