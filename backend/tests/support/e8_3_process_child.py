"""Independent real LOGIN process used only by the component evidence suite."""

import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text

# Standalone child scripts do not load pytest.ini pythonpath.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.support.e8_3_postgres import PrivatePostgres  # noqa: E402


def main():
    subject, epoch, count = sys.argv[1], UUID(sys.argv[2]), int(sys.argv[3])
    engine = PrivatePostgres.from_environment().engine("api")
    print("ready", flush=True)
    if sys.stdin.readline().strip() != "go":
        raise RuntimeError("explicit process barrier required")
    statuses = []
    try:
        for _ in range(count):
            with engine.begin() as conn:
                result = conn.scalar(
                    text("SELECT app.e8n_execute(:issuer,:subject,:epoch,'issue',:key,:hash,'{}')"),
                    {
                        "issuer": "https://nemesis-identity.example.test/realm",
                        "subject": subject,
                        "epoch": epoch,
                        "key": uuid4(),
                        "hash": "0" * 64,
                    },
                )
            statuses.append(result["http_status"])
        print(json.dumps(statuses), flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
