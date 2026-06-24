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

### Local development

Build and run with Docker Compose (handles env, volumes, and restart policy):

```bash
docker compose up --build
```

Or manually with `docker run`:

```bash
docker build -t discord-rust-bot .
docker run --rm \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  discord-rust-bot
```

On Windows PowerShell:

```powershell
docker build -t discord-rust-bot .
docker run --rm `
  --env-file .env `
  -v "${PWD}/data:/app/data" `
  discord-rust-bot
```

### Remote deployment

**1. Build and push the image**

```bash
docker build -t discord-rust-bot .
docker tag discord-rust-bot your-registry/discord-rust-bot:latest
docker push your-registry/discord-rust-bot:latest
```

(Use your own registry—Docker Hub, GitHub Container Registry, or private registry.)

**2. On the remote server, prepare the environment**

```bash
# Create a deployment directory
mkdir -p ~/discord-rust-bot
cd ~/discord-rust-bot

# Create .env with your configuration (manual step)
cat > .env << 'EOF'
DISCORD_TOKEN=your_token_here
DISCORD_GUILD_ID=your_guild_id
ALERT_CHANNEL_ID=your_channel_id
RUST_SERVER_IP=your_server_ip
RUST_SERVER_PORT=server_port
RUST_STEAM_ID=your_steam_id
RUST_PLAYER_TOKEN=your_player_token
FERNET_KEY=your_fernet_key
EOF

# Create persistent data directory
mkdir -p data
```

**3. Pull and run the image**

```bash
docker pull your-registry/discord-rust-bot:latest

docker run -d \
  --name discord-rust-bot \
  --restart unless-stopped \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  your-registry/discord-rust-bot:latest
```

**4. Monitor and manage**

```bash
# View logs
docker logs -f discord-rust-bot

# Stop the bot
docker stop discord-rust-bot

# Restart the bot
docker restart discord-rust-bot

# Remove the container (data persists in ./data)
docker rm discord-rust-bot
```

### Data persistence

The SQLite database is stored in `/app/data` inside the container and mounted to `./data` on the host. This ensures:

- Database survives container restarts
- Easy backups (copy `./data/rustbot.db`)
- Simple recovery if needed

**Keep `FERNET_KEY` separate from database backups**—the key is stored in `.env` (in the environment), not in the database.

### Notes

- No inbound ports are exposed (the bot makes only outbound connections).
- The container runs as a non-root user (`rustbot:1000`) for security.
- Use `restart: unless-stopped` in production so the bot restarts automatically after a crash or host reboot.

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
