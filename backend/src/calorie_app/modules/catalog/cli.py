"""Operator-only local catalog commands; never exposed as HTTP writes."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from calorie_app.modules.catalog.export import export_package, publish_package, write_immutable
from calorie_app.modules.catalog.pagination import prune_legacy_tokens
from calorie_app.modules.catalog.service import import_catalog, recover_timestamp
from calorie_app.modules.catalog.validation import (
    MAX_UNCOMPRESSED_BYTES,
    CatalogValidationError,
    canonical_json,
    parse_json,
    validate_package,
)


def read_input(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(MAX_UNCOMPRESSED_BYTES + 1)
    value = parse_json(raw)
    validate_package(value)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prune-page-tokens")
    for name in ("validate", "import", "recover-timestamp"):
        sub.add_parser(name).add_argument("--input", type=Path, required=True)
    for name in ("export", "publish"):
        command = sub.add_parser(name)
        command.add_argument("--package-id", type=UUID, required=True)
        command.add_argument("--release", type=int, required=True)
        if name == "export":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    engine = None
    try:
        if args.command in {"validate", "import", "recover-timestamp"}:
            value = read_input(args.input)
            if args.command == "validate":
                print(json.dumps({"status": "valid", "counts": value["counts"]}))
                return 0
        # Only PostgreSQL commands read DATABASE_URL. Validation and the offline
        # reference reader run without a server, credentials or network.
        from calorie_app.core.config import Settings
        from calorie_app.db.session import make_engine

        settings = Settings()
        engine = make_engine(settings)
        if args.command in {"import", "recover-timestamp"}:
            operation = import_catalog if args.command == "import" else recover_timestamp
            result = operation(engine, value)
            print(
                json.dumps(
                    {
                        "package_id": str(result.package_id),
                        "release": result.release,
                        "created": result.created,
                    }
                )
            )
        elif args.command == "export":
            artifact = export_package(engine, args.package_id, args.release)
            write_immutable(args.output / artifact.manifest["path"], artifact.compressed)
            write_immutable(args.output / "manifest.json", canonical_json(artifact.manifest))
            print(json.dumps(artifact.manifest))
        elif args.command == "prune-page-tokens":
            from sqlalchemy.orm import Session

            with Session(engine) as session, session.begin():
                removed = prune_legacy_tokens(session)
            print(json.dumps({"removed": removed, "batch_limit": 1000}))
        else:
            print(
                json.dumps(
                    publish_package(
                        engine,
                        args.package_id,
                        args.release,
                        settings.catalog_artifact_root,
                    )
                )
            )
        return 0
    except CatalogValidationError as error:
        parser.exit(1, f"Catalog rejected: {error.code}\n")
    except (SQLAlchemyError, OSError):
        # Credentials and input strings can be present in exception messages.
        parser.exit(1, "Catalog operation failed; check DB/storage and operator permissions.\n")
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
