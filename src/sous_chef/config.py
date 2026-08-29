"""Environment-based runtime settings for the sous-chef bot."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_DB_PATH = "./sous_chef.db"


class ConfigError(ValueError):
    """A required environment variable is missing or has an invalid value."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime configuration resolved from the environment."""

    anthropic_api_key: str
    telegram_token: str
    chat_id: int
    db_path: Path
    tz: tzinfo
    model: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        return cls(
            anthropic_api_key=_require(source, "ANTHROPIC_API_KEY"),
            telegram_token=_require(source, "SOUS_CHEF_TELEGRAM_TOKEN"),
            chat_id=_parse_chat_id(_require(source, "SOUS_CHEF_CHAT_ID")),
            db_path=Path(source.get("SOUS_CHEF_DB_PATH", DEFAULT_DB_PATH)),
            tz=_parse_tz(source.get("SOUS_CHEF_TZ")),
            model=source.get("SOUS_CHEF_MODEL", DEFAULT_MODEL),
        )


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"required environment variable {name} is not set")
    return value


def _parse_chat_id(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(
            f"SOUS_CHEF_CHAT_ID must be a numeric Telegram chat id, got {raw!r}"
        ) from None


def _parse_tz(raw: str | None) -> tzinfo:
    # Default to the machine's local zone when unset.
    if raw is None or not raw.strip():
        local = datetime.now().astimezone().tzinfo
        assert local is not None  # astimezone() always attaches a tzinfo
        return local
    try:
        return ZoneInfo(raw.strip())
    except ZoneInfoNotFoundError:
        raise ConfigError(
            f"SOUS_CHEF_TZ must be a valid IANA timezone name, got {raw!r}"
        ) from None
