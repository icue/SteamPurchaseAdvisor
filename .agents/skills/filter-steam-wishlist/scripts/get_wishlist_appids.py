#!/usr/bin/env python3

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    BATCH_SIZE,
    STEAM_SHOP_ID,
    USER_AGENT,
    ItadRateLimitError,
    batched,
    parse_country_argument,
    post,
)
from steam_purchase_advisor.steam_identity import (  # noqa: E402
    SteamIdentityResolutionError,
    resolve_steam_profile,
)
from steam_purchase_advisor.steam_price_identity import (  # noqa: E402
    PriceIdentityError,
    SteamAppDetails,
    SteamAppDetailsError,
    fetch_steam_appdetails,
    select_itad_price_identity,
)


WISHLIST_URL = "https://api.steampowered.com/IWishlistService/GetWishlist/v1/"
EARLY_ACCESS_GENRE_ID = "70"
PRICE_STATE_CHOICES = ("any", "on-sale", "historical-low")
RELEASE_STATE_CHOICES = ("any", "unreleased", "early-access", "full-release")
DEMO_STATE_CHOICES = ("any", "available", "unavailable")
STORE_MAX_WORKERS = 4


class StoreMetadataUnavailableError(RuntimeError):
    """Raised when Steam AppDetails cannot be fetched or parsed."""

    def __init__(self, failures: dict[int, str]) -> None:
        self.failures = failures
        super().__init__(
            "Steam Store metadata was unavailable for "
            f"{len(failures)} candidate game(s)."
        )


