// Supabase Edge Function: Proxy DVF tiles from Supabase Storage
// Route: /{couche}/{z}/{x}/{y}.mvt
// Validates layer/zoom, returns 204 if invalid, proxies Storage otherwise

import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import {
  zxyToTileId,
  parsePMTilesDirectory,
  parsePMTilesHeader,
  decompressGzip,
} from "./pmtiles-parser.ts";

const SUPABASE_URL = "https://bqwbazolhtwizafxqzlr.supabase.co";
const BUCKET = "tiles";
const PMTILES_FILE = "dvf.pmtiles";

// Valid layers and zoom ranges
const LAYER_RANGES: Record<string, [number, number]> = {
  mutations: [4, 14],
  communes: [6, 10],
  departements: [4, 6],
};

// In-memory caches for tile index, PMTiles header, and tile directory
// deno-lint-ignore no-explicit-any
let tileIndexCache: any = null;
let pmtilesHeaderCache: Uint8Array | null = null;
let tileDirectoryCache: Map<bigint, { offset: number; length: number }> | null = null;

/**
 * Load and cache the tile index from index.json
 * Returns structure: { layer: { z: { x: { y: { present: boolean } } } } }
 */
async function loadTileIndex() {
  // Return cached index if available
  if (tileIndexCache !== null) {
    return tileIndexCache;
  }

  try {
    const indexUrl = `${SUPABASE_URL}/storage/v1/object/public/${BUCKET}/index.json`;
    const response = await fetch(indexUrl);

    if (!response.ok) {
      throw new Error(`Failed to fetch index.json: ${response.status}`);
    }

    const indexData = await response.json();
    tileIndexCache = indexData;
    return indexData;
  } catch (error) {
    console.error("Error loading tile index:", error);
    throw error;
  }
}

/**
 * Get PMTiles header by fetching first 512 bytes
 * Uses HTTP Range header to minimize data transfer
 */
