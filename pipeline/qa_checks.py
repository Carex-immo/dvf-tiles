#!/usr/bin/env python3
"""
Controles qualite post-build (spec §6).

Verifie l'archive dvf.pmtiles :
  1. structure : 3 couches aux zooms attendus
  2. comptages : mutations par millesime vs prepare_stats.json (et vs build
     precedent si build/qa_report.json existe, tolerance +/-20 %)
  3. decodage : echantillon de tuiles (Lyon, Bourg-en-Bresse, Paris si present),
     attributs obligatoires, couverture/bornes vf, adresse (adr/cp presents a
     z>=13, absents a z12 — exclus de la passe basse par build_tiles.sh -x),
     taille des tuiles exhaustives (construites sans limite) ; chaque palier
     z12/z13/z14 doit avoir au moins un echantillon decode
  4. exhaustivite : a partir de z13 les tuiles mutations sont construites sans
     limite (-pk -pf, cf. build_tiles.sh) ; chaque tuile z13 d'echantillon doit
     contenir tous les ids (hors buffer) de ses 4 filles z14, et la plus dense
     est comparee au comptage DuckDB de sa bbox dans mutations.geojsonl
Sortie : build/qa_report.json - code retour != 0 si echec bloquant.

Usage: python3 qa_checks.py build
"""
import gzip
import json
import math
import os
import sys

import mapbox_vector_tile
from pmtiles.reader import Reader, MmapSource

EXPECTED_LAYERS = {"mutations": (4, 14), "communes": (6, 10), "departements": (4, 6)}
# vf est omissible (mutation sans valeur fonciere), adr/cp garantis a z>=13
# seulement : controles dedies plus bas, pas dans les attributs requis.
REQUIRED_ATTRS = {"id", "date", "nat", "type", "sb", "st", "np", "nl", "com"}
EXHAUSTIVE_ZOOM = 13   # zoom contractuel : stats exactes garanties a partir de ce zoom
VF_COVERAGE_MIN = 0.90    # part minimale de features portant vf (warning)
ADR_COVERAGE_MIN = 0.80   # part minimale de features portant adr a z>=13 (warning)
TILE_SIZE_WARN_KB = 800   # tuiles z13+ sans limite tippecanoe : alerte de poids
SAMPLES = [("Lyon", 4.835, 45.76), ("Bourg-en-Bresse", 5.228, 46.205),
           ("Paris", 2.347, 48.859), ("Marseille", 5.38, 43.297)]


def tile_xy(lon, lat, z):
    n = 2 ** z
    lr = math.radians(lat)
    return int((lon + 180) / 360 * n), int((1 - math.log(math.tan(lr) + 1 / math.cos(lr)) / math.pi) / 2 * n)


def decode(data):
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    # y_coord_down : coordonnees MVT brutes (origine en haut a gauche), sans
    # inversion d'axe — necessaire pour que le test de buffer [0, extent[ soit exact
    return mapbox_vector_tile.decode(data, default_options={"y_coord_down": True})


