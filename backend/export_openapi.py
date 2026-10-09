"""Export implemented operations only; does not open a DB connection."""

import json
from pathlib import Path

from calorie_app.core.config import Settings
from calorie_app.main import create_app

if __name__ == "__main__":
    settings = Settings(database_url="postgresql+psycopg://unused@localhost/unused")
    app = create_app(settings)
    try:
        Path(__file__).with_name("openapi.json").write_text(
            json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    finally:
        app.state.engine.dispose()
