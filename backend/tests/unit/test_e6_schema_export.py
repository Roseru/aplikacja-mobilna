"""Clean Windows checkouts accept CRLF, while real generated drift fails."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def exporter(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "community_schema_export_test", BACKEND / "export_community_schemas.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    backend = tmp_path / "backend"
    backend.mkdir()
    backend.joinpath("openapi.json").write_bytes(BACKEND.joinpath("openapi.json").read_bytes())
    monkeypatch.setattr(module, "__file__", str(backend / "export_community_schemas.py"))
    monkeypatch.setattr(sys, "argv", [module.__file__, "--check"])
    target = tmp_path / "contracts/schemas/community.schema.json"
    target.parent.mkdir(parents=True)
    expected = module.generate(json.loads(backend.joinpath("openapi.json").read_text("utf-8")))
    return module, target, expected


@pytest.mark.parametrize("eol", [b"\n", b"\r\n"])
def test_generated_schema_check_accepts_checkout_line_endings(exporter, eol):
    module, target, expected = exporter
    original = expected.replace(b"\n", eol)
    target.write_bytes(original)
    module.main()
    assert target.read_bytes() == original  # --check must leave the checkout clean.


@pytest.mark.parametrize("drift", ["value", "indentation", "missing_final_newline"])
def test_generated_schema_check_still_rejects_content_and_format_drift(exporter, drift):
    module, target, expected = exporter
    if drift == "value":
        changed = expected.replace(b"Generated structural E6 contracts", b"Incorrect E6 contracts")
    elif drift == "indentation":
        changed = expected.replace(b'  "$schema"', b'    "$schema"', 1)
    else:
        changed = expected.rstrip(b"\n")
    assert changed != expected
    original = changed.replace(b"\n", b"\r\n")
    target.write_bytes(original)
    with pytest.raises(SystemExit) as failure:
        module.main()
    assert failure.value.code == 2
    assert target.read_bytes() == original


def test_committed_and_bundled_community_schema_have_the_same_generated_text(exporter):
    _, _, expected = exporter
    normative = BACKEND.parent / "contracts/schemas/community.schema.json"
    bundled = files("calorie_app.modules.catalog.resources").joinpath("community.schema.json")
    # All generated text stays exact; only platform text line endings vary.
    assert normative.read_text(encoding="utf-8") == expected.decode("utf-8")
    assert bundled.read_text(encoding="utf-8") == expected.decode("utf-8")