def mutations_ids(reader, z, x, y, inner_only=False):
    """Ids de la couche mutations d'une tuile ; inner_only exclut le buffer
    (points hors [0, extent[, dupliques depuis les tuiles voisines)."""
    data = reader.get(z, x, y)
    if data is None:
        return set()
    layer = decode(data).get("mutations", {})
    extent = layer.get("extent", 4096)
    ids = set()
    for f in layer.get("features", []):
        if inner_only:
            geom = f["geometry"]
            pts = geom["coordinates"] if geom["type"] == "MultiPoint" else [geom["coordinates"]]
            if not any(0 <= p[0] < extent and 0 <= p[1] < extent for p in pts):
                continue
        fid = f["properties"].get("id")
        if fid is not None:
            ids.add(fid)
    return ids


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("build", nargs="?", default="build")
    ap.add_argument("--reset-baseline", action="store_true",
                    help="ne pas comparer au build precedent (changement de perimetre, ex: poc -> france)")
    args = ap.parse_args()
    build = args.build
    path = os.path.join(build, "dvf.pmtiles")
    report = {"archive": path, "taille_mo": round(os.path.getsize(path) / 1e6, 1)}
    errors, warnings = [], []

    r = Reader(MmapSource(open(path, "rb")))
    meta = r.metadata()

    # 1. structure
    layers = {l["id"]: (l.get("minzoom"), l.get("maxzoom")) for l in meta["vector_layers"]}
    report["couches"] = layers
    for name, zooms in EXPECTED_LAYERS.items():
        if name not in layers:
            errors.append(f"couche absente : {name}")
        elif tuple(layers[name]) != zooms:
            # bloquant : les plages sont deterministes (-Z/-z explicites dans
            # build_tiles.sh) — un ecart signale une passe omise du tile-join
            errors.append(f"zooms {name} : {layers[name]} != attendu {zooms}")

    # 2. comptages
    stats_path = os.path.join(build, "prepare_stats.json")
    if os.path.exists(stats_path):
        stats = json.load(open(stats_path))
        report["mutations_uniques"] = stats.get("mutations_uniques")
        report["par_annee"] = stats.get("par_annee")
        if stats.get("communes_sans_geometrie", 0) > 0:
            warnings.append(f"{stats['communes_sans_geometrie']} codes commune sans geometrie")
        # remplace l'ancien taux_geoloc_pct (la consolidation parite rejette
        # les mutations sans ancre au lieu de les garder sans coordonnees)
        rejets, total = stats.get("mutations_rejetees_sans_ancre"), stats.get("mutations_uniques")
        if rejets is not None and total:
            pct = 100 * rejets / (rejets + total)
            report["rejets_sans_ancre_pct"] = round(pct, 2)
            if pct > 5:
                warnings.append(f"taux de rejets sans ancre eleve : {pct:.1f} %")
    prev_path = os.path.join(build, "qa_report.json")
    if os.path.exists(prev_path) and not args.reset_baseline:
        prev = json.load(open(prev_path))
        a, b = prev.get("mutations_uniques"), report.get("mutations_uniques")
        if a and b and abs(b - a) / a > 0.20:
            errors.append(f"comptage mutations hors tolerance vs build precedent : {a} -> {b} "
                          f"(si changement de perimetre volontaire : --reset-baseline)")

    # 3. decodage d'echantillons
    decoded = 0
    decoded_par_zoom = {12: 0, EXHAUSTIVE_ZOOM: 0, 14: 0}
    for name, lon, lat in SAMPLES:
        for z in (12, EXHAUSTIVE_ZOOM, 14):
            x, y = tile_xy(lon, lat, z)
            data = r.get(z, x, y)
            if data is None:
                continue
            feats = decode(data).get("mutations", {}).get("features", [])
            if not feats:
                continue
            decoded += 1
            decoded_par_zoom[z] += 1
            # attributs requis sur TOUTES les features (l'ordre dans un MVT
            # n'est pas contractuel, la premiere seule ne prouve rien)
            common = set(feats[0]["properties"])
            for f in feats[1:]:
                common &= set(f["properties"])
            missing = REQUIRED_ATTRS - common
            if missing:
                errors.append(f"attributs manquants ({name} z{z}) : {missing}")
            with_vf = [f for f in feats if "vf" in f["properties"]]
            if not with_vf:
                errors.append(f"vf absent de toutes les features ({name} z{z})")
            elif len(with_vf) < VF_COVERAGE_MIN * len(feats):
                warnings.append(f"couverture vf {len(with_vf)}/{len(feats)} ({name} z{z})")
            bad_vf = [f for f in with_vf if not (1 <= f["properties"]["vf"] < 1e9)]
            if bad_vf:
                warnings.append(f"{len(bad_vf)} vf hors bornes ({name} z{z})")
            # adr/cp : presents a z>=13 (contrat liste iOS), absents a z12
            # (exclus de la passe z4-12 par build_tiles.sh -x adr -x cp) ;
            # la fuite a z12 se detecte a la presence de la CLE (une valeur
            # vide prouverait deja que -x a saute)
            couverture = {}
            for attr in ("adr", "cp"):
                non_vide = sum(1 for f in feats if f["properties"].get(attr))
                fuite = sum(1 for f in feats if attr in f["properties"])
                couverture[attr] = round(non_vide / len(feats), 3)
                if z >= EXHAUSTIVE_ZOOM:
                    if non_vide == 0:
                        errors.append(f"{attr} absent de toutes les features ({name} z{z})")
                    elif non_vide < ADR_COVERAGE_MIN * len(feats):
                        warnings.append(f"couverture {attr} {non_vide}/{len(feats)} ({name} z{z})")
                elif fuite:
                    errors.append(f"{attr} present a z{z} ({name}) : "
                                  f"l'exclusion -x de la passe z4-12 a saute")
            ko_gz = round(len(data) / 1024)
            if z >= EXHAUSTIVE_ZOOM and ko_gz > TILE_SIZE_WARN_KB:
                warnings.append(f"tuile {name} z{z} : {ko_gz} Ko gz (> {TILE_SIZE_WARN_KB})")
            report.setdefault("echantillons", {})[f"{name}_z{z}"] = {
                "tuile": [z, x, y], "features": len(feats),
                "adr_couverture": couverture["adr"],
                "cp_couverture": couverture["cp"],
                "ko_gz": ko_gz}
    if decoded == 0:
        errors.append("aucune tuile d'echantillon decodable")
    else:
        for z, n in decoded_par_zoom.items():
            if n == 0:
                errors.append(f"aucun echantillon decodable a z{z} "
                              f"(controles z{z} non exerces)")

    # 4. exhaustivite au zoom contractuel
    exhaustive = {}
    for name, lon, lat in SAMPLES:
        x, y = tile_xy(lon, lat, EXHAUSTIVE_ZOOM)
        parent = mutations_ids(r, EXHAUSTIVE_ZOOM, x, y)
        if not parent:
            continue
        children = set()
        for dx in (0, 1):
            for dy in (0, 1):
                children |= mutations_ids(r, EXHAUSTIVE_ZOOM + 1,
                                          2 * x + dx, 2 * y + dy, inner_only=True)
        missing = children - parent
        exhaustive[name] = {"tuile": [EXHAUSTIVE_ZOOM, x, y],
                            "ids_tuile": len(parent), "ids_filles": len(children),
                            "manquants_vs_filles": len(missing)}
        if missing:
            errors.append(f"exhaustivite z{EXHAUSTIVE_ZOOM} violee ({name}) : {len(missing)} ids "
                          f"presents a z{EXHAUSTIVE_ZOOM + 1} absents de la tuile z{EXHAUSTIVE_ZOOM}")
    report["exhaustivite"] = exhaustive
    if not exhaustive:
        errors.append(f"aucune tuile z{EXHAUSTIVE_ZOOM} d'echantillon decodable "
                      f"(exhaustivite non verifiable)")

    # ancrage source : la tuile dense doit contenir tous les points de sa bbox
    geojsonl = os.path.join(build, "mutations.geojsonl")
    if exhaustive and os.path.exists(geojsonl):
        try:
            import duckdb
            densest = max(exhaustive, key=lambda k: exhaustive[k]["ids_tuile"])
            z, x, y = exhaustive[densest]["tuile"]
            n = 2 ** z
            src = duckdb.sql(f"""
                SELECT count(*) FROM read_json('{geojsonl.replace("'", "''")}', format='newline_delimited',
                    columns={{'geometry': 'STRUCT(type VARCHAR, coordinates DOUBLE[])'}})
                WHERE floor((geometry.coordinates[1] + 180) / 360 * {n}) = {x}
                  AND floor((1 - ln(tan(radians(geometry.coordinates[2]))
                                    + 1 / cos(radians(geometry.coordinates[2]))) / pi()) / 2 * {n}) = {y}
            """).fetchone()[0]
            tuile = len(mutations_ids(r, z, x, y, inner_only=True))
            exhaustive[densest]["source_bbox"] = src
            exhaustive[densest]["ids_tuile_hors_buffer"] = tuile
            # tolerance : ecarts d'arrondi possibles sur les points exactement
            # en limite de tuile (projection tippecanoe vs floor SQL)
            if tuile < src - max(2, src // 1000):
                errors.append(f"exhaustivite z{z} violee ({densest}) : {tuile} ids hors buffer "
                              f"dans la tuile pour {src} mutations dans sa bbox source")
            elif tuile != src:
                warnings.append(f"exhaustivite z{z} ({densest}) : {tuile} ids hors buffer "
                                f"vs {src} en source (ecart de bord tolere)")
        except ImportError:
            warnings.append("duckdb absent : exhaustivite non ancree a la source")

    report["erreurs"] = errors
    report["avertissements"] = warnings
    # un build en echec ne doit pas devenir la baseline de comptage du suivant
    out_path = prev_path if not errors else os.path.join(build, "qa_report_echec.json")
    json.dump(report, open(out_path, "w"), indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if errors:
        print(f"QA : ECHEC (rapport : {out_path}, baseline conservee)", file=sys.stderr)
        return 1
    print(f"QA : OK ({len(warnings)} avertissement(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
