"""Extension dvf-tiles du pont de parité — lecture CSV enrichie.

`consolidate.py` (copie verbatim de carex.immo, cf. README.md) ne lit que les
champs du schéma golden. Le pipeline a besoin en plus, par mutation, de
l'adresse (`adr`), du code postal (`cp`), de la commune (`com`) et du
département (`dep`) — pris sur la 1ʳᵉ ligne du groupe, comme l'ancre et la
valeur foncière. Ce module réplique `read_rows` en composant ces champs
annexes (et en acceptant les `.csv.gz`), puis délègue TOUT le métier aux
fonctions importées verbatim ; la non-déviation est prouvée par
`test_parity_extended.py`, qui rejoue les goldens via ce chemin.
"""
from __future__ import annotations

import csv
import gzip
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from consolidate import (  # noqa: E402
    EXPECTED_FIELD_COUNT,
    LOT_CARREZ_COLUMNS,
    Result,
    Stats,
    build_coords_map,
    consolidate_group,
    contiguous_groups,
    fold_sum,
    parse_float,
    parse_int,
)

# Champs annexes hors schéma golden, portés par la 1ʳᵉ ligne de la mutation.
ANNEX_KEYS = ("adr", "cp", "com", "dep")


def _open_text(path: str):
    if path.endswith(".gz"):
        return gzip.open(path, mode="rt", encoding="utf-8-sig", newline="")
    return open(path, newline="", encoding="utf-8-sig")


def read_rows_extended(path: str, stats: Stats) -> list[dict]:
    """Réplique de `consolidate.read_rows` + clés annexes par ligne.

    Les clés supplémentaires sont ignorées par `consolidate_group` (accès par
    clé) : seul l'enrichissement diffère, le filtrage (40 champs, champs
    requis) et le parsing restent identiques au verbatim.
    """
    rows: list[dict] = []
    with _open_text(path) as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return rows
        index = {name.strip(): i for i, name in enumerate(header)}
        required = ("id_mutation", "id_parcelle", "date_mutation")
        missing = [name for name in required if name not in index]
        if missing:
            raise ValueError(f"en-tête invalide — colonnes requises absentes : {missing}")
        for fields_ in reader:
            stats.rows_read += 1
            if len(fields_) != EXPECTED_FIELD_COUNT:
                stats.malformed_lines += 1
                continue

            def get(name: str) -> str | None:
                i = index.get(name)
                if i is None or i >= len(fields_) or fields_[i] == "":
                    return None
                return fields_[i]

            if any(get(name) is None for name in required):
                stats.skipped_rows += 1
                continue
            carrez_values = [parse_float(get(c)) for c in LOT_CARREZ_COLUMNS]
            carrez_present = [v for v in carrez_values if v is not None]
            adr = " ".join(p for p in (get("adresse_numero"), get("adresse_suffixe"),
                                       get("adresse_nom_voie")) if p)
            rows.append({
                "id_mutation": get("id_mutation"),
                "id_parcelle": get("id_parcelle"),
                "date_mutation": get("date_mutation"),
                "nature_mutation": get("nature_mutation"),
                "valeur_fonciere": parse_float(get("valeur_fonciere")),
                "type_local": get("type_local"),
                "surface_reelle_bati": parse_float(get("surface_reelle_bati")),
                "nombre_pieces_principales": parse_int(get("nombre_pieces_principales")),
                "surface_terrain": parse_float(get("surface_terrain")),
                "surface_carrez": fold_sum(carrez_present) if carrez_present else None,
                "longitude": parse_float(get("longitude")),
                "latitude": parse_float(get("latitude")),
                "adr": adr or None,
                "cp": get("code_postal"),
                "com": get("code_commune"),
                "dep": get("code_departement"),
            })
    return rows


def consolidate_file_extended(path: str) -> Result:
    """Réplique de `consolidate.consolidate_file` sur la lecture enrichie :
    chaque mutation conservée porte en plus les clés annexes de sa 1ʳᵉ ligne
    (celle qui fournit déjà l'ancre, la date et la valeur foncière)."""
    result = Result()
    rows = read_rows_extended(path, result.stats)
    coords = build_coords_map(rows)
    for group in contiguous_groups(rows, result.stats):
        mutation = consolidate_group(group, coords)
        if mutation is None:
            result.stats.rejected_mutations += 1
            result.rejected_ids.append(group[0]["id_mutation"])
            continue
        result.stats.embedded_no_coord_rows += sum(
            1 for r in group if r["longitude"] is None or r["latitude"] is None
        )
        for key in ANNEX_KEYS:
            mutation[key] = group[0][key]
        result.mutations.append(mutation)
    result.mutations.sort(key=lambda m: m["id"])
    result.rejected_ids.sort()
    return result
