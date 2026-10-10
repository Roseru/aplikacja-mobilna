"""Operator harness: persistent local files; no credentials in arguments or SQLite."""

import argparse
import json
import os
from pathlib import Path

from . import SyncHTTP, SyncStore
from .wire import AdaptationRequired, loads


def main():
    parser = argparse.ArgumentParser(description="Referencyjny klient E4 - osoba 2")
    parser.add_argument("--database", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register")
    register.add_argument("--issuer")
    register.add_argument("--subject")
    select = sub.add_parser("select")
    select.add_argument("scope")
    boot = sub.add_parser("bootstrap-result")
    boot.add_argument("input")
    source = sub.add_parser("source")
    source.add_argument("entity_type")
    source.add_argument("entity_id")
    source.add_argument("action")
    source.add_argument("input")
    source.add_argument("--source-id")
    materialize = sub.add_parser("materialize")
    materialize.add_argument("source_id")
    materialize.add_argument("--metadata")
    for name in ("pull", "push", "resume-pull"):
        network = sub.add_parser(name)
        network.add_argument("--api", required=True)
        if name == "pull":
            network.add_argument("--full", action="store_true")
            network.add_argument("--limit", type=int, default=500)
        if name == "resume-pull":
            network.add_argument("session_id")
    sub.add_parser("status")
    args = parser.parse_args()
    with SyncStore(args.database) as store:
        if args.command == "register":
            print(store.register(issuer=args.issuer, subject=args.subject))
        elif args.command == "select":
            store.select(args.scope)
        elif args.command == "bootstrap-result":
            active = store.db.execute("SELECT * FROM active WHERE id=1").fetchone()
            store.bootstrap(
                active["scope"],
                loads(Path(args.input).read_text(encoding="utf-8")),
                lease_generation=active["generation"],
            )
        elif args.command == "source":
            scope = store.db.execute("SELECT scope FROM active WHERE id=1").fetchone()[0]
            print(
                store.import_source(
                    scope,
                    args.entity_type,
                    args.entity_id,
                    args.action,
                    Path(args.input).read_text(encoding="utf-8"),
                    source_id=args.source_id,
                )
            )
        elif args.command == "materialize":
            try:
                metadata = (
                    loads(Path(args.metadata).read_text(encoding="utf-8"))
                    if args.metadata
                    else None
                )
                result = store.materialize(store.capture(), args.source_id, metadata=metadata)
                print(json.dumps({"operation_id": result["operation_id"]}))
            except AdaptationRequired as error:
                store.mark_review(args.source_id, str(error))
                raise
        elif args.command == "status":
            result = {
                table: store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("originals", "drafts", "wire_ops", "shadow", "pages", "conflicts")
            }
            print(json.dumps(result))
        else:
            token = os.environ["SYNC_ACCESS_TOKEN"]
            context = store.capture()
            http = SyncHTTP(
                args.api, token_supplier=lambda captured: token if captured == context else None
            )
            try:
                if args.command == "push":
                    http.push(store, context)
                elif args.command == "pull":
                    print(http.pull(store, context, full=args.full, limit=args.limit))
                else:
                    while not http.pull_page(store, context, args.session_id):
                        pass
            finally:
                http.close()


if __name__ == "__main__":
    main()
