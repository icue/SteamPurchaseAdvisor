#!/usr/bin/env python3
"""Resolve supported Steam profile references to a canonical SteamID64."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree


SHARED_LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED_LIB))

from steam_purchase_advisor.config import normalize_steam_id  # noqa: E402
from steam_purchase_advisor.itad_client import USER_AGENT  # noqa: E402


STEAM_COMMUNITY_HOSTS = {"steamcommunity.com", "www.steamcommunity.com"}
STEAM_PROFILE_XML_MAX_BYTES = 1_000_000


class SteamIdentityResolutionError(RuntimeError):
    """Raised when a Steam profile reference cannot be resolved to SteamID64."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


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


def emit_error(reason: str, message: str) -> None:
    print(
        json.dumps(
            {
                "error": "steam_identity_unavailable",
                "reason": reason,
                "message": message,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a SteamID64, profile URL, or exact custom ID to SteamID64."
    )
    parser.add_argument(
        "--steam-profile",
        "--steam-id",
        dest="steam_profile",
        required=True,
        help="SteamID64, Steam Community profile URL, or exact custom ID.",
    )
    args = parser.parse_args()

    try:
        steam_id = resolve_steam_profile(args.steam_profile)
    except SteamIdentityResolutionError as exc:
        emit_error(
            exc.reason,
            (
                f"{exc} If automatic resolution remains unavailable, use "
                "https://steamid.io/lookup/ and provide the resulting "
                "17-digit SteamID64."
            ),
        )
        return 2

    print(json.dumps({"steam_id": steam_id}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
