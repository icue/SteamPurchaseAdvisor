#!/usr/bin/env python3
"""Resolve localized Steam Store titles for a list of app IDs."""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SHARED_LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED_LIB))

from steam_purchase_advisor.config import (  # noqa: E402
    ConfigError,
    ConfigValueError,
    load_config,
    normalize_country,
)
from steam_purchase_advisor.itad_client import USER_AGENT  # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
DEFAULT_MAX_WORKERS = 4
MAX_ALLOWED_WORKERS = 8
RETRY_DELAYS = (1.0, 2.0)

STEAM_LANGUAGES = {
    "arabic",
    "bulgarian",
    "schinese",
    "tchinese",
    "czech",
    "danish",
    "dutch",
    "english",
    "finnish",
    "french",
    "german",
    "greek",
    "hungarian",
    "indonesian",
    "italian",
    "japanese",
    "koreana",
    "malay",
    "norwegian",
    "polish",
    "portuguese",
    "brazilian",
    "romanian",
    "russian",
    "spanish",
    "latam",
    "swedish",
    "thai",
    "turkish",
    "ukrainian",
    "vietnamese",
}

COUNTRY_TO_STEAM_LANGUAGE = {
    "AE": "arabic",
    "AR": "latam",
    "AT": "german",
    "AU": "english",
    "BE": "french",
    "BG": "bulgarian",
    "BH": "arabic",
    "BO": "latam",
    "BR": "brazilian",
    "BY": "russian",
    "CA": "english",
    "CH": "german",
    "CL": "latam",
    "CN": "schinese",
    "CO": "latam",
    "CR": "latam",
    "CU": "latam",
    "CY": "greek",
    "CZ": "czech",
    "DE": "german",
    "DK": "danish",
    "DO": "latam",
    "DZ": "arabic",
    "EC": "latam",
    "EG": "arabic",
    "ES": "spanish",
    "FI": "finnish",
    "FR": "french",
    "GB": "english",
    "GR": "greek",
    "GT": "latam",
    "HK": "tchinese",
    "HN": "latam",
    "HU": "hungarian",
    "ID": "indonesian",
    "IE": "english",
    "IN": "english",
    "IQ": "arabic",
    "IT": "italian",
    "JO": "arabic",
    "JP": "japanese",
    "KR": "koreana",
    "KW": "arabic",
    "KZ": "russian",
    "LB": "arabic",
    "MA": "arabic",
    "MO": "tchinese",
    "MX": "latam",
    "MY": "malay",
    "NI": "latam",
    "NL": "dutch",
    "NO": "norwegian",
    "NZ": "english",
    "OM": "arabic",
    "PA": "latam",
    "PE": "latam",
    "PH": "english",
    "PL": "polish",
    "PR": "latam",
    "PT": "portuguese",
    "PY": "latam",
    "QA": "arabic",
    "RO": "romanian",
    "RU": "russian",
    "SA": "arabic",
    "SE": "swedish",
    "SG": "english",
    "SV": "latam",
    "TH": "thai",
    "TN": "arabic",
    "TR": "turkish",
    "TW": "tchinese",
    "UA": "ukrainian",
    "US": "english",
    "UY": "latam",
    "VE": "latam",
    "VN": "vietnamese",
    "ZA": "english",
}


def parse_appid(value: str) -> int:
    if not value.isascii() or not value.isdigit() or int(value) <= 0:
        raise argparse.ArgumentTypeError("each appid must be a positive integer")
    return int(value)


