"""Unicode scalar text and bounded civil-time conversion shared by wire validators."""

import json
from datetime import datetime
from functools import cache
from importlib.resources import files
from zoneinfo import ZoneInfo

# ECMA-262 compatible, also correct for Python's scalar representation. The
# pair alternative permits valid non-BMP characters in UTF-16 schema engines.
UNICODE_TEXT_PATTERN = r"^(?:[^\u0000\uD800-\uDFFF]|[\uD800-\uDBFF][\uDC00-\uDFFF])*(?![\s\S])"


@cache
def common_pattern(definition: str) -> str:
    """DTOs and schema validators read the same bundled normative expression."""
    source = files("calorie_app.modules.catalog.resources").joinpath("common.schema.json")
    return json.loads(source.read_text(encoding="utf-8"))["$defs"][definition]["pattern"]


def validate_json_strings(value):
    """Do not normalize or repair text: it must encode and store losslessly."""
    if isinstance(value, str):
        if "\x00" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("invalid_unicode_text")
    elif isinstance(value, dict):
        for key, item in value.items():
            validate_json_strings(key)
            validate_json_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            validate_json_strings(item)


def local_day(instant: str, time_zone: str):
    try:
        return datetime.fromisoformat(instant).astimezone(ZoneInfo(time_zone)).date()
    except (ValueError, OverflowError):
        raise ValueError("local_time_out_of_range") from None
