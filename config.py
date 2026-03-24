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
class ChannelSettings:
    channel_ids: list[int]
    default_skill: str

    @property
    def channel_skills(self) -> dict[int, str]:
        return {channel_id: self.default_skill for channel_id in self.channel_ids}


@dataclass(frozen=True)
class ReplySettings:
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
class AppSettings:
    credentials: Credentials
    channels: ChannelSettings
    reply: ReplySettings
    ai: AISettings
    filters: FilterSettings


def load_settings() -> AppSettings:
    credentials = Credentials(
        discord_token=os.getenv("DISCORD_TOKEN"),
        openrouter_key=os.getenv("OPENROUTER_API_KEY"),
    )

    channels = ChannelSettings(
        channel_ids=_parse_channel_ids(os.getenv("CHANNEL_IDS")),
        default_skill=os.getenv("DEFAULT_SKILL", "donut_browser"),
    )

    reply = ReplySettings(
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
        channels=channels,
        reply=reply,
        ai=ai,
        filters=filters,
    )


SETTINGS = load_settings()

# Backward-compatible exports (for existing imports)
DISCORD_TOKEN = SETTINGS.credentials.discord_token
OPENROUTER_KEY = SETTINGS.credentials.openrouter_key

CHANNEL_IDS = SETTINGS.channels.channel_ids
DEFAULT_SKILL = SETTINGS.channels.default_skill
CHANNEL_SKILLS = SETTINGS.channels.channel_skills

MODELS = SETTINGS.ai.models
DELAYS = SETTINGS.reply.delays
REPLY_CHANCE = SETTINGS.reply.chance
MAX_TOKENS_CONVERSATION = SETTINGS.ai.max_tokens_conversation
MAX_TOKENS_CHIME_IN = SETTINGS.ai.max_tokens_chime_in
TEMPERATURE = SETTINGS.ai.temperature
HISTORY_LIMIT = SETTINGS.ai.history_limit
KEYWORDS = SETTINGS.ai.keywords
MIN_MESSAGE_LENGTH = SETTINGS.filters.min_message_length
SKIP_PREFIXES = SETTINGS.filters.skip_prefixes
