#!/usr/bin/env python3
"""
CAREX - Service de tuiles DVF - Etape de preparation.

Consolide les CSV geo-dvf via le pont de parite carex.immo (pipeline/parity/,
regles verrouillees par les goldens Swift) : 1 feature par mutation ancree par
les coordonnees de la parcelle de sa 1re ligne (jamais de repli ; sans ancre
-> rejetee + comptee). DuckDB ne porte plus de regle metier : il sert a l'aval
(remap COG, agregats annee x type, exports). Sorties :
  - build/mutations_consolidees.jsonl  (intermediaire, 1 ligne par mutation)
  - build/mutations.geojsonl           (points ; terrain nu exclu de la couche)
  - build/communes.geojson             (agregats + centroides cx/cy)
  - build/departements.geojson

Usage: python3 prepare.py --raw data/raw --geo data/geo --out build
Echelle France entiere : ~20 M lignes ; la consolidation Python traite les
fichiers un par un (~3-5 Go de pic par full.csv.gz), prevoir ~8 Go de RAM.
"""
import argparse
import glob
import json
import os
import sys

import duckdb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "parity"))
from extended import consolidate_file_extended  # regles : parity/consolidate.py (verbatim)

# Couche mutations (spec 2026-06-12) : proprietes exportees, dans cet ordre.
# adr/cp sont ensuite exclus de la passe tippecanoe z4-12 (build_tiles.sh -x).
TILE_PROPS = ["id", "date", "nat", "type", "vf", "sb", "st", "np", "nl",
              "com", "adr", "cp"]

# Paris/Lyon/Marseille : DVF code les mutations au niveau ARRONDISSEMENT
# (751xx/6938x/132xx). Le polygone de la commune parente, present dans les
# contours, ne doit ni recuperer leurs mutations via reassign_scissions
# (il n'a jamais de stats propres), ni apparaitre dans la couche communes
# (il masquerait les arrondissements avec un n_tot=0).
PLM_PARENTS = {"75056", "69123", "13055"}


