import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
import simulate_iris


def _layer(path):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"code_iris": "100000000"},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}}]}
    json.dump(fc, open(path, "w"))


def test_resolve_iris_at(tmp_path):
    layer = str(tmp_path / "iris_layer.geojson"); _layer(layer)
    assert simulate_iris.resolve_iris_at(layer, lon=0.5, lat=0.5) == "100000000"
    assert simulate_iris.resolve_iris_at(layer, lon=9.0, lat=9.0) is None
