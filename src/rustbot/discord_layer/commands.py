"""Slash command registration.

Commands are guild-scoped, permission-gated, and reply with embeds. Each defers
immediately so it always acknowledges within Discord's 3-second window (§6), then
reads from the in-memory ``ServerState`` (cheap, non-blocking) and follows up.
"""

from __future__ import annotations

import logging
from typing import Callable

import discord
from discord import app_commands

from ..domain.state import ServerState
from .embeds import build_server_embed, build_team_embed, build_wipe_embed

logger = logging.getLogger("rustbot.discord.commands")

StateProvider = Callable[[], ServerState]

_NO_MENTIONS = discord.AllowedMentions.none()


def register_commands(
    tree: app_commands.CommandTree,
    guild: discord.abc.Snowflake,
    get_state: StateProvider,
) -> None:
    """Attach the Phase 1 slash commands to the command tree for the given guild.
    
    Creates three commands: /server, /team, /wipe. All are guild-scoped,
    require manage_guild permission, and reply with embeds built from ServerState.
    Each command defers immediately (within 3-second Discord window per CLAUDE.md section 6).
    
    :param tree: Discord command tree to register commands with.
    :param guild: Discord guild (Snowflake) for guild-scoped command registration.
    :param get_state: Callable that returns current ServerState (for command responses).
    :return: None (registers command handlers as side effect).
    """

    @tree.command(
        name="server",
        description="Show the Rust server's online status and details.",
        guild=guild,
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def server(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        embed = build_server_embed(get_state())
        await interaction.followup.send(embed=embed, allowed_mentions=_NO_MENTIONS)

    @tree.command(
        name="team",
        description="Show which teammates are online or offline.",
        guild=guild,
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def team(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        embed = build_team_embed(get_state())
        await interaction.followup.send(embed=embed, allowed_mentions=_NO_MENTIONS)

    @tree.command(
        name="wipe",
        description="Show the last detected server wipe.",
        guild=guild,
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def wipe(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        embed = build_wipe_embed(get_state())
        await interaction.followup.send(embed=embed, allowed_mentions=_NO_MENTIONS)
