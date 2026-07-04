"""Load per-user Steam Purchase Advisor configuration without exposing secrets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "config.json"


class ConfigError(RuntimeError):
    """Raised when the configuration file cannot be loaded."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ConfigValueError(ConfigError):
    """Raised only when a caller accesses one invalid configuration field."""

    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        super().__init__(code, message)


def normalize_steam_id(value: str) -> str:
    """Normalize and validate a decimal SteamID64 string."""
    steam_id = value.strip()
    if len(steam_id) != 17 or not steam_id.isascii() or not steam_id.isdigit():
        raise ValueError("steam_id must be a 17-digit SteamID64 string")
    return steam_id


def normalize_country(value: str) -> str:
    """Normalize and validate an ISO 3166-1 alpha-2 country code."""
    country = value.strip().upper()
    if len(country) != 2 or not country.isascii() or not country.isalpha():
        raise ValueError("country must be a two-letter ISO code, such as CN or US")
    return country


@dataclass(frozen=True)
class AppConfig:
    """Provide lazy, field-specific validation for a config mapping."""

    data: dict[str, Any]
    path: Path = CONFIG_PATH

    def _optional_string(self, field: str) -> str | None:
        value = self.data.get(field)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ConfigValueError(
                field,
                f"invalid_{field}",
                f"{field} must be a string or null in {self.path}.",
            )
        value = value.strip()
        return value or None

    @property
    def steam_id(self) -> str | None:
        value = self._optional_string("steam_id")
        if value is None:
            return None
        try:
            return normalize_steam_id(value)
        except ValueError as exc:
            raise ConfigValueError(
                "steam_id", "invalid_steam_id", f"Invalid steam_id in {self.path}: {exc}."
            ) from exc

    @property
    def itad_api_key(self) -> str | None:
        return self._optional_string("itad_api_key")

    def _country(self, field: str) -> str | None:
        value = self._optional_string(field)
        if value is None:
            return None
        try:
            return normalize_country(value)
        except ValueError as exc:
            raise ConfigValueError(
                field, f"invalid_{field}", f"Invalid {field} in {self.path}: {exc}."
            ) from exc

    @property
    def pricing_country(self) -> str | None:
        return self._country("pricing_country")

    @property
    def report_country(self) -> str | None:
        return self._country("report_country")


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    """Load config.json, treating a missing file as an empty configuration."""
    try:
        with path.open(encoding="utf-8-sig") as config_file:
            payload = json.load(config_file)
    except FileNotFoundError:
        payload = {}
    except OSError as exc:
        raise ConfigError("config_unreadable", f"Could not read configuration at {path}.") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError("config_invalid_json", f"Invalid JSON in configuration at {path}.") from exc

    if not isinstance(payload, dict):
        raise ConfigError("config_not_object", f"Configuration at {path} must be a JSON object.")
    return AppConfig(payload, path)
