import json

import pytest

from orel import vision


@pytest.mark.parametrize("content", ["not-json", "[]", '{"wrong": true}'])
def test_invalid_model_manifest_disables_ppe_without_breaking_workspace(
    tmp_path, monkeypatch, content
):
    directory = tmp_path / "models"
    directory.mkdir()
    (directory / "active.json").write_text(content)
    monkeypatch.setattr(vision, "ROOT", tmp_path)
    catalog = vision.model_catalog()
    assert catalog["person"]["available"]
    assert not catalog["ppe"]["available"]


def test_manifest_cannot_override_adapter_capabilities(tmp_path, monkeypatch):
    directory = tmp_path / "models"
    directory.mkdir()
    weights = directory / "test.pt"
    weights.write_bytes(b"fixture-not-real-weights")
    (directory / "active.json").write_text(
        json.dumps({"path": str(weights), "available": False, "ppe": False, "name": "wrong"})
    )
    monkeypatch.setattr(vision, "ROOT", tmp_path)
    catalog = vision.model_catalog()
    assert catalog["ppe"]["available"]
    assert catalog["ppe"]["ppe"]
    assert catalog["ppe"]["name"] != "wrong"
