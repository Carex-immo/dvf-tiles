// Supabase Edge Function: Extract DVF tiles from PMTiles archive on-demand
// Route: /{couche}/{z}/{x}/{y}.mvt
// Returns gzip MVT tile data or 204 if not found

import { serve } from "https://deno.land/std@0.208.0/http/server.ts";

const SUPABASE_URL = "https://bqwbazolhtwizafxqzlr.supabase.co";
const BUCKET = "tiles";
const PMTILES_FILE = "dvf.pmtiles";

// Valid layers and zoom ranges
const LAYER_RANGES: Record<string, [number, number]> = {
  mutations: [4, 14],
  communes: [6, 10],
  departements: [4, 6],
};

// Cache for PMTiles metadata and tile index
let pmtilesMetadata: {
  minZoom: number;
  maxZoom: number;
  archivedTiles: number;
} | null = null;

// deno-lint-ignore no-explicit-any
let cachedTileIndex: any = null;

/**
 * Fetch and parse PMTiles metadata from the index.json file
 */
async function loadPMTilesMetadata() {
  if (pmtilesMetadata !== null) {
    return pmtilesMetadata;
  }

  try {
    const indexUrl = `${SUPABASE_URL}/storage/v1/object/public/${BUCKET}/tiles_index.json`;
    const response = await fetch(indexUrl);

    if (!response.ok) {
      throw new Error(`Failed to fetch index.json: ${response.status}`);
    }

    const indexData = await response.json();
    pmtilesMetadata = {
      minZoom: indexData.metadata.headerInfo.minZoom,
      maxZoom: indexData.metadata.headerInfo.maxZoom,
      archivedTiles: indexData.metadata.headerInfo.numAddressedTiles,
    };

    return pmtilesMetadata;
  } catch (error) {
    console.error("Error loading PMTiles metadata:", error);
    throw error;
  }
}

/**
 * Load and cache the tile index from tiles_index.json
 */
// deno-lint-ignore no-explicit-any
async function loadTileIndex(): Promise<any> {
  if (cachedTileIndex !== null) {
    return cachedTileIndex;
  }

  try {
    const indexUrl = `${SUPABASE_URL}/storage/v1/object/public/${BUCKET}/tiles_index.json`;
    const response = await fetch(indexUrl);

    if (!response.ok) {
      throw new Error(`Failed to fetch tile index: ${response.status}`);
    }

    const indexData = await response.json();
    cachedTileIndex = indexData.tiles;

    return cachedTileIndex;
  } catch (error) {
    console.error("Error loading tile index:", error);
    throw error;
  }
}

/**
 * Get tile metadata (offset and length) from the tile index
 */
// deno-lint-ignore no-explicit-any
async function getTileMetadata(z: number, x: number, y: number): Promise<any> {
  const index = await loadTileIndex();

  // Navigate: tiles[z][x][y]
  if (!index[z] || !index[z][x] || !index[z][x][y]) {
    return null; // Tile not in index
  }

  return index[z][x][y]; // Returns {offset, length}
}

/**
 * Fetch tile data from PMTiles archive via HTTP Range request
 */
async function fetchTileBytes(offset: number, length: number): Promise<Uint8Array | null> {
  try {
    const pmtilesUrl = `${SUPABASE_URL}/storage/v1/object/public/${BUCKET}/${PMTILES_FILE}`;
    const end = offset + length - 1;

    const response = await fetch(pmtilesUrl, {
      headers: {
        Range: `bytes=${offset}-${end}`,
      },
    });

    if (!response.ok) {
      console.error(`Failed to fetch bytes ${offset}-${end}: ${response.status}`);
      return null;
    }

    return new Uint8Array(await response.arrayBuffer());
  } catch (error) {
    console.error(`Error fetching tile bytes:`, error);
    return null;
  }
}

/**
 * Fetch a tile from the PMTiles archive using the pre-computed tile index
 * and HTTP Range requests for efficient on-demand extraction
 */
async function fetchTile(
  layer: string,
  z: number,
  x: number,
  y: number
): Promise<Uint8Array | null> {
  try {
    // Validate zoom range for layer
    const [minZ, maxZ] = LAYER_RANGES[layer];
    if (z < minZ || z > maxZ) {
      return null; // Out of range for this layer
    }

    // Get tile metadata from index
    const metadata = await getTileMetadata(z, x, y);
    if (!metadata) {
      return null; // Tile not in archive
    }

    // Fetch tile data via Range request
    const tileBytes = await fetchTileBytes(metadata.offset, metadata.length);
    if (!tileBytes) {
      return null;
    }

    // NOTE: Tile bytes are already gzip-compressed in the archive
    // Return as-is with Content-Encoding: gzip header in the response handler
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

  // Check if coordinates are valid for zoom level
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

  // Attempt to fetch tile
  try {
    const tileData = await fetchTile(layer, z, x, y);

    if (!tileData) {
      // Tile does not exist
      return new Response(null, {
        status: 204,
        headers: {
          "Cache-Control": "public, immutable, max-age=31536000",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }

    // Return tile data as gzipped MVT
    // deno-lint-ignore no-explicit-any
    return new Response(tileData as any, {
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
