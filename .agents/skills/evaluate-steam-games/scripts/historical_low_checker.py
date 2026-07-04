#!/usr/bin/env python3

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


SHARED_LIB = Path(__file__).resolve().parents[3] / "lib"
sys.path.insert(0, str(SHARED_LIB))

from steam_purchase_advisor.config import (  # noqa: E402
    ConfigError,
    ConfigValueError,
    load_config,
)
from steam_purchase_advisor.itad_client import (  # noqa: E402
    STEAM_SHOP_ID,
    ItadRateLimitError,
    parse_country_argument,
    post,
)


def parse_appid(value: str) -> str:
    appid = value.strip()
    if not appid.isascii() or not appid.isdigit() or int(appid) <= 0:
        raise argparse.ArgumentTypeError("appid must be a positive integer")
    return appid


def resolve_steam_appid_to_itad_id(api_key: str, appid: str) -> str:
    steam_id = f"app/{appid}"
    data = post(f"/lookup/id/shop/{STEAM_SHOP_ID}/v1", api_key, [steam_id])
    itad_id = data.get(steam_id)
    if not itad_id:
        raise RuntimeError(f"Could not resolve Steam appid {appid} to an ITAD game ID.")
    return itad_id


def get_price_overview(
    api_key: str, itad_id: str, country: str
) -> dict[str, Any]:
    data = post(
        "/games/overview/v2",
        api_key,
        [itad_id],
        params={"country": country, "vouchers": "true"},
    )
    prices = data.get("prices", [])
    if not prices:
        raise RuntimeError(f"No price overview returned for ITAD game ID {itad_id}.")
    return prices[0]


def extract_money(price: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(price, dict):
        return None
    amount = price.get("amount")
    currency = price.get("currency")
    if amount is None or not currency:
        return None
    return {"amount": amount, "currency": currency}


def extract_price(container: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(container, dict):
        return None
    return extract_money(container.get("price"))


def json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def extract_discount_percent(
    current_offer: dict[str, Any] | None,
    current_price: dict[str, Any] | None,
    regular_price: dict[str, Any] | None,
) -> int | float | None:
    if isinstance(current_offer, dict) and current_offer.get("cut") is not None:
        try:
            cut = Decimal(str(current_offer["cut"]))
        except (ValueError, ArithmeticError):
            cut = None
        if cut is not None and cut.is_finite() and Decimal("0") <= cut <= Decimal("100"):
            return json_number(cut)

    if current_price is None or regular_price is None:
        return None
    if current_price["currency"] != regular_price["currency"]:
        return None

    try:
        current_amount = Decimal(str(current_price["amount"]))
        regular_amount = Decimal(str(regular_price["amount"]))
    except (ValueError, ArithmeticError):
        return None

    if (
        not current_amount.is_finite()
        or not regular_amount.is_finite()
        or regular_amount <= 0
        or current_amount < 0
        or current_amount > regular_amount
    ):
        return None

    calculated = (
        (regular_amount - current_amount) / regular_amount * Decimal("100")
    ).quantize(Decimal("0.01"))
    return json_number(calculated)


def require_price(price: dict[str, Any] | None, label: str) -> None:
    if price is None:
        raise RuntimeError(f"Missing {label} price.")
    if price.get("amount") is None:
        raise RuntimeError(f"Missing amount for {label} price.")
    if not price.get("currency"):
        raise RuntimeError(f"Missing currency for {label} price.")


def require_comparable_prices(
    current_price: dict[str, Any] | None,
    historical_low_price: dict[str, Any] | None,
) -> None:
    require_price(current_price, "current")
    require_price(historical_low_price, "historical low")
    if current_price["currency"] != historical_low_price["currency"]:
        raise RuntimeError(
            "Cannot compare prices with different currencies: "
            f"{current_price['currency']} and {historical_low_price['currency']}."
        )


def unavailable_result(
    reason: str,
    message: str,
    country: str | None,
    report_country: str | None,
    *,
    report_country_error: str | None = None,
    retry_after: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "price_status": "unavailable",
        "reason": reason,
        "message": message,
        "country": country,
        "report_country": report_country,
        "is_historical_low": None,
        "current_price": None,
        "regular_price": None,
        "discount_percent": None,
        "historical_low_price": None,
    }
    if report_country_error:
        result["report_country_error"] = report_country_error
    if retry_after:
        result["retry_after"] = retry_after
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check a Steam game's current regional price against its ITAD historical low."
    )
    parser.add_argument("--appid", required=True, type=parse_appid, help="Steam appid, e.g. 220")
    parser.add_argument(
        "--country",
        type=parse_country_argument,
        help="Pricing country for this request; overrides config.json.",
    )
    parser.add_argument(
        "--report-country",
        type=parse_country_argument,
        help="Report country for this request; overrides config.json.",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        print(
            json.dumps(
                unavailable_result(exc.code, str(exc), args.country, args.report_country),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    report_country_error: str | None = None
    try:
        report_country = args.report_country or config.report_country
    except ConfigValueError as exc:
        report_country = None
        report_country_error = exc.code

    pricing_country_error: ConfigValueError | None = None
    try:
        country = args.country or config.pricing_country
    except ConfigValueError as exc:
        country = args.country
        pricing_country_error = exc

    try:
        api_key = config.itad_api_key
    except ConfigValueError as exc:
        print(
            json.dumps(
                unavailable_result(
                    exc.code,
                    str(exc),
                    country,
                    report_country,
                    report_country_error=report_country_error,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if api_key is None:
        print(
            json.dumps(
                unavailable_result(
                    "missing_itad_api_key",
                    "ITAD price data is unavailable because itad_api_key is not configured.",
                    country,
                    report_country,
                    report_country_error=report_country_error,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if pricing_country_error is not None:
        print(
            json.dumps(
                unavailable_result(
                    pricing_country_error.code,
                    str(pricing_country_error),
                    None,
                    report_country,
                    report_country_error=report_country_error,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if country is None:
        print(
            json.dumps(
                unavailable_result(
                    "missing_pricing_country",
                    "pricing_country is required for ITAD price data.",
                    None,
                    report_country,
                    report_country_error=report_country_error,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    try:
        itad_id = resolve_steam_appid_to_itad_id(api_key, args.appid)
        overview = get_price_overview(api_key, itad_id, country)
        current_offer = overview.get("current")
        current_price = extract_price(current_offer)
        regular_price = extract_money(
            current_offer.get("regular") if isinstance(current_offer, dict) else None
        )
        discount_percent = extract_discount_percent(
            current_offer, current_price, regular_price
        )
        historical_low_price = extract_price(overview.get("lowest"))
        require_comparable_prices(current_price, historical_low_price)
    except ItadRateLimitError as exc:
        print(
            json.dumps(
                unavailable_result(
                    "itad_rate_limited",
                    str(exc),
                    country,
                    report_country,
                    report_country_error=report_country_error,
                    retry_after=exc.retry_after,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        print(
            json.dumps(
                unavailable_result(
                    "itad_request_failed",
                    str(exc),
                    country,
                    report_country,
                    report_country_error=report_country_error,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    is_historical_low = Decimal(str(current_price["amount"])) <= Decimal(
        str(historical_low_price["amount"])
    )

    print(
        json.dumps(
            {
                "price_status": "available",
                "reason": None,
                "country": country,
                "report_country": report_country,
                "report_country_error": report_country_error,
                "is_historical_low": is_historical_low,
                "current_price": current_price,
                "regular_price": regular_price,
                "discount_percent": discount_percent,
                "historical_low_price": historical_low_price,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

