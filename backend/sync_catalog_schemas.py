"""Generate/check installed schema resources from the normative E0 contracts."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    backend = Path(__file__).resolve().parent
    source = backend.parent / "contracts" / "schemas"
    destination = backend / "src/calorie_app/modules/catalog/resources"
    for name in (
        "common.schema.json",
        "catalog.schema.json",
        "domain.schema.json",
        "sync.schema.json",
    ):
        data = (source / name).read_bytes()
        target = destination / name
        if args.check:
            if not target.exists() or target.read_bytes() != data:
                parser.error(f"Stale generated resource: {name}")
        else:
            target.write_bytes(data)
    print("PASS catalog schema resources")


if __name__ == "__main__":
    main()
