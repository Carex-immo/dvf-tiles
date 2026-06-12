#!/usr/bin/env python3
"""
CAREX - Service de tuiles DVF - Etape de preparation.

Lit les CSV geo-dvf (full ou departements), agrege en 1 point par mutation,
calcule les agregats communes/departements (annee x type), exporte :
  - build/mutations.geojsonl
  - build/communes.geojson
  - build/departements.geojson

Usage: python3 prepare.py --raw data/raw --geo data/geo --out build
Echelle France entiere : ~20 M lignes, prevoir ~8 Go de RAM ou utiliser
--memory-limit (DuckDB bascule alors sur disque via --tmp).
"""
import argparse
import glob
import json
import os
import sys

import duckdb

# Encodages compacts (cf. spec §5)
NATURE_SQL = """
CASE nature_mutation
  WHEN 'Vente' THEN 1
  WHEN 'Vente en l''état futur d''achèvement' THEN 2
  WHEN 'Adjudication' THEN 3
  WHEN 'Echange' THEN 4
  WHEN 'Expropriation' THEN 5
  WHEN 'Vente terrain à bâtir' THEN 6
  ELSE 0 END
"""


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
        "SELECT DISTINCT com FROM mutations").fetchall() if r[0] not in geo_codes]
    if not missing:
        qa["cog_remappage"] = {}
        return
    depts = {r[0]: r[1] for r in con.execute(f"""
        SELECT com, any_value(dep) FROM mutations
        WHERE com IN ({','.join(['?']*len(missing))}) GROUP BY 1""", missing).fetchall()}
    # geometries des departements concernes uniquement
    feats_by_dept = {}
    for dep in set(depts.values()):
        feats = []
        for path in sorted(glob.glob(os.path.join(geo_dir, f"communes_*{dep}.geojson"))):
            for ft in json.load(open(path)).get("features", []):
                if ft["properties"].get("code"):
                    feats.append((ft["properties"]["code"], ft["geometry"]))
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
    le point tombe dans son polygone."""
    have_stats = {r[0] for r in con.execute(
        "SELECT DISTINCT com FROM mutations").fetchall()}
    reaff = {}
    for path in sorted(glob.glob(os.path.join(geo_dir, "communes_*.geojson"))):
        for ft in json.load(open(path)).get("features", []):
            code = ft["properties"].get("code")
            if not code or code in have_stats:
                continue
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
                "WHERE lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?",
                [min(xs), max(xs), min(ys), max(ys)]).fetchall()
            ids = [str(r[0]) for r in rows if point_in_geom(r[1], r[2], geom)]
            if ids:
                con.execute(f"UPDATE mutations SET com = ? "
                            f"WHERE rowid IN ({','.join(ids)})", [code])
                reaff[code] = len(ids)
    qa["scissions_reaffectees"] = reaff
    if reaff:
        print(f"scissions : {len(reaff)} communes retablies recuperent leurs mutations "
              f"par localisation (ex: {dict(list(reaff.items())[:3])})")


# nature_culture dominante -> code compact
def ncult_sql(col: str) -> str:
    return f"""
CASE
  WHEN {col} IS NULL THEN 0
  WHEN {col} = 'S'  THEN 1
  WHEN {col} = 'T'  THEN 2
  WHEN {col} LIKE 'P%' THEN 3
  WHEN {col} = 'VI' THEN 4
  WHEN {col} LIKE 'B%' THEN 5
  WHEN {col} = 'J'  THEN 6
  ELSE 7 END
