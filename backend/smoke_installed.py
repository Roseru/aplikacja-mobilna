"""Run with Python -I outside the checkout, including an image without OS tzdata."""

import asyncio
from importlib.resources import files
from zoneinfo import ZoneInfo, reset_tzpath

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from calorie_app.modules.diary.validation import validate_payload
from calorie_app.modules.profiles.schemas import EstimateInput
from calorie_app.modules.profiles.service import estimate_energy


def main():
    # This checks the declared Python tzdata fallback even on a host with IANA files.
    reset_tzpath(())
    ZoneInfo.clear_cache()
    assert ZoneInfo("Europe/Warsaw").key == "Europe/Warsaw"
    assert files("calorie_app.modules.catalog.resources").joinpath("domain.schema.json").is_file()
    assert files("calorie_app.modules.catalog.resources").joinpath("sync.schema.json").is_file()
    validate_payload(
        {
            "weight_kg": "80",
            "occurred_at": "2026-10-10T10:00:00Z",
            "local_date": "2026-10-10",
            "time_zone": "Europe/Warsaw",
        },
        "Weight",
    )
    data = EstimateInput(
        age_years=30,
        height_cm="180",
        weight_kg="80",
        equation_variant="plus_5",
        activity_class="line",
    )
    assert estimate_energy(data)["maintenance_kcal"] == "3204"
    app = create_app(Settings(database_url="postgresql+psycopg://unused@127.0.0.1:1/unused"))
    assert "/api/v1/me/bootstrap" in app.openapi()["paths"]
    assert "/api/v1/products" in app.openapi()["paths"]
    assert "/api/v1/sync/push" in app.openapi()["paths"]
    assert "/api/v1/sync/pull" in app.openapi()["paths"]
    app.state.engine.dispose()
    asyncio.run(app.state.oidc_verifier.close())
    print("PASS installed E4 runtime: bundled schemas, tzdata, calculator, OIDC and sync routes")


if __name__ == "__main__":
    main()
