# discord-rust-bot

A self-hosted Discord bot for the game **Rust** that connects to a server via the
unofficial **Rust+** protocol, receives real-time push events, and posts alerts /
answers slash commands. Non-commercial, personal/community use only.

This is **Phase 1 (Foundation / MVP)** — alerts only, no device control:

| Feature | Detail |
| --- | --- |
| Server online/offline | Alert when the server becomes (un)reachable |
| Wipe detection | Alert when the server's wipe time changes |
| Team online/offline | Alert when a teammate's online status changes |
| `/server` | Server status, players, map seed/size, last wipe |
| `/team` | Teammates online/offline (names only — no positions) |
| `/wipe` | Last detected wipe time |

> Later phases (smart devices, turrets, rules engine, multi-server) are intentionally
> out of scope — see `PROJECT_PLAN.md`.

## Architecture

Strict layer separation (see `CLAUDE.md` §4):

```
rustplus_client → event_router → domain → discord_layer
                                    ↕
                                persistence (SQLite)
```

Nothing outside `rustplus_client` imports the third-party `rustplus` library; nothing
outside `discord_layer` imports `discord.py`. The domain emits neutral `Alert` objects
to a sink the Discord layer implements.

## Requirements

- **Python 3.11+** (developed/tested on 3.12)
- A Discord application + bot token
- Rust+ pairing credentials for your server (see below)

## Setup

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
# (runtime only: requirements.txt)

cp .env.example .env   # then fill it in
```

### 1. Discord bot

1. Create an application at the Discord Developer Portal and add a **Bot**.
2. Copy the bot token into `DISCORD_TOKEN`.
3. Invite the bot with the `bot` + `applications.commands` scopes (no privileged
   intents are required — this bot does not read message content).
4. Put your guild ID in `DISCORD_GUILD_ID` and the alerts channel ID in
   `ALERT_CHANNEL_ID`.

Slash commands are **guild-scoped** (they appear instantly) and gated behind the
*Manage Server* permission by default; adjust per-role in **Server Settings →
Integrations** if needed.

### 2. Rust+ pairing credentials (manual, one-time)

This bot does **not** implement the Google/Steam FCM pairing flow (a deliberate scope
decision). Obtain the four values once using the standard community tool, then paste
them into `.env`:

1. Install Node.js and run the registration helper:
   ```bash
   npx @liamcottle/rustplus.js fcm-register
   ```
   This opens a browser to log in with Google + Steam and writes a credentials file.
2. In Rust, open the in-game contacts/pairing menu and **pair** with your server.
3. The helper (e.g. `npx @liamcottle/rustplus.js fcm-listen`) prints the server
   `ip`, `port`, `playerId`, and `playerToken`. Put them in `.env`:
   - `RUST_SERVER_IP`, `RUST_SERVER_PORT`
   - `RUST_STEAM_ID`  (the `playerId`, your 64-bit Steam ID — an integer)
   - `RUST_PLAYER_TOKEN`  (the `playerToken` — an integer)

### 3. Encryption key

The player token is stored **encrypted at rest** in SQLite. Generate a Fernet key:

```bash
python -m rustbot.genkey
```

Put it in `FERNET_KEY`. **Keep this key out of any database backups** — see Security.

### 4. Run

```bash
# from the project root, with .venv active
python -m rustbot
# or without activating: PYTHONPATH=src python -m rustbot
```

## Docker

This application can run in Docker using environment variables for configuration.

Build the image:

```bash
docker build -t discord-rust-bot .
```

Run the container with an env file and a mounted data directory:

```bash
docker run --rm \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  discord-rust-bot
```

On Windows PowerShell, use:

```powershell
docker run --rm `
  --env-file .env `
  -v "${PWD}/data:/app/data" `
  discord-rust-bot
```

No Docker port publishing is required because the bot makes only outbound connections.

If you prefer Compose, use:

```bash
docker compose up --build
```

## Testing

```bash
python -m pytest
```

The suite covers the change-detection rules (baseline-then-transition, no duplicate
alerts), alert rendering, persistence round-trips (incl. token encryption), and router
event flow. None of it requires a live Rust server or Discord connection.

## Security notes

- **Treat `RUST_PLAYER_TOKEN` and `DISCORD_TOKEN` like passwords.** They are never
  logged (a redaction filter masks them defensively) and never echoed to Discord.
- **Encryption at rest** protects a leaked DB file/backup *only if `FERNET_KEY` is not
  stored alongside it*. The key lives in the environment, not the database. This is
  "simple encryption"; it does not defend against full host compromise.
- **Untrusted game data** (server/player names) is sanitised and posted with mentions
  disabled, so a player named `@everyone` cannot ping your server.
- `/team` shows online/offline + names only — **no coordinates** — to avoid leaking
  teammate locations.
- `DEBUG_PROTOBUF` logs raw Rust+ traffic and **may contain sensitive data**; it is off
  by default and should not be enabled in shared environments.
- `.env`, `*.db`, and credential files are git-ignored. Never commit real secrets.

## Legal / ethical

The Rust+ protocol is unofficial and unstable. Keep this for personal use and small
communities, non-commercial, and not redistributed as a hosted service.
