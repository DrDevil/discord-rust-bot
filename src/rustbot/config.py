"""Configuration loading.

All secrets come from environment variables (CLAUDE.md §8). A local ``.env`` is
supported via python-dotenv. Nothing here is hardcoded, and invalid/missing
config fails loudly at startup rather than half-working later.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Immutable, validated runtime configuration."""

    # Discord
    discord_token: str
    guild_id: int
    alert_channel_id: int

    # Rust+ pairing
    server_ip: str
    server_port: int
    steam_id: int
    player_token: int
    server_id: str

    # Security
    fernet_key: str

    # Behaviour
    poll_interval: float
    database_path: str
    log_level: str
    debug_protobuf: bool


def _require(name: str) -> str:
    """Load a required string environment variable.
    
    :param name: Name of the environment variable to retrieve.
    :return: The non-empty environment variable value.
    :raises ConfigError: If the variable is missing or empty.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _require_int(name: str) -> int:
    """Load a required integer environment variable.
    
    :param name: Name of the environment variable to retrieve.
    :return: The parsed integer value.
    :raises ConfigError: If the variable is missing, empty, or not a valid integer.
    """
    raw = _require(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be an integer") from exc


def _optional(name: str, default: str) -> str:
    """Load an optional string environment variable with a fallback default.
    
    :param name: Name of the environment variable to retrieve.
    :param default: Default value if the variable is missing or empty.
    :return: The environment variable value, or default if not set.
    """
    value = os.environ.get(name, "").strip()
    return value or default


def _as_bool(value: str) -> bool:
    """Parse a string value as a boolean.
    
    Accepts '1', 'true', 'yes', 'on' (case-insensitive) as truthy.
    
    :param value: String value to parse.
    :return: True if value is a recognized truthy string; False otherwise.
    """
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(*, load_dotenv_file: bool = True) -> Settings:
    """Load and validate settings from environment variables (and optional .env).
    
    Reads all required Discord, Rust+, and security settings from the environment.
    Validates ranges (e.g., POLL_INTERVAL >= 5 seconds) and types. Falls back to
    defaults for optional settings (DATABASE_PATH, LOG_LEVEL, DEBUG_PROTOBUF).
    
    :param load_dotenv_file: If True, loads .env file first; defaults to True.
    :return: Immutable Settings object with all validated configuration.
    :raises ConfigError: If any required variable is missing or invalid.
    """
    if load_dotenv_file:
        load_dotenv()

    server_ip = _require("RUST_SERVER_IP")
    server_port = _require_int("RUST_SERVER_PORT")
    server_id = _optional("RUST_SERVER_ID", f"{server_ip}:{server_port}")

    try:
        poll_interval = float(_optional("POLL_INTERVAL", "30"))
    except ValueError as exc:
        raise ConfigError("POLL_INTERVAL must be a number") from exc
    if poll_interval < 5:
        # Guard against hammering the unofficial Rust+ endpoint (§7).
        raise ConfigError("POLL_INTERVAL must be at least 5 seconds")

    return Settings(
        discord_token=_require("DISCORD_TOKEN"),
        guild_id=_require_int("DISCORD_GUILD_ID"),
        alert_channel_id=_require_int("ALERT_CHANNEL_ID"),
        server_ip=server_ip,
        server_port=server_port,
        steam_id=_require_int("RUST_STEAM_ID"),
        player_token=_require_int("RUST_PLAYER_TOKEN"),
        server_id=server_id,
        fernet_key=_require("FERNET_KEY"),
        poll_interval=poll_interval,
        database_path=_optional("DATABASE_PATH", "data/rustbot.db"),
        log_level=_optional("LOG_LEVEL", "INFO").upper(),
        debug_protobuf=_as_bool(_optional("DEBUG_PROTOBUF", "false")),
    )
