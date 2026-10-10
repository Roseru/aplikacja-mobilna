"""Repository convenience entry point; install the backend package first."""

from calorie_app.modules.catalog.offline_import import main

if __name__ == "__main__":
    raise SystemExit(main())
