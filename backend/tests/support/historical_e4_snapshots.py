"""Published E4 snapshot algorithm for real pre-E5 migration fixtures only.

The immutable source predates E5 admission and E9 capability. Shared domain,
token and model dependencies remain current; the fixture validates their E4
compatibility on the actual historical schema. Production gates are untouched.
The PostgreSQL CI job checks out full history, as existing E9 legacy tests do.
"""

import hashlib
import subprocess
import types
from functools import cache
from pathlib import Path

SOURCE_COMMIT = "83f2feeb86eb9d7fe53ee684ab9069f1f51af353"
SOURCE_PATH = "backend/src/calorie_app/modules/sync/snapshots.py"
SOURCE_SHA256 = "d20c101cb928b7386daed1b7e1e1b8cf892c677975a51cf4745bc0cf4961f12a"
ROOT = Path(__file__).resolve().parents[3]


@cache
def published_e4_snapshots():
    raw = subprocess.run(
        ["git", "show", SOURCE_COMMIT + ":" + SOURCE_PATH],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256, "Historical E4 source changed"
    module = types.ModuleType("published_e4_snapshots_83f2feeb")
    exec(compile(raw, "published-83f2feeb-snapshots.py", "exec"), module.__dict__)
    return module
