"""Application wiring and lifecycle.

Builds every layer, connects them, and runs the Discord client and the Rust+
poll loop concurrently on a single asyncio loop (CLAUDE.md §13 — nothing blocks
the event loop). On startup the player token is encrypted and stored at rest, and
the last-known state is restored from SQLite so the bot survives restarts without
re-firing stale alerts.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from .config import ConfigError, Settings, load_settings
from .crypto import TokenCipher
from .discord_layer.bot import DiscordBot
from .domain.alerts import AlertEngine
from .event_router.router import EventRouter, restore_state
from .logging_setup import setup_logging
from .persistence.sqlite_store import SqliteRepository
from .rustplus_client.client import RustClient

logger = logging.getLogger("rustbot.app")


async def _ensure_token_stored(
    repo: SqliteRepository, cipher: TokenCipher, settings: Settings
) -> None:
    """Persist the player token encrypted at rest (idempotent)."""
    encrypted = cipher.encrypt(str(settings.player_token))
    await repo.upsert_server(
        server_id=settings.server_id,
        ip=settings.server_ip,
        port=settings.server_port,
        steam_id=settings.steam_id,
        encrypted_player_token=encrypted,
    )


async def run(settings: Settings) -> None:
    cipher = TokenCipher(settings.fernet_key)

    repo = SqliteRepository(settings.database_path)
    await repo.connect()
    await _ensure_token_stored(repo, cipher, settings)

    # Restore last-known state so we don't re-alert on restart.
    record = await repo.load_server_state(settings.server_id)
    state = restore_state(record, settings.server_id)

    router = EventRouter(state=state, repository=repo)

    bot = DiscordBot(
        guild_id=settings.guild_id,
        alert_channel_id=settings.alert_channel_id,
        state_provider=lambda: router.state,
    )

    engine = AlertEngine(sink=bot)
    router.subscribe(engine.handle_event)

    client = RustClient(
        server_id=settings.server_id,
        ip=settings.server_ip,
        port=settings.server_port,
        steam_id=settings.steam_id,
        player_token=settings.player_token,
        poll_interval=settings.poll_interval,
        on_info=router.on_info,
        on_team=router.on_team,
        on_raw=router.on_raw,
        debug=settings.debug_protobuf,
    )

    logger.info(
        "starting bot",
        extra={"server_id": settings.server_id, "event_type": "startup"},
    )

    try:
        await client.start()
        # bot.start blocks until disconnect; run it as the main coroutine.
        await bot.start(settings.discord_token)
    finally:
        logger.info(
            "shutting down",
            extra={"server_id": settings.server_id, "event_type": "shutdown"},
        )
        await client.stop()
        if not bot.is_closed():
            await bot.close()
        await repo.close()


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        # Logging is not configured yet; emit a single clear line to stderr and
        # exit non-zero so the operator sees exactly what is missing.
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    setup_logging(
        settings.log_level,
        secrets=(
            settings.discord_token,
            str(settings.player_token),
            settings.fernet_key,
        ),
        debug_protobuf=settings.debug_protobuf,
    )
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        logger.info("interrupted by user", extra={"event_type": "interrupt"})


if __name__ == "__main__":
    main()
