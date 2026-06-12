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

// Cache for PMTiles metadata
let pmtilesMetadata: {
  minZoom: number;
  maxZoom: number;
  archivedTiles: number;
} | null = null;

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
 * Fetch a tile from the PMTiles archive using HTTP Range requests
 * The pmtiles library is not available in Deno, so we implement basic MVT extraction
 *
 * For the MVP, we can:
 * 1. Return 204 for tiles outside zoom range
 * 2. Return stub/empty MVT for tiles in range (not in this function to be implemented later)
 */
async function fetchTile(
  layer: string,
  z: number,
  x: number,
  y: number
): Promise<Uint8Array | null> {
  try {
    // Load metadata to validate zoom range
    const metadata = await loadPMTilesMetadata();

    // Validate zoom range for layer
    const [minZ, maxZ] = LAYER_RANGES[layer];
    if (z < minZ || z > maxZ) {
      return null; // Out of range for this layer
    }

    // Check against global zoom range
    if (z < metadata.minZoom || z > metadata.maxZoom) {
      return null; // Out of range
    }

    // TODO: Implement actual tile extraction from PMTiles
    // For now, return null to trigger 204
    // A proper implementation would:
    // 1. Fetch PMTiles header (127 bytes)
    // 2. Navigate the directory structure
    // 3. Locate the tile using Hilbert curve ID
    // 4. Fetch tile bytes from tileDataOffset + entry.offset
    // 5. Return gzipped MVT bytes

    return null;
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
