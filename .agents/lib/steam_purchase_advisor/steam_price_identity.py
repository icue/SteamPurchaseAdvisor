"""Match Steam Store app pricing to the correct ITAD game identity."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .itad_client import STEAM_SHOP_ID, USER_AGENT


STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_RETRY_DELAYS = (1.0, 2.0)


class SteamAppDetailsError(RuntimeError):
    """Raised when Steam does not return usable AppDetails metadata."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class PriceIdentityError(RuntimeError):
    """Raised when no unique ITAD identity matches Steam's current offer."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True)
class SteamAppDetails:
    """Steam metadata needed for release-state and price-identity decisions."""

    appid: str
    data: dict[str, Any]
    currency: str | None
    initial_amount_int: int | None
    final_amount_int: int | None
    discount_percent: int | float | None
    all_products: tuple[str, ...]
    base_package_products: tuple[str, ...]

    @property
    def has_price(self) -> bool:
        return (
            self.currency is not None
            and self.initial_amount_int is not None
            and self.final_amount_int is not None
        )

    @property
    def is_discounted(self) -> bool:
        return (
            self.has_price
            and self.final_amount_int is not None
            and self.initial_amount_int is not None
            and self.final_amount_int < self.initial_amount_int
        )


@dataclass(frozen=True)
class SelectedPriceIdentity:
    """A single Steam product and ITAD identity with an exact price match."""

    product: str
    itad_id: str
    offer: dict[str, Any]
    source: str


def _positive_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdigit():
        parsed = int(value)
        if parsed > 0:
            return str(parsed)
    return None


def _amount_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _is_true(value: Any) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() in {"1", "true"}


def parse_steam_appdetails(appid: str | int, data: dict[str, Any]) -> SteamAppDetails:
    """Normalize one successful Steam AppDetails data object."""
    appid_text = str(appid)
    price_overview = data.get("price_overview")
    if isinstance(price_overview, dict):
        currency_value = price_overview.get("currency")
        currency = (
            currency_value
            if isinstance(currency_value, str) and currency_value
            else None
        )
        initial = _amount_int(price_overview.get("initial"))
        final = _amount_int(price_overview.get("final"))
        discount_value = price_overview.get("discount_percent")
        discount_percent = (
            discount_value
            if isinstance(discount_value, (int, float))
            and not isinstance(discount_value, bool)
            else None
        )
    else:
        currency = None
        initial = None
        final = None
        discount_percent = None

    package_ids: list[str] = []
    packages = data.get("packages")
    if not isinstance(packages, list):
        packages = []
    for value in packages:
        package_id = _positive_id(value)
        if package_id is not None:
            package_ids.append(package_id)

    base_package_ids: list[str] = []
    package_groups = data.get("package_groups")
    if not isinstance(package_groups, list):
        package_groups = []
    for group in package_groups:
        if not isinstance(group, dict):
            continue
        subs = group.get("subs")
        if not isinstance(subs, list):
            continue
        for sub in subs:
            if not isinstance(sub, dict):
                continue
            package_id = _positive_id(sub.get("packageid"))
            if package_id is None:
                continue
            package_ids.append(package_id)
            if _is_true(sub.get("is_free_license")) or _is_true(
                sub.get("can_get_free_license")
            ):
                continue
            sub_price = _amount_int(sub.get("price_in_cents_with_discount"))
            if final is not None and sub_price == final:
                base_package_ids.append(package_id)

    all_products = [f"app/{appid_text}"]
    all_products.extend(f"sub/{package_id}" for package_id in package_ids)
    base_products = [f"sub/{package_id}" for package_id in base_package_ids]

    return SteamAppDetails(
        appid=appid_text,
        data=data,
        currency=currency,
        initial_amount_int=initial,
        final_amount_int=final,
        discount_percent=discount_percent,
        all_products=tuple(dict.fromkeys(all_products)),
        base_package_products=tuple(dict.fromkeys(base_products)),
    )


def fetch_steam_appdetails(
    appid: str | int, country: str | None = None
) -> SteamAppDetails:
    """Fetch one regional AppDetails record with bounded retries."""
    appid_text = str(appid)
    params: dict[str, str] = {"appids": appid_text, "l": "english"}
    if country is not None:
        params["cc"] = country
    request = Request(
        f"{STEAM_APPDETAILS_URL}?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )

    attempts = len(STEAM_RETRY_DELAYS) + 1
    last_reason = "steam_store_request_failed"
    last_message = "Steam AppDetails request failed."

    for attempt in range(attempts):
        retryable = True
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
            entry = payload.get(appid_text) if isinstance(payload, dict) else None
            data = (
                entry.get("data")
                if isinstance(entry, dict) and entry.get("success") is True
                else None
            )
            if not isinstance(data, dict):
                last_reason = "steam_invalid_response"
                last_message = "Steam returned no usable app details."
            else:
                return parse_steam_appdetails(appid_text, data)
        except HTTPError as exc:
            last_reason = f"steam_http_{exc.code}"
            last_message = f"Steam AppDetails request failed with HTTP {exc.code}."
            retryable = exc.code == 429 or 500 <= exc.code < 600
        except json.JSONDecodeError:
            last_reason = "steam_invalid_response"
            last_message = "Steam returned invalid AppDetails JSON."
        except (URLError, TimeoutError, OSError):
            last_reason = "steam_store_request_failed"
            last_message = "Steam AppDetails request failed."

        if not retryable or attempt == attempts - 1:
            break
        time.sleep(STEAM_RETRY_DELAYS[attempt])

    raise SteamAppDetailsError(last_reason, last_message)


def offer_matches_steam(
    offer: dict[str, Any], steam_details: SteamAppDetails
) -> bool:
    """Require an exact regional currency and minor-unit price match."""
    if not steam_details.has_price:
        return False
    shop = offer.get("shop")
    if not isinstance(shop, dict) or shop.get("id") != STEAM_SHOP_ID:
        return False
    price = offer.get("price")
    regular = offer.get("regular")
    if not isinstance(price, dict) or not isinstance(regular, dict):
        return False
    if (
        price.get("currency") != steam_details.currency
        or regular.get("currency") != steam_details.currency
    ):
        return False
    return (
        _amount_int(price.get("amountInt")) == steam_details.final_amount_int
        and _amount_int(regular.get("amountInt"))
        == steam_details.initial_amount_int
    )


def select_itad_price_identity(
    steam_details: SteamAppDetails,
    product_to_itad_id: dict[str, str],
    offers_by_itad_id: dict[str, list[dict[str, Any]]],
) -> SelectedPriceIdentity:
    """Prefer the app identity, then require one unambiguous base package."""
    if not steam_details.has_price:
        raise PriceIdentityError(
            "steam_price_metadata_unavailable",
            "Steam returned no complete regional price metadata.",
        )

    def matching_offer(itad_id: str) -> dict[str, Any] | None:
        for offer in offers_by_itad_id.get(itad_id, []):
            if isinstance(offer, dict) and offer_matches_steam(offer, steam_details):
                return offer
        return None

    app_product = f"app/{steam_details.appid}"
    app_itad_id = product_to_itad_id.get(app_product)
    if app_itad_id:
        app_offer = matching_offer(app_itad_id)
        if app_offer is not None:
            return SelectedPriceIdentity(
                product=app_product,
                itad_id=app_itad_id,
                offer=app_offer,
                source="app",
            )

    package_matches: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for product in steam_details.base_package_products:
        itad_id = product_to_itad_id.get(product)
        if not itad_id:
            continue
        offer = matching_offer(itad_id)
        if offer is not None:
            package_matches.setdefault(itad_id, []).append((product, offer))

    if not package_matches:
        raise PriceIdentityError(
            "steam_price_identity_unresolved",
            "No ITAD app or base-package identity matched Steam's regional price.",
        )
    if len(package_matches) > 1:
        raise PriceIdentityError(
            "steam_price_identity_ambiguous",
            "Multiple distinct ITAD package identities matched Steam's regional price.",
        )

    itad_id, matches = next(iter(package_matches.items()))
    product, offer = min(matches, key=lambda match: match[0])
    return SelectedPriceIdentity(
        product=product,
        itad_id=itad_id,
        offer=offer,
        source="package",
    )
