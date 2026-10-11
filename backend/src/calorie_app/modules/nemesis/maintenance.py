"""One bounded lifecycle maintenance invocation with a dedicated least-privilege LOGIN."""

import argparse
import json

from sqlalchemy import create_engine, text

from calorie_app.core.config import Settings


def maintain(engine, batch=100):
    if type(batch) is not int or not 1 <= batch <= 1000:
        raise ValueError("Nemesis batch must be in 1..1000")
    with engine.begin() as connection:
        result = connection.scalar(text("SELECT app.e8n_maintain(:batch)"), {"batch": batch})
    return result


def main():
    parser = argparse.ArgumentParser(description="Bounded Nemesis expiry/end/response cleanup")
    parser.add_argument("--batch", type=int, default=100)
    args = parser.parse_args()
    settings = Settings()
    engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True)
    try:
        print(json.dumps(maintain(engine, args.batch), sort_keys=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
