#!/usr/bin/env python3
"""Proxy Python du chemin iOS : point GPS -> IRIS -> mutations.

Côté iOS, la résolution GPS->IRIS se fait par décodage MVT de la couche `iris`
puis point-in-polygon ; ici on valide la même logique sur iris_layer.geojson.
"""
import argparse
import json
import os

from shapely.geometry import shape, Point


def resolve_iris_at(layer_geojson, lon, lat):
    """Retourne le code_iris contenant (lon, lat), ou None."""
    pt = Point(lon, lat)
    fc = json.load(open(layer_geojson))
    for ft in fc["features"]:
        if shape(ft["geometry"]).contains(pt):
            return ft["properties"]["code_iris"]
    return None


def mutations_at(layer_geojson, iris_dir, lon, lat):
    """Résout l'IRIS puis charge ses mutations depuis iris/{code}.json."""
    code = resolve_iris_at(layer_geojson, lon, lat)
    if code is None:
        return None, []
    path = os.path.join(iris_dir, f"{code}.json")
    if not os.path.exists(path):
        return code, []
    return code, json.load(open(path))["mutations"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", default="build/iris_layer.geojson")
    ap.add_argument("--iris-dir", default="build/iris")
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--lat", type=float, required=True)
    args = ap.parse_args()
    code, muts = mutations_at(args.layer, args.iris_dir, args.lon, args.lat)
    print(f"IRIS = {code} | {len(muts)} mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
