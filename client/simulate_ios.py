#!/usr/bin/env python3
"""
Simulateur du client iOS (MapKit natif) - valide le chemin de consommation :
  bbox ecran -> coordonnees de tuiles -> fetch -> decodage MVT -> filtres -> stats

Ici les tuiles sont lues depuis l'archive PMTiles locale ; en production l'app
lit des tuiles a plat sur Supabase Storage ({version}/tiles/{z}/{x}/{y}.pbf,
contrat carex.immo 2026-06-11) — meme contenu MVT.

Usage: python3 simulate_ios.py build/dvf.pmtiles
"""
import gzip
import math
import sys
import time

import mapbox_vector_tile
from pmtiles.reader import Reader, MmapSource



def bbox_to_tiles(lon_min, lat_min, lon_max, lat_max, z):
    """Equivalent Swift : visibleMapRect -> [(z,x,y)]."""
    def t(lon, lat):
        n = 2 ** z
        x = int((lon + 180) / 360 * n)
        lr = math.radians(lat)
        y = int((1 - math.log(math.tan(lr) + 1 / math.cos(lr)) / math.pi) / 2 * n)
        return x, y
    x0, y1 = t(lon_min, lat_min)
    x1, y0 = t(lon_max, lat_max)
    return [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def decode(data):
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return mapbox_vector_tile.decode(data)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "build/dvf.pmtiles"
    reader = Reader(MmapSource(open(path, "rb")))

    # bbox ~ ecran iPhone centre sur la Presqu'ile de Lyon, zoom carte 14
    bbox = (4.81, 45.745, 4.86, 45.775)
    z = 14
    tiles = bbox_to_tiles(*bbox, z)
    print(f"bbox {bbox} @z{z} -> {len(tiles)} tuiles")

    t0 = time.time()
    feats, total_bytes = [], 0
    for (tz, tx, ty) in tiles:
        data = reader.get(tz, tx, ty)
        if data is None:
            continue
        total_bytes += len(data)
        layers = decode(data)
        for f in layers.get("mutations", {}).get("features", []):
            feats.append(f["properties"])
    dt = (time.time() - t0) * 1000
    print(f"fetch+decode : {dt:.0f} ms, {total_bytes/1024:.0f} Ko compresses, {len(feats)} mutations")

    # Filtres "iOS" en memoire : appartements, 2024-2025, 2000-8000 EUR/m2.
    # annee et pm2 ne sont plus des attributs : derives de date et vf/sb
    # (regle de l'app : pm2 seulement si vf et sb > 0).
    def pm2(p):
        return round(p["vf"] / p["sb"]) if p.get("vf", 0) > 0 and p.get("sb", 0) > 0 else None

    t0 = time.time()
    sel = [p for p in feats
           if p.get("type") == 2 and p.get("date", 0) // 10000 >= 2024
           and pm2(p) is not None and 2000 <= pm2(p) <= 8000]
    dt = (time.time() - t0) * 1000
    print(f"filtre appart/2024+/2000-8000 EUR/m2 : {len(sel)} resultats en {dt:.1f} ms")
    if sel:
        s = sorted(pm2(p) for p in sel)
        print(f"  pm2 median filtre : {s[len(s)//2]} EUR/m2")

    # Adresse (liste iOS) : garantie a z>=13 uniquement (exclue de la passe z4-12)
    with_adr = [p for p in feats if p.get("adr")]
    print(f"adresses presentes (z{z}) : {len(with_adr)}/{len(feats)}")
    if with_adr:
        ex = with_adr[0]
        print(f"  ex: {ex['adr']}" + (f" ({ex['cp']})" if ex.get("cp") else "")
              + f" — com {ex.get('com', '?')}")

    # Couche agregee (z8, vue departementale) : recomposition d'un agregat filtre
    zt = bbox_to_tiles(4.5, 45.6, 5.2, 46.3, 8)
    n_2025_appart = 0
    for (tz, tx, ty) in zt:
        data = reader.get(tz, tx, ty)
        if data is None:
            continue
        for f in decode(data).get("communes", {}).get("features", []):
            n_2025_appart += f["properties"].get("n_2025_t2", 0) or 0
    print(f"agregat z8 recompose (appartements 2025, communes visibles, avec doublons inter-tuiles bruts) : {n_2025_appart}")
    print("NB: en prod dedupliquer par properties.code avant somme.")


if __name__ == "__main__":
    main()
