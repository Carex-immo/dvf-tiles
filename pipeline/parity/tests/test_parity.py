"""Tests de parité Python ↔ Swift (lot P1).

Les goldens (tests/goldens/*.golden.json) sont générés par le test Swift
`GeoDvfGoldenTests` (carex.immoTests) : ils contiennent TOUTES les mutations
consolidées par le code de l'app, y compris celles sans ancre (clé `lat`
absente) — que la réplique Python REJETTE (règle du pipeline). La parité
vérifie donc : mutations conservées == entrées avec `lat`, champ à champ
(aucune tolérance sauf coordonnées ≤ 1e-5), et rejets == entrées sans `lat`.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from consolidate import consolidate_file, round_half_away  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = ["73065-2024", "75101-2024", "2A004-2024", "synthetic"]

SCALAR_KEYS = ("type", "nature", "prix", "date", "surfBati", "surfTerrain", "pieces")
BIEN_KEYS = ("type", "surfBati", "pieces", "surfTerrain", "surfCarrez")


def load_golden(name):
    with open(os.path.join(HERE, "goldens", f"{name}.golden.json")) as f:
        return json.load(f)


def assert_mutation_equal(produced, golden, mid):
    for key in SCALAR_KEYS:
        assert produced.get(key) == golden.get(key), (
            f"{mid}.{key}: python={produced.get(key)!r} swift={golden.get(key)!r}")
    assert abs(produced["lat"] - golden["lat"]) <= 1e-5, f"{mid}.lat"
    assert abs(produced["lon"] - golden["lon"]) <= 1e-5, f"{mid}.lon"
    p_biens, g_biens = produced["biens"], golden["biens"]
    assert len(p_biens) == len(g_biens), (
        f"{mid}: {len(p_biens)} biens python vs {len(g_biens)} swift")
    for i, (pb, gb) in enumerate(zip(p_biens, g_biens)):
        for key in BIEN_KEYS:
            assert pb.get(key) == gb.get(key), (
                f"{mid}.biens[{i}].{key}: python={pb.get(key)!r} swift={gb.get(key)!r}")


@pytest.mark.parametrize("name", FIXTURES)
def test_parity(name):
    golden = load_golden(name)
    result = consolidate_file(os.path.join(HERE, "fixtures", f"{name}.csv"))

    golden_kept = {g["id"]: g for g in golden if "lat" in g}
    golden_rejected = sorted(g["id"] for g in golden if "lat" not in g)

    produced = {m["id"]: m for m in result.mutations}
    assert sorted(produced) == sorted(golden_kept), (
        f"{name}: ids conservés divergents")
    assert result.rejected_ids == golden_rejected, (
        f"{name}: ids rejetés divergents")

    for mid, g in golden_kept.items():
        assert_mutation_equal(produced[mid], g, f"{name}/{mid}")


def test_compteurs_synthetic():
    """Les compteurs du rapport de build sont eux aussi sous contrat."""
    result = consolidate_file(os.path.join(HERE, "fixtures", "synthetic.csv"))
    assert result.stats.rejected_mutations == 1          # S-02
    assert result.stats.embedded_no_coord_rows == 3      # S-01 ×2 + S-03
    assert result.stats.skipped_rows == 1                # ligne à id vide
    assert result.stats.malformed_lines == 0


def test_bom_et_entete_invalide(tmp_path):
    """BOM strippé (utf-8-sig) ; en-tête sans colonnes requises → échec FORT."""
    from consolidate import HEADER
    values = {"id_mutation": "M-1", "date_mutation": "2024-01-01",
              "id_parcelle": "P1", "longitude": "5.9", "latitude": "45.5"}
    data_row = ",".join(values.get(name, "") for name in HEADER)
    bom = tmp_path / "bom.csv"
    bom.write_text("\ufeff" + ",".join(HEADER) + "\n" + data_row + "\n",
                   encoding="utf-8")
    result = consolidate_file(str(bom))
    assert [m["id"] for m in result.mutations] == ["M-1"]

    bad = tmp_path / "bad-header.csv"
    bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="colonnes requises"):
        consolidate_file(str(bad))


def test_non_finis_sans_crash():
    """inf/nan/débordement dans un champ numérique : None, jamais d'exception
    (sinon round_half_away crasherait le build P2 sur une ligne exotique)."""
    from consolidate import parse_float
    assert parse_float("inf") is None
    assert parse_float("-inf") is None
    assert parse_float("nan") is None
    assert parse_float("1e400") is None


def test_contiguite_tri_de_secours():
    """Fixture désordonnée (mutations entrelacées, ordre interne préservé) →
    violation détectée, tri stable de secours, résultat identique au golden
    de la fixture ordonnée."""
    golden = load_golden("synthetic")
    result = consolidate_file(os.path.join(HERE, "fixtures", "synthetic-desordonne.csv"))
    assert result.stats.contiguity_violated is True

    golden_kept = {g["id"]: g for g in golden if "lat" in g}
    produced = {m["id"]: m for m in result.mutations}
    assert sorted(produced) == sorted(golden_kept)
    for mid, g in golden_kept.items():
        assert_mutation_equal(produced[mid], g, f"desordonne/{mid}")


def test_lignes_invalides_comptees(tmp_path):
    """Lignes malformées (≠ 40 champs) et sans champs requis : ignorées +
    comptées, jamais d'exception."""
    names = (["id_mutation", "date_mutation"] + [f"c{i}" for i in range(13)]
             + ["id_parcelle"] + [f"d{i}" for i in range(22)] + ["longitude", "latitude"])
    assert len(names) == 40

    def row(**kw):
        base = {k: "" for k in names}
        base.update(kw)
        return ",".join(base[k] for k in names)

    bad = tmp_path / "bad.csv"
    bad.write_text(
        ",".join(names) + "\n"
        + "trop,court\n"                                # 2 champs → malformée
        + row(date_mutation="2024-01-01", id_parcelle="P1",
              longitude="5.9", latitude="45.5") + "\n"  # id vide → requise absente
        + row(id_mutation="M-1", date_mutation="2024-01-01", id_parcelle="P1",
              longitude="5.9", latitude="45.5") + "\n",
        encoding="utf-8",
    )
    result = consolidate_file(str(bad))
    assert result.stats.malformed_lines == 1
    assert result.stats.skipped_rows == 1
    assert [m["id"] for m in result.mutations] == ["M-1"]


def test_round_half_away():
    """Half-away-from-zero — PAS l'arrondi au pair de round()."""
    assert round_half_away(0.5) == 1
    assert round_half_away(1.5) == 2
    assert round_half_away(2.5) == 3      # round() Python donnerait 2
    assert round_half_away(-0.5) == -1
    assert round_half_away(-2.5) == -3
    assert round_half_away(118750.49) == 118750
