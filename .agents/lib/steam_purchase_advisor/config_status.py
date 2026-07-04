#!/usr/bin/env python3
"""Print non-secret configuration capability status for skill coordinators."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable


SHARED_LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED_LIB))

from steam_purchase_advisor.config import (  # noqa: E402
    CONFIG_PATH,
    ConfigError,
    ConfigValueError,
    load_config,
)


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(
            json.dumps(
                {
                    "config_present": CONFIG_PATH.is_file(),
                    "config_error": exc.code,
                    "steam_id_configured": False,
                    "itad_api_key_configured": False,
                    "pricing_country": None,
                    "report_country": None,
                },
                indent=2,
            )
        )
        return 2

    errors: dict[str, str] = {}

    def read(field: str, getter: Callable[[], Any]) -> Any:
        try:
            return getter()
        except ConfigValueError as exc:
            errors[field] = exc.code
            return None

    steam_id = read("steam_id", lambda: config.steam_id)
    api_key = read("itad_api_key", lambda: config.itad_api_key)
    pricing_country = read("pricing_country", lambda: config.pricing_country)
    report_country = read("report_country", lambda: config.report_country)

    print(
        json.dumps(
            {
                "config_present": CONFIG_PATH.is_file(),
                "config_error": None,
                "steam_id_configured": steam_id is not None,
                "itad_api_key_configured": api_key is not None,
                "pricing_country": pricing_country,
                "report_country": report_country,
                "field_errors": errors,
            },
            indent=2,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
