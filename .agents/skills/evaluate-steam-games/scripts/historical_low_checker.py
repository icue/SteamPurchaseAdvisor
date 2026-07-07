#!/usr/bin/env python3

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
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
    get,
    parse_country_argument,
    post,
)
from steam_purchase_advisor.steam_price_identity import (  # noqa: E402
    PriceIdentityError,
    SteamAppDetails,
    SteamAppDetailsError,
    fetch_steam_appdetails,
    select_itad_price_identity,
)


HISTORICAL_BUNDLE_LIMIT = 3
RECENT_BUNDLE_DAYS = 365
RECURRENT_BUNDLE_DAYS = 730
SUBSCRIPTION_COUNTRY = "US"
EPIC_SHOP_ID = 16
EPIC_GIVEAWAY_COUNTRY = "US"
EPIC_GIVEAWAY_SINCE = "2017-01-01T00:00:00+00:00"
RELATED_TITLE_SUFFIXES = (
    "Ultimate Edition",
    "Complete Edition",
    "Definitive Edition",
    "Deluxe Edition",
    "Gold Edition",
    "Game of the Year Edition",
    "GOTY Edition",
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def parse_appid(value: str) -> str:
    appid = value.strip()
    if not appid.isascii() or not appid.isdigit() or int(appid) <= 0:
        raise argparse.ArgumentTypeError("appid must be a positive integer")
    return appid


def resolve_steam_products_to_itad_ids(
    api_key: str, products: list[str]
) -> tuple[dict[str, str], list[str]]:
    data = post(f"/lookup/id/shop/{STEAM_SHOP_ID}/v1", api_key, products)
    if not isinstance(data, dict):
        raise RuntimeError("ITAD returned an invalid product lookup response.")

    product_to_itad_id: dict[str, str] = {}
    for product in products:
        itad_id = data.get(product)
        if isinstance(itad_id, str) and itad_id:
            product_to_itad_id[product] = itad_id
    aliases = list(dict.fromkeys(product_to_itad_id.values()))
    return product_to_itad_id, aliases


def get_price_overviews(
    api_key: str, itad_ids: list[str], country: str
) -> dict[str, dict[str, Any]]:
    data = post(
        "/games/overview/v2",
        api_key,
        itad_ids,
        params={
            "country": country,
            "shops": str(STEAM_SHOP_ID),
            "vouchers": "false",
        },
    )
    if not isinstance(data, dict) or not isinstance(data.get("prices"), list):
        raise RuntimeError("ITAD returned an invalid price-overview response.")
    prices = data["prices"]
    overviews: dict[str, dict[str, Any]] = {}
    for price in prices:
        if isinstance(price, dict) and price.get("id") in itad_ids:
            overviews[price["id"]] = price
    return overviews


def get_steam_store_low(
    api_key: str, itad_id: str, country: str
) -> dict[str, Any] | None:
    data = post(
        "/games/storelow/v2",
        api_key,
        [itad_id],
        params={"country": country, "shops": str(STEAM_SHOP_ID)},
    )
    if not isinstance(data, list):
        raise RuntimeError("ITAD returned an invalid store-low response.")
    for entry in data:
        if not isinstance(entry, dict) or entry.get("id") != itad_id:
            continue
        lows = entry.get("lows")
        if not isinstance(lows, list):
            continue
        for low in lows:
            if (
                isinstance(low, dict)
                and isinstance(low.get("shop"), dict)
                and low["shop"].get("id") == STEAM_SHOP_ID
            ):
                return low
    return None


def get_steam_history(
    api_key: str, itad_id: str, country: str
) -> list[dict[str, Any]]:
    data = get(
        "/games/history/v2",
        api_key,
        params={
            "id": itad_id,
            "country": country,
            "shops": str(STEAM_SHOP_ID),
            "since": "2010-01-01T00:00:00+00:00",
        },
    )
    if not isinstance(data, list):
        raise RuntimeError("ITAD returned an invalid history response.")
    return data


def get_epic_history(api_key: str, itad_id: str) -> list[dict[str, Any]]:
    data = get(
        "/games/history/v2",
        api_key,
        params={
            "id": itad_id,
            "country": EPIC_GIVEAWAY_COUNTRY,
            "shops": str(EPIC_SHOP_ID),
            "since": EPIC_GIVEAWAY_SINCE,
        },
    )
    if not isinstance(data, list):
        raise RuntimeError("ITAD returned an invalid Epic history response.")
    return data


def search_itad_games(api_key: str, title: str) -> list[dict[str, Any]]:
    data = get(
        "/games/search/v1",
        api_key,
        params={"title": title, "results": "20"},
    )
    if not isinstance(data, list):
        raise RuntimeError("ITAD returned an invalid game-search response.")
    return [row for row in data if isinstance(row, dict)]


def get_itad_info(api_key: str, itad_id: str) -> dict[str, Any]:
    data = get("/games/info/v2", api_key, params={"id": itad_id})
    if not isinstance(data, dict):
        raise RuntimeError("ITAD returned an invalid game-info response.")
    return data


def collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def derive_related_base_title(title: Any) -> str | None:
    if not isinstance(title, str):
        return None
    normalized = collapse_whitespace(title)
    if not normalized:
        return None

    for suffix in RELATED_TITLE_SUFFIXES:
        pattern = rf"^(.+?)(?:\s*[:\-]\s*|\s+){re.escape(suffix)}$"
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        base_title = collapse_whitespace(match.group(1))
        if len(base_title) >= 3:
            return base_title
        return None
    return None


def normalized_title_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = collapse_whitespace(value)
    return normalized.casefold() if normalized else None


def extract_entity_names(container: dict[str, Any] | None) -> set[str]:
    if not isinstance(container, dict):
        return set()

    names: set[str] = set()
    for field in ("developers", "publishers"):
        values = container.get(field)
        if not isinstance(values, list):
            continue
        for value in values:
            name: Any
            if isinstance(value, dict):
                name = value.get("name")
            else:
                name = value
            key = normalized_title_key(name)
            if key is not None:
                names.add(key)
    return names


def decimal_value_equals(value: Any, target: Decimal) -> bool:
    if value is None:
        return False
    try:
        parsed = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return False
    return parsed.is_finite() and parsed == target


def extract_epic_giveaway_events(
    history: list[dict[str, Any]], itad_id: str, title: str, scope: str
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen_timestamps: set[str] = set()

    for entry in history:
        if not isinstance(entry, dict):
            continue
        timestamp = entry.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.strip():
            continue

        deal = entry.get("deal")
        if not isinstance(deal, dict):
            continue

        price = deal.get("price")
        amount_is_zero = (
            isinstance(price, dict)
            and decimal_value_equals(price.get("amount"), Decimal("0"))
        )
        cut_is_full = decimal_value_equals(deal.get("cut"), Decimal("100"))

        if not amount_is_zero and not cut_is_full:
            continue
        if timestamp in seen_timestamps:
            continue
        seen_timestamps.add(timestamp)
        events.append({
            "timestamp": timestamp,
            "itad_id": itad_id,
            "title": title,
            "scope": scope,
        })

    return events


def epic_giveaway_unavailable_fields(
    reason: str,
    message: str,
    *,
    retry_after: str | None = None,
) -> dict[str, Any]:
    return {
        "epic_giveaway_status": "unavailable",
        "epic_giveaway_detected": None,
        "epic_giveaway_scope": None,
        "epic_giveaway_events": [],
        "epic_giveaway_reason": reason,
        "epic_giveaway_message": message,
        "epic_giveaway_retry_after": retry_after,
    }


def epic_giveaway_available_fields(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    scope = events[0]["scope"] if events else None
    return {
        "epic_giveaway_status": "available",
        "epic_giveaway_detected": bool(events),
        "epic_giveaway_scope": scope,
        "epic_giveaway_events": events,
        "epic_giveaway_reason": None,
        "epic_giveaway_message": None,
        "epic_giveaway_retry_after": None,
    }


def epic_giveaway_partial_fields(reason: str, message: str) -> dict[str, Any]:
    return {
        "epic_giveaway_status": "partial",
        "epic_giveaway_detected": False,
        "epic_giveaway_scope": None,
        "epic_giveaway_events": [],
        "epic_giveaway_reason": reason,
        "epic_giveaway_message": message,
        "epic_giveaway_retry_after": None,
    }


def find_related_title_candidate(
    api_key: str, exact_itad_id: str, steam_details: SteamAppDetails
) -> dict[str, Any] | None:
    steam_title = steam_details.data.get("name")
    base_title = derive_related_base_title(steam_title)
    if base_title is None:
        return None

    base_key = normalized_title_key(base_title)
    if base_key is None:
        return None

    candidates = [
        row
        for row in search_itad_games(api_key, base_title)
        if row.get("id") != exact_itad_id
        and row.get("type") == "game"
        and normalized_title_key(row.get("title")) == base_key
    ]
    if len(candidates) != 1:
        return None

    candidate = candidates[0]
    candidate_id = candidate.get("id")
    candidate_title = collapse_whitespace(str(candidate.get("title", "")))
    if not isinstance(candidate_id, str) or not candidate_id:
        return None
    if not candidate_title:
        return None

    candidate_info = get_itad_info(api_key, candidate_id)
    steam_names = extract_entity_names(steam_details.data)
    candidate_names = extract_entity_names(candidate_info)
    if not steam_names or not candidate_names or not steam_names.intersection(candidate_names):
        return None

    return {"id": candidate_id, "title": candidate_title}


def build_epic_giveaway_result(
    api_key: str, exact_itad_id: str, steam_details: SteamAppDetails
) -> dict[str, Any]:
    try:
        exact_history = get_epic_history(api_key, exact_itad_id)
    except ItadRateLimitError as exc:
        return epic_giveaway_unavailable_fields(
            "itad_rate_limited", str(exc), retry_after=exc.retry_after
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return epic_giveaway_unavailable_fields("itad_request_failed", str(exc))

    steam_title_value = steam_details.data.get("name")
    steam_title = (
        collapse_whitespace(steam_title_value)
        if isinstance(steam_title_value, str)
        else ""
    )
    exact_title = steam_title or f"Steam app {steam_details.appid}"
    exact_events = extract_epic_giveaway_events(
        exact_history, exact_itad_id, exact_title, "exact"
    )
    if exact_events:
        return epic_giveaway_available_fields(exact_events)

    if derive_related_base_title(steam_details.data.get("name")) is None:
        return epic_giveaway_available_fields([])

    try:
        related_candidate = find_related_title_candidate(
            api_key, exact_itad_id, steam_details
        )
    except ItadRateLimitError as exc:
        return {
            **epic_giveaway_partial_fields("itad_rate_limited", str(exc)),
            "epic_giveaway_retry_after": exc.retry_after,
        }
    except (RuntimeError, OSError, ValueError) as exc:
        return epic_giveaway_partial_fields("itad_request_failed", str(exc))

    if related_candidate is None:
        return epic_giveaway_available_fields([])

    try:
        related_history = get_epic_history(api_key, related_candidate["id"])
    except ItadRateLimitError as exc:
        return {
            **epic_giveaway_partial_fields("itad_rate_limited", str(exc)),
            "epic_giveaway_retry_after": exc.retry_after,
        }
    except (RuntimeError, OSError, ValueError) as exc:
        return epic_giveaway_partial_fields("itad_request_failed", str(exc))

    related_events = extract_epic_giveaway_events(
        related_history,
        related_candidate["id"],
        related_candidate["title"],
        "related_title",
    )
    return epic_giveaway_available_fields(related_events)


def extract_sale_episodes(
    history: list[dict[str, Any]], reference_currency: str
) -> list[dict[str, Any]]:
    sorted_history = sorted(
        history,
        key=lambda h: parse_itad_datetime(h.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
    )

    episodes: list[dict[str, Any]] = []
    in_sale = False
    episode_start: str | None = None
    low_price: dict[str, Any] | None = None
    low_timestamp: str | None = None
    low_amount: Decimal | None = None
    episode_regular_price: dict[str, Any] | None = None
    episode_regular_amount: Decimal | None = None

    def append_episode(end_timestamp: Any) -> None:
        episodes.append({
            "start_timestamp": episode_start,
            "end_timestamp": end_timestamp,
            "low_price": low_price,
            "low_timestamp": low_timestamp,
            "regular_price": episode_regular_price,
        })

    for entry in sorted_history:
        if not isinstance(entry, dict):
            continue
        timestamp = entry.get("timestamp")
        deal = entry.get("deal")

        if deal is None:
            if in_sale:
                append_episode(timestamp)
                in_sale = False
            continue

        if not isinstance(deal, dict):
            continue

        price_data = deal.get("price")
        regular_data = deal.get("regular")
        if not isinstance(price_data, dict) or not isinstance(regular_data, dict):
            continue

        currency = price_data.get("currency")
        if currency != reference_currency:
            continue
        if regular_data.get("currency") != reference_currency:
            continue

        try:
            price_amount = Decimal(str(price_data["amount"]))
            regular_amount = Decimal(str(regular_data["amount"]))
        except (ValueError, ArithmeticError, KeyError):
            continue

        if not price_amount.is_finite() or not regular_amount.is_finite():
            continue

        is_discounted = price_amount < regular_amount

        if is_discounted:
            if in_sale and regular_amount != episode_regular_amount:
                append_episode(timestamp)
                in_sale = False

            if not in_sale:
                in_sale = True
                episode_start = timestamp
                low_amount = price_amount
                low_price = extract_money(price_data)
                low_timestamp = timestamp
                episode_regular_amount = regular_amount
                episode_regular_price = extract_money(regular_data)
            elif low_amount is None or price_amount < low_amount:
                low_amount = price_amount
                low_price = extract_money(price_data)
                low_timestamp = timestamp
        else:
            if in_sale:
                append_episode(timestamp)
                in_sale = False

    if in_sale:
        append_episode(None)

    return episodes


def classify_low_recurrence(
    episodes: list[dict[str, Any]],
    steam_low_amount: Decimal,
    steam_low_currency: str,
    now: datetime,
) -> dict[str, Any]:
    cutoff_365 = now - timedelta(days=365)
    cutoff_730 = now - timedelta(days=730)

    total_exact = 0
    exact_within_365 = 0
    exact_within_730 = 0

    for episode in episodes:
        low = episode.get("low_price")
        if not isinstance(low, dict):
            continue
        if low.get("currency") != steam_low_currency:
            continue
        try:
            ep_amount = Decimal(str(low["amount"]))
        except (ValueError, ArithmeticError, KeyError):
            continue
        if ep_amount != steam_low_amount:
            continue

        total_exact += 1
        ts = parse_itad_datetime(episode.get("low_timestamp"))
        if ts is not None:
            if ts >= cutoff_365:
                exact_within_365 += 1
                exact_within_730 += 1
            elif ts >= cutoff_730:
                exact_within_730 += 1

    if total_exact == 0:
        pattern = "insufficient"
    elif exact_within_730 >= 2 and exact_within_365 >= 1:
        pattern = "recurring"
    elif exact_within_365 >= 1:
        pattern = "recent_isolated"
    elif exact_within_730 >= 1:
        pattern = "aging"
    elif total_exact >= 2:
        pattern = "stale_previously_repeated"
    else:
        pattern = "stale_isolated"

    return {
        "pattern": pattern,
        "total_exact_episodes": total_exact,
        "exact_within_365": exact_within_365,
        "exact_within_730": exact_within_730,
    }


def find_recurring_regime_sale_price(
    episodes: list[dict[str, Any]],
    current_regular_amount: Decimal,
    current_regular_currency: str,
    now: datetime,
) -> dict[str, Any] | None:
    cutoff_365 = now - timedelta(days=365)
    cutoff_730 = now - timedelta(days=730)

    price_episodes: dict[str, list[datetime]] = {}

    for episode in episodes:
        low = episode.get("low_price")
        regular = episode.get("regular_price")
        if not isinstance(low, dict) or low.get("currency") != current_regular_currency:
            continue
        if (
            not isinstance(regular, dict)
            or regular.get("currency") != current_regular_currency
        ):
            continue
        ts = parse_itad_datetime(episode.get("low_timestamp"))
        if ts is None:
            continue
        try:
            ep_amount = Decimal(str(low["amount"]))
            ep_regular_amount = Decimal(str(regular["amount"]))
        except (ValueError, ArithmeticError, KeyError):
            continue
        if (
            not ep_amount.is_finite()
            or not ep_regular_amount.is_finite()
            or ep_regular_amount != current_regular_amount
        ):
            continue
        key = str(ep_amount)
        price_episodes.setdefault(key, []).append(ts)

    best_price: Decimal | None = None
    best_currency: str | None = None

    for amount_str, timestamps in price_episodes.items():
        amount = Decimal(amount_str)
        within_730 = [t for t in timestamps if t >= cutoff_730]
        within_365 = [t for t in timestamps if t >= cutoff_365]
        if len(within_730) >= 2 and len(within_365) >= 1:
            if best_price is None or amount < best_price:
                best_price = amount
                best_currency = current_regular_currency

    if best_price is None:
        return None
    return {"amount": json_number(best_price), "currency": best_currency}


def detect_list_price_change(
    history: list[dict[str, Any]],
    current_regular_price: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    sorted_history = sorted(
        history,
        key=lambda h: parse_itad_datetime(h.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
    )

    observations: list[dict[str, Any]] = []
    for entry in sorted_history:
        if not isinstance(entry, dict):
            continue
        deal = entry.get("deal")
        if deal is None or not isinstance(deal, dict):
            continue
        regular = deal.get("regular")
        if not isinstance(regular, dict):
            continue
        amount = regular.get("amount")
        currency = regular.get("currency")
        if amount is None or not currency:
            continue
        ts = parse_itad_datetime(entry.get("timestamp"))
        if ts is None:
            continue

        try:
            reg_amount = Decimal(str(amount))
        except (ValueError, ArithmeticError):
            continue
        if not reg_amount.is_finite():
            continue

        observation = {
            "amount_str": str(reg_amount),
            "currency": currency,
            "timestamp": ts,
        }
        if observations and observations[-1]["timestamp"] == ts:
            if (
                observations[-1]["amount_str"] != observation["amount_str"]
                or observations[-1]["currency"] != observation["currency"]
            ):
                return {"type": "ambiguous"}
            continue
        observations.append(observation)

    if not observations:
        return {"type": "insufficient"}

    try:
        current_reg_amount = Decimal(str(current_regular_price["amount"]))
        current_reg_currency = current_regular_price["currency"]
    except (ValueError, ArithmeticError, KeyError):
        return {"type": "ambiguous"}

    if not current_reg_amount.is_finite() or not isinstance(current_reg_currency, str):
        return {"type": "ambiguous"}

    runs: list[dict[str, Any]] = []
    for observation in observations:
        run_key = (observation["amount_str"], observation["currency"])
        if runs and (runs[-1]["amount_str"], runs[-1]["currency"]) == run_key:
            continue
        runs.append({
            "amount_str": observation["amount_str"],
            "currency": observation["currency"],
            "first_ts": observation["timestamp"],
        })

    terminal = runs[-1]
    terminal_amount = Decimal(terminal["amount_str"])
    if (
        terminal_amount != current_reg_amount
        or terminal["currency"] != current_reg_currency
        or terminal["first_ts"] > now
    ):
        return {"type": "ambiguous"}

    minimum_duration = 30 * 86400
    sustained: list[dict[str, Any]] = []
    for index, run in enumerate(runs):
        end_ts = runs[index + 1]["first_ts"] if index + 1 < len(runs) else now
        duration = (end_ts - run["first_ts"]).total_seconds()
        if duration >= minimum_duration:
            sustained.append(run)

    terminal_duration = (now - terminal["first_ts"]).total_seconds()
    if terminal_duration < minimum_duration:
        return {"type": "insufficient"}

    if len(sustained) < 2:
        return {"type": "none"}

    old_run = sustained[-2]
    new_run = sustained[-1]
    if new_run is not terminal:
        return {"type": "insufficient"}

    old_amount = Decimal(old_run["amount_str"])
    new_amount = Decimal(new_run["amount_str"])
    old_currency = old_run["currency"]
    new_currency = new_run["currency"]
    if old_currency != new_currency:
        return {"type": "ambiguous"}
    if old_amount == new_amount:
        return {"type": "none"}

    direction = "increase" if new_amount > old_amount else "decrease"
    if old_amount > Decimal("0"):
        pct = abs(new_amount - old_amount) / old_amount * Decimal("100")
        pct = pct.quantize(Decimal("0.01"))
    else:
        pct = None

    return {
        "type": "confirmed",
        "direction": direction,
        "from_amount": json_number(old_amount),
        "to_amount": json_number(new_amount),
        "currency": new_currency,
        "date": new_run["first_ts"].strftime("%Y-%m-%d"),
        "percentage": json_number(pct) if pct is not None else None,
    }


def steam_history_unavailable_fields(
    reason: str, message: str
) -> dict[str, Any]:
    return {
        "steam_history_status": "unavailable",
        "steam_history_reason": reason,
        "steam_history_message": message,
        "sale_episode_count": None,
        "exact_low_pattern": None,
        "exact_low_total_episodes": None,
        "exact_low_within_365": None,
        "exact_low_within_730": None,
        "recurring_sale_price": None,
        "list_price_change": None,
    }


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


def steam_low_unavailable_fields(
    reason: str,
    message: str,
    *,
    retry_after: str | None = None,
) -> dict[str, Any]:
    return {
        "steam_low_status": "unavailable",
        "steam_low_reason": reason,
        "steam_low_message": message,
        "steam_low_retry_after": retry_after,
        "historical_low_price": None,
        "steam_low_timestamp": None,
        "steam_low_regular": None,
        "steam_low_cut": None,
        "is_historical_low": None,
        "steam_low_comparison_status": "unavailable",
        "steam_low_comparison_reason": reason,
        "steam_low_comparison_message": message,
    }


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
        "price_scope": "steam",
        **steam_low_unavailable_fields(reason, message, retry_after=retry_after),
        "steam_history_status": "unavailable",
        "steam_history_reason": reason,
        "steam_history_message": message,
        "sale_episode_count": None,
        "exact_low_pattern": None,
        "exact_low_total_episodes": None,
        "exact_low_within_365": None,
        "exact_low_within_730": None,
        "recurring_sale_price": None,
        "list_price_change": None,
        **epic_giveaway_unavailable_fields(reason, message, retry_after=retry_after),
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


def subscription_unavailable_fields(
    reason: str,
    message: str,
    *,
    retry_after: str | None = None,
) -> dict[str, Any]:
    error = {
        "country": SUBSCRIPTION_COUNTRY,
        "reason": reason,
        "message": message,
    }
    return {
        "subscription_status": "unavailable",
        "subscription_country": SUBSCRIPTION_COUNTRY,
        "subscriptions": [],
        "subscription_reason": reason,
        "subscription_message": message,
        "subscription_retry_after": retry_after,
        "subscription_errors": [error],
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
        **subscription_unavailable_fields(reason, message, retry_after=retry_after),
    }


def build_price_result(
    api_key: str,
    steam_details: SteamAppDetails | None,
    steam_details_error: SteamAppDetailsError | None,
    product_to_itad_id: dict[str, str],
    itad_aliases: list[str],
    country: str,
    report_country: str | None,
    report_country_error: str | None,
) -> dict[str, Any]:
    if steam_details is None:
        return price_unavailable_fields(
            "steam_price_metadata_unavailable",
            str(steam_details_error or "Steam regional price metadata is unavailable."),
            country,
            report_country,
            report_country_error=report_country_error,
        )
    if not itad_aliases:
        return price_unavailable_fields(
            "steam_price_identity_unresolved",
            "Could not resolve any Steam app or package product to an ITAD game ID.",
            country,
            report_country,
            report_country_error=report_country_error,
        )

    result = price_unavailable_fields(
        "itad_request_failed",
        "Could not resolve price data.",
        country,
        report_country,
        report_country_error=report_country_error,
    )

    current_price = None
    regular_price = None
    target_itad_id = itad_aliases[0] if len(itad_aliases) == 1 else None
    epic_itad_id: str | None = product_to_itad_id.get(f"app/{steam_details.appid}")

    # --- Phase 1: deterministically select a Steam-matching ITAD identity ---
    try:
        overviews = get_price_overviews(api_key, itad_aliases, country)
        offers_by_itad_id = {
            itad_id: [overview["current"]]
            for itad_id, overview in overviews.items()
            if isinstance(overview.get("current"), dict)
        }
        selection = select_itad_price_identity(
            steam_details, product_to_itad_id, offers_by_itad_id
        )
        target_itad_id = selection.itad_id
        if epic_itad_id is None:
            epic_itad_id = selection.itad_id
        overview = overviews[target_itad_id]
        current_offer = selection.offer
        current_price = extract_price(current_offer)
        regular_price = extract_money(
            current_offer.get("regular") if isinstance(current_offer, dict) else None
        )
        discount_percent = extract_discount_percent(
            current_offer, current_price, regular_price
        )
        itad_url = overview.get("urls", {}).get("game")
        require_price(current_price, "current")
        
        result.update({
            "price_status": "available",
            "reason": None,
            "message": None,
            "itad_url": itad_url,
            "current_price": current_price,
            "regular_price": regular_price,
            "discount_percent": discount_percent,
        })
    except PriceIdentityError as exc:
        result = price_unavailable_fields(
            exc.reason,
            str(exc),
            country,
            report_country,
            report_country_error=report_country_error,
        )
        if target_itad_id is None:
            return result
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
        result = price_unavailable_fields(
            "itad_request_failed",
            str(exc),
            country,
            report_country,
            report_country_error=report_country_error,
        )
        if target_itad_id is None:
            return result

    # --- Phase 2: Steam store low ---
    steam_low_price: dict[str, Any] | None = None
    try:
        store_low = get_steam_store_low(api_key, target_itad_id, country)
        if store_low is None:
            result.update(steam_low_unavailable_fields(
                "steam_low_not_returned",
                "ITAD returned no Steam Store historical low for the selected identity.",
            ))
        else:
            steam_low_price = extract_money(store_low.get("price"))
            if steam_low_price is None:
                raise ValueError("ITAD returned a Steam Store low without a valid price.")
            ts_parsed = parse_itad_datetime(store_low.get("timestamp"))
            cut_value = store_low.get("cut")
            try:
                steam_low_cut = int(cut_value) if cut_value is not None else None
            except (TypeError, ValueError):
                steam_low_cut = None

            result.update({
                "steam_low_status": "available",
                "steam_low_reason": None,
                "steam_low_message": None,
                "steam_low_retry_after": None,
                "historical_low_price": steam_low_price,
                "price_scope": "steam",
                "steam_low_timestamp": ts_parsed.isoformat() if ts_parsed else None,
                "steam_low_regular": extract_money(store_low.get("regular")),
                "steam_low_cut": steam_low_cut,
            })
            if current_price is None:
                result.update({
                    "is_historical_low": None,
                    "steam_low_comparison_status": "unavailable",
                    "steam_low_comparison_reason": "current_price_unavailable",
                    "steam_low_comparison_message": (
                        "The Steam Store low is available, but no current price is "
                        "available for comparison."
                    ),
                })
            else:
                try:
                    require_comparable_prices(current_price, steam_low_price)
                    current_amount = Decimal(str(current_price["amount"]))
                    low_amount = Decimal(str(steam_low_price["amount"]))
                    if not current_amount.is_finite() or not low_amount.is_finite():
                        raise ValueError("Current or historical-low amount is not finite.")
                    result.update({
                        "is_historical_low": current_amount <= low_amount,
                        "steam_low_comparison_status": "available",
                        "steam_low_comparison_reason": None,
                        "steam_low_comparison_message": None,
                    })
                except RuntimeError as exc:
                    result.update({
                        "is_historical_low": None,
                        "steam_low_comparison_status": "unavailable",
                        "steam_low_comparison_reason": "steam_low_currency_mismatch",
                        "steam_low_comparison_message": str(exc),
                    })
                except (ValueError, ArithmeticError, KeyError) as exc:
                    result.update({
                        "is_historical_low": None,
                        "steam_low_comparison_status": "unavailable",
                        "steam_low_comparison_reason": "steam_low_comparison_failed",
                        "steam_low_comparison_message": str(exc),
                    })
    except ItadRateLimitError as exc:
        result.update(steam_low_unavailable_fields(
            "itad_rate_limited", str(exc), retry_after=exc.retry_after
        ))
    except ValueError as exc:
        result.update(steam_low_unavailable_fields(
            "steam_low_invalid_response", str(exc)
        ))
    except (RuntimeError, OSError) as exc:
        result.update(steam_low_unavailable_fields(
            "itad_request_failed", str(exc)
        ))

    # --- Phase 3: Steam price history ---
    now = datetime.now(timezone.utc)
    try:
        history = get_steam_history(api_key, target_itad_id, country)
    except ItadRateLimitError as exc:
        history = None
        result.update(steam_history_unavailable_fields("itad_rate_limited", str(exc)))
    except (RuntimeError, OSError, ValueError) as exc:
        history = None
        result.update(steam_history_unavailable_fields("itad_request_failed", str(exc)))

    if history is not None:
        ref_currency = None
        if current_price is not None:
            ref_currency = current_price["currency"]
        elif steam_low_price is not None:
            ref_currency = steam_low_price["currency"]

        if ref_currency is not None:
            episodes = extract_sale_episodes(history, ref_currency)
        else:
            episodes = []

        recurrence: dict[str, Any] | None = None
        if steam_low_price is not None:
            try:
                low_amount = Decimal(str(steam_low_price["amount"]))
                recurrence = classify_low_recurrence(
                    episodes, low_amount, steam_low_price["currency"], now
                )
            except (ValueError, ArithmeticError, KeyError):
                recurrence = None

        regime_price: dict[str, Any] | None = None
        if regular_price is not None:
            try:
                reg_amount = Decimal(str(regular_price["amount"]))
                regime_price = find_recurring_regime_sale_price(
                    episodes, reg_amount, regular_price["currency"], now
                )
            except (ValueError, ArithmeticError, KeyError):
                regime_price = None

        list_change: dict[str, Any] | None = None
        if regular_price is not None:
            try:
                list_change = detect_list_price_change(history, regular_price, now)
            except (ValueError, ArithmeticError, KeyError):
                list_change = None

        result.update({
            "steam_history_status": "available",
            "steam_history_reason": None,
            "steam_history_message": None,
            "sale_episode_count": len(episodes) if ref_currency else 0,
            "exact_low_pattern": recurrence["pattern"] if recurrence else None,
            "exact_low_total_episodes": recurrence["total_exact_episodes"] if recurrence else None,
            "exact_low_within_365": recurrence["exact_within_365"] if recurrence else None,
            "exact_low_within_730": recurrence["exact_within_730"] if recurrence else None,
            "recurring_sale_price": regime_price,
            "list_price_change": list_change,
        })

    # --- Phase 4: Epic Games Store giveaway history ---
    if epic_itad_id is None:
        result.update(epic_giveaway_unavailable_fields(
            "steam_price_identity_unresolved",
            "Could not resolve a direct Steam app or Steam-matched ITAD identity "
            "for Epic giveaway lookup.",
        ))
    else:
        result.update(build_epic_giveaway_result(api_key, epic_itad_id, steam_details))

    return result


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


def get_subscriptions(api_key: str, itad_ids: list[str]) -> list[Any]:
    data = post(
        "/games/subs/v1",
        api_key,
        itad_ids,
        params={"country": SUBSCRIPTION_COUNTRY},
    )
    if not isinstance(data, list):
        raise RuntimeError("ITAD returned an invalid subscription response.")
    return data


def safe_subscription_itad_ids(
    appid: str,
    steam_details: SteamAppDetails | None,
    product_to_itad_id: dict[str, str],
) -> list[str]:
    products = [f"app/{appid}"]
    if steam_details is not None:
        products.extend(steam_details.base_package_products)
    return list(
        dict.fromkeys(
            itad_id
            for product in products
            if (itad_id := product_to_itad_id.get(product))
        )
    )


def normalize_subscriptions(
    rows: list[Any],
    queried_ids: list[str],
    now: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    queried = set(queried_ids)
    subscriptions: dict[tuple[str, str], dict[str, Any]] = {}
    errors: list[dict[str, str]] = []

    def add_error(reason: str, message: str) -> None:
        errors.append({"reason": reason, "message": message})

    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            add_error(
                "invalid_subscription_row",
                f"Subscription row {row_index} is not an object.",
            )
            continue
        row_id = row.get("id")
        if not isinstance(row_id, str) or row_id not in queried:
            add_error(
                "unexpected_subscription_identity",
                f"Subscription row {row_index} has an unexpected game identity.",
            )
            continue
        raw_subscriptions = row.get("subs")
        if not isinstance(raw_subscriptions, list):
            add_error(
                "invalid_subscription_list",
                f"Subscription row {row_index} has no valid subscription list.",
            )
            continue

        for sub_index, raw_subscription in enumerate(raw_subscriptions):
            if not isinstance(raw_subscription, dict):
                add_error(
                    "invalid_subscription_record",
                    f"Subscription record {row_index}:{sub_index} is not an object.",
                )
                continue
            name_value = raw_subscription.get("name")
            if not isinstance(name_value, str) or not name_value.strip():
                add_error(
                    "invalid_subscription_name",
                    f"Subscription record {row_index}:{sub_index} has no valid name.",
                )
                continue
            name = " ".join(name_value.split())

            raw_id = raw_subscription.get("id")
            subscription_id: int | str | None
            if isinstance(raw_id, bool):
                subscription_id = None
            elif isinstance(raw_id, int) and raw_id >= 0:
                subscription_id = raw_id
            elif isinstance(raw_id, str) and raw_id.strip():
                subscription_id = raw_id.strip()
            else:
                subscription_id = None

            leaving_value = raw_subscription.get("leaving")
            leaving: str | None = None
            if leaving_value is not None:
                leaving_date = parse_itad_datetime(leaving_value)
                if leaving_date is None:
                    add_error(
                        "invalid_subscription_leaving_date",
                        f"Subscription record {row_index}:{sub_index} has an invalid leaving date.",
                    )
                    continue
                if leaving_date <= now:
                    add_error(
                        "expired_subscription_record",
                        f"Subscription record {row_index}:{sub_index} has already passed its leaving date.",
                    )
                    continue
                leaving = leaving_date.isoformat()

            normalized_name = name.casefold()
            key = (
                ("id", str(subscription_id).casefold())
                if subscription_id is not None
                else ("name", normalized_name)
            )
            incoming = {"id": subscription_id, "name": name, "leaving": leaving}
            existing = subscriptions.get(key)
            if existing is None:
                subscriptions[key] = incoming
                continue

            if existing["name"].casefold() != normalized_name:
                add_error(
                    "conflicting_subscription_name",
                    f"Duplicate subscription {key[1]} has conflicting names.",
                )
            known_leaving = {
                value
                for value in (existing.get("leaving"), leaving)
                if isinstance(value, str)
            }
            if len(known_leaving) > 1:
                add_error(
                    "conflicting_subscription_leaving_date",
                    f"Duplicate subscription {name} has conflicting leaving dates.",
                )
            if known_leaving:
                existing["leaving"] = min(known_leaving)

    normalized = sorted(
        subscriptions.values(),
        key=lambda subscription: (
            subscription["name"].casefold(),
            str(subscription["id"]),
        ),
    )
    return normalized, errors


def load_us_subscription_result(
    api_key: str,
    itad_ids: list[str],
    now: datetime,
) -> dict[str, Any]:
    try:
        rows = get_subscriptions(api_key, itad_ids)
        subscriptions, errors = normalize_subscriptions(rows, itad_ids, now)
    except ItadRateLimitError as exc:
        return {
            "status": "unavailable",
            "subscriptions": [],
            "reason": "itad_rate_limited",
            "message": str(exc),
            "retry_after": exc.retry_after,
            "errors": [{"reason": "itad_rate_limited", "message": str(exc)}],
        }
    except (RuntimeError, OSError, ValueError) as exc:
        return {
            "status": "unavailable",
            "subscriptions": [],
            "reason": "itad_subscription_request_failed",
            "message": str(exc),
            "retry_after": None,
            "errors": [
                {"reason": "itad_subscription_request_failed", "message": str(exc)}
            ],
        }

    status = "partial" if errors else "available"
    if status == "partial":
        reason = "partial_subscription_coverage"
        message = (
            f"Some ITAD subscription records for {SUBSCRIPTION_COUNTRY} were invalid; "
            "valid records were retained."
        )
    else:
        reason = None
        message = None
    return {
        "status": status,
        "subscriptions": subscriptions,
        "reason": reason,
        "message": message,
        "retry_after": None,
        "errors": errors,
    }


def build_subscription_result(
    api_key: str,
    appid: str,
    steam_details: SteamAppDetails | None,
    product_to_itad_id: dict[str, str],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    itad_ids = safe_subscription_itad_ids(
        appid, steam_details, product_to_itad_id
    )
    if not itad_ids:
        return subscription_unavailable_fields(
            "subscription_identity_unresolved",
            "Could not resolve a safe Steam app or base-package identity for subscription lookup.",
        )

    evidence_time = now or datetime.now(timezone.utc)
    result = load_us_subscription_result(api_key, itad_ids, evidence_time)

    errors = [
        {"country": SUBSCRIPTION_COUNTRY, **error}
        for error in result.pop("errors")
    ]

    return {
        "subscription_status": result["status"],
        "subscription_country": SUBSCRIPTION_COUNTRY,
        "subscriptions": result["subscriptions"],
        "subscription_reason": result["reason"],
        "subscription_message": result["message"],
        "subscription_retry_after": result["retry_after"],
        "subscription_errors": errors,
    }


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
            "and retrieve its ITAD bundle and subscription context."
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
                    "ITAD price, bundle, subscription, and Epic giveaway data are "
                    "unavailable because itad_api_key is not configured.",
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
                    "pricing_country is required for regional ITAD price and bundle data.",
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
    steam_details: SteamAppDetails | None = None
    steam_details_error: SteamAppDetailsError | None = None
    try:
        steam_details = fetch_steam_appdetails(args.appid, country)
        steam_products = list(steam_details.all_products)
    except SteamAppDetailsError as exc:
        steam_products = [f"app/{args.appid}"]
        package_status = "unavailable"
        package_error = str(exc)
        steam_details_error = exc

    try:
        product_to_itad_id, aliases = resolve_steam_products_to_itad_ids(
            api_key, steam_products
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
        steam_details,
        steam_details_error,
        product_to_itad_id,
        aliases,
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
    subscription_result = build_subscription_result(
        api_key,
        args.appid,
        steam_details,
        product_to_itad_id,
    )
    print(
        json.dumps(
            {**price_result, **bundle_result, **subscription_result},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

