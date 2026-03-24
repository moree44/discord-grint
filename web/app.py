from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
SETTINGS_PATH = ROOT / "web_settings.json"
RUNTIME_DIR = ROOT / "runtime"
PID_PATH = RUNTIME_DIR / "bot.pid"
BOT_LOG_PATH = RUNTIME_DIR / "bot.log"

ENV_EDITABLE_KEYS = [
    "AI_MODELS",
]

WEB_EDITABLE_KEYS = [
    "CHANNEL_IDS",
    "CHANNEL_SKILLS",
    "DEFAULT_SKILL",
    "MEMORY_DB_PATH",
    "MEMORY_TTL_SECONDS",
    "MAX_RECENT_CONTEXT",
    "MAX_EVENTS_PER_USER",
    "ANTI_REPEAT_WINDOW",
    "RANDOM_COOLDOWN_SECONDS",
    "DIRECT_REPLY_COOLDOWN_SECONDS",
    "SMALLTALK_REPLY_CHANCE",
    "KEYWORD_REPLY_CHANCE",
    "RANDOM_REPLY_CHANCE",
    "DELAY_DIRECT_MIN",
    "DELAY_DIRECT_MAX",
    "DELAY_KEYWORD_MIN",
    "DELAY_KEYWORD_MAX",
    "DELAY_RANDOM_MIN",
    "DELAY_RANDOM_MAX",
]

DEFAULT_WEB_SETTINGS = {
    "CHANNEL_IDS": "",
    "CHANNEL_SKILLS": "",
    "DEFAULT_SKILL": "donut_browser",
    "MEMORY_DB_PATH": "storage/memories.db",
    "MEMORY_TTL_SECONDS": 21600,
    "MAX_RECENT_CONTEXT": 40,
    "MAX_EVENTS_PER_USER": 120,
    "ANTI_REPEAT_WINDOW": 8,
    "RANDOM_COOLDOWN_SECONDS": 45,
    "DIRECT_REPLY_COOLDOWN_SECONDS": 12,
    "SMALLTALK_REPLY_CHANCE": 0.35,
    "KEYWORD_REPLY_CHANCE": 0.50,
    "RANDOM_REPLY_CHANCE": 0.20,
    "DELAY_DIRECT_MIN": 16,
    "DELAY_DIRECT_MAX": 30,
    "DELAY_KEYWORD_MIN": 30,
    "DELAY_KEYWORD_MAX": 90,
    "DELAY_RANDOM_MIN": 45,
    "DELAY_RANDOM_MAX": 120,
}


def _parse_channel_skills_map(raw: str | None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not raw:
        return items
    for part in raw.split(","):
        token = part.strip()
        if not token or ":" not in token:
            continue
        channel_id, skill = token.split(":", 1)
        channel_id = channel_id.strip()
        skill = skill.strip()
        if not channel_id or not skill:
            continue
        items.append({"channel_id": channel_id, "skill": skill})
    return items


def _format_channel_skills_map(items: list[dict[str, str]]) -> str:
    chunks: list[str] = []
    for item in items:
        channel_id = str(item.get("channel_id", "")).strip()
        skill = str(item.get("skill", "")).strip()
        if not channel_id or not skill:
            continue
        chunks.append(f"{channel_id}:{skill}")
    return ",".join(chunks)


def _ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _load_env_map() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _save_env_keys(updates: dict[str, str]) -> None:
    lines = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    seen: set[str] = set()
    new_lines: list[str] = []

    for raw in lines:
        if "=" not in raw or raw.lstrip().startswith("#"):
            new_lines.append(raw)
            continue
        key, _ = raw.split("=", 1)
        key = key.strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(raw)

    for key in updates:
        if key not in seen:
            new_lines.append(f"{key}={updates[key]}")

    ENV_PATH.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def _load_web_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_WEB_SETTINGS)
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return dict(DEFAULT_WEB_SETTINGS)
    except Exception:
        return dict(DEFAULT_WEB_SETTINGS)
    merged = dict(DEFAULT_WEB_SETTINGS)
    merged.update(raw)
    return merged


