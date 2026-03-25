# discord-grint

Discord self-bot with:
- agent-style reply pipeline (`classify -> plan -> retrieve memory -> generate -> critique -> send`)
- SQLite memory store
- terminal-style web panel for settings, monitoring, and bot start/stop/restart

## Requirements

- Python 3.12+
- Discord token (self-bot account)
- OpenRouter API key

## Quick Start

1. Clone and enter project:

```bash
git clone https://github.com/moree44/discord-grint.git
cd discord-grint
```

2. Create and activate virtualenv:

```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies:

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

5. Run web panel:

```bash
python web/app.py
```

Open `http://127.0.0.1:9799`.
If `WEB_UI_PASSWORD` is set, browser will prompt Basic Auth login.

6. From web panel:
- set `CHANNEL_IDS`
- set `DEFAULT_SKILL` and channel-skill mapping if needed
- click `Save + Restart Bot`

## Config Model

The project now uses two config sources:

- `.env` (minimal, secrets + model list)
  - `DISCORD_TOKEN`
  - `OPENROUTER_API_KEY`
  - `AI_MODELS`

- `web_settings.json` (operational settings managed by web UI)
  - channel routing (`CHANNEL_IDS`, `CHANNEL_SKILLS`, `DEFAULT_SKILL`)
  - memory and cooldown settings

## Persona and Skills

- Base persona (always applied):
  - `skills/base/general.md`
- Project persona (applied for project/crypto context):
  - `skills/projects/donut_browser.md`

You can add project skills by creating new files in `skills/projects/`.

## Architecture

- `bot.py`: main Discord event loop and orchestration
- `agent/`
  - `classifier.py`: mode detection
  - `planner.py`: reply or ignore decisions
  - `generator.py`: model prompting with persona + memory context
  - `critic.py`: output constraints (length, repetition, project forcing)
- `memory/`
  - `recent_context.py`: short-term in-memory cache
  - `user_profile.py`: lightweight user language/style/topic profile
  - `event_store.py`: memory events with TTL
- `storage/sqlite_store.py`: SQLite adapter
- `web/`: web control panel

## Runtime Files

- `storage/memories.db`: SQLite memory database
- `runtime/bot.pid`: bot process PID (managed by web panel)
- `runtime/bot.log`: bot runtime logs

## Common Issues

- `ModuleNotFoundError: No module named ...`
  - activate correct virtualenv
  - reinstall dependencies in the active env

- Bot not replying
  - ensure bot is running from web panel
  - check `CHANNEL_IDS`
  - check runtime log in web panel
  - raise `SMALLTALK_REPLY_CHANCE` if chat is mostly smalltalk

- `sqlite3.OperationalError: unable to open database file`
  - ensure `MEMORY_DB_PATH` in `web_settings.json` points to a file path, not directory

## Release Notes (latest)

Commit `9c5020e`:
- implemented agent pipeline with memory modules
- added SQLite event/user profile storage
- added layered persona loading (base + project)
- added terminal-style web panel
- added bot process control from web (`start/stop/restart`)
- moved operational settings to `web_settings.json`
