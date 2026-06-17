import copy, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
import patch_manifest as pm

LIVE = {"version": "20260614T102335Z", "generated": "20260614T102335Z",
        "dense_threshold": 200, "years": [2021, 2022, 2023, 2024, 2025],
        "layers": {"departements": "stats/departements.json",
                   "communes": "stats/dep/{DD}.json"},
        "departements": ["01", "2A", "974"],
        "compteurs": {"departements": 109, "communes": 34902, "bundles_dep": 100}}


def _index_dir(tmp_path):
    d = tmp_path / "iris_index"; d.mkdir()
    json.dump([{"code": "010010000"}, {"code": "010010001"}], open(d / "01.json", "w"))
    json.dump([{"code": "2A0040000"}], open(d / "2A.json", "w"))
    return str(d)


def test_count_iris(tmp_path):
    n, deps = pm.count_iris(_index_dir(tmp_path))
    assert n == 3
    assert deps == ["01", "2A"]


def test_merge_adds_iris_bits():
    m = pm.merge(copy.deepcopy(LIVE), "2026", 48000)
    assert m["millesime_iris"] == "2026"
    assert m["layers"]["iris_index"] == "stats/iris_index/{DD}.json"
    assert m["compteurs"]["iris"] == 48000


def test_merge_preserves_existing():
    m = pm.merge(copy.deepcopy(LIVE), "2026", 48000)
    assert m["version"] == "20260614T102335Z"          # version jamais touchée
    assert m["generated"] == "20260614T102335Z"
    assert m["dense_threshold"] == 200
    assert m["years"] == [2021, 2022, 2023, 2024, 2025]
    assert m["layers"]["communes"] == "stats/dep/{DD}.json"
    assert m["compteurs"]["bundles_dep"] == 100
    assert m["departements"] == ["01", "2A", "974"]


def test_merge_idempotent():
    m1 = pm.merge(copy.deepcopy(LIVE), "2026", 48000)
    m2 = pm.merge(copy.deepcopy(m1), "2026", 48000)
    assert m1 == m2


def test_load_manifest_file(tmp_path):
    p = tmp_path / "manifest.json"; json.dump(LIVE, open(p, "w"))
    assert pm.load_manifest(file=str(p))["version"] == "20260614T102335Z"


def test_extra_deps():
    # 975/977 sont dans l'index mais pas dans manifest.departements (cas réel DOM).
    assert pm.extra_deps(["01", "974", "975", "977"], LIVE) == ["975", "977"]
    assert pm.extra_deps(["01", "2A"], LIVE) == []
