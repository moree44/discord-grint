"""Centralized app settings for discord-grind-bot."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent
WEB_SETTINGS_PATH = Path(os.getenv("WEB_SETTINGS_PATH", str(ROOT_DIR / "web_settings.json")))
if not WEB_SETTINGS_PATH.is_absolute():
    WEB_SETTINGS_PATH = (ROOT_DIR / WEB_SETTINGS_PATH).resolve()


def _load_web_settings() -> dict:
    if not WEB_SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(WEB_SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


WEB_SETTINGS = _load_web_settings()


def _get_setting(name: str, default):
    value = WEB_SETTINGS.get(name)
    if value is not None and str(value).strip() != "":
        return value
    env_value = os.getenv(name)
    if env_value is not None and env_value.strip() != "":
        return env_value
    return default


def _parse_channel_ids(raw_value) -> list[int]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        values: list[int] = []
        for item in raw_value:
            if isinstance(item, int):
                values.append(item)
            elif isinstance(item, str) and item.strip().isdigit():
                values.append(int(item.strip()))
            else:
                raise ValueError("CHANNEL_IDS list must contain numeric IDs")
        return values

    raw_text = str(raw_value)
    if not raw_text.strip():
        return []
    channel_ids = []
    for part in raw_text.split(","):
        value = part.strip()
        if not value:
            continue
        if not value.isdigit():
            raise ValueError(
                "CHANNEL_IDS must be comma-separated numeric IDs, e.g. 123456789,987654321"
            )
        channel_ids.append(int(value))
    return channel_ids


def _parse_channel_skills(raw_value) -> dict[int, str]:
    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        parsed: dict[int, str] = {}
        for key, value in raw_value.items():
            key_text = str(key).strip()
            skill = str(value).strip()
            if not key_text.isdigit() or not skill:
                continue
            parsed[int(key_text)] = skill
        return parsed

    raw_text = str(raw_value)
    if not raw_text.strip():
        return {}

    mapping: dict[int, str] = {}
    for part in raw_text.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(
                "CHANNEL_SKILLS must be comma-separated channel_id:project pairs"
            )
        channel_part, skill_part = item.split(":", 1)
        channel_text = channel_part.strip()
        skill = skill_part.strip()
        if not channel_text.isdigit():
            raise ValueError(
                "CHANNEL_SKILLS channel id must be numeric, e.g. 123456789012345678:donut_browser"
            )
        if not skill:
            raise ValueError(
                "CHANNEL_SKILLS project key cannot be empty, e.g. 123456789012345678:donut_browser"
            )
        mapping[int(channel_text)] = skill
    return mapping


def _int_setting(name: str, default: int) -> int:
    raw = _get_setting(name, default)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _float_setting(name: str, default: float) -> float:
    raw = _get_setting(name, default)
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a float") from exc


def _parse_csv_list(raw_value) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return [str(part).strip() for part in raw_value if str(part).strip()]
    raw_text = str(raw_value)
    if not raw_text.strip():
        return []
    return [part.strip() for part in raw_text.split(",") if part.strip()]


@dataclass(frozen=True)
class Credentials:
    discord_token: str | None
    openrouter_key: str | None


@dataclass(frozen=True)
class ReplyProfile:
    chance: dict[str, float]
    delays: dict[str, tuple[int, int]]


@dataclass(frozen=True)
class AISettings:
    models: list[str]
    max_tokens_conversation: int
    max_tokens_chime_in: int
    temperature: float
    history_limit: int
    keywords: list[str]


@dataclass(frozen=True)
class FilterSettings:
    min_message_length: int
    skip_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class MemorySettings:
    db_path: str
    event_ttl_seconds: int
    max_recent_context: int
    max_events_per_user: int
    anti_repeat_window: int


@dataclass(frozen=True)
class AgentSettings:
    random_cooldown_seconds: int
    direct_reply_cooldown_seconds: int
    smalltalk_reply_chance: float


@dataclass(frozen=True)
class ChannelOverride:
    skill: str | None = None
    profile: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class ServerConfig:
    default_skill: str | None = None
    default_profile: str | None = None
    channels: dict[int, ChannelOverride] | None = None


@dataclass(frozen=True)
class RoutingSettings:
    channel_ids: list[int]
    channel_skills: dict[int, str]
    default_skill: str
    default_profile: str
    profiles: dict[str, ReplyProfile]
    servers: dict[int, ServerConfig]

    @property
    def watched_channel_ids(self) -> set[int]:
        watched = set(self.channel_ids)
        watched.update(self.channel_skills.keys())
        for server_cfg in self.servers.values():
            if not server_cfg.channels:
                continue
            watched.update(server_cfg.channels.keys())
        return watched


@dataclass(frozen=True)
class ResolvedChannelConfig:
    enabled: bool
    skill: str
    profile_name: str
    profile: ReplyProfile


@dataclass(frozen=True)
class AppSettings:
    credentials: Credentials
    routing: RoutingSettings
    ai: AISettings
    filters: FilterSettings
    memory: MemorySettings
    agent: AgentSettings


def resolve_channel_config(
    settings: AppSettings, guild_id: int | None, channel_id: int
) -> ResolvedChannelConfig:
    skill = settings.routing.default_skill
    profile_name = settings.routing.default_profile
    enabled = (
        channel_id in settings.routing.channel_ids
        or channel_id in settings.routing.channel_skills
    )

    global_channel_skill = settings.routing.channel_skills.get(channel_id)
    if global_channel_skill:
        skill = global_channel_skill

    server_cfg = settings.routing.servers.get(guild_id) if guild_id is not None else None
    if server_cfg:
        if server_cfg.default_skill:
            skill = server_cfg.default_skill
        if server_cfg.default_profile:
            profile_name = server_cfg.default_profile

        channel_override = (server_cfg.channels or {}).get(channel_id)
        if channel_override:
            enabled = channel_override.enabled
            if channel_override.skill:
                skill = channel_override.skill
            if channel_override.profile:
                profile_name = channel_override.profile

    profile = settings.routing.profiles.get(profile_name)
    if profile is None:
        raise ValueError(f"Unknown profile '{profile_name}' in channel routing config")

    return ResolvedChannelConfig(
        enabled=enabled,
        skill=skill,
        profile_name=profile_name,
        profile=profile,
    )


def load_settings() -> AppSettings:
    credentials = Credentials(
        discord_token=os.getenv("DISCORD_TOKEN"),
        openrouter_key=os.getenv("OPENROUTER_API_KEY"),
    )

    channel_ids = _parse_channel_ids(_get_setting("CHANNEL_IDS", ""))
    channel_skills = _parse_channel_skills(_get_setting("CHANNEL_SKILLS", ""))
    default_skill = str(_get_setting("DEFAULT_SKILL", "donut_browser"))

    profiles = {
        "normal": ReplyProfile(
            chance={
                "keyword_hit": _float_setting("KEYWORD_REPLY_CHANCE", 0.50),
                "random": _float_setting("RANDOM_REPLY_CHANCE", 0.20),
            },
            delays={
                "replied_to_us": (
                    _int_setting("DELAY_DIRECT_MIN", 16),
                    _int_setting("DELAY_DIRECT_MAX", 30),
                ),
                "mentioned": (
                    _int_setting("DELAY_DIRECT_MIN", 16),
                    _int_setting("DELAY_DIRECT_MAX", 30),
                ),
                "keyword_hit": (
                    _int_setting("DELAY_KEYWORD_MIN", 30),
                    _int_setting("DELAY_KEYWORD_MAX", 90),
                ),
                "random": (
                    _int_setting("DELAY_RANDOM_MIN", 45),
                    _int_setting("DELAY_RANDOM_MAX", 120),
                ),
            },
        ),
        "slow_60s": ReplyProfile(
            chance={
                "keyword_hit": 0.35,
                "random": 0.08,
            },
            delays={
                "replied_to_us": (65, 95),
                "mentioned": (65, 90),
                "keyword_hit": (90, 180),
                "random": (150, 300),
            },
        ),
        "quiet": ReplyProfile(
            chance={
                "keyword_hit": 0.15,
                "random": 0.03,
            },
            delays={
                "replied_to_us": (25, 45),
                "mentioned": (25, 40),
                "keyword_hit": (90, 180),
                "random": (180, 360),
            },
        ),
    }

    servers: dict[int, ServerConfig] = {}

    routing = RoutingSettings(
        channel_ids=channel_ids,
        channel_skills=channel_skills,
        default_skill=default_skill,
        default_profile="normal",
        profiles=profiles,
        servers=servers,
    )

    ai_models = _parse_csv_list(os.getenv("AI_MODELS")) or [
        "arcee-ai/trinity-large-preview:free",
    ]

    ai = AISettings(
        models=ai_models,
        max_tokens_conversation=55,
        max_tokens_chime_in=40,
        temperature=0.72,
        history_limit=15,
        keywords=[
            "donut",
            "agent",
            "token",
            "airdrop",
            "wen",
            "wallet",
            "browser",
            "launch",
            "testnet",
            "og glazer",
            "wagmi",
            "ngmi",
            "raise",
            "funding",
            "whitelist",
        ],
    )

    filters = FilterSettings(
        min_message_length=8,
        skip_prefixes=("http", "!", "/", ".", "$", "@"),
    )

    memory = MemorySettings(
        db_path=str(_get_setting("MEMORY_DB_PATH", "storage/memories.db")),
        event_ttl_seconds=_int_setting("MEMORY_TTL_SECONDS", 21600),
        max_recent_context=_int_setting("MAX_RECENT_CONTEXT", 40),
        max_events_per_user=_int_setting("MAX_EVENTS_PER_USER", 120),
        anti_repeat_window=_int_setting("ANTI_REPEAT_WINDOW", 8),
    )

    agent = AgentSettings(
        random_cooldown_seconds=_int_setting("RANDOM_COOLDOWN_SECONDS", 45),
        direct_reply_cooldown_seconds=_int_setting("DIRECT_REPLY_COOLDOWN_SECONDS", 12),
        smalltalk_reply_chance=_float_setting("SMALLTALK_REPLY_CHANCE", 0.35),
    )

    return AppSettings(
        credentials=credentials,
        routing=routing,
        ai=ai,
        filters=filters,
        memory=memory,
        agent=agent,
    )


SETTINGS = load_settings()

# Backward-compatible exports (for existing imports)
DISCORD_TOKEN = SETTINGS.credentials.discord_token
OPENROUTER_KEY = SETTINGS.credentials.openrouter_key

CHANNEL_IDS = SETTINGS.routing.channel_ids
DEFAULT_SKILL = SETTINGS.routing.default_skill
CHANNEL_SKILLS = {
    channel_id: SETTINGS.routing.channel_skills.get(channel_id, DEFAULT_SKILL)
    for channel_id in SETTINGS.routing.watched_channel_ids
}

MODELS = SETTINGS.ai.models
DELAYS = SETTINGS.routing.profiles[SETTINGS.routing.default_profile].delays
REPLY_CHANCE = SETTINGS.routing.profiles[SETTINGS.routing.default_profile].chance
MAX_TOKENS_CONVERSATION = SETTINGS.ai.max_tokens_conversation
MAX_TOKENS_CHIME_IN = SETTINGS.ai.max_tokens_chime_in
TEMPERATURE = SETTINGS.ai.temperature
HISTORY_LIMIT = SETTINGS.ai.history_limit
KEYWORDS = SETTINGS.ai.keywords
MIN_MESSAGE_LENGTH = SETTINGS.filters.min_message_length
SKIP_PREFIXES = SETTINGS.filters.skip_prefixes
MEMORY_DB_PATH = SETTINGS.memory.db_path