def _point_in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_geom(x, y, geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        if _point_in_ring(x, y, poly[0]) and not any(_point_in_ring(x, y, h) for h in poly[1:]):
            return True
    return False


def _ring_area_centroid(ring):
    """Aire signee (shoelace) et centroide de surface d'un anneau ferme."""
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[i + 1][0], ring[i + 1][1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-14:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return a / 2, cx / (3 * a), cy / (3 * a)


def feature_centroid(geom):
    """Centroide du plus grand anneau exterieur du (Multi)Polygon — point
    representatif pour les cercles proportionnels MapKit (cx/cy du contrat)."""
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    best = None
    for poly in polys:
        area, cx, cy = _ring_area_centroid(poly[0])
        if best is None or abs(area) > best[0]:
            best = (abs(area), cx, cy)
    return (round(best[1], 5), round(best[2], 5)) if best else None


def load_cog_mouvements(geo_dir):
    """Table INSEE v_mvt_commune : mapping code retire -> code actuel.
    On garde le dernier evenement COM -> COM par code, puis on resout les
    chaines (une commune absorbee peut l'avoir ete par une commune elle-meme
    fusionnee ensuite)."""
    path = os.path.join(geo_dir, "cog_mouvements.csv")
    if not os.path.exists(path):
        return {}
    import csv
    latest = {}  # com_av -> (date_eff, com_ap)
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["TYPECOM_AV"] != "COM" or row["TYPECOM_AP"] != "COM":
                continue
            av, ap = row["COM_AV"], row["COM_AP"]
            if av == ap:
                continue
            if av not in latest or row["DATE_EFF"] > latest[av][0]:
                latest[av] = (row["DATE_EFF"], ap)
    mapping = {}
    for av in latest:
        cur, hops = av, 0
        while cur in latest and hops < 8:
            cur = latest[cur][1]
            hops += 1
        mapping[av] = cur
    return mapping


def load_scissions(geo_dir):
    """Table INSEE v_mvt_commune : retablissements de communes (MOD 21,
    COM -> COM). Retourne enfant retabli -> ensemble des communes parentes."""
    path = os.path.join(geo_dir, "cog_mouvements.csv")
    scissions = {}
    if not os.path.exists(path):
        return scissions
    import csv
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row["MOD"] == "21" and row["TYPECOM_AV"] == "COM"
                    and row["TYPECOM_AP"] == "COM" and row["COM_AV"] != row["COM_AP"]):
                scissions.setdefault(row["COM_AP"], set()).add(row["COM_AV"])
    return scissions


def remap_cog(con, geo_dir, qa):
    """geo-dvf conserve le COG d'origine de chaque millesime : les codes des
    communes fusionnees depuis (ex: Pierrefitte-sur-Seine 93059 -> Saint-Denis
    93066 au 01/01/2025) n'existent plus dans les contours actuels. On
    reaffecte ces mutations a la commune actuelle : par localisation des
    points quand il y en a, sinon via la table INSEE des mouvements (les
    mutations des communes fusionnees perdent souvent leur geolocalisation,
    ex: Saint-Pardoux-Corbier 19230 -> Les Trois-Saints 19248)."""
    # codes connus des contours (lecture legere, geometries jetees)
    geo_codes = set()
    for path in sorted(glob.glob(os.path.join(geo_dir, "communes_*.geojson"))):
        for ft in json.load(open(path)).get("features", []):
            c = ft["properties"].get("code")
            if c:
                geo_codes.add(c)
    if not geo_codes:
        return
    missing = [r[0] for r in con.execute(
        "SELECT DISTINCT com FROM mutations WHERE com IS NOT NULL").fetchall()
        if r[0] not in geo_codes]
    if not missing:
        qa["cog_remappage"] = {}
        return
    depts = {r[0]: r[1] for r in con.execute(f"""
        SELECT com, any_value(dep) FROM mutations
        WHERE com IN ({','.join(['?']*len(missing))}) GROUP BY 1""", missing).fetchall()}
    # geometries des departements concernes uniquement (motifs exacts : le
    # joker communes_*71.geojson matcherait communes_971.geojson) ; les
    # parents PLM sont exclus des candidats au vote, comme partout ailleurs
    feats_by_dept = {}
    for dep in set(depts.values()):
        feats = []
        for pat in (f"communes_{dep}.geojson", f"communes_arr{dep}.geojson"):
            for path in sorted(glob.glob(os.path.join(geo_dir, pat))):
                for ft in json.load(open(path)).get("features", []):
                    c = ft["properties"].get("code")
                    if c and c not in PLM_PARENTS:
                        feats.append((c, ft["geometry"]))
        feats_by_dept[dep] = feats
    insee = load_cog_mouvements(geo_dir)
    mapping, mapping_insee, orphelins = {}, {}, []
    for code in missing:
        pts = con.execute(
            "SELECT lon, lat FROM mutations WHERE com = ? AND lon IS NOT NULL LIMIT 7",
            [code]).fetchall()
        votes = {}
        for lon, lat in pts:
            for cand, geom in feats_by_dept.get(depts.get(code), []):
                if point_in_geom(lon, lat, geom):
                    votes[cand] = votes.get(cand, 0) + 1
                    break
        if votes:
            mapping[code] = max(votes, key=votes.get)
        elif insee.get(code) in geo_codes:
            mapping_insee[code] = insee[code]
        else:
            orphelins.append(code)
    mapping.update(mapping_insee)
    if mapping:
        con.executemany("UPDATE mutations SET com = ? WHERE com = ?",
                        [[new, old] for old, new in mapping.items()])
    qa["cog_remappage"] = mapping
    qa["cog_remappage_insee"] = mapping_insee
    if orphelins:
        qa["cog_orphelins"] = orphelins
    print(f"remappage COG : {len(mapping)} codes retires reaffectes "
          f"(dont {len(mapping_insee)} via table INSEE), {len(orphelins)} orphelins")


def reassign_scissions(con, geo_dir, qa):
    """Cas inverse du remappage : communes retablies par scission (ex:
    Chalinargues 15035, retablie au 01/01/2025 depuis Neussargues-en-Pinatelle
    15141). geo-dvf code leurs mutations sous la commune parente : le polygone
    actuel n'a aucune stat. On lui reaffecte les mutations geolocalisees dont
    le point tombe dans son polygone. Deux gardes indispensables : seules les
    communes retablies par scission (MOD 21 de la table INSEE) sont candidates,
    et seules les mutations encore codees sous leur commune parente sont
    capturees — sans elles, toute commune sans vente aspirerait les points
    frontaliers (bruit de geocodage, contours simplifies)."""
    scissions = load_scissions(geo_dir)
    if not scissions:
        qa["scissions_reaffectees"] = {}
        return
    have_stats = {r[0] for r in con.execute(
        "SELECT DISTINCT com FROM mutations").fetchall()}
    reaff = {}
    for path in sorted(glob.glob(os.path.join(geo_dir, "communes_*.geojson"))):
        for ft in json.load(open(path)).get("features", []):
            code = ft["properties"].get("code")
            if (not code or code not in scissions or code in have_stats
                    or code in PLM_PARENTS):
                continue
            parents = sorted(scissions[code])
            geom = ft["geometry"]
            xs, ys = [], []

            def walk(c):
                if isinstance(c[0], (int, float)):
                    xs.append(c[0])
                    ys.append(c[1])
                else:
                    for cc in c:
                        walk(cc)
            walk(geom["coordinates"])
            rows = con.execute(
                "SELECT rowid, lon, lat FROM mutations "
                f"WHERE com IN ({','.join(['?'] * len(parents))}) "
                "AND lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?",
                parents + [min(xs), max(xs), min(ys), max(ys)]).fetchall()
            ids = [str(r[0]) for r in rows if point_in_geom(r[1], r[2], geom)]
            if ids:
                con.execute(f"UPDATE mutations SET com = ? "
                            f"WHERE rowid IN ({','.join(ids)})", [code])
                reaff[code] = len(ids)
    qa["scissions_reaffectees"] = reaff
    if reaff:
        print(f"scissions : {len(reaff)} communes retablies recuperent leurs mutations "
              f"par localisation (ex: {dict(list(reaff.items())[:3])})")


def consolidate_sources(files, out_path, qa):
    """Consolidation parite, fichier par fichier (RAM liberee entre deux) ;
    ecrit l'intermediaire jsonl plat et remplit les compteurs QA."""
    totals = {"rows_read": 0, "malformed_lines": 0, "skipped_rows": 0,
              "rejected_mutations": 0, "embedded_no_coord_rows": 0}
    kept = terrain_nu = 0
    contig = []
    with open(out_path, "w") as f:
        for path in files:
            res = consolidate_file_extended(path)
            for k in totals:
                totals[k] += getattr(res.stats, k)
            if res.stats.contiguity_violated:
                contig.append(os.path.basename(path))
            for m in res.mutations:
                kept += 1
                if m["type"] is None:
                    terrain_nu += 1
                rec = {
                    "id": m["id"],
                    "date": int(m["date"].replace("-", "")),
                    "nat": m["nature"],
                    "type": m["type"],
                    "vf": m["prix"],
                    "sb": m["surfBati"],
                    "st": m["surfTerrain"],
                    "np": m["pieces"],
                    "nl": len(m["biens"]),
                    "com": m["com"], "dep": m["dep"],
                    "adr": m["adr"], "cp": m["cp"],
                    "lon": m["lon"], "lat": m["lat"],
                }
                f.write(json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n")
            print(f"  {os.path.basename(path)} : {len(res.mutations)} mutations, "
                  f"{res.stats.rejected_mutations} rejetees sans ancre, "
                  f"{res.stats.malformed_lines} lignes malformees")
    qa.update({
        "lignes_source": totals["rows_read"],
        "lignes_malformees": totals["malformed_lines"],
        "lignes_ignorees_champs_requis": totals["skipped_rows"],
        "mutations_uniques": kept,
        "mutations_rejetees_sans_ancre": totals["rejected_mutations"],
        "mutations_terrain_nu": terrain_nu,
        "lignes_sans_coord_embarquees": totals["embedded_no_coord_rows"],
    })
    if contig:
        qa["fichiers_contiguite_violee"] = contig
    print(f"mutations consolidees : {kept} (rejets sans ancre : "
          f"{totals['rejected_mutations']} ; terrain nu, hors couche points : {terrain_nu})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--geo", default="data/geo")
    ap.add_argument("--out", default="build")
    ap.add_argument("--pattern", default="*.csv.gz",
                    help="globs separes par virgule, ex: '*_full.csv.gz' ou '*_69.csv.gz,*_01.csv.gz'")
    ap.add_argument("--memory-limit", default=None,
                    help="ex: 6GB - limite memoire DuckDB (deborde sur disque)")
    ap.add_argument("--tmp", default=None, help="repertoire temporaire DuckDB")
    ap.add_argument("--layers-only", action="store_true",
                    help="ne pas relire les CSV : reconstruire uniquement communes/departements "
                         "depuis build/mutations.geojsonl (population points : terrains nus "
                         "et rejets exclus, agregats legerement sous-evalues)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    out_pts = os.path.join(args.out, "mutations.geojsonl")
    consolidated = os.path.join(args.out, "mutations_consolidees.jsonl")

    files = []
    if not args.layers_only:
        files = sorted({f for pat in args.pattern.split(",")
                        for f in glob.glob(os.path.join(args.raw, pat.strip()))})
        if not files:
            print(f"Aucun CSV correspondant a '{args.pattern}' dans {args.raw}", file=sys.stderr)
            return 1
        print(f"{len(files)} fichiers source ({args.pattern})")
    elif not os.path.exists(out_pts):
        print(f"--layers-only : {out_pts} introuvable", file=sys.stderr)
        return 1

    qa = {}
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    if args.memory_limit:
        con.execute(f"SET memory_limit='{args.memory_limit}'")
    if args.tmp:
        con.execute(f"SET temp_directory='{args.tmp}'")

    if args.layers_only:
        # Reconstruction des agregats depuis les points exportes. dep est
        # derive de com (97x -> 3 caracteres, sinon 2 — couvre 2A/2B), comme
        # dans le chemin complet (dep y est realigne sur com apres remap).
        # Les compteurs du build complet sont conserves dans prepare_stats.
        print(f"--layers-only : lecture de {out_pts}")
        prev_stats = os.path.join(args.out, "prepare_stats.json")
        if os.path.exists(prev_stats):
            qa = json.load(open(prev_stats))
        # columns explicite : vf/adr/cp sont omis des features qui ne les
        # portent pas — l'inference sur echantillon leverait un Binder Error
        # si la cle manquait des premieres lignes (cles hors schema ignorees).
        con.execute(f"""
        CREATE TABLE mutations AS
        SELECT properties.id   AS id,  properties.date AS date,
               properties.nat  AS nat, properties.type AS type,
               properties.vf   AS vf,  properties.sb   AS sb,
               properties.com  AS com,
               CASE WHEN properties.com LIKE '97%' THEN substr(properties.com, 1, 3)
                    ELSE substr(properties.com, 1, 2) END AS dep,
               geometry.coordinates[1] AS lon, geometry.coordinates[2] AS lat
        FROM read_json('{out_pts}', format='newline_delimited',
          columns={{'geometry': 'STRUCT(type VARCHAR, coordinates DOUBLE[])',
                    'properties': 'STRUCT(id VARCHAR, date INTEGER, nat INTEGER,
                                          type INTEGER, vf BIGINT, sb INTEGER,
                                          com VARCHAR)'}})
        """)
    else:
        # ---- Consolidation (pont de parite, regles goldens) ---------------
        consolidate_sources(files, consolidated, qa)
        con.execute(f"""
        CREATE TABLE mutations AS
        SELECT * FROM read_json('{consolidated}', format='newline_delimited',
          columns={{'id':'VARCHAR','date':'INTEGER','nat':'INTEGER','type':'INTEGER',
                    'vf':'BIGINT','sb':'INTEGER','st':'INTEGER','np':'INTEGER',
                    'nl':'INTEGER','com':'VARCHAR','dep':'VARCHAR','adr':'VARCHAR',
                    'cp':'VARCHAR','lon':'DOUBLE','lat':'DOUBLE'}})
        """)
        n, nd = con.execute("SELECT count(*), count(DISTINCT id) FROM mutations").fetchone()
        if n != nd:
            print(f"ERREUR : {n - nd} id_mutation en double entre fichiers source "
                  f"(motifs --pattern qui se recouvrent ?)", file=sys.stderr)
            return 1
        qa["par_annee"] = dict(con.execute(
            "SELECT date // 10000, count(*) FROM mutations GROUP BY 1 ORDER BY 1").fetchall())

    # ---- Remappage COG (codes retires -> commune actuelle) ---------------
    remap_cog(con, args.geo, qa)
    # ---- Scissions (communes retablies sans stats -> par localisation) ---
    reassign_scissions(con, args.geo, qa)

    # com fait foi apres remap/scissions : dep est realigne (un remap INSEE
    # peut traverser un departement) — meme derivation qu'en --layers-only.
    con.execute("""
    UPDATE mutations SET dep = CASE WHEN com LIKE '97%' THEN substr(com, 1, 3)
                                    ELSE substr(com, 1, 2) END
    WHERE com IS NOT NULL""")

    # Contrat spec §3 : com jamais omis (DvfTileClient.swift le decode
    # non-optionnel) — echec dur plutot qu'un trou silencieux dans les tuiles.
    sans_com = con.execute(
        "SELECT count(*) FROM mutations WHERE com IS NULL").fetchone()[0]
    if sans_com:
        print(f"ERREUR : {sans_com} mutations sans code commune (com NULL) — "
              f"contrat 'com jamais omis' viole (spec §3)", file=sys.stderr)
        return 1

    # Export GeoJSONL — couche points : terrain nu exclu (contrat), props
    # nulles omises (MVT sans sentinelle), coordonnees deja arrondies round5.
    if not args.layers_only:
        with open(out_pts, "w") as f:
            cur = con.execute(f"SELECT {', '.join(TILE_PROPS)}, lon, lat FROM mutations "
                              "WHERE type IS NOT NULL")
            while True:
                rows = cur.fetchmany(50000)
                if not rows:
                    break
                for r in rows:
                    props = {k: v for k, v in zip(TILE_PROPS, r[:-2]) if v is not None}
                    f.write(json.dumps({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [r[-2], r[-1]]},
                        "properties": props,
                    }, separators=(",", ":"), ensure_ascii=False) + "\n")
        print("->", out_pts, f"{os.path.getsize(out_pts)/1e6:.1f} Mo")

    # ---- Agregats annee x type --------------------------------------------
    # annee et pm2 sont des derives (la couche points ne les porte plus) :
    # annee = date // 10000 ; pm2 = vf/sb si les deux > 0 (regle de l'app).
    con.execute("""
    CREATE VIEW stats_src AS
    SELECT *, date // 10000 AS annee,
           CASE WHEN vf > 0 AND sb > 0 THEN vf * 1.0 / sb END AS pm2
    FROM mutations
    """)

    def agg_stats(key: str):
        """Stats par entite (commune ou departement): retour dict code -> props.
        n_tot/vf_med couvrent toutes les mutations consolidees (terrain nu
        inclus) ; les seaux n_/p_ par type ne portent que les types 1-5."""
        rows = con.execute(f"""
          SELECT {key} AS k, annee, type,
                 count(*)::INT AS n, CAST(median(pm2) AS INT) AS p
          FROM stats_src WHERE type IS NOT NULL GROUP BY 1, 2, 3
        """).fetchall()
        tot = con.execute(f"""
          SELECT {key} AS k, count(*)::INT,
                 CAST(median(pm2) AS INT), CAST(median(vf) AS BIGINT)
          FROM stats_src GROUP BY 1
        """).fetchall()
        props: dict[str, dict] = {}
        for k, annee, typ, n_, p_ in rows:
            if k is None:
                continue
            d = props.setdefault(k, {})
            d[f"n_{annee}_t{typ}"] = n_
            if p_ is not None:
                d[f"p_{annee}_t{typ}"] = p_
        for k, n_tot, pm2_med, vf_med in tot:
            if k is None:
                continue
            d = props.setdefault(k, {})
            d["n_tot"] = n_tot
            if pm2_med is not None:
                d["pm2_med"] = pm2_med
            if vf_med is not None:
                d["vf_med"] = vf_med
        return props

    com_stats = agg_stats("com")
    dep_stats = agg_stats("dep")

    # ---- Jointure aux geometries ----------------------------------------
    def build_layer(pattern: str, code_key, out_name: str, stats: dict,
                    exclude=frozenset()):
        feats, seen = [], set()
        for path in sorted(glob.glob(os.path.join(args.geo, pattern))):
            data = json.load(open(path))
            items = data["features"] if data.get("type") == "FeatureCollection" else [data]
            for ft in items:
                code = code_key(ft)
                if code in seen or code in exclude:
                    continue  # doublon entre fichiers de contours, ou parent PLM
                # les entites sans mutation sont rendues avec n_tot=0
                # (une commune sans vente n'est pas un trou sur la carte)
                st = stats.get(code) or {"n_tot": 0}
                seen.add(code)
                centroid = feature_centroid(ft["geometry"])
                ft["properties"] = {"code": code,
                                    "nom": ft.get("properties", {}).get("nom", ""),
                                    **({"cx": centroid[0], "cy": centroid[1]}
                                       if centroid else {}),
                                    **st}
                feats.append(ft)
        out = os.path.join(args.out, out_name)
        json.dump({"type": "FeatureCollection", "features": feats},
                  open(out, "w"), separators=(",", ":"), ensure_ascii=False)
        print("->", out, f"{len(feats)} entites, {os.path.getsize(out)/1e6:.1f} Mo")
        return seen

    seen_com = build_layer("communes_*.geojson",
                           lambda ft: ft["properties"].get("code"),
                           "communes.geojson", com_stats, exclude=PLM_PARENTS)
    seen_dep = build_layer("dept_*.geojson",
                           lambda ft: ft["properties"].get("code"),
                           "departements.geojson", dep_stats)
    qa["communes"] = len(seen_com)
    qa["departements"] = len(seen_dep)

    # codes commune avec mutations mais sans geometrie
    # (controle : arrondissements PLM manquants, communes fusionnees, COG decale)
    missing = sorted(set(com_stats) - seen_com)
    qa["communes_sans_geometrie"] = len(missing)
    if missing:
        n_miss = sum(com_stats[c].get("n_tot", 0) for c in missing)
        pct = 100 * n_miss / max(qa.get("mutations_uniques", 1), 1)
        qa["mutations_sans_geometrie_commune"] = n_miss
        qa["mutations_sans_geometrie_pct"] = round(pct, 3)
        qa["exemples_sans_geometrie"] = missing[:20]
        print(f"ATTENTION : {len(missing)} codes commune sans geometrie, "
              f"{n_miss} mutations ({pct:.2f} % — points conserves dans la couche "
              f"mutations, absents des seuls agregats communes) "
              f"(ex: {missing[:5]})", file=sys.stderr)
    json.dump(qa, open(os.path.join(args.out, "prepare_stats.json"), "w"),
              indent=2, ensure_ascii=False)
    print("->", os.path.join(args.out, "prepare_stats.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