def parse_report_country(value: str) -> str:
    try:
        return normalize_country(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_max_workers(value: str) -> int:
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("max-workers must be an integer") from exc
    if not 1 <= workers <= MAX_ALLOWED_WORKERS:
        raise argparse.ArgumentTypeError(
            f"max-workers must be between 1 and {MAX_ALLOWED_WORKERS}"
        )
    return workers


def emit_error(reason: str, message: str) -> None:
    print(
        json.dumps({"error": "title_resolution_unavailable", "reason": reason, "message": message}),
        file=sys.stderr,
    )


def steam_language_for_country(country: str) -> str:
    """Return Steam's API language code, using English as the platform fallback."""
    return COUNTRY_TO_STEAM_LANGUAGE.get(country, "english")


def fetch_title(appid: int, report_country: str, language: str) -> dict[str, Any]:
    params = urlencode(
        {
            "appids": appid,
            "cc": report_country,
            "l": language,
        }
    )
    request = Request(
        f"{APPDETAILS_URL}?{params}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )

    def unavailable(error: str) -> dict[str, Any]:
        return {
            "appid": appid,
            "name": None,
            "url": f"https://store.steampowered.com/app/{appid}/",
            "error": error,
        }

    attempts = len(RETRY_DELAYS) + 1
    last_error = "steam_title_request_failed"
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                return unavailable("steam_invalid_response")
            entry = payload.get(str(appid))
            if not isinstance(entry, dict):
                return unavailable("steam_invalid_response")
            if entry.get("success") is False:
                return unavailable("steam_title_not_returned")
            if entry.get("success") is not True:
                return unavailable("steam_invalid_response")
            data = entry.get("data")
            if not isinstance(data, dict):
                return unavailable("steam_invalid_response")
            name = data.get("name") if isinstance(data, dict) else None
            if not isinstance(name, str) or not name.strip():
                return unavailable("steam_title_not_returned")
            return {
                "appid": appid,
                "name": name.strip(),
                "url": (
                    f"https://store.steampowered.com/app/{appid}/"
                    f"?{urlencode({'cc': report_country, 'l': language})}"
                ),
                "error": None,
            }
        except HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            last_error = f"steam_http_{exc.code}"
            if not retryable:
                return unavailable(last_error)
        except json.JSONDecodeError:
            last_error = "steam_invalid_response"
        except (URLError, TimeoutError, OSError):
            last_error = "steam_title_request_failed"

        if attempt == attempts - 1:
            return unavailable(last_error)

        time.sleep(RETRY_DELAYS[attempt])

    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve localized Steam Store titles for app IDs."
    )
    parser.add_argument(
        "--appids",
        nargs="+",
        required=True,
        type=parse_appid,
        help="One or more Steam app IDs.",
    )
    parser.add_argument(
        "--report-country",
        type=parse_report_country,
        help="Title/report country for this request; overrides config.json.",
    )
    parser.add_argument(
        "--language",
        choices=sorted(STEAM_LANGUAGES),
        help="Steam API language override for multilingual countries.",
    )
    parser.add_argument(
        "--max-workers",
        type=parse_max_workers,
        default=DEFAULT_MAX_WORKERS,
        help=(
            f"Maximum simultaneous Store requests "
            f"(default: {DEFAULT_MAX_WORKERS}, max: {MAX_ALLOWED_WORKERS})."
        ),
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        emit_error(exc.code, str(exc))
        return 2

    try:
        report_country = args.report_country or config.report_country
    except ConfigValueError as exc:
        emit_error(exc.code, str(exc))
        return 2

    if report_country is None:
        emit_error(
            "missing_report_country",
            "report_country is required for localized Steam titles.",
        )
        return 2

    language = args.language or steam_language_for_country(report_country)
    appids = list(dict.fromkeys(args.appids))
    results_by_appid: dict[int, dict[str, Any]] = {}

    workers = min(args.max_workers, len(appids))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_title, appid, report_country, language): appid
            for appid in appids
        }
        for future in as_completed(futures):
            appid = futures[future]
            try:
                results_by_appid[appid] = future.result()
            except Exception:
                results_by_appid[appid] = {
                    "appid": appid,
                    "name": None,
                    "url": f"https://store.steampowered.com/app/{appid}/",
                    "error": "unexpected_title_resolution_error",
                }

    print(
        json.dumps(
            {
                "report_country": report_country,
                "steam_language": language,
                "max_workers": workers,
                "results": [results_by_appid[appid] for appid in appids],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

