# Phase 1 — Foundation (MVP)

## Goal: “Free alternative with core value”

## Features:

* Rust+ login & pairing
* Server online/offline
* Wipe detection
* Team online/offline
* Discord alerts only (no control)

## Commands:

* /server
* /team
* /wipe

# Phase 2 — Smart Devices

## Goal: Match paid bots’ killer features

## Features:

* Smart alarm notifications
* Smart switch state tracking
* Storage access alerts

## Commands:

* /switch on|off
* /alarms

# Phase 3 — Combat & Defense

## Goal: Base defense awareness

## Features:

* Turret online/offline
* Turret ammo warnings
* SAM triggers

## Commands:

* /turrets

# Phase 4 — Automation & Rules

## Goal: Replace “premium tiers”

## Features:

* Alert rules engine
* Cooldowns
* Role pings
* Quiet hours

# Phase 5 — Multi-Server & Polish

## Goal: Paid-level replacement

## Features:

* Multiple servers
* Multiple Discord guilds
* Persistent config
* Backup & restore

# Technology Stack (Suggested)
Language: Python
Discord: discord.py (slash commands)
Rust+: Custom Rust+ client (WebSocket + Protobuf)
Storage: SQLite or JSON (initially)
Async runtime: asyncio
Deployment: Docker

# Known Limitations (Phase 1)

## Configuration reload
The bot reads `.env` configuration **once at startup**. If you change a setting
(e.g., server IP, port, Discord channel ID), the bot must be **restarted** for
the change to take effect. Dynamic reload is out of scope for MVP.

---

# Legal & Ethical Notes (Important)

Rust+ protocol is unofficial
Many bots reverse-engineer it

Keep it:
* Personal use
* Small communities
* Non-commercial
