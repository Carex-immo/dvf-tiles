// Supabase Edge Function: Proxy DVF tiles from Supabase Storage
// Route: /{couche}/{z}/{x}/{y}.mvt
// Validates layer/zoom, returns 204 if invalid, proxies Storage otherwise

import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { zxyToTileId } from "./pmtiles-parser.ts";

const SUPABASE_URL = "https://bqwbazolhtwizafxqzlr.supabase.co";
const BUCKET = "tiles";
const PMTILES_FILE = "dvf.pmtiles";
const ANON_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJxd2Jhem9saHR3aXphZnhxemxyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk4OTU2MzAsImV4cCI6MjA5NTQ3MTYzMH0.EC8z7YAPF-UNZ_KjXN1eIOmRQi31kLRua2qu5X2eKeM";

// Valid layers and zoom ranges
const LAYER_RANGES: Record<string, [number, number]> = {
  mutations: [4, 14],
  communes: [6, 10],
  departements: [4, 6],
};

// In-memory caches for tile index and PMTiles header
let tileIndexCache: Record<string, Record<number, Record<number, Record<number, number>>>> | null = null;
let pmtilesHeaderCache: Uint8Array | null = null;

/**
 * Load and cache the tile index from index.json
 * Returns structure: { layer: { z: { x: { y: offset } } } }
 */
async function loadTileIndex(): Promise<Record<string, Record<number, Record<number, Record<number, number>>>>> {
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
 * Check if a tile exists in the tile index
 * Returns true if the tile is present in the index
 */
async function tileExists(
  layer: string,
  z: number,
  x: number,
  y: number
): Promise<boolean> {
  try {
    const index = await loadTileIndex();

    // Navigate through nested structure: index[layer][z][x][y]
    if (
      !index[layer] ||
      !index[layer][z] ||
      !index[layer][z][x] ||
      typeof index[layer][z][x][y] !== "number"
    ) {
      return false;
    }

    return true;
  } catch (error) {
    console.error(`Error checking tile existence for ${layer}/${z}/${x}/${y}:`, error);
    return false;
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

  // Check if tile exists in the index
  try {
    const exists = await tileExists(layer, z, x, y);

    if (!exists) {
      // Tile does not exist in index
      return new Response(null, {
        status: 204,
        headers: {
          "Cache-Control": "public, immutable, max-age=31536000",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }

    // Tile exists - full byte-range extraction will be implemented in Task 4
    // For now, return 204 to indicate tile exists but full implementation pending
    return new Response(null, {
      status: 204,
      headers: {
        "Cache-Control": "public, immutable, max-age=31536000",
        "Access-Control-Allow-Origin": "*",
        "X-Tile": `${layer}/${z}/${x}/${y}`,
        "X-Debug": "Tile found in index; byte-range extraction in Task 4",
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
