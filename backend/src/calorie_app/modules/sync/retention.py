"""Bounded technical retention; parents/tombstones remain until account purge."""

import argparse
import json
from uuid import UUID

from sqlalchemy import text


def prune(session, owner_id: UUID, batch: int = 1000) -> dict:
    """Caller owns commit. The DB function verifies active owner and lock order."""
    return session.scalar(
        text("SELECT app.prune_sync(:owner,:batch)"), {"owner": owner_id, "batch": batch}
    )


def main():
    from sqlalchemy.orm import Session

    from calorie_app.core.config import Settings
    from calorie_app.db.session import make_engine

    parser = argparse.ArgumentParser(description="Bounded synchronization technical retention")
    parser.add_argument("owner", type=UUID)
    parser.add_argument(
        "--batch", type=int, default=1000, choices=range(1, 1001), metavar="1..1000"
    )
    args = parser.parse_args()
    engine = make_engine(Settings())
    try:
        with Session(engine) as session:
            result = prune(session, args.owner, args.batch)
            session.commit()
        print(json.dumps(result, sort_keys=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
