# discord-grint

Discord self-bot with:
- agent-style reply pipeline (`classify -> plan -> retrieve memory -> generate -> critique -> send`)
- SQLite memory store
- Flask web panel for settings, monitoring, and bot control

## Stack
- Python 3.12+
- `discord.py-self`
- `openai` (OpenRouter endpoint)
- `python-dotenv`
- `flask`
- SQLite

## Project Layout
- `bot.py`: main bot loop
- `config.py`: merged config loader (`.env` + `web_settings.json`)
- `agent/`: classifier, planner, generator, critic
- `memory/`: context cache, event store, user profile store
- `storage/sqlite_store.py`: SQLite adapter
- `web/`: web UI + API (`web/app.py`)
- `skills/base/general.md`: base persona (always loaded)
- `skills/projects/donut_browser.md`: project persona (crypto/project mode)

## Quick Start
1. Clone:
```bash
git clone https://github.com/moree44/discord-grint.git
cd discord-grint
```

2. Create venv:
```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install deps:
```bash
python -m pip install -U pip
python -m pip install discord.py-self openai python-dotenv flask
```

4. Create `.env`:
```env
DISCORD_TOKEN=your_discord_token
OPENROUTER_API_KEY=your_openrouter_api_key
AI_MODELS=arcee-ai/trinity-large-preview:free
WEB_UI_USERNAME=admin
WEB_UI_PASSWORD=change_this_password
```

5. Start web panel:
```bash
python web/app.py
```

6. Open:
- `http://127.0.0.1:9799`
- If `WEB_UI_PASSWORD` is set, Basic Auth login is required.

7. In web panel:
- set `CHANNEL_IDS`
- set `DEFAULT_SKILL`
- optional: set `CHANNEL_SKILLS` mapping
- click `Save + Restart Bot`

## Config Sources
Configuration is loaded in this order:
1. `web_settings.json` (if key exists and non-empty)
2. `.env`
3. hardcoded default

Main secret keys (keep in `.env`):
- `DISCORD_TOKEN`
- `OPENROUTER_API_KEY`
- `AI_MODELS`
- `WEB_UI_USERNAME`
- `WEB_UI_PASSWORD`

Main operational keys (managed by web UI to `web_settings.json`):
- routing: `CHANNEL_IDS`, `CHANNEL_SKILLS`, `DEFAULT_SKILL`
- reply tuning: `SMALLTALK_REPLY_CHANCE`, `KEYWORD_REPLY_CHANCE`, `RANDOM_REPLY_CHANCE`
- delay windows: `DELAY_*`
- memory: `MEMORY_DB_PATH`, `MEMORY_TTL_SECONDS`, `MAX_RECENT_CONTEXT`, `MAX_EVENTS_PER_USER`
- anti-repeat/cooldown: `ANTI_REPEAT_WINDOW`, `RANDOM_COOLDOWN_SECONDS`, `DIRECT_REPLY_COOLDOWN_SECONDS`

## Runtime Files
- `storage/memories.db`: memory database
- `runtime/bot.log`: bot output log
- `runtime/bot.pid`: PID file used by web panel
- `runtime/bot.instance.lock`: single-instance lock (prevents duplicate bot process)

## Reliability Notes
- Bot has single-instance lock in `bot.py`.
- Web start/stop validates PID process identity before kill.
- Context prompt excludes internal planning events (`bot_plan`).

## VPS 24/7 Checklist
- Use strong `WEB_UI_PASSWORD`.
- Do not expose Web UI directly without firewall/reverse proxy.
- Prefer running Web UI and bot under `systemd`.
- Add log rotation for `runtime/bot.log`.
- Keep `storage/` writable by service user.

## Common Issues
- `ModuleNotFoundError`:
  - activate correct venv
  - reinstall dependencies

- Bot not replying:
  - verify bot is running in web panel
  - verify `CHANNEL_IDS` / `CHANNEL_SKILLS`
  - check `runtime/bot.log`
  - tune reply chance values

- SQLite open/lock errors:
  - ensure `MEMORY_DB_PATH` points to a file path, not directory
  - ensure service user has write permission on DB directory

## Notes
- This repository is designed for controlled/private operation.
- Use responsibly and follow platform rules of your deployment target.
