from __future__ import annotations

import asyncio
from collections import deque
import fcntl
import random
import re
import sys
from pathlib import Path

import discord
from dotenv import load_dotenv
from openai import AsyncOpenAI

from agent.classifier import classify_message
from agent.critic import critique_reply
from agent.generator import build_system_prompt, build_user_prompt, generate_reply
from agent.planner import plan_reply
from config import SETTINGS, resolve_channel_config
from memory.event_store import EventScope, EventStore
from memory.recent_context import RecentContextCache
from memory.user_profile import UserProfileStore
from storage.sqlite_store import SQLiteStore

load_dotenv()

TARGET_CHANNELS = SETTINGS.routing.watched_channel_ids
CRYPTO_SIGNAL_TERMS = (
    "token",
    "airdrop",
    "wallet",
    "testnet",
    "launch",
    "farming",
    "whitelist",
    "funding",
    "listing",
    "claim",
    "xp",
    "snapshot",
)


if hasattr(discord, "Intents"):
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents, self_bot=True)
else:
    client = discord.Client(self_bot=True)

ai = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=SETTINGS.credentials.openrouter_key,
)

sqlite_store = SQLiteStore(SETTINGS.memory.db_path)
event_store = EventStore(
    sqlite_store,
    ttl_seconds=SETTINGS.memory.event_ttl_seconds,
    max_recent_context=SETTINGS.memory.max_recent_context,
    max_events_per_user=SETTINGS.memory.max_events_per_user,
)
recent_context = RecentContextCache(max_items=SETTINGS.memory.max_recent_context)
user_profiles = UserProfileStore(sqlite_store)
_INSTANCE_LOCK_FILE = None
_SEEN_MESSAGE_IDS: set[int] = set()
_SEEN_MESSAGE_ORDER: deque[int] = deque(maxlen=4000)


def _acquire_single_instance_lock() -> None:
    global _INSTANCE_LOCK_FILE
    runtime_dir = Path("runtime")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_dir / "bot.instance.lock"
    lock_fh = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("❌ Another bot instance is already running. Exiting.")
        sys.exit(1)
    _INSTANCE_LOCK_FILE = lock_fh


def _is_duplicate_message(message_id: int) -> bool:
    if message_id in _SEEN_MESSAGE_IDS:
        return True
    if len(_SEEN_MESSAGE_ORDER) == _SEEN_MESSAGE_ORDER.maxlen:
        old_id = _SEEN_MESSAGE_ORDER.popleft()
        _SEEN_MESSAGE_IDS.discard(old_id)
    _SEEN_MESSAGE_ORDER.append(message_id)
    _SEEN_MESSAGE_IDS.add(message_id)
    return False


def passes_basic_filters(message, allow_short_message: bool = False):
    if message.author.bot:
        return False, "author_is_bot"
    if not message.content:
        return False, "empty_content"
    if not allow_short_message and len(message.content) < SETTINGS.filters.min_message_length:
        return False, "too_short"
    if message.content.startswith(SETTINGS.filters.skip_prefixes):
        return False, "prefixed_command"
    if re.match(r"^[\W\d\s]+$", message.content):
        return False, "non_textual"
    return True, None


def _quick_smalltalk_reply(message_content: str) -> str | None:
    text = re.sub(r"\s+", " ", message_content.lower()).strip()
    text = text.replace(",", "").replace(".", "").replace("!", "").replace("?", "")
    if not text:
        return None
    if any(greet in text for greet in ("good morning", "morning", "gm", "gdonut", "hello", "hi")):
        return random.choice(["gm", "morning bro", "hey bro", "hey"])
    if "how are you" in text or "how you doing" in text or "wby" in text:
        return random.choice(["i dey alright, you?", "doing good, you?", "i'm good bro"])
    if "thanks" in text or "thank you" in text:
        return random.choice(["anytime bro", "no wahala", "you good"])
    if "wassup" in text or text == "sup":
        return random.choice(["all good bro", "steady here", "chilling fr"])
    return None


def _event_scope_from_message(message) -> EventScope:
    guild_id = message.guild.id if message.guild else None
    channel_id = message.channel.id
    thread_id = None
    if isinstance(message.channel, discord.Thread):
        thread_id = message.channel.id
        channel_id = message.channel.parent_id or message.channel.id
    return EventScope(guild_id=guild_id, channel_id=channel_id, thread_id=thread_id)


