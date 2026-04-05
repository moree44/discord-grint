from __future__ import annotations

import json
import hmac
import os
import secrets
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
SETTINGS_PATH = ROOT / "web_settings.json"
RUNTIME_DIR = ROOT / "runtime"
PID_PATH = RUNTIME_DIR / "bot.pid"
BOT_LOG_PATH = RUNTIME_DIR / "bot.log"
load_dotenv(ENV_PATH)
WEB_UI_USERNAME = (os.getenv("WEB_UI_USERNAME") or "admin").strip() or "admin"
WEB_UI_PASSWORD = (os.getenv("WEB_UI_PASSWORD") or "").strip()
WEB_UI_SECRET_KEY = (os.getenv("WEB_UI_SECRET_KEY") or "").strip()

ENV_EDITABLE_KEYS = [
    "AI_MODELS",
]

WEB_EDITABLE_KEYS = [
    "CHANNEL_SKILLS",
    "CHANNEL_PROFILES",
    "CHANNEL_CUSTOM_DELAYS",
    "CHANNEL_IDS",
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
    "CHANNEL_SKILLS": "",
    "CHANNEL_PROFILES": "",
    "CHANNEL_CUSTOM_DELAYS": "",
    "CHANNEL_IDS": "",
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
PROFILE_OPTIONS = ["normal", "slow_60s", "quiet"]

INT_SETTING_KEYS = {
    "MEMORY_TTL_SECONDS",
    "MAX_RECENT_CONTEXT",
    "MAX_EVENTS_PER_USER",
    "ANTI_REPEAT_WINDOW",
    "RANDOM_COOLDOWN_SECONDS",
    "DIRECT_REPLY_COOLDOWN_SECONDS",
    "DELAY_DIRECT_MIN",
    "DELAY_DIRECT_MAX",
    "DELAY_KEYWORD_MIN",
    "DELAY_KEYWORD_MAX",
    "DELAY_RANDOM_MIN",
    "DELAY_RANDOM_MAX",
}

FLOAT_SETTING_KEYS = {
    "SMALLTALK_REPLY_CHANCE",
    "KEYWORD_REPLY_CHANCE",
    "RANDOM_REPLY_CHANCE",
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


def _parse_channel_profiles_map(raw: str | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not raw:
        return mapping
    for part in raw.split(","):
        token = part.strip()
        if not token or ":" not in token:
            continue
        channel_id, profile = token.split(":", 1)
        channel_id = channel_id.strip()
        profile = profile.strip()
        if not channel_id or not profile:
            continue
        mapping[channel_id] = profile
    return mapping


def _parse_channel_custom_delays_map(raw: str | None) -> dict[str, dict[str, int]]:
    mapping: dict[str, dict[str, int]] = {}
    if not raw:
        return mapping
    for part in str(raw).split(","):
        token = part.strip()
        if not token or ":" not in token:
            continue
        channel_id, ranges_part = token.split(":", 1)
        channel_id = channel_id.strip()
        segments = [seg.strip() for seg in ranges_part.split("|")]
        if not channel_id or len(segments) != 3:
            continue
        try:
            direct_min, direct_max = [int(x.strip()) for x in segments[0].split("-", 1)]
            keyword_min, keyword_max = [int(x.strip()) for x in segments[1].split("-", 1)]
            random_min, random_max = [int(x.strip()) for x in segments[2].split("-", 1)]
        except (TypeError, ValueError):
            continue
        mapping[channel_id] = {
            "direct_min": direct_min,
            "direct_max": direct_max,
            "keyword_min": keyword_min,
            "keyword_max": keyword_max,
            "random_min": random_min,
            "random_max": random_max,
        }
    return mapping


def _format_channel_custom_delays_map(items: list[dict[str, str]]) -> str:
    chunks: list[str] = []
    for item in items:
        channel_id = str(item.get("channel_id", "")).strip()
        if not channel_id:
            continue
        custom_enabled = str(item.get("custom_enabled", "")).strip().lower() in {"1", "true", "yes", "on"}
        if not custom_enabled:
            continue
        try:
            direct_min = int(str(item.get("direct_min", "")).strip())
            direct_max = int(str(item.get("direct_max", "")).strip())
            keyword_min = int(str(item.get("keyword_min", "")).strip())
            keyword_max = int(str(item.get("keyword_max", "")).strip())
            random_min = int(str(item.get("random_min", "")).strip())
            random_max = int(str(item.get("random_max", "")).strip())
        except (TypeError, ValueError):
            continue
        if not (direct_min <= direct_max and keyword_min <= keyword_max and random_min <= random_max):
            continue
        chunks.append(
            f"{channel_id}:{direct_min}-{direct_max}|{keyword_min}-{keyword_max}|{random_min}-{random_max}"
        )
    return ",".join(chunks)


def _format_channel_profiles_map(items: list[dict[str, str]]) -> str:
    chunks: list[str] = []
    for item in items:
        channel_id = str(item.get("channel_id", "")).strip()
        profile = str(item.get("profile", "")).strip()
        if not channel_id or not profile:
            continue
        chunks.append(f"{channel_id}:{profile}")
    return ",".join(chunks)


def _parse_channel_ids_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for part in str(raw).split(","):
        token = part.strip()
        if token:
            out.append(token)
    return out


def _build_channel_route_rows(values: dict[str, str]) -> list[dict[str, str]]:
    channel_ids = set(_parse_channel_ids_list(values.get("CHANNEL_IDS")))
    skill_rows = _parse_channel_skills_map(values.get("CHANNEL_SKILLS"))
    profile_map = _parse_channel_profiles_map(values.get("CHANNEL_PROFILES"))
    custom_delay_map = _parse_channel_custom_delays_map(values.get("CHANNEL_CUSTOM_DELAYS"))

    channel_ids.update(item["channel_id"] for item in skill_rows if item.get("channel_id"))
    channel_ids.update(profile_map.keys())
    channel_ids.update(custom_delay_map.keys())

    skill_by_channel = {item["channel_id"]: item["skill"] for item in skill_rows}
    default_skill = str(values.get("DEFAULT_SKILL") or DEFAULT_WEB_SETTINGS["DEFAULT_SKILL"]).strip()

    rows: list[dict[str, str]] = []
    for channel_id in sorted(channel_ids, key=lambda x: int(x) if x.isdigit() else x):
        custom_delay = custom_delay_map.get(channel_id) or {}
        rows.append(
            {
                "channel_id": channel_id,
                "skill": skill_by_channel.get(channel_id, default_skill),
                "profile": profile_map.get(channel_id, "normal"),
                "custom_enabled": "1" if custom_delay else "",
                "direct_min": str(custom_delay.get("direct_min", "")),
                "direct_max": str(custom_delay.get("direct_max", "")),
                "keyword_min": str(custom_delay.get("keyword_min", "")),
                "keyword_max": str(custom_delay.get("keyword_max", "")),
                "random_min": str(custom_delay.get("random_min", "")),
                "random_max": str(custom_delay.get("random_max", "")),
            }
        )
    return rows


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


def _validate_channel_ids(raw: str) -> None:
    text = str(raw).strip()
    if not text:
        return
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        if not item.isdigit():
            raise ValueError("CHANNEL_IDS must be comma-separated numeric IDs")


def _validate_channel_skills(raw: str) -> None:
    text = str(raw).strip()
    if not text:
        return
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError("CHANNEL_SKILLS must use channel_id:skill format")
        channel_id, skill = item.split(":", 1)
        if not channel_id.strip().isdigit():
            raise ValueError("CHANNEL_SKILLS channel id must be numeric")
        if not skill.strip():
            raise ValueError("CHANNEL_SKILLS skill cannot be empty")


def _validate_channel_profiles(raw: str) -> None:
    text = str(raw).strip()
    if not text:
        return
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError("CHANNEL_PROFILES must use channel_id:profile format")
        channel_id, profile = item.split(":", 1)
        channel_id = channel_id.strip()
        profile = profile.strip()
        if not channel_id.isdigit():
            raise ValueError("CHANNEL_PROFILES channel id must be numeric")
        if profile not in PROFILE_OPTIONS:
            raise ValueError(f"CHANNEL_PROFILES profile must be one of: {', '.join(PROFILE_OPTIONS)}")


def _validate_channel_custom_delays(raw: str) -> None:
    text = str(raw).strip()
    if not text:
        return
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError("CHANNEL_CUSTOM_DELAYS must use channel_id:ranges format")
        channel_id, ranges_part = item.split(":", 1)
        channel_id = channel_id.strip()
        if not channel_id.isdigit():
            raise ValueError("CHANNEL_CUSTOM_DELAYS channel id must be numeric")
        segments = [seg.strip() for seg in ranges_part.split("|")]
        if len(segments) != 3:
            raise ValueError("CHANNEL_CUSTOM_DELAYS requires 3 ranges: direct|keyword|random")
        for segment in segments:
            if "-" not in segment:
                raise ValueError("CHANNEL_CUSTOM_DELAYS range must use min-max")
            min_part, max_part = segment.split("-", 1)
            low = int(min_part.strip())
            high = int(max_part.strip())
            if low > high:
                raise ValueError("CHANNEL_CUSTOM_DELAYS min must be <= max")


def _validate_web_updates(web_updates: dict) -> None:
    int_values: dict[str, int] = {}

    for key in INT_SETTING_KEYS:
        if key not in web_updates:
            continue
        raw = str(web_updates[key]).strip()
        if raw == "":
            raise ValueError(f"{key} cannot be empty")
        int_values[key] = int(raw)

    for key in FLOAT_SETTING_KEYS:
        if key not in web_updates:
            continue
        raw = str(web_updates[key]).strip()
        if raw == "":
            raise ValueError(f"{key} cannot be empty")
        value = float(raw)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{key} must be between 0 and 1")

    if "CHANNEL_IDS" in web_updates:
        _validate_channel_ids(str(web_updates["CHANNEL_IDS"]))
    if "CHANNEL_SKILLS" in web_updates:
        _validate_channel_skills(str(web_updates["CHANNEL_SKILLS"]))
    if "CHANNEL_PROFILES" in web_updates:
        _validate_channel_profiles(str(web_updates["CHANNEL_PROFILES"]))
    if "CHANNEL_CUSTOM_DELAYS" in web_updates:
        _validate_channel_custom_delays(str(web_updates["CHANNEL_CUSTOM_DELAYS"]))
    if "DEFAULT_SKILL" in web_updates and not str(web_updates["DEFAULT_SKILL"]).strip():
        raise ValueError("DEFAULT_SKILL cannot be empty")

    min_max_pairs = (
        ("DELAY_DIRECT_MIN", "DELAY_DIRECT_MAX"),
        ("DELAY_KEYWORD_MIN", "DELAY_KEYWORD_MAX"),
        ("DELAY_RANDOM_MIN", "DELAY_RANDOM_MAX"),
    )
    for min_key, max_key in min_max_pairs:
        min_val = int_values.get(min_key)
        max_val = int_values.get(max_key)
        if min_val is None or max_val is None:
            continue
        if min_val > max_val:
            raise ValueError(f"{min_key} must be <= {max_key}")


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
            "channel_breakdown": [],
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
            "channel_breakdown": [],
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
            channel_rows = conn.execute(
                """
                SELECT
                    guild_id,
                    channel_id,
                    COUNT(*) AS total_events,
                    SUM(CASE WHEN event_type = 'bot_reply' THEN 1 ELSE 0 END) AS bot_replies_total,
                    SUM(
                        CASE
                            WHEN event_type = 'bot_reply' AND created_at >= ? THEN 1
                            ELSE 0
                        END
                    ) AS bot_replies_24h,
                    MAX(created_at) AS last_event_ts
                FROM events
                GROUP BY guild_id, channel_id
                ORDER BY last_event_ts DESC
                LIMIT 120
                """,
                (day_ago,),
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
            channel_breakdown = [
                {
                    "guild_id": int(row["guild_id"]) if row["guild_id"] is not None else None,
                    "channel_id": int(row["channel_id"]),
                    "total_events": int(row["total_events"] or 0),
                    "bot_replies_total": int(row["bot_replies_total"] or 0),
                    "bot_replies_24h": int(row["bot_replies_24h"] or 0),
                    "last_event_ts": int(row["last_event_ts"]) if row["last_event_ts"] else None,
                }
                for row in channel_rows
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
                "channel_breakdown": channel_breakdown,
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
            "channel_breakdown": [],
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
    if "bot.py" not in cmd:
        return False

    root_text = str(ROOT).lower()
    if root_text in cmd:
        return True

    proc_cwd = Path(f"/proc/{pid}/cwd")
    try:
        cwd_text = str(proc_cwd.resolve()).lower()
    except OSError:
        return False
    return cwd_text == root_text


def _find_running_bot_pid() -> int | None:
    proc_root = Path("/proc")
    if not proc_root.exists():
        return None
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if _is_pid_running(pid) and _is_pid_our_bot_process(pid):
            return pid
    return None


def _bot_status() -> dict:
    pid = _read_pid()
    running = bool(pid and _is_pid_running(pid) and _is_pid_our_bot_process(pid))
    if not running:
        fallback_pid = _find_running_bot_pid()
        if fallback_pid:
            pid = fallback_pid
            running = True
            PID_PATH.write_text(str(pid), encoding="utf-8")
        elif pid and PID_PATH.exists():
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
if WEB_UI_SECRET_KEY:
    app.secret_key = WEB_UI_SECRET_KEY
else:
    # Avoid predictable fallback keys when password auth is enabled.
    app.secret_key = secrets.token_urlsafe(48)
    if WEB_UI_PASSWORD:
        print("⚠️  WEB_UI_SECRET_KEY is not set; using ephemeral random secret for this process.")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


def _web_auth_enabled() -> bool:
    return bool(WEB_UI_PASSWORD)


def _is_session_authorized() -> bool:
    return bool(session.get("web_auth_ok"))


@app.before_request
def require_web_auth():
    if not _web_auth_enabled():
        return None
    if request.path.startswith("/static/"):
        return None
    if request.endpoint in {"login", "login_submit", "logout"}:
        return None
    if _is_session_authorized():
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return redirect(url_for("login"))


@app.get("/login")
def login():
    if not _web_auth_enabled():
        return redirect(url_for("index"))
    if _is_session_authorized():
        return redirect(url_for("index"))
    return render_template("login.html", username=WEB_UI_USERNAME, error=None)


@app.post("/login")
def login_submit():
    if not _web_auth_enabled():
        return redirect(url_for("index"))

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if hmac.compare_digest(username, WEB_UI_USERNAME) and hmac.compare_digest(
        password, WEB_UI_PASSWORD
    ):
        session["web_auth_ok"] = True
        return redirect(url_for("index"))
    return render_template(
        "login.html",
        username=WEB_UI_USERNAME,
        error="Username atau password salah.",
    )


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def index():
    return redirect(url_for("settings_page"))


@app.get("/settings")
def settings_page():
    values = _merged_ui_settings()
    return render_template(
        "panel.html",
        settings=values,
        skill_options=_discover_project_skills(),
        channel_route_rows=_build_channel_route_rows(values),
        profile_options=PROFILE_OPTIONS,
        base_persona="skills/base/general.md (wayss persona)",
        initial_view="settings",
    )


@app.get("/monitoring")
def monitoring_page():
    values = _merged_ui_settings()
    return render_template(
        "panel.html",
        settings=values,
        skill_options=_discover_project_skills(),
        channel_route_rows=_build_channel_route_rows(values),
        profile_options=PROFILE_OPTIONS,
        base_persona="skills/base/general.md (wayss persona)",
        initial_view="monitoring",
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
            "channel_route_rows": _build_channel_route_rows(values),
            "profile_options": PROFILE_OPTIONS,
        }
    )


@app.post("/api/settings")
def api_settings():
    payload = request.get_json(silent=True) or {}
    env_updates: dict[str, str] = {}
    web_updates: dict = {}

    if "CHANNEL_SKILL_ROWS" in payload and isinstance(payload["CHANNEL_SKILL_ROWS"], list):
        web_updates["CHANNEL_SKILLS"] = _format_channel_skills_map(payload["CHANNEL_SKILL_ROWS"])
    if "CHANNEL_ROUTE_ROWS" in payload and isinstance(payload["CHANNEL_ROUTE_ROWS"], list):
        route_rows = payload["CHANNEL_ROUTE_ROWS"]
        channel_ids = [
            str(item.get("channel_id", "")).strip()
            for item in route_rows
            if str(item.get("channel_id", "")).strip()
        ]
        web_updates["CHANNEL_IDS"] = ",".join(list(dict.fromkeys(channel_ids)))
        web_updates["CHANNEL_SKILLS"] = _format_channel_skills_map(route_rows)
        web_updates["CHANNEL_PROFILES"] = _format_channel_profiles_map(route_rows)
        web_updates["CHANNEL_CUSTOM_DELAYS"] = _format_channel_custom_delays_map(route_rows)

    for key in ENV_EDITABLE_KEYS:
        if key in payload:
            env_updates[key] = str(payload[key]).strip()
    for key in WEB_EDITABLE_KEYS:
        if key in payload:
            web_updates[key] = payload[key]

    try:
        _validate_web_updates(web_updates)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

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
