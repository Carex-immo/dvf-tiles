"""Parité du chemin enrichi (extended.py) — propre à dvf-tiles.

Deux garanties :
  1. non-déviation : les goldens Swift rejoués via `consolidate_file_extended`
     donnent exactement le même résultat que le chemin verbatim ;
  2. extraction annexe : adr/cp/com/dep viennent de la 1ʳᵉ ligne du groupe,
     champs vides → None, et les `.csv.gz` sont acceptés.
"""
import gzip
import json
import os
import shutil
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))
from extended import ANNEX_KEYS, consolidate_file_extended  # noqa: E402
from consolidate import consolidate_file, HEADER  # noqa: E402
from test_parity import FIXTURES, assert_mutation_equal, load_golden  # noqa: E402

FIXTURE_DIR = os.path.join(HERE, "tests", "fixtures")


@pytest.mark.parametrize("name", FIXTURES)
def test_goldens_via_chemin_etendu(name):
    """Mêmes assertions que test_parity, à travers la lecture enrichie."""
    golden = load_golden(name)
    result = consolidate_file_extended(os.path.join(FIXTURE_DIR, f"{name}.csv"))

    golden_kept = {g["id"]: g for g in golden if "lat" in g}
    golden_rejected = sorted(g["id"] for g in golden if "lat" not in g)

    produced = {m["id"]: m for m in result.mutations}
    assert sorted(produced) == sorted(golden_kept)
    assert result.rejected_ids == golden_rejected
    for mid, g in golden_kept.items():
        assert_mutation_equal(produced[mid], g, f"{name}/{mid}")
        for key in ANNEX_KEYS:
            assert key in produced[mid]


@pytest.mark.parametrize("name", FIXTURES)
def test_compteurs_identiques_au_verbatim(name):
    """Les compteurs de build (sous contrat) ne dévient pas non plus."""
    path = os.path.join(FIXTURE_DIR, f"{name}.csv")
    ext, ref = consolidate_file_extended(path), consolidate_file(path)
    assert ext.rejected_ids == ref.rejected_ids
    for attr in ("rows_read", "malformed_lines", "skipped_rows",
                 "contiguity_violated", "rejected_mutations",
                 "embedded_no_coord_rows"):
        assert getattr(ext.stats, attr) == getattr(ref.stats, attr), attr


def _row(**kw):
    base = {name: "" for name in HEADER}
    base.update(kw)
    return ",".join(base[name] for name in HEADER)


def test_annexes_premiere_ligne(tmp_path):
    """adr composée numéro+suffixe+voie (vides sautés), cp/com/dep bruts —
    pris sur la 1ʳᵉ ligne même si les suivantes diffèrent."""
    csv_path = tmp_path / "annexes.csv"
    csv_path.write_text("\n".join([
        ",".join(HEADER),
        _row(id_mutation="M-1", date_mutation="2024-01-05", id_parcelle="P1",
             adresse_numero="28", adresse_suffixe="B",
             adresse_nom_voie="RUE JEAN CLAUDE BARTET", code_postal="69410",
             code_commune="69040", code_departement="69",
             longitude="4.794854", latitude="45.791146"),
        _row(id_mutation="M-1", date_mutation="2024-01-05", id_parcelle="P1",
             adresse_numero="99", adresse_nom_voie="AUTRE VOIE",
             code_postal="69999", code_commune="69999", code_departement="99",
             longitude="4.794854", latitude="45.791146"),
        _row(id_mutation="M-2", date_mutation="2024-02-01", id_parcelle="P2",
             adresse_nom_voie="IMPASSE DE L'EPINE", code_postal="01000",
             code_commune="01053", code_departement="01",
             longitude="5.228", latitude="46.205"),
        _row(id_mutation="M-3", date_mutation="2024-03-01", id_parcelle="P3",
             longitude="5.0", latitude="46.0"),
    ]) + "\n", encoding="utf-8")
    result = consolidate_file_extended(str(csv_path))
    by_id = {m["id"]: m for m in result.mutations}

    assert by_id["M-1"]["adr"] == "28 B RUE JEAN CLAUDE BARTET"
    assert by_id["M-1"]["cp"] == "69410"
    assert by_id["M-1"]["com"] == "69040"
    assert by_id["M-1"]["dep"] == "69"
    assert by_id["M-2"]["adr"] == "IMPASSE DE L'EPINE"   # sans numéro ni suffixe
    assert by_id["M-2"]["cp"] == "01000"                 # zéros de tête préservés
    assert by_id["M-3"]["adr"] is None                   # adresse vide → omise
    assert by_id["M-3"]["cp"] is None


def test_gzip_equivalent(tmp_path):
    """Un .csv.gz donne le même résultat que le .csv en clair."""
    src = os.path.join(FIXTURE_DIR, "synthetic.csv")
    gz = tmp_path / "synthetic.csv.gz"
    with open(src, "rb") as fin, gzip.open(gz, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    a = consolidate_file_extended(src)
    b = consolidate_file_extended(str(gz))
    assert [m["id"] for m in a.mutations] == [m["id"] for m in b.mutations]
    assert json.dumps(a.mutations, sort_keys=True) == json.dumps(b.mutations, sort_keys=True)