def _save_web_settings(updates: dict) -> None:
    data = _load_web_settings()
    data.update(updates)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _merged_ui_settings() -> dict[str, str]:
    env_values = _load_env_map()
    web_values = _load_web_settings()
    merged = {}
    for key in ENV_EDITABLE_KEYS:
        merged[key] = env_values.get(key, "")
    for key in WEB_EDITABLE_KEYS:
        merged[key] = str(web_values.get(key, DEFAULT_WEB_SETTINGS.get(key, "")))
    return merged


def _resolve_db_path(values: dict[str, str]) -> Path:
    db_raw = (values.get("MEMORY_DB_PATH") or "").strip() or "storage/memories.db"
    db_path = Path(db_raw)
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    return db_path


def _query_stats(db_path: Path) -> dict:
    if db_path.exists() and db_path.is_dir():
        return {
            "db_exists": False,
            "db_path": str(db_path),
            "error": "MEMORY_DB_PATH points to a directory, not a sqlite file",
            "total_events": 0,
            "total_users": 0,
            "bot_replies_24h": 0,
            "last_event_ts": None,
            "last_event_age_sec": None,
            "recent_events": [],
        }
    if not db_path.exists():
        return {
            "db_exists": False,
            "db_path": str(db_path),
            "total_events": 0,
            "total_users": 0,
            "bot_replies_24h": 0,
            "last_event_ts": None,
            "last_event_age_sec": None,
            "recent_events": [],
        }
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            now = int(time.time())
            day_ago = now - 86400
            total_events = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
            total_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS n FROM events WHERE user_id IS NOT NULL"
            ).fetchone()["n"]
            bot_replies_24h = conn.execute(
                """
                SELECT COUNT(*) AS n FROM events
                WHERE event_type = 'bot_reply' AND created_at >= ?
                """,
                (day_ago,),
            ).fetchone()["n"]
            last_row = conn.execute(
                "SELECT created_at FROM events ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            recent_rows = conn.execute(
                """
                SELECT created_at, event_type, author_name, content
                FROM events
                ORDER BY created_at DESC
                LIMIT 40
                """
            ).fetchall()
            recent_events = [
                {
                    "created_at": int(row["created_at"]),
                    "event_type": row["event_type"],
                    "author_name": row["author_name"] or "unknown",
                    "content": row["content"],
                }
                for row in recent_rows
            ]
            last_event_ts = int(last_row["created_at"]) if last_row else None
            return {
                "db_exists": True,
                "db_path": str(db_path),
                "total_events": int(total_events),
                "total_users": int(total_users),
                "bot_replies_24h": int(bot_replies_24h),
                "last_event_ts": last_event_ts,
                "last_event_age_sec": (now - last_event_ts) if last_event_ts else None,
                "recent_events": recent_events,
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {
            "db_exists": False,
            "db_path": str(db_path),
            "error": f"sqlite_error: {exc}",
            "total_events": 0,
            "total_users": 0,
            "bot_replies_24h": 0,
            "last_event_ts": None,
            "last_event_age_sec": None,
            "recent_events": [],
        }


def _discover_project_skills() -> list[str]:
    names: set[str] = set()
    projects_dir = ROOT / "skills" / "projects"
    if projects_dir.exists():
        for path in projects_dir.rglob("*.md"):
            if path.name.lower() == "skill.md":
                names.add(path.parent.name)
            else:
                names.add(path.stem)
    legacy_dir = ROOT / "skills"
    if legacy_dir.exists():
        for path in legacy_dir.glob("*.md"):
            if path.name.lower() == "skill.md":
                continue
            if path.parent.name == "skills":
                names.add(path.stem)
    return sorted(names)


def _tail_log(path: Path, max_lines: int = 120) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return lines[-max_lines:]


def _read_pid() -> int | None:
    if not PID_PATH.exists():
        return None
    try:
        return int(PID_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _is_pid_our_bot_process(pid: int) -> bool:
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if not proc_cmdline.exists():
        return False
    try:
        raw = proc_cmdline.read_bytes().decode("utf-8", errors="ignore")
    except OSError:
        return False
    cmd = raw.replace("\x00", " ").strip().lower()
    return "bot.py" in cmd and str(ROOT).lower() in cmd


def _bot_status() -> dict:
    pid = _read_pid()
    running = bool(pid and _is_pid_running(pid) and _is_pid_our_bot_process(pid))
    if pid and not running and PID_PATH.exists():
        PID_PATH.unlink(missing_ok=True)
    return {
        "running": running,
        "pid": pid if running else None,
        "log_path": str(BOT_LOG_PATH),
    }


def _start_bot() -> dict:
    _ensure_runtime_dir()
    status = _bot_status()
    if status["running"]:
        return {"ok": True, "message": "bot already running", **status}

    log_file = open(BOT_LOG_PATH, "a", encoding="utf-8")
    log_file.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] web start bot\n")
    log_file.flush()

    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, str(ROOT / "bot.py")],
        cwd=str(ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    return {"ok": True, "message": "bot started", **_bot_status()}


def _stop_bot() -> dict:
    status = _bot_status()
    if not status["running"]:
        return {"ok": True, "message": "bot already stopped", **status}

    pid = int(status["pid"])
    if not _is_pid_our_bot_process(pid):
        PID_PATH.unlink(missing_ok=True)
        return {
            "ok": False,
            "message": "pid file pointed to non-bot process; refused to kill",
            **_bot_status(),
        }
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        PID_PATH.unlink(missing_ok=True)
        return {"ok": False, "message": f"failed to stop: {exc}", **_bot_status()}

    deadline = time.time() + 5
    while time.time() < deadline:
        if not _is_pid_running(pid):
            PID_PATH.unlink(missing_ok=True)
            return {"ok": True, "message": "bot stopped", **_bot_status()}
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    PID_PATH.unlink(missing_ok=True)
    return {"ok": True, "message": "bot force-stopped", **_bot_status()}


app = Flask(__name__, template_folder="templates", static_folder="static")


@app.get("/")
def index():
    values = _merged_ui_settings()
    return render_template(
        "index.html",
        settings=values,
        skill_options=_discover_project_skills(),
        channel_skill_rows=_parse_channel_skills_map(values.get("CHANNEL_SKILLS")),
        base_persona="skills/base/general.md (wayss persona)",
    )


@app.get("/api/status")
def api_status():
    values = _merged_ui_settings()
    db_path = _resolve_db_path(values)
    stats = _query_stats(db_path)
    return jsonify(
        {
            **stats,
            "bot": _bot_status(),
            "log_tail": _tail_log(BOT_LOG_PATH, max_lines=120),
            "skill_options": _discover_project_skills(),
            "channel_skill_rows": _parse_channel_skills_map(values.get("CHANNEL_SKILLS")),
        }
    )


@app.post("/api/settings")
def api_settings():
    payload = request.get_json(silent=True) or {}
    env_updates: dict[str, str] = {}
    web_updates: dict = {}

    if "CHANNEL_SKILL_ROWS" in payload and isinstance(payload["CHANNEL_SKILL_ROWS"], list):
        web_updates["CHANNEL_SKILLS"] = _format_channel_skills_map(payload["CHANNEL_SKILL_ROWS"])

    for key in ENV_EDITABLE_KEYS:
        if key in payload:
            env_updates[key] = str(payload[key]).strip()
    for key in WEB_EDITABLE_KEYS:
        if key in payload:
            web_updates[key] = payload[key]

    if env_updates:
        _save_env_keys(env_updates)
    if web_updates:
        _save_web_settings(web_updates)

    return jsonify({"ok": True, "updated_keys": sorted([*env_updates.keys(), *web_updates.keys()])})


@app.post("/api/bot/start")
def api_bot_start():
    return jsonify(_start_bot())


@app.post("/api/bot/stop")
def api_bot_stop():
    return jsonify(_stop_bot())


@app.post("/api/bot/restart")
def api_bot_restart():
    _stop_bot()
    return jsonify(_start_bot())


if __name__ == "__main__":
    _ensure_runtime_dir()
    port = int(os.getenv("WEB_UI_PORT", "9799"))
    app.run(host="0.0.0.0", port=port, debug=False)