class WishlistUnavailableError(RuntimeError):
    """Raised when Steam does not return a usable public wishlist."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class ReleaseStateUnavailableError(RuntimeError):
    """Raised when a release-state filter cannot classify every candidate."""

    def __init__(self, failures: dict[int, str]) -> None:
        self.failures = failures
        super().__init__(
            "Steam release-state metadata was unavailable for "
            f"{len(failures)} candidate game(s)."
        )


class PriceMetadataUnavailableError(RuntimeError):
    """Raised when regional AppDetails metadata is incomplete."""

    def __init__(self, failures: dict[int, str]) -> None:
        self.failures = failures
        super().__init__(
            "Steam regional price metadata was unavailable for "
            f"{len(failures)} wishlist game(s)."
        )


def emit_error(error: str, reason: str, message: str, **details: object) -> None:
    payload: dict[str, object] = {
        "error": error,
        "reason": reason,
        "message": message,
    }
    payload.update({key: value for key, value in details.items() if value is not None})
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


def get_wishlist_appids(steam_id: str) -> list[int]:
    url = f"{WISHLIST_URL}?{urlencode({'steamid': steam_id})}"
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise WishlistUnavailableError(
            "steam_http_error",
            f"Steam did not return a public wishlist (HTTP {exc.code}).",
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise WishlistUnavailableError(
            "steam_request_failed",
            "Steam wishlist request failed.",
        ) from exc
    except json.JSONDecodeError as exc:
        raise WishlistUnavailableError(
            "steam_invalid_response",
            "Steam returned invalid wishlist JSON.",
        ) from exc

    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, dict) or "items" not in response:
        raise WishlistUnavailableError(
            "wishlist_not_returned",
            "Steam returned no wishlist items field. Verify the SteamID64 and wishlist visibility.",
        )

    items = response["items"]
    if not isinstance(items, list):
        raise WishlistUnavailableError(
            "steam_invalid_response",
            "Steam returned an invalid wishlist items value.",
        )

    appids: list[int] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("appid"), int):
            raise WishlistUnavailableError(
                "steam_invalid_response",
                "Steam returned an invalid wishlist item.",
            )
        appids.append(item["appid"])
    return appids


def classify_release_state(details: SteamAppDetails) -> str:
    """Classify one successful Steam Store appdetails data object."""
    data = details.data
    if not isinstance(data, dict):
        return "unknown"

    release_date = data.get("release_date")
    if not isinstance(release_date, dict):
        return "unknown"

    coming_soon = release_date.get("coming_soon")
    if not isinstance(coming_soon, bool):
        return "unknown"

    if coming_soon:
        return "unreleased"

    genres = data.get("genres")
    if not isinstance(genres, list):
        return "unknown"

    genre_ids: set[str] = set()
    for genre in genres:
        if not isinstance(genre, dict):
            return "unknown"
        genre_id = genre.get("id")
        if not isinstance(genre_id, (str, int)):
            return "unknown"
        genre_ids.add(str(genre_id))

    if EARLY_ACCESS_GENRE_ID in genre_ids:
        return "early-access"
    return "full-release"


def select_appids_by_release_state(
    appids: list[int], release_state: str, states: dict[int, str]
) -> list[int]:
    """Select a release-state subset without changing wishlist order."""
    if release_state == "any":
        return list(appids)
    return [appid for appid in appids if states.get(appid) == release_state]


def get_release_state_filtered_appids(
    appids: list[int], release_state: str, details_by_appid: dict[int, SteamAppDetails]
) -> list[int]:
    if release_state == "any" or not appids:
        return list(appids)

    states: dict[int, str] = {}
    failures: dict[int, str] = {}
    
    for appid in appids:
        details = details_by_appid[appid]
            
        state = classify_release_state(details)
        states[appid] = state
        if state == "unknown":
            failures[appid] = "steam_invalid_response"

    if failures:
        raise ReleaseStateUnavailableError(failures)
        
    return select_appids_by_release_state(appids, release_state, states)


def fetch_store_metadata(
    appids: list[int], country: str | None = None
) -> dict[int, SteamAppDetails]:
    """Fetch every requested AppDetails record or fail the complete filter."""
    if not appids:
        return {}

    details: dict[int, SteamAppDetails] = {}
    failures: dict[int, str] = {}
    workers = min(STORE_MAX_WORKERS, len(appids))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_steam_appdetails, appid, country): appid
            for appid in appids
        }
        for future in as_completed(futures):
            appid = futures[future]
            try:
                details[appid] = future.result()
            except SteamAppDetailsError as exc:
                failures[appid] = exc.reason
            except Exception:
                failures[appid] = "unexpected_store_error"

    if failures:
        raise StoreMetadataUnavailableError(failures)
    return details


def validate_price_metadata(
    appids: list[int], details_by_appid: dict[int, SteamAppDetails]
) -> None:
    failures: dict[int, str] = {}
    for appid in appids:
        details = details_by_appid[appid]
        price_overview = details.data.get("price_overview")
        malformed_price = price_overview is not None and (
            not isinstance(price_overview, dict)
            or not details.has_price
            or details.final_amount_int > details.initial_amount_int
        )
        if malformed_price:
            failures[appid] = "steam_price_metadata_malformed"
    if failures:
        raise PriceMetadataUnavailableError(failures)


def get_filtered_sale_appids(
    appids: list[int],
    details_by_appid: dict[int, SteamAppDetails],
    api_key: str,
    historical_low_only: bool,
    country: str,
) -> list[int]:
    sale_candidates = {
        appid: details_by_appid[appid]
        for appid in appids
        if details_by_appid[appid].is_discounted
    }
    if not sale_candidates:
        return []

    products: list[str] = []
    for appid, details in sale_candidates.items():
        products.append(f"app/{appid}")
        products.extend(details.base_package_products)
    products = list(dict.fromkeys(products))

    product_to_itad_id: dict[str, str] = {}
    for product_batch in batched(products, BATCH_SIZE):
        lookup = post(
            f"/lookup/id/shop/{STEAM_SHOP_ID}/v1", api_key, product_batch
        )
        if not isinstance(lookup, dict):
            raise RuntimeError("ITAD returned an invalid product lookup response.")
        for product in product_batch:
            itad_id = lookup.get(product)
            if isinstance(itad_id, str) and itad_id:
                product_to_itad_id[product] = itad_id

    offers_by_itad_id: dict[str, list[dict[str, Any]]] = {}
    itad_ids = list(dict.fromkeys(product_to_itad_id.values()))
    for itad_id_batch in batched(itad_ids, BATCH_SIZE):
        price_results = post(
            "/games/prices/v3",
            api_key,
            itad_id_batch,
            params={"country": country, "deals": "true", "vouchers": "false", "shops": str(STEAM_SHOP_ID)},
        )
        if not isinstance(price_results, list):
            raise RuntimeError("ITAD returned an invalid prices response.")
        for game in price_results:
            if not isinstance(game, dict) or not isinstance(game.get("id"), str):
                continue
            deals = game.get("deals")
            if isinstance(deals, list):
                offers_by_itad_id[game["id"]] = [
                    deal for deal in deals if isinstance(deal, dict)
                ]

    matches: set[int] = set()
    for appid, steam_details in sale_candidates.items():
        try:
            selection = select_itad_price_identity(
                steam_details, product_to_itad_id, offers_by_itad_id
            )
        except PriceIdentityError:
            continue

        if not historical_low_only:
            matches.add(appid)
            continue

        offer = selection.offer
        deal_price = offer.get("price")
        store_low = offer.get("storeLow")
        if not isinstance(deal_price, dict) or not isinstance(store_low, dict):
            continue
        if (
            deal_price.get("currency") != store_low.get("currency")
            or deal_price.get("amount") is None
            or store_low.get("amount") is None
        ):
            continue
        try:
            deal_amount = Decimal(str(deal_price["amount"]))
            low_amount = Decimal(str(store_low["amount"]))
        except (ValueError, ArithmeticError):
            continue
        if (
            deal_amount.is_finite()
            and low_amount.is_finite()
            and deal_amount <= low_amount
        ):
            matches.add(appid)

    return [appid for appid in appids if appid in matches]


def get_price_state_filtered_appids(
    appids: list[int],
    price_state: str,
    details_by_appid: dict[int, SteamAppDetails],
    api_key: str | None,
    country: str | None,
) -> list[int]:
    if price_state == "any":
        return list(appids)

    if api_key is None or country is None:
        raise RuntimeError("api_key and country are required for price filtering")

    validate_price_metadata(appids, details_by_appid)

    return get_filtered_sale_appids(
        appids,
        details_by_appid,
        api_key,
        historical_low_only=(price_state == "historical-low"),
        country=country,
    )


def get_demo_state_filtered_appids(
    appids: list[int],
    demo_state: str,
    details_by_appid: dict[int, SteamAppDetails],
) -> list[int]:
    """Select a demo-availability subset without changing wishlist order."""
    if demo_state == "any":
        return list(appids)

    required_has_demo = demo_state == "available"

    return [
        appid
        for appid in appids
        if details_by_appid[appid].has_demo is required_has_demo
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Return app IDs from a public Steam wishlist."
    )
    parser.add_argument(
        "--price-state",
        choices=PRICE_STATE_CHOICES,
        default="on-sale",
        help="Filter by price state (default: on-sale).",
    )
    parser.add_argument(
        "--release-state",
        choices=RELEASE_STATE_CHOICES,
        default="any",
        help="Filter by Steam release state (default: any).",
    )
    parser.add_argument(
        "--demo-state",
        choices=DEMO_STATE_CHOICES,
        default="any",
        help="Filter by Steam Demo availability (default: any).",
    )
    parser.add_argument(
        "--steam-profile",
        "--steam-id",
        dest="steam_profile",
        help=(
            "SteamID64, Steam Community profile URL, or exact custom ID for this "
            "request."
        ),
    )
    parser.add_argument(
        "--country",
        type=parse_country_argument,
        help="Pricing country for this request.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    resolved_request_steam_id: str | None = None
    if args.steam_profile:
        try:
            resolved_request_steam_id = resolve_steam_profile(args.steam_profile)
        except SteamIdentityResolutionError as exc:
            emit_error(
                "wishlist_unavailable",
                exc.reason,
                (
                    f"{exc} If automatic resolution remains unavailable, use "
                    "https://steamid.io/lookup/ and provide the resulting "
                    "17-digit SteamID64."
                ),
            )
            return 2

    try:
        config = load_config()
    except ConfigError as exc:
        emit_error("configuration_unavailable", exc.code, str(exc))
        return 2

    if resolved_request_steam_id is not None:
        steam_id = resolved_request_steam_id
    else:
        try:
            steam_id = config.steam_id
        except ConfigValueError as exc:
            emit_error("wishlist_unavailable", exc.code, str(exc))
            return 2

    if steam_id is None:
        emit_error(
            "wishlist_unavailable",
            "missing_steam_id",
            "A valid SteamID64 and a public wishlist are required.",
        )
        return 2

    price_filter_active = args.price_state != "any"
    release_filter_active = args.release_state != "any"
    demo_filter_active = args.demo_state != "any"
    metadata_filter_active = price_filter_active or release_filter_active or demo_filter_active

    country: str | None = None
    api_key: str | None = None
    if price_filter_active:
        try:
            api_key = config.itad_api_key
        except ConfigValueError as exc:
            emit_error("price_data_unavailable", exc.code, str(exc))
            return 3
        if api_key is None:
            emit_error(
                "price_data_unavailable",
                "missing_itad_api_key",
                "ITAD price data is unavailable because itad_api_key is not configured.",
            )
            return 3

        try:
            country = args.country or config.pricing_country
        except ConfigValueError as exc:
            emit_error("price_data_unavailable", exc.code, str(exc))
            return 3
        if country is None:
            emit_error(
                "price_data_unavailable",
                "missing_pricing_country",
                "pricing_country is required for ITAD price filtering.",
            )
            return 3

    try:
        appids = get_wishlist_appids(steam_id)
    except WishlistUnavailableError as exc:
        emit_error(
            "wishlist_unavailable",
            exc.reason,
            f"{exc} A valid SteamID64 and a public wishlist are required.",
        )
        return 2

    details_by_appid: dict[int, SteamAppDetails] = {}
    if metadata_filter_active:
        try:
            details_by_appid = fetch_store_metadata(
                appids,
                country if price_filter_active else None,
            )
        except StoreMetadataUnavailableError as exc:
            emit_error(
                "store_metadata_unavailable",
                "store_metadata_unavailable",
                str(exc),
                unknown_appids=sorted(exc.failures),
            )
            return 5

    if price_filter_active:
        try:
            appids = get_price_state_filtered_appids(
                appids, args.price_state, details_by_appid, api_key, country
            )
        except PriceMetadataUnavailableError as exc:
            reasons = sorted(set(exc.failures.values()))
            emit_error(
                "price_data_unavailable",
                reasons[0] if len(reasons) == 1 else "steam_price_metadata_unavailable",
                str(exc),
                unknown_appids=sorted(exc.failures),
            )
            return 3
        except ItadRateLimitError as exc:
            emit_error(
                "price_data_unavailable",
                "itad_rate_limited",
                str(exc),
                retry_after=exc.retry_after,
            )
            return 3
        except (RuntimeError, OSError, ValueError) as exc:
            emit_error(
                "price_data_unavailable",
                "itad_request_failed",
                str(exc),
            )
            return 3

    if release_filter_active:
        try:
            appids = get_release_state_filtered_appids(
                appids, args.release_state, details_by_appid
            )
        except ReleaseStateUnavailableError as exc:
            reasons = sorted(set(exc.failures.values()))
            emit_error(
                "release_state_data_unavailable",
                reasons[0] if len(reasons) == 1 else "steam_release_state_lookup_failed",
                str(exc),
                unknown_appids=sorted(exc.failures),
            )
            return 4

    if demo_filter_active:
        appids = get_demo_state_filtered_appids(
            appids, args.demo_state, details_by_appid
        )

    print(json.dumps(appids, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

