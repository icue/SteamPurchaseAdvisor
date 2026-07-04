"""Shared IsThereAnyDeal API helpers for the repository's Steam skills."""

from __future__ import annotations

import argparse
import json
from typing import Any, TypeVar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import AppConfig, load_config, normalize_country


BASE_URL = "https://api.isthereanydeal.com"
STEAM_SHOP_ID = 61
BATCH_SIZE = 200
USER_AGENT = "SteamPurchaseAdvisor/1.0"

T = TypeVar("T")


def parse_country_argument(value: str) -> str:
    """Parse a country code for argparse while preserving a useful error."""
    try:
        return normalize_country(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


class ItadRateLimitError(RuntimeError):
    """Raised when ITAD returns HTTP 429 without retrying automatically."""

    def __init__(self, retry_after: str | None) -> None:
        self.retry_after = retry_after
        retry_value = retry_after or "not provided"
        super().__init__(
            "Rate limited by ITAD (HTTP 429). "
            f"Retry-After: {retry_value}. No automatic retry was attempted."
        )


class MissingItadApiKeyError(RuntimeError):
    """Raised when no ITAD key is configured."""


def load_itad_api_key(config: AppConfig | None = None) -> str:
    """Load the ITAD key from repository-local config.json."""
    value = (config or load_config()).itad_api_key
    if value is None:
        raise MissingItadApiKeyError("itad_api_key is not configured in config.json.")
    return value


def batched(values: list[T], size: int = BATCH_SIZE) -> list[list[T]]:
    """Split values into ITAD-sized request batches."""
    if size <= 0:
        raise ValueError("Batch size must be greater than zero.")
    return [values[index : index + size] for index in range(0, len(values), size)]


def post(
    path: str,
    api_key: str,
    body: Any,
    params: dict[str, Any] | None = None,
) -> Any:
    """POST JSON to ITAD, surfacing rate limits without aggressive retries."""
    url = f"{BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "ITAD-API-Key": api_key,
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 429:
            raise ItadRateLimitError(exc.headers.get("Retry-After")) from exc

        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ITAD API error {exc.code}: {response_body}") from exc
