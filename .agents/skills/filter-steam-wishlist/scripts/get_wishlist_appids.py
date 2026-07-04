#!/usr/bin/env python3

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
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


WISHLIST_URL = "https://api.steampowered.com/IWishlistService/GetWishlist/v1/"


class WishlistUnavailableError(RuntimeError):
    """Raised when Steam does not return a usable public wishlist."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


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


def get_filtered_sale_appids(
    appids: list[int],
    api_key: str,
    historical_low_only: bool,
    country: str,
) -> list[int]:
    itad_id_by_appid: dict[int, str] = {}

    for appid_batch in batched(appids, BATCH_SIZE):
        steam_ids = [f"app/{appid}" for appid in appid_batch]
        lookup = post(f"/lookup/id/shop/{STEAM_SHOP_ID}/v1", api_key, steam_ids)
        for appid in appid_batch:
            itad_id = lookup.get(f"app/{appid}")
            if itad_id:
                itad_id_by_appid[appid] = itad_id

    matching_itad_ids: set[str] = set()
    itad_ids = list(dict.fromkeys(itad_id_by_appid.values()))
    for itad_id_batch in batched(itad_ids, BATCH_SIZE):
        price_results = post(
            "/games/prices/v3",
            api_key,
            itad_id_batch,
            params={"country": country, "deals": "true", "vouchers": "true"},
        )
        for game in price_results:
            sale_deals = [
                deal for deal in game.get("deals", []) if deal.get("cut", 0) > 0
            ]
            if not sale_deals:
                continue

            if not historical_low_only:
                matching_itad_ids.add(game["id"])
                continue

            historical_low = game.get("historyLow", {}).get("all", {}).get("amount")
            if historical_low is None:
                continue

            if any(
                deal.get("price", {}).get("amount") is not None
                and Decimal(str(deal["price"]["amount"]))
                <= Decimal(str(historical_low))
                for deal in sale_deals
            ):
                matching_itad_ids.add(game["id"])

    return [
        appid
        for appid in appids
        if itad_id_by_appid.get(appid) in matching_itad_ids
    ]


def get_on_sale_appids(
    appids: list[int], api_key: str, country: str
) -> list[int]:
    return get_filtered_sale_appids(
        appids, api_key, historical_low_only=False, country=country
    )


def get_historical_low_sale_appids(
    appids: list[int], api_key: str, country: str
) -> list[int]:
    return get_filtered_sale_appids(
        appids, api_key, historical_low_only=True, country=country
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Return app IDs from a public Steam wishlist."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--on-sale-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Only return games currently discounted (default: enabled).",
    )
    mode.add_argument(
        "--historical-low-only",
        action="store_true",
        help="Only return discounted games at or below their ITAD historical low.",
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
    args = parser.parse_args()

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

    should_filter = args.historical_low_only or args.on_sale_only
    country: str | None = None
    api_key: str | None = None
    if should_filter:
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

    if should_filter:
        try:
            if args.historical_low_only:
                appids = get_historical_low_sale_appids(appids, api_key, country)
            else:
                appids = get_on_sale_appids(appids, api_key, country)
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

    print(json.dumps(appids, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

