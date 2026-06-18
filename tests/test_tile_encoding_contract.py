"""Verrou du contrat d'encodage compact (les « 4 fichiers consommateurs »).

Source de vérité : pipeline/tile_encoding.json. Ce test garantit que les clés
de propriétés des features mutations et les codes nat/type ne dérivent pas
silencieusement entre les fichiers qui dupliquent l'encodage à la main.

Backbone (verrou exact) : prepare.py TILE_PROPS == JSON mutation_keys ==
champs `let` du struct Mutation (DvfTileClient.swift). Cf. design
docs/superpowers/specs/2026-06-18-ci-github-actions-design.md.
"""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "pipeline" / "tile_encoding.json").read_text())


def _tile_props_from_prepare():
    """Lit TILE_PROPS par AST (sans importer prepare.py : il charge duckdb)."""
    src = (ROOT / "pipeline" / "prepare.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TILE_PROPS" for t in node.targets
        ):
            return [el.value for el in node.value.elts]
    raise AssertionError("TILE_PROPS introuvable dans pipeline/prepare.py")


def _swift_struct_fields():
    """Champs `let <clé>:` du struct Mutation, hors `coordinate` (géométrie)."""
    lines = (ROOT / "client" / "DvfTileClient.swift").read_text().splitlines()
    fields, inside = [], False
    for line in lines:
        if line.startswith("struct Mutation"):
            inside = True
            continue
        if inside:
            if line.startswith("}"):
                break
            m = re.match(r"\s*let (\w+)\s*:", line)
            if m and m.group(1) != "coordinate":
                fields.append(m.group(1))
    return fields


def test_tile_props_match_spec():
    assert _tile_props_from_prepare() == SPEC["mutation_keys"]


def test_swift_struct_matches_spec():
    assert _swift_struct_fields() == SPEC["mutation_keys"]


EXPECTED_CODES = {"1", "2", "3", "4", "5"}


def test_spec_code_sets():
    assert set(SPEC["nat"]) == EXPECTED_CODES
    assert set(SPEC["type"]) == EXPECTED_CODES


def test_demo_type_codes_match_spec():
    """Le mapping `const types = {…}` du JS couvre exactement les codes type 1..5."""
    src = (ROOT / "demo" / "index.html").read_text()
    m = re.search(r"const types\s*=\s*\{([^}]*)\}", src)
    assert m, "objet `const types` introuvable dans demo/index.html"
    codes = set(re.findall(r"(\d+)\s*:", m.group(1)))
    assert codes == set(SPEC["type"]), f"codes type demo={codes}"


def test_swift_comment_codes_match_spec():
    """Les commentaires `// 1 …, 2 …` du struct listent exactement les codes 1..5."""
    src = (ROOT / "client" / "DvfTileClient.swift").read_text()
    for key in ("nat", "type"):
        m = re.search(rf"let {key}\s*:[^/]*//(.*)", src)
        assert m, f"commentaire de `let {key}` introuvable dans le struct"
        codes = set(re.findall(r"\b([1-5])\b", m.group(1)))
        assert codes == set(SPEC[key]), f"codes {key} Swift={codes}"
