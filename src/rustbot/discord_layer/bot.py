"""Discord client: command registration/sync and alert delivery.

Implements the domain ``AlertSink`` protocol (``send_alert``) so the alert engine
can post without knowing anything about discord.py. Uses minimal gateway intents
(guilds only — no message content) per the least-privilege security decision.
"""

from __future__ import annotations

import logging
from typing import Callable

import discord
from discord import app_commands

from ..domain.alerts import Alert
from ..domain.state import ServerState
from .commands import register_commands
from .embeds import build_alert_embed

logger = logging.getLogger("rustbot.discord.bot")

StateProvider = Callable[[], ServerState]

_NO_MENTIONS = discord.AllowedMentions.none()


def _minimal_intents() -> discord.Intents:
    intents = discord.Intents.none()
    intents.guilds = True  # needed for channel cache / command sync
    return intents


class DiscordBot(discord.Client):
    def __init__(
        self,
        *,
        guild_id: int,
        alert_channel_id: int,
        state_provider: StateProvider,
    ) -> None:
        super().__init__(intents=_minimal_intents(), allowed_mentions=_NO_MENTIONS)
        self._guild = discord.Object(id=guild_id)
        self._alert_channel_id = alert_channel_id
        self._state_provider = state_provider
        self.tree = app_commands.CommandTree(self)
        register_commands(self.tree, self._guild, state_provider)

    async def setup_hook(self) -> None:
        # Guild-scoped sync is instant (no global propagation delay).
        await self.tree.sync(guild=self._guild)
        logger.info(
            "slash commands synced",
            extra={"event_type": "commands_synced"},
        )

    async def on_ready(self) -> None:
        user = self.user
        logger.info(
            "discord connected as %s",
            user,
            extra={"event_type": "discord_ready"},
        )

    # ----------------------------------------------------- AlertSink protocol
    async def send_alert(self, alert: Alert) -> None:
        """Render and deliver an alert embed to the configured channel."""
        await self.wait_until_ready()
        channel = await self._resolve_channel()
        if channel is None:
            logger.error(
                "alert channel %s not found or not sendable",
                self._alert_channel_id,
                extra={"event_type": "alert_channel_missing"},
            )
            return
        try:
            await channel.send(
                embed=build_alert_embed(alert), allowed_mentions=_NO_MENTIONS
            )
        except discord.DiscordException:
            logger.exception(
                "failed to send alert",
                extra={
                    "server_id": alert.server_id,
                    "event_type": "alert_send_error",
                },
            )

    async def _resolve_channel(self) -> "discord.abc.Messageable | None":
        channel = self.get_channel(self._alert_channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(self._alert_channel_id)
            except discord.DiscordException:
                return None
        return channel if isinstance(channel, discord.abc.Messageable) else None
