#!/usr/bin/env python3
"""Détecte la dernière édition CONTOURS-IRIS publiée sur la Géoplateforme.

Parcourt le flux Atom *paginé* du service de téléchargement, filtre les éditions
au format voulu (défaut : GPKG WGS84G France entière), retourne la plus récente
avec son URL de téléchargement .7z et sa taille. Sert aussi à savoir si une
édition plus récente qu'une version épinglée est disponible (code retour 10).

Usage :
  python3 pipeline/iris_latest.py
  python3 pipeline/iris_latest.py --current CONTOURS-IRIS_3-0__GPKG_WGS84G_FRA_2026-01-01
"""
import argparse
import re
import sys
import urllib.request

RESOURCE = "https://data.geopf.fr/telechargement/resource/CONTOURS-IRIS"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "carex-iris/1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def list_editions(pattern):
    """Toutes les éditions (titres) matchant `pattern`, sur toutes les pages."""
    rx = re.compile(pattern)
    seen, editions = set(), []
    for page in range(1, 30):
        try:
            xml = _get(f"{RESOURCE}?page={page}")
        except Exception:
            break
        titles = re.findall(r"<title[^>]*>(CONTOURS-IRIS_[^<]+)</title>", xml)
        new = [t for t in titles if t not in seen]
        if not new:                      # plus rien de nouveau -> fin de pagination
            break
        for t in new:
            seen.add(t)
            if rx.search(t):
                editions.append(t)
    return editions


def _date(ed):
    m = re.search(r"_(\d{4}-\d{2}-\d{2})$", ed)
    return m.group(1) if m else ""


def latest(pattern):
    eds = list_editions(pattern)
    return max(eds, key=_date) if eds else None


def resolve_download(edition):
    """(url .7z, taille en octets) depuis le flux de l'édition."""
    xml = _get(f"{RESOURCE}/{edition}")
    for tag in re.findall(r"<link\b[^>]*>", xml):
        if "x-7z-compressed" in tag:
            href = re.search(r'href="([^"]+)"', tag)
            length = re.search(r'gpf_dl:length="(\d+)"', tag)
            return (href.group(1) if href else None,
                    int(length.group(1)) if length else None)
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default=r"GPKG_WGS84G_FRA",
                    help="motif de filtrage de l'édition (format_CRS_territoire)")
    ap.add_argument("--current", default=None,
                    help="édition épinglée, pour comparaison")
    args = ap.parse_args()
    ed = latest(args.pattern)
    if not ed:
        print("Aucune édition pour le motif", args.pattern, file=sys.stderr)
        return 2
    url, size = resolve_download(ed)
    print("latest :", ed)
    print("url    :", url)
    print("taille :", f"{size / 1e6:.1f} Mo" if size else "?")
    if args.current:
        newer = _date(ed) > _date(args.current)
        print("newer  :", "OUI" if newer else "non", f"(épinglé: {args.current})")
        return 10 if newer else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
