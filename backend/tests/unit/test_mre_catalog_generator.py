import gzip
import hashlib
import importlib.util
import json
from pathlib import Path


def test_mre_generator_reproduces_canonical_demo_release(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "mre_catalog_generator", root / "tools/catalog/build_mre_2026.py"
    )
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    generator.build(tmp_path)

    assets = root / "android/app/src/main/assets/catalog/mre2026"
    for name in (
        "base-pl.1.json.gz.bin",
        "manifest.json",
        "selection-rules.json",
        "source.json",
    ):
        assert (tmp_path / name).read_bytes() == (assets / name).read_bytes(), name

    compressed = (tmp_path / "base-pl.1.json.gz.bin").read_bytes()
    raw = gzip.decompress(compressed)
    assert len(compressed) == 27924
    assert compressed[9] == 255
    assert hashlib.sha256(compressed).hexdigest() == (
        "2c0a1ff730e408cc90ab1fcfcb2b9eef21ebce8fa2d935d429f296d225260880"
    )
    assert len(raw) == 246314
    assert raw.endswith(b"\n")
    assert hashlib.sha256(raw).hexdigest() == (
        "0552172f59de3f71597074b88dcb99c22d8c227eba7cb3ce96ac30f3e0a9d967"
    )
    assert hashlib.sha256((tmp_path / "source.json").read_bytes()).hexdigest() == (
        "f519ef7390287c06293e7d45ff65371d5fa5cc68565994c948baebd2b0c2ad94"
    )
    payload = json.loads(raw)
    assert payload["package_id"] == "3aa9b766-b01d-5111-8fd0-4c5b6257961b"
    assert payload["kind"] == "demo"
    assert payload["release"] == 1
    counts = {"products": 111, "rations": 24, "components": 235, "sources": 112}
    assert payload["counts"] == counts
    assert len(payload["products"]) == counts["products"]
    assert len(payload["rations"]) == counts["rations"]
    ration_keys = [(ration["ration_id"], ration["revision"]) for ration in payload["rations"]]
    assert ration_keys == sorted(ration_keys)
    assert sum(len(ration["components"]) for ration in payload["rations"]) == counts["components"]
    assert len(payload["sources"]) == counts["sources"]
    manifest_raw = (tmp_path / "manifest.json").read_bytes()
    assert manifest_raw.endswith(b"\n")
    assert hashlib.sha256(manifest_raw).hexdigest() == (
        "dc0a0b9b818dd7ea9f224424c6fe07b11d8af574dbb6109a9658c12297c149bf"
    )
    manifest = json.loads(manifest_raw)
    assert manifest["counts"] == counts
    assert manifest["sha256"] == hashlib.sha256(compressed).hexdigest()