async def _is_reference_to_self(message) -> bool:
    if not message.reference or not client.user:
        return False
    try:
        ref_id = message.reference.message_id
        if ref_id is None:
            return False
        ref = await message.channel.fetch_message(ref_id)
        return ref.author == client.user
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


async def safe_reply(message, text: str) -> bool:
    if not text:
        return False
    try:
        await message.reply(text, mention_author=False)
        print(f"✅ Replied: {text[:70]}")
        return True
    except discord.errors.HTTPException as e:
        if e.status == 429:
            wait = getattr(e, "retry_after", 16) + 1
            print(f"⏳ Slowmode! Waiting {wait:.1f}s then retry...")
            await asyncio.sleep(wait)
            try:
                await message.reply(text, mention_author=False)
                print(f"✅ Retry replied: {text[:70]}")
                return True
            except Exception as retry_err:
                print(f"❌ Retry failed: {retry_err}")
                return False
        print(f"❌ HTTP {e.status}: {e.text}")
        return False
    except discord.errors.Forbidden:
        print("❌ No permission in this channel")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


@client.event
async def on_ready():
    print(f"\n{'='*45}")
    print(f"  ✅ Logged in as : {client.user}")
    print(f"  📡 Watching     : {len(TARGET_CHANNELS)} channel(s)")
    print(f"  🧠 Memory DB    : {SETTINGS.memory.db_path}")
    if not TARGET_CHANNELS:
        print("  ⚠️  No channel configured. Set CHANNEL_IDS/CHANNEL_SKILLS in .env")
    for ch_id in TARGET_CHANNELS:
        ch = client.get_channel(ch_id)
        if not ch:
            continue
        slowmode = ch.slowmode_delay
        try:
            resolved = resolve_channel_config(
                SETTINGS,
                ch.guild.id if getattr(ch, "guild", None) else None,
                ch_id,
            )
            min_reply_delay = resolved.profile.delays["replied_to_us"][0]
            status = "✅" if min_reply_delay > slowmode else "⚠️ "
            print(
                f"  {status} #{ch.name} — slowmode: {slowmode}s, profile: {resolved.profile_name}, project: {resolved.skill}"
            )
        except Exception as e:
            print(f"  ⚠️  #{ch.name} config error: {e}")
    print(f"{'='*45}\n")


