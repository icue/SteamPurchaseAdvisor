#!/usr/bin/env python3
"""Safely merge approved non-secret Steam Purchase Advisor config fields."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


SHARED_LIB = Path(__file__).resolve().parents[1]
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


DEFAULT_CONFIG: dict[str, str] = {
    "steam_id": "",
    "itad_api_key": "",
    "pricing_country": "",
    "report_country": "",
}


class ConfigUpdateConflict(RuntimeError):
    """Raised when an update would replace a valid configured value."""

    def __init__(self, fields: list[str]) -> None:
        self.fields = fields
        super().__init__("Refusing to replace already configured fields without approval.")


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


def parse_steam_id_argument(value: str) -> str:
    try:
        return normalize_steam_id(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_country_argument(value: str) -> str:
    try:
        return normalize_country(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def emit_error(reason: str, message: str, **details: object) -> None:
    payload: dict[str, object] = {
        "error": "configuration_not_updated",
        "reason": reason,
        "message": message,
    }
    payload.update({key: value for key, value in details.items() if value is not None})
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely update approved non-secret configuration fields."
    )
    parser.add_argument("--steam-id", type=parse_steam_id_argument)
    parser.add_argument(
        "--pricing-country",
        "--country",
        dest="pricing_country",
        type=parse_country_argument,
    )
    parser.add_argument("--report-country", type=parse_country_argument)
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace valid fields only after separate explicit user confirmation.",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=CONFIG_PATH,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    updates = {
        field: value
        for field, value in {
            "steam_id": args.steam_id,
            "pricing_country": args.pricing_country,
            "report_country": args.report_country,
        }.items()
        if value is not None
    }
    if not updates:
        emit_error(
            "missing_update_fields",
            (
                "Provide at least one of --steam-id, --pricing-country, or "
                "--report-country."
            ),
        )
        return 2

    try:
        result = update_config(
            args.config_path,
            updates,
            replace_existing=args.replace_existing,
        )
    except ConfigUpdateConflict as exc:
        emit_error("fields_already_configured", str(exc), fields=exc.fields)
        return 3
    except ConfigError as exc:
        emit_error(exc.code, str(exc))
        return 2
    except ValueError as exc:
        emit_error("invalid_update", str(exc))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
