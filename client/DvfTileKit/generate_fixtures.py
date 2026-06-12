#!/usr/bin/env python3
"""
Génère les fixtures de parité du décodeur Swift depuis l'archive PMTiles.

Pour chaque tuile témoin : {nom}.mvt (MVT décompressé, tel que reçu par l'app
après décompression URLSession) + {nom}.expected.json (golden produit par
mapbox_vector_tile, la référence de simulate_ios.py).

Golden, par couche, features triées par `id` (mutations) ou `code` (agrégats) :
- properties : dict brut
- type : "Point" / "Polygon" / "MultiPolygon"
- coords : [x, y] tuile (y vers le bas, y_coord_down=True) pour les points
- rings / vertices : nombre d'anneaux et de sommets (sans le sommet de
  fermeture GeoJSON) pour les polygones — invariants de décodage qui ne
  dépendent pas de l'assemblage extérieur/trous de la lib.

Usage : source .venv/bin/activate && python3 client/DvfTileKit/generate_fixtures.py build/dvf.pmtiles
"""
import gzip
import json
import sys
from pathlib import Path

import mapbox_vector_tile
from pmtiles.reader import Reader, MmapSource

TILES = [
    ("mutations_z14_lyon", 14, 8411, 5844),
    ("mutations_z13_lyon", 13, 4205, 2922),
    ("communes_z8_lyon", 8, 131, 91),
    ("departements_z5", 5, 16, 11),
]


def rings_of(geometry):
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    if geometry["type"] == "MultiPolygon":
        return [ring for poly in geometry["coordinates"] for ring in poly]
    raise ValueError(f"géométrie inattendue : {geometry['type']}")


def main():
    pmtiles_path = sys.argv[1] if len(sys.argv) > 1 else "build/dvf.pmtiles"
    out_dir = Path(__file__).parent / "Tests" / "DvfTileKitTests" / "Fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    reader = Reader(MmapSource(open(pmtiles_path, "rb")))

    for name, z, x, y in TILES:
        data = reader.get(z, x, y)
        assert data, f"tuile absente : {z}/{x}/{y}"
        raw = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        (out_dir / f"{name}.mvt").write_bytes(raw)

        decoded = mapbox_vector_tile.decode(raw, default_options={"y_coord_down": True})
        golden = {}
        for lname, layer in decoded.items():
            feats = []
            for f in layer["features"]:
                g = f["geometry"]
                entry = {"properties": f["properties"], "type": g["type"]}
                if g["type"] == "Point":
                    entry["coords"] = list(g["coordinates"])
                elif g["type"] == "MultiPoint":
                    # MultiPoint avec un seul point : on stocke les coords du premier
                    entry["type"] = "Point"
                    entry["coords"] = list(g["coordinates"][0])
                else:
                    rings = rings_of(g)
                    entry["rings"] = len(rings)
                    entry["vertices"] = sum(len(r) - 1 for r in rings)
                feats.append(entry)
            key = "id" if lname == "mutations" else "code"
            feats.sort(key=lambda e: e["properties"][key])
            golden[lname] = feats
        (out_dir / f"{name}.expected.json").write_text(
            json.dumps(golden, ensure_ascii=False, sort_keys=True))
        print(f"{name}: {len(raw)} octets, couches "
              + ", ".join(f"{k}={len(v)}" for k, v in golden.items()))

    print("Fixtures écrites dans", out_dir)


if __name__ == "__main__":
    main()