@client.event
async def on_message(message):
    if _is_duplicate_message(message.id):
        print(f"🔁 Skip duplicate message id={message.id}")
        return

    if message.author == client.user:
        return

    scope = _event_scope_from_message(message)
    resolved = resolve_channel_config(SETTINGS, scope.guild_id, scope.channel_id)
    if not resolved.enabled:
        return

    is_reference_to_self = await _is_reference_to_self(message)
    is_mentioned = bool(client.user and client.user.mentioned_in(message))

    mode = classify_message(
        content=message.content or "",
        has_reference_to_self=is_reference_to_self,
        is_mentioned=is_mentioned,
        keywords=SETTINGS.ai.keywords,
        crypto_terms=CRYPTO_SIGNAL_TERMS,
    )

    ok, reason = passes_basic_filters(message, allow_short_message=mode.is_direct_reply)
    if not ok:
        print(f"🔇 Skip [{reason}] -> {message.content[:40]}")
        return

    event_store.purge_expired()
    recent_context.remember(
        channel_id=scope.channel_id,
        thread_id=scope.thread_id,
        author_name=message.author.display_name,
        content=message.content,
    )
    event_store.add_event(
        scope=scope,
        user_id=message.author.id,
        author_name=message.author.display_name,
        event_type="user_message",
        content=message.content,
        metadata={"mode_hint": mode.mode},
    )
    user_profiles.update_from_message(
        user_id=message.author.id,
        display_name=message.author.display_name,
        content=message.content,
    )

    plan = plan_reply(
        mode=mode,
        profile=resolved.profile,
        latest_bot_reply_ts=event_store.latest_bot_reply_ts(scope.channel_id),
        agent_settings=SETTINGS.agent,
    )
    if plan.action == "ignore" or not plan.delay_type:
        print(f"🔇 Plan ignore [{plan.reason}|{mode.mode}] -> {message.content[:50]}")
        return

    delay = random.randint(*resolved.profile.delays[plan.delay_type])
    print(
        f"💬 [{plan.delay_type}|{resolved.profile_name}|{mode.mode}] Replying in {delay}s -> {message.content[:50]}..."
    )
    event_store.add_event(
        scope=scope,
        user_id=client.user.id if client.user else None,
        author_name=str(client.user.display_name) if client.user else "bot",
        event_type="bot_plan",
        content=(
            f"planned reply in {delay}s ({plan.delay_type}|{resolved.profile_name}|{mode.mode}) "
            f"for: {message.content[:70]}"
        ),
        metadata={"delay_seconds": delay, "delay_type": plan.delay_type},
    )
    await asyncio.sleep(delay)

    cached_context = recent_context.get_context(
        channel_id=scope.channel_id,
        thread_id=scope.thread_id,
        limit=SETTINGS.ai.history_limit,
    )
    db_context = event_store.get_recent_context(
        scope=scope,
        limit=SETTINGS.ai.history_limit,
    )
    combined_context = (cached_context + db_context)[-SETTINGS.ai.history_limit :]
    profile = user_profiles.get_profile(message.author.id)
    system_prompt = build_system_prompt(resolved.skill, mode.is_crypto)
    user_prompt = build_user_prompt(
        latest_message=message.content,
        recent_context=combined_context,
        mode=mode.mode,
        user_profile=profile,
        is_direct_reply=mode.is_direct_reply,
    )
    max_tokens = (
        SETTINGS.ai.max_tokens_conversation
        if mode.is_direct_reply
        else SETTINGS.ai.max_tokens_chime_in
    )

    reply_candidate = None
    if mode.mode == "smalltalk" and not mode.is_crypto:
        reply_candidate = _quick_smalltalk_reply(message.content)

    if not reply_candidate:
        generation = await generate_reply(
            ai=ai,
            models_to_try=SETTINGS.ai.models or ["arcee-ai/trinity-large-preview:free"],
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=SETTINGS.ai.temperature,
            retries=3,
        )
        reply_candidate = generation.text

    recent_replies = event_store.get_recent_bot_replies(
        scope=scope,
        limit=SETTINGS.memory.anti_repeat_window,
    )
    reviewed_reply = critique_reply(
        text=reply_candidate,
        mode=mode.mode,
        is_crypto=mode.is_crypto,
        recent_replies=recent_replies,
    )
    if not reviewed_reply:
        print("⚠️  Critic rejected candidate reply, regenerating once...")
        banned = " | ".join(recent_replies[:4]) if recent_replies else "(none)"
        retry_prompt = (
            f"{user_prompt}\n\n"
            "Retry constraints:\n"
            "- Previous draft was rejected.\n"
            "- Keep one short sentence.\n"
            "- Stay tightly relevant to latest message.\n"
            f"- Do not repeat these recent bot replies: {banned}\n"
        )
        retry_generation = await generate_reply(
            ai=ai,
            models_to_try=SETTINGS.ai.models or ["arcee-ai/trinity-large-preview:free"],
            system_prompt=system_prompt,
            user_prompt=retry_prompt,
            max_tokens=min(max_tokens, 36),
            temperature=max(0.35, SETTINGS.ai.temperature - 0.15),
            retries=2,
        )
        reviewed_reply = critique_reply(
            text=retry_generation.text,
            mode=mode.mode,
            is_crypto=mode.is_crypto,
            recent_replies=recent_replies,
        )
        if not reviewed_reply:
            print("⚠️  Critic rejected retry reply")
            return

    sent = await safe_reply(message, reviewed_reply)
    if not sent:
        return

    bot_name = str(client.user.display_name) if client.user else "bot"
    recent_context.remember(
        channel_id=scope.channel_id,
        thread_id=scope.thread_id,
        author_name=bot_name,
        content=reviewed_reply,
    )
    event_store.add_event(
        scope=scope,
        user_id=client.user.id if client.user else None,
        author_name=bot_name,
        event_type="bot_reply",
        content=reviewed_reply,
        metadata={"mode": mode.mode, "delay_type": plan.delay_type},
    )

_acquire_single_instance_lock()
client.run(SETTINGS.credentials.discord_token)