"""


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
    ap.add_argument("--no-stats", action="store_true",
                    help="sauter le calcul du taux de geolocalisation (1 scan en moins)")
    ap.add_argument("--layers-only", action="store_true",
                    help="ne pas relire les CSV : reconstruire uniquement communes/departements "
                         "depuis build/mutations.geojsonl existant")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    out_pts = os.path.join(args.out, "mutations.geojsonl")

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

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    if args.memory_limit:
        con.execute(f"SET memory_limit='{args.memory_limit}'")
    if args.tmp:
        con.execute(f"SET temp_directory='{args.tmp}'")

    read_csv = f"""read_csv({files!r}, header=true, all_varchar=false,
        delim=',', quote='"', escape='"',
        types={{'code_commune':'VARCHAR','code_departement':'VARCHAR',
                'code_postal':'VARCHAR','code_type_local':'VARCHAR',
                'code_nature_culture':'VARCHAR','id_mutation':'VARCHAR',
                'numero_disposition':'VARCHAR','adresse_numero':'VARCHAR',
                'lot1_numero':'VARCHAR','lot2_numero':'VARCHAR','lot3_numero':'VARCHAR',
                'lot4_numero':'VARCHAR','lot5_numero':'VARCHAR'}})"""

    # ---- Mode reconstruction : agregats depuis le geojsonl existant ------
    qa = {}
    if args.layers_only:
        print(f"--layers-only : lecture de {out_pts}")
        con.execute(f"""
        CREATE TABLE mutations AS
        SELECT properties.annee AS annee, properties.type AS type,
               properties.pm2  AS pm2,  properties.vf   AS vf,
               properties.dep  AS dep,  properties.com  AS com,
               geometry.coordinates[1] AS lon, geometry.coordinates[2] AS lat
        FROM read_json('{out_pts}', format='newline_delimited', sample_size=100000)
        """)

    # ---- Controle qualite source (taux de geolocalisation) ---------------
    if not args.layers_only and not args.no_stats:
        tot, geo, vf_ok = con.execute(f"""
          SELECT count(*),
                 count(*) FILTER (WHERE longitude IS NOT NULL AND latitude IS NOT NULL),
                 count(*) FILTER (WHERE valeur_fonciere IS NOT NULL AND valeur_fonciere > 0)
          FROM {read_csv}""").fetchone()
        qa = {"lignes_source": tot, "lignes_geolocalisees": geo,
              "taux_geoloc_pct": round(100 * geo / tot, 2),
              "lignes_vf_valide": vf_ok}
        print(f"lignes source : {tot} | geolocalisees : {geo} ({qa['taux_geoloc_pct']} %)")

    if not args.layers_only:
        # NB : pas de filtre geoloc ici — les mutations sans coordonnees (souvent
        # des communes fusionnees re-immatriculees au cadastre) comptent dans les
        # agregats communes/departements ; seuls les POINTS exigent des coordonnees.
        con.execute(f"""
        CREATE VIEW base AS
        SELECT * FROM {read_csv}
        WHERE valeur_fonciere IS NOT NULL AND valeur_fonciere > 0
        """)

        # ---- 1 point par mutation ---------------------------------------
        con.execute(f"""
    CREATE TABLE mutations AS
    WITH locaux AS (  -- locaux distincts (les lignes se repetent par disposition/parcelle)
      SELECT DISTINCT id_mutation, id_parcelle, numero_disposition,
             code_type_local, surface_reelle_bati, nombre_pieces_principales
      FROM base WHERE code_type_local IS NOT NULL
    ),
    agg_loc AS (
      SELECT id_mutation,
             SUM(COALESCE(surface_reelle_bati,0))::INT  AS sb,
             MAX(COALESCE(nombre_pieces_principales,0))::INT AS np,
             COUNT(*)::INT                              AS nl,
             arg_max(code_type_local, COALESCE(surface_reelle_bati,0)) AS ct
      FROM locaux GROUP BY 1
    ),
    parcelles AS (
      SELECT id_mutation, id_parcelle,
             MAX(COALESCE(surface_terrain,0)) AS st_p,
             arg_max(code_nature_culture, COALESCE(surface_terrain,0)) AS c
      FROM base GROUP BY 1, 2
    ),
    agg_par AS (
      SELECT id_mutation, SUM(st_p)::INT AS st,
             arg_max(c, st_p) AS c
      FROM parcelles GROUP BY 1
    ),
    head AS (
      SELECT id_mutation,
             any_value(date_mutation)    AS dm,
             any_value(nature_mutation)  AS nature_mutation,
             MAX(valeur_fonciere)        AS vf,
             any_value(code_commune)     AS com,
             any_value(code_departement) AS dep,
             any_value(longitude)        AS lon,
             any_value(latitude)         AS lat
      FROM base GROUP BY 1
    )
    SELECT h.id_mutation                              AS id,
           CAST(strftime(h.dm, '%Y%m%d') AS INT)      AS date,
           CAST(strftime(h.dm, '%Y') AS INT)          AS annee,
           {NATURE_SQL.replace('nature_mutation','h.nature_mutation')} AS nat,
           COALESCE(TRY_CAST(l.ct AS INT), 0)         AS type,
           CAST(round(h.vf) AS BIGINT)                AS vf,
           COALESCE(l.sb, 0)                          AS sb,
           COALESCE(p.st, 0)                          AS st,
           CASE WHEN COALESCE(l.sb,0) > 0
                THEN CAST(round(h.vf / l.sb) AS INT) END AS pm2,
           COALESCE(l.np, 0)                          AS np,
           COALESCE(l.nl, 0)                          AS nl,
           {ncult_sql('p.c')}  AS nc,
           h.dep                                      AS dep,
           h.com                                      AS com,
           h.lon, h.lat
    FROM head h
    LEFT JOIN agg_loc l USING (id_mutation)
    LEFT JOIN agg_par p USING (id_mutation)
    """)

    n, n_geo = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE lon IS NOT NULL) FROM mutations").fetchone()
    qa["mutations_uniques"] = n
    qa["mutations_geolocalisees"] = n_geo
    qa["par_annee"] = dict(con.execute(
        "SELECT annee, count(*) FROM mutations GROUP BY 1 ORDER BY 1").fetchall())
    print(f"mutations uniques : {n} (dont geolocalisees : {n_geo} -> couche points ; "
          f"toutes comptent dans les agregats)")

    # ---- Remappage COG (codes retires -> commune actuelle) ---------------
    remap_cog(con, args.geo, qa)
    # ---- Scissions (communes retablies sans stats -> par localisation) ---
    reassign_scissions(con, args.geo, qa)

    # Export GeoJSONL
    if not args.layers_only:
        cols = ["id", "date", "annee", "nat", "type", "vf", "sb", "st",
                "pm2", "np", "nl", "nc", "dep", "com"]
        with open(out_pts, "w") as f:
            cur = con.execute(f"SELECT {', '.join(cols)}, lon, lat FROM mutations "
                              "WHERE lon IS NOT NULL AND lat IS NOT NULL")
            while True:
                rows = cur.fetchmany(50000)
                if not rows:
                    break
                for r in rows:
                    props = {k: v for k, v in zip(cols, r[:-2]) if v is not None}
                    f.write(json.dumps({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [round(r[-2], 6), round(r[-1], 6)]},
                        "properties": props,
                    }, separators=(",", ":"), ensure_ascii=False) + "\n")
        print("->", out_pts, f"{os.path.getsize(out_pts)/1e6:.1f} Mo")

    # ---- Agregats annee x type ------------------------------------------
    def agg_stats(key: str):
        """Stats par entite (commune ou departement): retour dict code -> props."""
        rows = con.execute(f"""
          SELECT {key} AS k, annee, type,
                 count(*)::INT AS n, CAST(median(pm2) AS INT) AS p
          FROM mutations GROUP BY 1, 2, 3
        """).fetchall()
        tot = con.execute(f"""
          SELECT {key} AS k, count(*)::INT,
                 CAST(median(pm2) AS INT), CAST(median(vf) AS BIGINT)
          FROM mutations GROUP BY 1
        """).fetchall()
        props: dict[str, dict] = {}
        for k, annee, typ, n_, p_ in rows:
            d = props.setdefault(k, {})
            d[f"n_{annee}_t{typ}"] = n_
            if p_ is not None:
                d[f"p_{annee}_t{typ}"] = p_
        for k, n_tot, pm2_med, vf_med in tot:
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
    def build_layer(pattern: str, code_key, out_name: str, stats: dict):
        feats, seen = [], set()
        for path in sorted(glob.glob(os.path.join(args.geo, pattern))):
            data = json.load(open(path))
            items = data["features"] if data.get("type") == "FeatureCollection" else [data]
            for ft in items:
                code = code_key(ft)
                if code in seen:
                    continue  # doublon entre fichiers de contours
                # les entites sans mutation sont rendues avec n_tot=0
                # (une commune sans vente n'est pas un trou sur la carte)
                st = stats.get(code) or {"n_tot": 0}
                seen.add(code)
                ft["properties"] = {"code": code,
                                    "nom": ft.get("properties", {}).get("nom", ""),
                                    **st}
                feats.append(ft)
        out = os.path.join(args.out, out_name)
        json.dump({"type": "FeatureCollection", "features": feats},
                  open(out, "w"), separators=(",", ":"), ensure_ascii=False)
        print("->", out, f"{len(feats)} entites, {os.path.getsize(out)/1e6:.1f} Mo")
        return seen

    seen_com = build_layer("communes_*.geojson",
                           lambda ft: ft["properties"].get("code"),
                           "communes.geojson", com_stats)
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
