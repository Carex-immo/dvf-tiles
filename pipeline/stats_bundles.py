#!/usr/bin/env python3
"""Extracteur de stats riches par entité (commune/département) — artefact
build/stats/ consommé directement par l'app iOS (panneau au tap).

Source : la vue DuckDB `stats_src` de prepare.py (post remap COG/scissions),
même base que les agrégats des tuiles -> parité garantie. Tout en MÉDIANES
(robuste, précalculable ; les médianes ne se recombinent pas -> on précalcule
à la granularité d'affichage : année puis année x type).

Schéma EntityStats : cf.
docs/superpowers/specs/2026-06-14-stats-bundles-dept-commune-design.md
"""
import json
import os


def years(con):
    """Millésimes présents dans stats_src, triés (axe commun à tous les arrays)."""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT annee FROM stats_src ORDER BY 1").fetchall()]


def _dept_of(code):
    """Département d'un code commune (préfixe), même règle que prepare.py :
    97x -> 3 caractères, sinon 2 (couvre la Corse 2A/2B)."""
    return code[:3] if code.startswith("97") else code[:2]


def entity_stats(con, key, names, yrs, dense_threshold=200):
    """Retourne {code: EntityStats} pour la dimension `key` ('com' ou 'dep').

    names : {code: nom} des entités à émettre (géométrie connue) ; une entité
    sans vente sort avec n_tot=0. yrs : axe années commun (cf. years()).
    Trimestriel (clé 'quarters') seulement si n_tot >= dense_threshold, point
    omis si n < 5."""
    assert key in ("com", "dep"), f"clé inconnue : {key!r}"
    idx = {y: i for i, y in enumerate(yrs)}
    n = len(yrs)
    out = {code: {"code": code, "nom": nom, "n_tot": 0,
                  "pm2_med": None, "vf_med": None, "years": yrs,
                  "overall": {"n": [0] * n, "pm2_med": [None] * n},
                  "byType": {}}
           for code, nom in names.items()}

    # totaux toute période (terrain nu inclus dans n_tot ; pm2/vf ignorent les NULL)
    for code, n_tot, pm2_med, vf_med in con.execute(f"""
        SELECT {key}, count(*)::INT, CAST(median(pm2) AS INT),
               CAST(median(vf) AS BIGINT)
        FROM stats_src WHERE {key} IS NOT NULL GROUP BY 1""").fetchall():
        e = out.get(code)
        if e is not None:
            e["n_tot"], e["pm2_med"], e["vf_med"] = n_tot, pm2_med, vf_med

    # tendance annuelle, tous types confondus
    for code, annee, cnt, p in con.execute(f"""
        SELECT {key}, annee, count(*)::INT, CAST(median(pm2) AS INT)
        FROM stats_src WHERE {key} IS NOT NULL GROUP BY 1, 2""").fetchall():
        e = out.get(code)
        if e is not None and annee in idx:
            e["overall"]["n"][idx[annee]] = cnt
            e["overall"]["pm2_med"][idx[annee]] = p

    # détail par type (1-5) x année
    for code, typ, annee, cnt, pm2, vf, sb, st, np_ in con.execute(f"""
        SELECT {key}, type, annee, count(*)::INT,
               CAST(median(pm2) AS INT), CAST(median(vf) AS BIGINT),
               CAST(median(sb) AS INT), CAST(median(st) AS INT),
               CAST(median(np) AS INT)
        FROM stats_src WHERE {key} IS NOT NULL AND type IS NOT NULL
        GROUP BY 1, 2, 3""").fetchall():
        e = out.get(code)
        if e is None or annee not in idx:
            continue
        i = idx[annee]
        bt = e["byType"].setdefault(str(typ), {
            "n": [0] * n, "pm2_med": [None] * n, "vf_med": [None] * n,
            "sb_med": [None] * n, "st_med": [None] * n, "np_med": [None] * n})
        bt["n"][i] = cnt
        bt["pm2_med"][i] = pm2
        bt["vf_med"][i] = vf
        bt["sb_med"][i] = sb
        bt["st_med"][i] = st
        bt["np_med"][i] = np_

    # tendance trimestrielle : entités denses, point omis si n < 5
    dense = {c for c, e in out.items() if e["n_tot"] >= dense_threshold}
    if dense:
        for code, annee, q, cnt, p in con.execute(f"""
            SELECT {key}, annee, ((((date // 100) % 100) - 1) // 3 + 1) AS q,
                   count(*)::INT, CAST(median(pm2) AS INT)
            FROM stats_src WHERE {key} IS NOT NULL
            GROUP BY 1, 2, 3 HAVING count(*) >= 5 ORDER BY 2, 3""").fetchall():
            if code in dense:
                out[code].setdefault("quarters", []).append(
                    {"p": f"{annee}Q{q}", "n": cnt, "pm2_med": p})
    return out


def build_stats_bundles(con, com_names, dep_names, out_dir, version,
                        dense_threshold=200):
    """Écrit out_dir/stats/{manifest.json, departements.json, dep/{DD}.json}.
    Retourne les compteurs (pour prepare_stats.json / QA)."""
    yrs = years(con)
    stats_dir = os.path.join(out_dir, "stats")
    dep_dir = os.path.join(stats_dir, "dep")
    os.makedirs(dep_dir, exist_ok=True)

    dep_stats = entity_stats(con, "dep", dep_names, yrs, dense_threshold)
    com_stats = entity_stats(con, "com", com_names, yrs, dense_threshold)

    def _write(path, entities):
        json.dump({"version": version, "entities": entities},
                  open(path, "w"), separators=(",", ":"), ensure_ascii=False)

    _write(os.path.join(stats_dir, "departements.json"), list(dep_stats.values()))

    # communes regroupées par département -> un fichier par département
    by_dep = {}
    for code, e in com_stats.items():
        by_dep.setdefault(_dept_of(code), []).append(e)
    for dd, entities in by_dep.items():
        _write(os.path.join(dep_dir, f"{dd}.json"), entities)

    compteurs = {"departements": len(dep_stats), "communes": len(com_stats),
                 "bundles_dep": len(by_dep)}
    manifest = {"version": version, "generated": version,
                "dense_threshold": dense_threshold, "years": yrs,
                "layers": {"departements": "stats/departements.json",
                           "communes": "stats/dep/{DD}.json"},
                "departements": sorted(by_dep), "compteurs": compteurs}
    json.dump(manifest, open(os.path.join(stats_dir, "manifest.json"), "w"),
              separators=(",", ":"), ensure_ascii=False)
    return compteurs
