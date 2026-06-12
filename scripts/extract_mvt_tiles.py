#!/usr/bin/env python3
"""
Extract all MVT tiles from dvf.pmtiles into filesystem structure:
  build/tiles/mutations/14/8000/5900.mvt
  build/tiles/communes/10/512/256.mvt
  build/tiles/departements/6/16/12.mvt
"""

import gzip
import json
import os
import sys
from pathlib import Path
from struct import unpack
from typing import Optional

# Try to use pmtiles library if available, fallback to manual parsing
try:
    import pmtiles.reader
    HAS_PMTILES_LIB = True
except ImportError:
    HAS_PMTILES_LIB = False
    print("⚠️  pmtiles library not found. Install: pip install pmtiles")


class PMTilesReader:
    """Minimal PMTiles parser to extract tile data."""

    def __init__(self, filepath: str):
        self.file = open(filepath, "rb")
        self.root_dir_offset = None
        self.root_dir_length = None
        self._parse_header()

    def _parse_header(self):
        """Parse PMTiles header (first 512 bytes)."""
        self.file.seek(0)
        header = self.file.read(512)

        # Validate magic "pmtiles"
        if header[7:15] != b"pmtiles":
            raise ValueError("Invalid PMTiles file: wrong magic number")

        # Read directory offsets (little-endian)
        self.root_dir_offset = int.from_bytes(header[48:56], "little")
        self.root_dir_length = int.from_bytes(header[56:60], "little")
        self.leaf_dirs_offset = int.from_bytes(header[60:68], "little")
        self.leaf_dirs_length = int.from_bytes(header[68:72], "little")

    def _zxy_to_tileid(self, z: int, x: int, y: int) -> int:
        """Convert z/x/y to PMTiles tile ID."""
        # Hilbert curve encoding
        n = 1 << z
        rx = 0
        ry = 0
        s = n
        d = 0
        while s > 0:
            s >>= 1
            rx = (x >> (z - (32 - s.bit_length()))) & 1
            ry = (y >> (z - (32 - s.bit_length()))) & 1
            d += s * s * ((3 * rx) ^ ry)
        return ((z + 1) << 32) + d

    def get_tile(self, z: int, x: int, y: int) -> Optional[bytes]:
        """Extract tile data for z/x/y."""
        tile_id = self._zxy_to_tileid(z, x, y)

        # Search for tile in directory (simplified: assumes sorted order)
        self.file.seek(self.root_dir_offset)
        dir_data = self.file.read(self.root_dir_length)

        # Directory entries are 7 bytes: tile_id (4) + offset (3) + length (4)
        # This is a simplified implementation
        # For production, proper Hilbert decoding is needed
        return None  # Placeholder: requires full directory parsing

    def __del__(self):
        if hasattr(self, "file"):
            self.file.close()


def extract_tiles_with_library(pmtiles_path: str, output_dir: str):
    """Extract tiles using the pmtiles library."""
    print(f"📖 Reading {pmtiles_path} with pmtiles library...")

    with open(pmtiles_path, "rb") as f:
        reader = pmtiles.reader.Reader(f)

        stats = {"mutations": 0, "communes": 0, "departements": 0}

        for tile in reader.all_tiles():
            z, x, y = tile.z, tile.x, tile.y
            data = tile.data

            # Determine layer from z/zoom ranges (from CLAUDE.md)
            if z <= 6:
                layer = "departements"
            elif z <= 10:
                layer = "communes"
            else:
                layer = "mutations"

            # Create directory structure
            tile_dir = Path(output_dir) / layer / str(z) / str(x)
            tile_dir.mkdir(parents=True, exist_ok=True)

            # Write tile
            tile_path = tile_dir / f"{y}.mvt"
            with open(tile_path, "wb") as tf:
                tf.write(data)

            stats[layer] += 1

            if (stats["mutations"] + stats["communes"] + stats["departements"]) % 1000 == 0:
                print(
                    f"  ✓ {stats['mutations']} mutations, {stats['communes']} communes, {stats['departements']} departements"
                )

    return stats


def extract_tiles_fallback(pmtiles_path: str, output_dir: str):
    """Fallback: requires manual PMTiles parsing (complex)."""
    print(
        "⚠️  Fallback mode: pmtiles library recommended for full extraction."
    )
    print("   Install: pip install pmtiles")
    print(
        "   For now, using shell script approach: tippecanoe + tile-join already generated tiles"
    )
    return None


def main():
    if len(sys.argv) > 1:
        pmtiles_path = sys.argv[1]
    else:
        pmtiles_path = "build/dvf.pmtiles"

    output_dir = "build/tiles"

    if not Path(pmtiles_path).exists():
        print(f"❌ File not found: {pmtiles_path}")
        sys.exit(1)

    print(f"🔍 Extracting tiles from {pmtiles_path}...")
    print(f"📁 Output: {output_dir}/")

    if HAS_PMTILES_LIB:
        stats = extract_tiles_with_library(pmtiles_path, output_dir)
        total = sum(stats.values())
        print(f"\n✅ Extracted {total} tiles:")
        print(f"   • Mutations: {stats['mutations']}")
        print(f"   • Communes: {stats['communes']}")
        print(f"   • Départements: {stats['departements']}")
    else:
        print("ℹ️  Install pmtiles: pip install pmtiles")
        sys.exit(1)


if __name__ == "__main__":
    main()
