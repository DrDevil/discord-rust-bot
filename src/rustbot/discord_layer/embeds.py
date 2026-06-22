"""Embed builders and untrusted-text sanitisation.

All text originating from the Rust server (server name, player names) is
untrusted and is sanitised here before being placed in an embed: mention tokens
are defanged and length is bounded. Mentions are additionally disabled at send
time via ``discord.AllowedMentions.none()`` in ``bot.py`` (defence in depth).
"""

from __future__ import annotations

from datetime import datetime, timezone

import discord

from ..domain.alerts import Alert, AlertLevel
from ..domain.state import ServerState

_MAX_FIELD = 256

_LEVEL_COLOURS = {
    AlertLevel.GOOD: discord.Colour.green(),
    AlertLevel.INFO: discord.Colour.blurple(),
    AlertLevel.WARNING: discord.Colour.orange(),
}


def sanitize(text: str | None, *, max_len: int = _MAX_FIELD) -> str:
    """Neutralise mention tokens and bound the length of untrusted text."""
    if not text:
        return "—"
    cleaned = (
        text.replace("@everyone", "@​everyone")
        .replace("@here", "@​here")
        .replace("<@", "<​@")
    )
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1] + "…"
    return cleaned


def _epoch_to_str(epoch: int | None) -> str:
    if not epoch:
        return "Unknown"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_alert_embed(alert: Alert) -> discord.Embed:
    embed = discord.Embed(
        title=sanitize(alert.title, max_len=256),
        description=sanitize(alert.description, max_len=2048),
        colour=_LEVEL_COLOURS.get(alert.level, discord.Colour.light_grey()),
        timestamp=alert.timestamp,
    )
    for name, value in alert.fields:
        embed.add_field(name=sanitize(name, max_len=256), value=sanitize(value), inline=True)
    embed.set_footer(text=f"server: {sanitize(alert.server_id, max_len=64)}")
    return embed


def build_server_embed(state: ServerState) -> discord.Embed:
    online = state.online
    if online is True:
        colour, status = discord.Colour.green(), "🟢 Online"
    elif online is False:
        colour, status = discord.Colour.red(), "🔴 Offline"
    else:
        colour, status = discord.Colour.light_grey(), "❔ Unknown"

    embed = discord.Embed(title="Rust Server Status", colour=colour)
    embed.add_field(name="Status", value=status, inline=True)

    info = state.last_info
    if info is not None:
        embed.add_field(name="Name", value=sanitize(info.name), inline=False)
        if info.players is not None and info.max_players is not None:
            players = f"{info.players}/{info.max_players}"
            if info.queued_players:
                players += f" (+{info.queued_players} queued)"
            embed.add_field(name="Players", value=players, inline=True)
        if info.size is not None:
            embed.add_field(name="Map size", value=str(info.size), inline=True)
        if info.seed is not None:
            embed.add_field(name="Seed", value=str(info.seed), inline=True)
        embed.add_field(name="Last wipe", value=_epoch_to_str(state.wipe_time), inline=True)
    else:
        embed.description = "No server information has been received yet."

    embed.set_footer(text=f"server: {sanitize(state.server_id, max_len=64)}")
    return embed


def build_team_embed(state: ServerState) -> discord.Embed:
    embed = discord.Embed(title="Team Status", colour=discord.Colour.blurple())

    if not state.member_names:
        embed.description = "No team information has been received yet."
        embed.set_footer(text=f"server: {sanitize(state.server_id, max_len=64)}")
        return embed

    online_lines = []
    offline_lines = []
    for steam_id, name in sorted(state.member_names.items(), key=lambda kv: kv[1].lower()):
        # Phase 1 intentionally shows online/offline + name only — no positions,
        # to avoid leaking teammate locations (security review decision).
        label = sanitize(name, max_len=64)
        if state.members.get(steam_id):
            online_lines.append(f"🟢 {label}")
        else:
            offline_lines.append(f"⚪ {label}")

    embed.add_field(
        name=f"Online ({len(online_lines)})",
        value="\n".join(online_lines) or "—",
        inline=False,
    )
    embed.add_field(
        name=f"Offline ({len(offline_lines)})",
        value="\n".join(offline_lines) or "—",
        inline=False,
    )
    embed.set_footer(text=f"server: {sanitize(state.server_id, max_len=64)}")
    return embed


def build_wipe_embed(state: ServerState) -> discord.Embed:
    embed = discord.Embed(title="Last Detected Wipe", colour=discord.Colour.orange())
    if state.wipe_time:
        embed.add_field(name="Wipe time", value=_epoch_to_str(state.wipe_time), inline=False)
    else:
        embed.description = "No wipe has been detected yet."
    embed.set_footer(text=f"server: {sanitize(state.server_id, max_len=64)}")
    return embed
