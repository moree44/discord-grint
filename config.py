"""Centralized app settings for discord-grind-bot."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


def _parse_channel_ids(raw_value: str | None) -> list[int]:
    if not raw_value:
        return []

    channel_ids = []
    for part in raw_value.split(","):
        value = part.strip()
        if not value:
            continue
        if not value.isdigit():
            raise ValueError(
                "CHANNEL_IDS must be comma-separated numeric IDs, e.g. 123456789,987654321"
            )
        channel_ids.append(int(value))
    return channel_ids


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
    default_skill: str
    default_profile: str
    profiles: dict[str, ReplyProfile]
    servers: dict[int, ServerConfig]

    @property
    def watched_channel_ids(self) -> set[int]:
        watched = set(self.channel_ids)
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


def resolve_channel_config(
    settings: AppSettings, guild_id: int | None, channel_id: int
) -> ResolvedChannelConfig:
    skill = settings.routing.default_skill
    profile_name = settings.routing.default_profile
    enabled = channel_id in settings.routing.channel_ids

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

    # Legacy watchlist from .env. Keep this for quick setup.
    channel_ids = _parse_channel_ids(os.getenv("CHANNEL_IDS"))
    default_skill = os.getenv("DEFAULT_SKILL", "donut_browser")

    # Profiles can be reused across multi-server/channel routing.
    profiles = {
        "normal": ReplyProfile(
            chance={
                "keyword_hit": 0.50,
                "random": 0.20,
            },
            delays={
                "replied_to_us": (16, 30),
                "mentioned": (16, 25),
                "keyword_hit": (30, 90),
                "random": (45, 120),
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

    # Optional advanced routing for multi server/channel setup.
    # Example:
    # servers = {
    #     123456789012345678: ServerConfig(
    #         default_profile="normal",
    #         channels={
    #             223456789012345678: ChannelOverride(profile="slow_60s"),
    #             323456789012345678: ChannelOverride(profile="quiet", skill="donut_browser"),
    #         },
    #     ),
    # }
    servers: dict[int, ServerConfig] = {}

    routing = RoutingSettings(
        channel_ids=channel_ids,
        default_skill=default_skill,
        default_profile="normal",
        profiles=profiles,
        servers=servers,
    )

    ai = AISettings(
        models=[
            "arcee-ai/trinity-large-preview:free",
        ],
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

    return AppSettings(
        credentials=credentials,
        routing=routing,
        ai=ai,
        filters=filters,
    )


SETTINGS = load_settings()

# Backward-compatible exports (for existing imports)
DISCORD_TOKEN = SETTINGS.credentials.discord_token
OPENROUTER_KEY = SETTINGS.credentials.openrouter_key

CHANNEL_IDS = SETTINGS.routing.channel_ids
DEFAULT_SKILL = SETTINGS.routing.default_skill
CHANNEL_SKILLS = {channel_id: DEFAULT_SKILL for channel_id in CHANNEL_IDS}

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
