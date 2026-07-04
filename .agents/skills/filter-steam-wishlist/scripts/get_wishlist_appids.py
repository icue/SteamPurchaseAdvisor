#!/usr/bin/env python3

import argparse
import json
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree


SHARED_LIB = Path(__file__).resolve().parents[3] / "lib"
sys.path.insert(0, str(SHARED_LIB))

from steam_purchase_advisor.config import (  # noqa: E402
    CONFIG_PATH,
    AppConfig,
    ConfigError,
    ConfigValueError,
    load_config,
    normalize_country,
    normalize_steam_id,
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


WISHLIST_URL = "https://api.steampowered.com/IWishlistService/GetWishlist/v1/"
STEAM_COMMUNITY_HOSTS = {"steamcommunity.com", "www.steamcommunity.com"}
STEAM_PROFILE_XML_MAX_BYTES = 1_000_000
DEFAULT_CONFIG: dict[str, str] = {
    "steam_id": "",
    "itad_api_key": "",
    "pricing_country": "",
    "report_country": "",
}


class WishlistUnavailableError(RuntimeError):
    """Raised when Steam does not return a usable public wishlist."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class SteamIdentityResolutionError(RuntimeError):
    """Raised when a Steam profile reference cannot be resolved to SteamID64."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class ConfigUpdateConflict(RuntimeError):
    """Raised when an update would replace a valid configured value."""

    def __init__(self, fields: list[str]) -> None:
        self.fields = fields
        super().__init__("Refusing to replace already configured fields without approval.")


def normalize_vanity_id(value: str) -> str:
    """Validate one exact Steam custom-profile path segment."""
    vanity_id = value.strip()
    if (
        not vanity_id
        or len(vanity_id) > 128
        or any(
            character.isspace()
            or character in "/\\?#"
            or ord(character) < 32
            for character in vanity_id
        )
    ):
        raise SteamIdentityResolutionError(
            "invalid_steam_profile",
            "Steam custom IDs must be exact, non-empty profile path values.",
        )
    return vanity_id


def parse_steam_profile_reference(value: str) -> tuple[str, str]:
    """Return ('steam_id', value) or ('vanity_id', value) for supported input."""
    profile_reference = value.strip()
    if not profile_reference:
        raise SteamIdentityResolutionError(
            "invalid_steam_profile",
            "A SteamID64, Steam profile URL, or exact custom ID is required.",
        )

    try:
        return "steam_id", normalize_steam_id(profile_reference)
    except ValueError:
        pass

    candidate_url = profile_reference
    if profile_reference.lower().startswith(
        ("steamcommunity.com/", "www.steamcommunity.com/")
    ):
        candidate_url = f"https://{profile_reference}"

    parsed = urlparse(candidate_url)
    if parsed.scheme or parsed.netloc:
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.hostname is None
            or parsed.hostname.lower() not in STEAM_COMMUNITY_HOSTS
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise SteamIdentityResolutionError(
                "invalid_steam_profile",
                "Only Steam Community profile URLs are supported.",
            )

        path_parts = [unquote(part) for part in parsed.path.split("/") if part]
        if len(path_parts) != 2:
            raise SteamIdentityResolutionError(
                "invalid_steam_profile",
                "Steam profile URLs must use /profiles/<SteamID64> or /id/<custom-id>.",
            )

        profile_kind, profile_value = path_parts
        if profile_kind.lower() == "profiles":
            try:
                return "steam_id", normalize_steam_id(profile_value)
            except ValueError as exc:
                raise SteamIdentityResolutionError(
                    "invalid_steam_profile",
                    "The Steam Community /profiles/ URL does not contain a valid SteamID64.",
                ) from exc
        if profile_kind.lower() == "id":
            return "vanity_id", normalize_vanity_id(profile_value)
        raise SteamIdentityResolutionError(
            "invalid_steam_profile",
            "Steam profile URLs must use /profiles/<SteamID64> or /id/<custom-id>.",
        )

    return "vanity_id", normalize_vanity_id(profile_reference)


def resolve_steam_profile(value: str) -> str:
    """Resolve a supported Steam profile reference to a validated SteamID64."""
    reference_kind, reference_value = parse_steam_profile_reference(value)
    if reference_kind == "steam_id":
        return reference_value

    profile_url = (
        "https://steamcommunity.com/id/"
        f"{quote(reference_value, safe='')}/?xml=1"
    )
    request = Request(
        profile_url,
        headers={
            "Accept": "application/xml, text/xml;q=0.9, */*;q=0.1",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read(STEAM_PROFILE_XML_MAX_BYTES + 1)
    except HTTPError as exc:
        raise SteamIdentityResolutionError(
            "steam_profile_http_error",
            f"Steam did not resolve the custom profile (HTTP {exc.code}).",
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SteamIdentityResolutionError(
            "steam_profile_request_failed",
            "The Steam custom-profile lookup failed.",
        ) from exc

    if len(payload) > STEAM_PROFILE_XML_MAX_BYTES:
        raise SteamIdentityResolutionError(
            "steam_profile_invalid_response",
            "Steam returned an unexpectedly large custom-profile response.",
        )

    try:
        profile = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise SteamIdentityResolutionError(
            "steam_profile_invalid_response",
            "Steam returned invalid custom-profile XML.",
        ) from exc

    steam_id = profile.findtext(".//steamID64")
    if steam_id is None:
        raise SteamIdentityResolutionError(
            "steam_profile_not_resolved",
            "Steam did not return a numeric ID for that exact custom profile.",
        )
    try:
        return normalize_steam_id(steam_id)
    except ValueError as exc:
        raise SteamIdentityResolutionError(
            "steam_profile_invalid_response",
            "Steam returned an invalid SteamID64 for the custom profile.",
        ) from exc


def normalize_config_updates(updates: dict[str, str]) -> dict[str, str]:
    """Validate and normalize every supported non-secret update."""
    normalized: dict[str, str] = {}
    for field, value in updates.items():
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        if field == "steam_id":
            normalized[field] = normalize_steam_id(value)
        elif field in {"pricing_country", "report_country"}:
            normalized[field] = normalize_country(value)
        else:
            raise ValueError(f"Unsupported configuration field: {field}")
    if not normalized:
        raise ValueError("At least one configuration field is required")
    return normalized


def current_valid_config_value(config: AppConfig, field: str) -> str | None:
    """Read one validated field, treating an invalid value as unconfigured."""
    try:
        return getattr(config, field)
    except ConfigValueError:
        return None


def write_config_atomically(path: Path, data: dict[str, Any]) -> None:
    """Write JSON beside the target and atomically replace it."""
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            text=True,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as exc:
        raise ConfigError(
            "config_write_failed",
            f"Could not safely write configuration at {path}.",
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def update_config(
    path: Path,
    updates: dict[str, str],
    *,
    replace_existing: bool = False,
) -> dict[str, object]:
    """Merge approved fields while preserving secrets and unrelated settings."""
    normalized_updates = normalize_config_updates(updates)
    config = load_config(path)
    config_created = not path.is_file()

    conflicts: list[str] = []
    updated_fields: list[str] = []
    unchanged_fields: list[str] = []
    for field, value in normalized_updates.items():
        current = current_valid_config_value(config, field)
        if current == value:
            unchanged_fields.append(field)
        elif current is not None and not replace_existing:
            conflicts.append(field)
        else:
            updated_fields.append(field)

    if conflicts:
        raise ConfigUpdateConflict(conflicts)

    if config_created or updated_fields:
        merged: dict[str, Any] = dict(DEFAULT_CONFIG)
        merged.update(config.data)
        for field in updated_fields:
            merged[field] = normalized_updates[field]
        write_config_atomically(path, merged)

    return {
        "config_created": config_created,
        "config_updated": bool(updated_fields),
        "updated_fields": updated_fields,
        "unchanged_fields": unchanged_fields,
    }


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
        description=(
            "Return app IDs from a public Steam wishlist or safely update "
            "approved non-secret configuration fields."
        )
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
            "request, or identity to save with --update-config-only."
        ),
    )
    parser.add_argument(
        "--country",
        type=parse_country_argument,
        help="Pricing country for this request, or to save with --update-config-only.",
    )
    parser.add_argument(
        "--report-country",
        type=parse_country_argument,
        help="Report country to save with --update-config-only.",
    )
    parser.add_argument(
        "--update-config-only",
        action="store_true",
        help="Safely update approved config fields and exit without fetching a wishlist.",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace valid config values after separate explicit user confirmation.",
    )
    args = parser.parse_args()

    if args.replace_existing and not args.update_config_only:
        parser.error("--replace-existing requires --update-config-only")
    if args.report_country and not args.update_config_only:
        parser.error("--report-country requires --update-config-only")

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

    if args.update_config_only:
        updates = {
            field: value
            for field, value in {
                "steam_id": resolved_request_steam_id,
                "pricing_country": args.country,
                "report_country": args.report_country,
            }.items()
            if value is not None
        }
        if not updates:
            emit_error(
                "configuration_not_updated",
                "missing_update_fields",
                (
                    "Provide at least one of --steam-profile, --country, or "
                    "--report-country with --update-config-only."
                ),
            )
            return 2
        try:
            result = update_config(
                CONFIG_PATH,
                updates,
                replace_existing=args.replace_existing,
            )
        except ConfigUpdateConflict as exc:
            emit_error(
                "configuration_not_updated",
                "fields_already_configured",
                str(exc),
                fields=exc.fields,
            )
            return 3
        except ConfigError as exc:
            emit_error("configuration_not_updated", exc.code, str(exc))
            return 2
        except ValueError as exc:
            emit_error("configuration_not_updated", "invalid_update", str(exc))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

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