async function getPMTilesHeader(): Promise<Uint8Array> {
  // Return cached header if available
  if (pmtilesHeaderCache !== null) {
    return pmtilesHeaderCache;
  }

  try {
    const pmtilesUrl = `${SUPABASE_URL}/storage/v1/object/public/${BUCKET}/${PMTILES_FILE}`;
    const response = await fetch(pmtilesUrl, {
      headers: {
        Range: "bytes=0-511", // First 512 bytes contain the header
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch PMTiles header: ${response.status}`);
    }

    const buffer = await response.arrayBuffer();
    pmtilesHeaderCache = new Uint8Array(buffer);
    return pmtilesHeaderCache;
  } catch (error) {
    console.error("Error loading PMTiles header:", error);
    throw error;
  }
}

/**
 * Load and cache the PMTiles directory (root directory entries)
 * Uses HTTP Range request to fetch only the directory section
 */
async function loadTileDirectory(): Promise<Map<bigint, { offset: number; length: number }>> {
  // Return cached directory if available
  if (tileDirectoryCache !== null) {
    return tileDirectoryCache;
  }

  try {
    // Get header to find directory location
    const header = parsePMTilesHeader(await getPMTilesHeader());

    // Fetch root directory using Range request
    const pmtilesUrl = `${SUPABASE_URL}/storage/v1/object/public/${BUCKET}/${PMTILES_FILE}`;
    const dirStart = header.rootDirOffset;
    const dirEnd = header.rootDirOffset + header.rootDirLength - 1;

    const response = await fetch(pmtilesUrl, {
      headers: {
        Range: `bytes=${dirStart}-${dirEnd}`,
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch PMTiles directory: ${response.status}`);
    }

    const buffer = await response.arrayBuffer();
    const dirBytes = new Uint8Array(buffer);

    // Check if directory is gzip-compressed
    if (dirBytes[0] === 0x1f && dirBytes[1] === 0x8b) {
      // Directory is gzip-compressed, decompress it
      const decompressed = await decompressGzip(dirBytes);
      tileDirectoryCache = parsePMTilesDirectory(decompressed);
    } else {
      // Directory is not compressed
      tileDirectoryCache = parsePMTilesDirectory(dirBytes);
    }

    return tileDirectoryCache;
  } catch (error) {
    console.error("Error loading PMTiles directory:", error);
    throw error;
  }
}

/**
 * Fetch actual tile data from PMTiles archive via byte-range requests
 * Returns Uint8Array if tile exists, null if not found or error
 */
async function fetchTile(
  layer: string,
  z: number,
  x: number,
  y: number
): Promise<Uint8Array | null> {
  try {
    // 1. Check if tile exists in index
    const index = await loadTileIndex();

    if (
      !index.index ||
      !index.index[layer] ||
      !index.index[layer][z] ||
      !index.index[layer][z][x] ||
      !index.index[layer][z][x][y]
    ) {
      return null;
    }

    // 2. Convert z/x/y to tile ID using Hilbert curve
    const tileId = zxyToTileId(z, x, y);

    // 3. Load directory and find tile offset/length
    const directory = await loadTileDirectory();
    const tileEntry = directory.get(tileId);

    if (!tileEntry) {
      console.warn(`Tile ${layer}/${z}/${x}/${y} (id=${tileId}) not found in directory`);
      return null;
    }

    // 4. Fetch tile bytes using Range request
    const pmtilesUrl = `${SUPABASE_URL}/storage/v1/object/public/${BUCKET}/${PMTILES_FILE}`;
    const tileStart = tileEntry.offset;
    const tileEnd = tileEntry.offset + tileEntry.length - 1;

    const response = await fetch(pmtilesUrl, {
      headers: {
        Range: `bytes=${tileStart}-${tileEnd}`,
      },
    });

    if (!response.ok) {
      console.error(`Failed to fetch tile data: ${response.status}`);
      return null;
    }

    const buffer = await response.arrayBuffer();
    const tileBytes = new Uint8Array(buffer);

    // 5. Decompress if gzip (check magic bytes)
    if (tileBytes.length >= 2 && tileBytes[0] === 0x1f && tileBytes[1] === 0x8b) {
      try {
        const decompressed = await decompressGzip(tileBytes);
        return decompressed;
      } catch (error) {
        console.error(`Failed to decompress tile ${layer}/${z}/${x}/${y}:`, error);
        // Return raw bytes if decompression fails
        return tileBytes;
      }
    }

    return tileBytes;
  } catch (error) {
    console.error(`Error fetching tile ${layer}/${z}/${x}/${y}:`, error);
    return null;
  }
}

serve(async (req: Request) => {
  // CORS
  if (req.method === "OPTIONS") {
    return new Response(null, {
      status: 200,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
      },
    });
  }

  if (req.method !== "GET") {
    return new Response(null, { status: 405 });
  }

  // Parse URL: /{layer}/{z}/{x}/{y}.mvt
  const url = new URL(req.url);
  const pathParts = url.pathname
    .split("/")
    .filter((p) => p && !["functions", "v1", "dvf-tiles"].includes(p));

  if (pathParts.length < 4) {
    return new Response(
      JSON.stringify({
        error: "Invalid path",
        expected: "/{layer}/{z}/{x}/{y}.mvt",
        example: "/mutations/14/8000/5900.mvt",
      }),
      {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }
    );
  }

  const layer = pathParts[0];
  const z = parseInt(pathParts[1], 10);
  const x = parseInt(pathParts[2], 10);
  const yWithExt = pathParts[3];
  const y = parseInt(yWithExt.replace(".mvt", ""), 10);

  // Validate inputs
  if (!(layer in LAYER_RANGES)) {
    return new Response(null, {
      status: 404,
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  }

  if (isNaN(z) || isNaN(x) || isNaN(y)) {
    return new Response(
      JSON.stringify({ error: "Invalid coordinates" }),
      {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }
    );
  }

  const [minZ, maxZ] = LAYER_RANGES[layer];
  const maxCoord = 1 << z;

  // Check if coordinates are valid
  if (z < minZ || z > maxZ || x < 0 || x >= maxCoord || y < 0 || y >= maxCoord) {
    // Tile is outside valid zoom range or coordinate bounds
    return new Response(null, {
      status: 204,
      headers: {
        "Cache-Control": "public, immutable, max-age=31536000",
        "Access-Control-Allow-Origin": "*",
      },
    });
  }

  // Fetch and extract tile data
  try {
    const tileData = await fetchTile(layer, z, x, y);

    if (!tileData) {
      // Tile does not exist or could not be retrieved
      return new Response(null, {
        status: 204,
        headers: {
          "Cache-Control": "public, immutable, max-age=31536000",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }

    // Tile found and extracted - return as MVT (gzip encoded)
    // Convert Uint8Array to a format that Response accepts
    const responseBody = tileData.length > 0 ? tileData : new Uint8Array(0);
    // deno-lint-ignore no-explicit-any
    return new Response(responseBody as any, {
      status: 200,
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Encoding": "gzip",
        "Cache-Control": "public, immutable, max-age=31536000",
        "Access-Control-Allow-Origin": "*",
      },
    });
  } catch (error) {
    console.error(`Error processing ${layer}/${z}/${x}/${y}:`, error);
    return new Response(null, {
      status: 500,
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  }
});
