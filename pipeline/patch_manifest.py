#!/usr/bin/env python3
"""CAREX — Enrichit le manifest stats existant avec les bits IRIS (additif).

⚠️ stats/manifest.json est généré par un pipeline externe (communes/départements
+ version). Ce script NE mint PAS de version : il charge le manifest live, AJOUTE
millesime_iris + layers.iris_index + compteurs.iris, et préserve tout le reste.
Idempotent. Une seule source de version (le pipeline stats)."""
import argparse
import glob
import json
import os
import urllib.request

IRIS_INDEX_LAYER = "stats/iris_index/{DD}.json"


def load_manifest(url=None, file=None):
    if url:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read())
    with open(file) as f:
        return json.load(f)


def count_iris(iris_index_dir):
    """(n_iris_total, [departements triés]) depuis iris_index/*.json."""
    deps, n = [], 0
    for path in sorted(glob.glob(os.path.join(iris_index_dir, "*.json"))):
        deps.append(os.path.splitext(os.path.basename(path))[0])
        n += len(json.load(open(path)))
    return n, deps


def merge(manifest, millesime, n_iris):
    """Ajoute/maj les 3 clés IRIS ; ne supprime ni n'altère aucune autre clé.
    Idempotent."""
    manifest["millesime_iris"] = millesime
    manifest.setdefault("layers", {})["iris_index"] = IRIS_INDEX_LAYER
    manifest.setdefault("compteurs", {})["iris"] = n_iris
    return manifest


def extra_deps(index_deps, manifest):
    """Départements présents dans l'index mais absents de manifest.departements
    (triés). Le client n'itère que manifest.departements : ces fichiers sont posés
    mais jamais demandés — on les signale (cas réel : 975-978)."""
    listed = set(manifest.get("departements", []))
    return sorted(d for d in index_deps if d not in listed)


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest-url")
    src.add_argument("--manifest-file")
    ap.add_argument("--iris-index-dir", default="build/iris_index")
    ap.add_argument("--millesime", default="2026")
    ap.add_argument("--out", default="build/manifest.json")
    args = ap.parse_args()

    manifest = load_manifest(url=args.manifest_url, file=args.manifest_file)
    n_iris, deps = count_iris(args.iris_index_dir)
    extra = extra_deps(deps, manifest)
    merge(manifest, args.millesime, n_iris)
    with open(args.out, "w") as f:
        json.dump(manifest, f, separators=(",", ":"), ensure_ascii=False)
    print(f"manifest enrichi -> {args.out} : version={manifest.get('version')} "
          f"(préservée), millesime_iris={args.millesime}, iris={n_iris}, "
          f"{len(deps)} dépt iris_index")
    if extra:
        print(f"  ⚠ {len(extra)} dépt dans l'index absents de manifest.departements "
              f"(non demandés par le client) : {', '.join(extra)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
