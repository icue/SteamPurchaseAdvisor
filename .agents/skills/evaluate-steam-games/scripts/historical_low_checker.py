#!/usr/bin/env python3

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SHARED_LIB = Path(__file__).resolve().parents[3] / "lib"
sys.path.insert(0, str(SHARED_LIB))

from steam_purchase_advisor.config import (  # noqa: E402
    ConfigError,
    ConfigValueError,
    load_config,
)
from steam_purchase_advisor.itad_client import (  # noqa: E402
    STEAM_SHOP_ID,
    USER_AGENT,
    ItadRateLimitError,
    get,
    parse_country_argument,
    post,
)


STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_RETRY_DELAYS = (1.0, 2.0)
HISTORICAL_BUNDLE_LIMIT = 3
RECENT_BUNDLE_DAYS = 365
RECURRENT_BUNDLE_DAYS = 730


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def parse_appid(value: str) -> str:
    appid = value.strip()
    if not appid.isascii() or not appid.isdigit() or int(appid) <= 0:
        raise argparse.ArgumentTypeError("appid must be a positive integer")
    return appid


def parse_package_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdigit() and int(value) > 0:
        return str(int(value))
    return None


def fetch_steam_products(appid: str, country: str) -> list[str]:
    params = urlencode({"appids": appid, "cc": country, "l": "english"})
    request = Request(
        f"{STEAM_APPDETAILS_URL}?{params}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    last_error: Exception | None = None

    for attempt in range(len(STEAM_RETRY_DELAYS) + 1):
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
            entry = payload.get(appid) if isinstance(payload, dict) else None
            data = entry.get("data") if isinstance(entry, dict) and entry.get("success") else None
            if not isinstance(data, dict):
                raise RuntimeError("Steam returned no app details.")

            package_ids: list[str] = []
            for value in data.get("packages", []):
                package_id = parse_package_id(value)
                if package_id:
                    package_ids.append(package_id)

            for group in data.get("package_groups", []):
                if not isinstance(group, dict):
                    continue
                for sub in group.get("subs", []):
                    if not isinstance(sub, dict):
                        continue
                    package_id = parse_package_id(sub.get("packageid"))
                    if package_id:
                        package_ids.append(package_id)

            products = [f"app/{appid}"]
            products.extend(f"sub/{package_id}" for package_id in package_ids)
            return list(dict.fromkeys(products))
        except HTTPError as exc:
            last_error = exc
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt == len(STEAM_RETRY_DELAYS):
                break
        except (URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt == len(STEAM_RETRY_DELAYS):
                break

        time.sleep(STEAM_RETRY_DELAYS[attempt])

    detail = str(last_error) if last_error else "unknown error"
    raise RuntimeError(f"Steam package discovery failed: {detail}")


def resolve_steam_products_to_itad_ids(
    api_key: str, appid: str, products: list[str]
) -> tuple[str | None, list[str]]:
    data = post(f"/lookup/id/shop/{STEAM_SHOP_ID}/v1", api_key, products)
    if not isinstance(data, dict):
        raise RuntimeError("ITAD returned an invalid product lookup response.")

    primary_id = data.get(f"app/{appid}")
    if not isinstance(primary_id, str) or not primary_id:
        primary_id = None

    aliases: list[str] = []
    for product in products:
        itad_id = data.get(product)
        if isinstance(itad_id, str) and itad_id:
            aliases.append(itad_id)
    return primary_id, list(dict.fromkeys(aliases))


def get_price_overview(
    api_key: str, itad_id: str, country: str
) -> dict[str, Any]:
    data = post(
        "/games/overview/v2",
        api_key,
        [itad_id],
        params={"country": country, "vouchers": "true"},
    )
    prices = data.get("prices", []) if isinstance(data, dict) else []
    for price in prices:
        if isinstance(price, dict) and price.get("id") == itad_id:
            return price
    raise RuntimeError(f"No price overview returned for ITAD game ID {itad_id}.")


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


def price_unavailable_fields(
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
        "itad_url": None,
        "is_historical_low": None,
        "current_price": None,
        "regular_price": None,
        "discount_percent": None,
        "historical_low_price": None,
    }
    result["report_country_error"] = report_country_error
    if retry_after:
        result["retry_after"] = retry_after
    return result


def bundle_unavailable_fields(
    reason: str,
    message: str,
    *,
    retry_after: str | None = None,
) -> dict[str, Any]:
    return {
        "bundle_status": "unavailable",
        "bundle_reason": reason,
        "bundle_message": message,
        "bundle_retry_after": retry_after,
        "bundle_lookup": {
            "steam_package_status": "unavailable",
            "itad_alias_count": 0,
            "queried_alias_count": 0,
        },
        "bundle_summary": {
            "total_count": None,
            "active_count": None,
            "expired_count": None,
            "unknown_count": None,
            "expired_within_365_days": None,
            "expired_within_730_days": None,
            "recurrent_recent": None,
        },
        "active_bundles": [],
        "historical_bundles": [],
        "unknown_bundles": [],
        "historical_bundles_truncated": None,
        "bundle_errors": [{"reason": reason, "message": message}],
    }


def unavailable_result(
    reason: str,
    message: str,
    country: str | None,
    report_country: str | None,
    *,
    report_country_error: str | None = None,
    retry_after: str | None = None,
) -> dict[str, Any]:
    return {
        **price_unavailable_fields(
            reason,
            message,
            country,
            report_country,
            report_country_error=report_country_error,
            retry_after=retry_after,
        ),
        **bundle_unavailable_fields(reason, message, retry_after=retry_after),
    }


def build_price_result(
    api_key: str,
    primary_itad_id: str | None,
    country: str,
    report_country: str | None,
    report_country_error: str | None,
) -> dict[str, Any]:
    if primary_itad_id is None:
        return price_unavailable_fields(
            "itad_request_failed",
            "Could not resolve the Steam app product to an ITAD game ID.",
            country,
            report_country,
            report_country_error=report_country_error,
        )

    try:
        overview = get_price_overview(api_key, primary_itad_id, country)
        current_offer = overview.get("current")
        current_price = extract_price(current_offer)
        regular_price = extract_money(
            current_offer.get("regular") if isinstance(current_offer, dict) else None
        )
        discount_percent = extract_discount_percent(
            current_offer, current_price, regular_price
        )
        historical_low_price = extract_price(overview.get("lowest"))
        itad_url = overview.get("urls", {}).get("game")
        require_comparable_prices(current_price, historical_low_price)
    except ItadRateLimitError as exc:
        return price_unavailable_fields(
            "itad_rate_limited",
            str(exc),
            country,
            report_country,
            report_country_error=report_country_error,
            retry_after=exc.retry_after,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return price_unavailable_fields(
            "itad_request_failed",
            str(exc),
            country,
            report_country,
            report_country_error=report_country_error,
        )

    is_historical_low = Decimal(str(current_price["amount"])) <= Decimal(
        str(historical_low_price["amount"])
    )
    return {
        "price_status": "available",
        "reason": None,
        "message": None,
        "country": country,
        "report_country": report_country,
        "report_country_error": report_country_error,
        "itad_url": itad_url,
        "is_historical_low": is_historical_low,
        "current_price": current_price,
        "regular_price": regular_price,
        "discount_percent": discount_percent,
        "historical_low_price": historical_low_price,
    }


def parse_itad_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def bundle_key(bundle: dict[str, Any]) -> tuple[str, str]:
    bundle_id = bundle.get("id")
    if bundle_id is not None:
        return ("id", str(bundle_id))
    details = bundle.get("details_url")
    if isinstance(details, str) and details:
        return ("details", details)
    return ("fallback", f"{bundle.get('title')}|{bundle.get('publish')}")


def normalize_qualifying_tier_prices(
    bundle: dict[str, Any], alias_id: str
) -> list[dict[str, Any]]:
    prices: list[dict[str, Any]] = []
    seen: set[str] = set()
    tiers = bundle.get("tiers")
    if not isinstance(tiers, list):
        return prices

    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        games = tier.get("games")
        if not isinstance(games, list) or not any(
            isinstance(game, dict) and game.get("id") == alias_id for game in games
        ):
            continue
        price = tier.get("price")
        normalized = {
            "amount": price.get("amount") if isinstance(price, dict) else None,
            "currency": price.get("currency") if isinstance(price, dict) else None,
            "addon": bool(tier.get("addon", False)),
        }
        key = json.dumps(normalized, sort_keys=True, ensure_ascii=True)
        if key not in seen:
            seen.add(key)
            prices.append(normalized)
    return prices


def normalize_bundle(
    bundle: dict[str, Any], alias_id: str, availability: str
) -> dict[str, Any]:
    page = bundle.get("page")
    counts = bundle.get("counts")
    return {
        "id": bundle.get("id"),
        "title": bundle.get("title"),
        "provider": page.get("name") if isinstance(page, dict) else None,
        "details_url": bundle.get("details"),
        "offer_url": bundle.get("url"),
        "publish": bundle.get("publish"),
        "expiry": bundle.get("expiry"),
        "availability": availability,
        "game_count": counts.get("games") if isinstance(counts, dict) else None,
        "note": bundle.get("note"),
        "qualifying_tier_prices": normalize_qualifying_tier_prices(bundle, alias_id),
    }


def merge_bundle(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    rank = {"expired": 0, "unknown": 1, "active": 2}
    if rank.get(incoming["availability"], 1) > rank.get(existing["availability"], 1):
        existing["availability"] = incoming["availability"]

    for field in (
        "title",
        "provider",
        "details_url",
        "offer_url",
        "publish",
        "expiry",
        "game_count",
        "note",
    ):
        if existing.get(field) in (None, "") and incoming.get(field) not in (None, ""):
            existing[field] = incoming[field]

    seen = {
        json.dumps(price, sort_keys=True, ensure_ascii=True)
        for price in existing["qualifying_tier_prices"]
    }
    for price in incoming["qualifying_tier_prices"]:
        key = json.dumps(price, sort_keys=True, ensure_ascii=True)
        if key not in seen:
            seen.add(key)
            existing["qualifying_tier_prices"].append(price)


def load_alias_bundles(
    api_key: str, alias_id: str, country: str, now: datetime
) -> tuple[list[dict[str, Any]] | None, list[dict[str, str]], str | None]:
    errors: list[dict[str, str]] = []
    retry_after: str | None = None
    try:
        bundles = get(
            "/games/bundles/v2",
            api_key,
            params={"id": alias_id, "country": country, "expired": "true"},
        )
        if not isinstance(bundles, list):
            raise RuntimeError("ITAD returned an invalid bundles response.")
    except ItadRateLimitError as exc:
        return None, [
            {"reason": "itad_rate_limited", "message": str(exc), "itad_id": alias_id}
        ], exc.retry_after
    except (RuntimeError, OSError, ValueError) as exc:
        return None, [
            {"reason": "itad_bundle_request_failed", "message": str(exc), "itad_id": alias_id}
        ], None

    needs_disambiguation = any(
        not isinstance(bundle, dict) or parse_itad_datetime(bundle.get("expiry")) is None
        for bundle in bundles
    )
    active_ids: set[Any] = set()
    active_lookup_complete = not needs_disambiguation

    if needs_disambiguation:
        try:
            active_bundles = get(
                "/games/bundles/v2",
                api_key,
                params={"id": alias_id, "country": country, "expired": "false"},
            )
            if not isinstance(active_bundles, list):
                raise RuntimeError("ITAD returned an invalid active-bundles response.")
            active_ids = {
                bundle.get("id") for bundle in active_bundles if isinstance(bundle, dict)
            }
            active_lookup_complete = True
        except ItadRateLimitError as exc:
            retry_after = exc.retry_after
            errors.append(
                {"reason": "itad_rate_limited", "message": str(exc), "itad_id": alias_id}
            )
        except (RuntimeError, OSError, ValueError) as exc:
            errors.append(
                {
                    "reason": "itad_active_bundle_request_failed",
                    "message": str(exc),
                    "itad_id": alias_id,
                }
            )

    normalized: list[dict[str, Any]] = []
    for bundle in bundles:
        if not isinstance(bundle, dict):
            errors.append(
                {
                    "reason": "invalid_bundle_record",
                    "message": "ITAD returned a non-object bundle record.",
                    "itad_id": alias_id,
                }
            )
            continue
        expiry = parse_itad_datetime(bundle.get("expiry"))
        if expiry is not None:
            availability = "active" if expiry > now else "expired"
        elif active_lookup_complete:
            availability = "active" if bundle.get("id") in active_ids else "expired"
        else:
            availability = "unknown"
        normalized.append(normalize_bundle(bundle, alias_id, availability))
    return normalized, errors, retry_after


def bundle_sort_timestamp(bundle: dict[str, Any]) -> float:
    parsed = parse_itad_datetime(bundle.get("expiry")) or parse_itad_datetime(
        bundle.get("publish")
    )
    return parsed.timestamp() if parsed else float("-inf")


def build_bundle_result(
    api_key: str,
    aliases: list[str],
    country: str,
    *,
    package_status: str,
    package_error: str | None,
) -> dict[str, Any]:
    if not aliases:
        result = bundle_unavailable_fields(
            "itad_request_failed",
            "Could not resolve any Steam app or package product to an ITAD game ID.",
        )
        result["bundle_lookup"]["steam_package_status"] = package_status
        if package_error:
            result["bundle_errors"].insert(
                0,
                {"reason": "steam_package_lookup_failed", "message": package_error},
            )
        return result

    now = datetime.now(timezone.utc)
    errors: list[dict[str, str]] = []
    if package_error:
        errors.append({"reason": "steam_package_lookup_failed", "message": package_error})
    retry_after: str | None = None
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    queried_alias_count = 0

    for alias_id in aliases:
        bundles, alias_errors, alias_retry_after = load_alias_bundles(
            api_key, alias_id, country, now
        )
        errors.extend(alias_errors)
        if alias_retry_after and retry_after is None:
            retry_after = alias_retry_after
        if bundles is None:
            continue
        queried_alias_count += 1
        for bundle in bundles:
            key = bundle_key(bundle)
            if key in merged:
                merge_bundle(merged[key], bundle)
            else:
                merged[key] = bundle

    if queried_alias_count == 0:
        reason = errors[0]["reason"] if errors else "itad_bundle_request_failed"
        message = errors[0]["message"] if errors else "No bundle query completed."
        result = bundle_unavailable_fields(reason, message, retry_after=retry_after)
        result["bundle_lookup"] = {
            "steam_package_status": package_status,
            "itad_alias_count": len(aliases),
            "queried_alias_count": 0,
        }
        result["bundle_errors"] = errors
        return result

    all_bundles = list(merged.values())
    active = sorted(
        (bundle for bundle in all_bundles if bundle["availability"] == "active"),
        key=bundle_sort_timestamp,
    )
    expired = sorted(
        (bundle for bundle in all_bundles if bundle["availability"] == "expired"),
        key=bundle_sort_timestamp,
        reverse=True,
    )
    unknown = sorted(
        (bundle for bundle in all_bundles if bundle["availability"] == "unknown"),
        key=bundle_sort_timestamp,
        reverse=True,
    )

    recent_cutoff = now - timedelta(days=RECENT_BUNDLE_DAYS)
    recurrent_cutoff = now - timedelta(days=RECURRENT_BUNDLE_DAYS)
    expired_within_365 = sum(
        1
        for bundle in expired
        if (expiry := parse_itad_datetime(bundle.get("expiry"))) is not None
        and expiry >= recent_cutoff
    )
    expired_within_730 = sum(
        1
        for bundle in expired
        if (expiry := parse_itad_datetime(bundle.get("expiry"))) is not None
        and expiry >= recurrent_cutoff
    )
    status = "available" if not errors else "partial"
    return {
        "bundle_status": status,
        "bundle_reason": None if status == "available" else "partial_bundle_coverage",
        "bundle_message": None
        if status == "available"
        else (
            "Some Steam package or ITAD bundle lookups failed; "
            "returned bundle coverage is partial."
        ),
        "bundle_retry_after": retry_after,
        "bundle_lookup": {
            "steam_package_status": package_status,
            "itad_alias_count": len(aliases),
            "queried_alias_count": queried_alias_count,
        },
        "bundle_summary": {
            "total_count": len(all_bundles),
            "active_count": len(active),
            "expired_count": len(expired),
            "unknown_count": len(unknown),
            "expired_within_365_days": expired_within_365,
            "expired_within_730_days": expired_within_730,
            "recurrent_recent": expired_within_365 >= 1 and expired_within_730 >= 2,
        },
        "active_bundles": active,
        "historical_bundles": expired[:HISTORICAL_BUNDLE_LIMIT],
        "unknown_bundles": unknown,
        "historical_bundles_truncated": len(expired) > HISTORICAL_BUNDLE_LIMIT,
        "bundle_errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check a Steam game's current regional price and historical low, "
            "and retrieve its ITAD bundle context."
        )
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
                    "ITAD price and bundle data are unavailable because "
                    "itad_api_key is not configured.",
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
                    "pricing_country is required for ITAD price and bundle data.",
                    None,
                    report_country,
                    report_country_error=report_country_error,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    package_status = "available"
    package_error: str | None = None
    try:
        steam_products = fetch_steam_products(args.appid, country)
    except RuntimeError as exc:
        steam_products = [f"app/{args.appid}"]
        package_status = "unavailable"
        package_error = str(exc)

    try:
        primary_itad_id, aliases = resolve_steam_products_to_itad_ids(
            api_key, args.appid, steam_products
        )
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

    price_result = build_price_result(
        api_key,
        primary_itad_id,
        country,
        report_country,
        report_country_error,
    )
    bundle_result = build_bundle_result(
        api_key,
        aliases,
        country,
        package_status=package_status,
        package_error=package_error,
    )
    print(
        json.dumps(
            {**price_result, **bundle_result},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

