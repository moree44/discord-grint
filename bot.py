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
from agent.generator import (
    build_proactive_prompt,
    build_system_prompt,
    build_user_prompt,
    detect_message_language,
    generate_reply,
)
from agent.planner import plan_reply
from config import load_settings, resolve_channel_config
from memory.event_store import EventScope, EventStore
from memory.recent_context import RecentContextCache
from memory.user_profile import UserProfileStore
from storage.sqlite_store import SQLiteStore

load_dotenv()

_CONFIG_FILES = (Path(".env"), Path("web_settings.json"))
_CONFIG_RELOAD_INTERVAL_SECONDS = 3
_CONFIG_RELOAD_TASK: asyncio.Task | None = None
_PROACTIVE_TASK: asyncio.Task | None = None
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

_CURRENT_SETTINGS = load_settings()
TARGET_CHANNELS = _CURRENT_SETTINGS.routing.watched_channel_ids


def _build_ai_client(api_key: str | None) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )


def _capture_config_state() -> tuple[tuple[str, float | None], ...]:
    state: list[tuple[str, float | None]] = []
    for path in _CONFIG_FILES:
        if path.exists():
            state.append((str(path), path.stat().st_mtime))
        else:
            state.append((str(path), None))
    return tuple(state)


ai = _build_ai_client(_CURRENT_SETTINGS.credentials.openrouter_key)
sqlite_store = SQLiteStore(_CURRENT_SETTINGS.memory.db_path)
event_store = EventStore(
    sqlite_store,
    ttl_seconds=_CURRENT_SETTINGS.memory.event_ttl_seconds,
    max_recent_context=_CURRENT_SETTINGS.memory.max_recent_context,
    max_events_per_user=_CURRENT_SETTINGS.memory.max_events_per_user,
)
recent_context = RecentContextCache(max_items=_CURRENT_SETTINGS.memory.max_recent_context)
user_profiles = UserProfileStore(sqlite_store)
_CONFIG_STATE = _capture_config_state()
_SETTINGS_RELOAD_LOCK = asyncio.Lock()
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


def passes_basic_filters(message, settings, allow_short_message: bool = False):
    if message.author.bot:
        return False, "author_is_bot"
    if not message.content:
        return False, "empty_content"
    if not allow_short_message and len(message.content) < settings.filters.min_message_length:
        return False, "too_short"
    if message.content.startswith(settings.filters.skip_prefixes):
        return False, "prefixed_command"
    if re.match(r"^[\W\d\s]+$", message.content):
        return False, "non_textual"
    return True, None


async def _maybe_reload_settings(*, force: bool = False) -> None:
    global _CURRENT_SETTINGS
    global TARGET_CHANNELS
    global ai
    global sqlite_store
    global event_store
    global recent_context
    global user_profiles
    global _CONFIG_STATE

    async with _SETTINGS_RELOAD_LOCK:
        current_state = _capture_config_state()
        if not force and current_state == _CONFIG_STATE:
            return

        old_settings = _CURRENT_SETTINGS
        try:
            new_settings = load_settings()
        except Exception as exc:
            print(f"⚠️  Config reload failed: {exc}")
            return

        _CURRENT_SETTINGS = new_settings
        TARGET_CHANNELS = new_settings.routing.watched_channel_ids

        if old_settings.credentials.openrouter_key != new_settings.credentials.openrouter_key:
            ai = _build_ai_client(new_settings.credentials.openrouter_key)

        if old_settings.memory.db_path != new_settings.memory.db_path:
            sqlite_store = SQLiteStore(new_settings.memory.db_path)
            user_profiles = UserProfileStore(sqlite_store)
            event_store = EventStore(
                sqlite_store,
                ttl_seconds=new_settings.memory.event_ttl_seconds,
                max_recent_context=new_settings.memory.max_recent_context,
                max_events_per_user=new_settings.memory.max_events_per_user,
            )
            recent_context = RecentContextCache(max_items=new_settings.memory.max_recent_context)
            print(f"🔄 Config reloaded: memory DB path -> {new_settings.memory.db_path}")
        else:
            event_store.ttl_seconds = new_settings.memory.event_ttl_seconds
            event_store.max_recent_context = new_settings.memory.max_recent_context
            event_store.max_events_per_user = new_settings.memory.max_events_per_user
            if recent_context.max_items != new_settings.memory.max_recent_context:
                recent_context = RecentContextCache(max_items=new_settings.memory.max_recent_context)

        _CONFIG_STATE = current_state
        print(
            "🔄 Config reloaded: "
            f"channels={len(TARGET_CHANNELS)}, model={','.join(new_settings.ai.models[:2])}"
        )


async def _config_reload_loop() -> None:
    while True:
        await asyncio.sleep(_CONFIG_RELOAD_INTERVAL_SECONDS)
        await _maybe_reload_settings()


def _normalize_text(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip().lower()


def _contains_backoff_signal(context_lines: list[str], bot_name: str | None) -> bool:
    signals = (
        "stop", "stop dulu", "diam", "jangan spam", "spam", "berisik",
        "quiet", "be quiet", "too much", "mute", "shut up", "no bot",
    )
    for raw_line in context_lines[-14:]:
        line = raw_line.strip()
        if not line:
            continue
        if bot_name and line.lower().startswith(f"{bot_name.lower()}:"):
            continue
        lowered = _normalize_text(line)
        if any(token in lowered for token in signals):
            return True
    return False


def _detect_crypto_context(context_lines: list[str]) -> bool:
    if not context_lines:
        return False
    sample = _normalize_text(" ".join(context_lines[-16:]))
    if "crypto" in sample:
        return True
    return any(term in sample for term in CRYPTO_SIGNAL_TERMS)


def _language_hint_from_context(context_lines: list[str]) -> str:
    if not context_lines:
        return "Mirror the latest users naturally."
    text = " ".join(context_lines[-12:])
    detected = detect_message_language(text)
    if detected == "id":
        return "Mostly Indonesian, casual community tone."
    if detected == "en":
        return "Mostly English, casual community tone."
    return "Mixed language is okay; mirror the latest crowd naturally."


def _build_proactive_chance(
    *,
    base_chance: float,
    user_messages_recent: int,
    min_messages: int,
    latest_bot_reply_ts: int | None,
    now_ts: int,
    resolved_profile,
    settings,
    has_backoff_signal: bool,
) -> float:
    safe_min = max(1, min_messages)
    activity_factor = min(1.9, 0.65 + (user_messages_recent / (safe_min * 1.6)))
    profile_random_chance = float(resolved_profile.chance.get("random", 0.2))
    profile_factor = min(1.5, max(0.55, profile_random_chance / 0.2))

    cooldown_factor = 1.0
    if latest_bot_reply_ts:
        age = max(0, now_ts - latest_bot_reply_ts)
        if age < settings.agent.direct_reply_cooldown_seconds:
            cooldown_factor = 0.2
        elif age < settings.agent.random_cooldown_seconds:
            cooldown_factor = 0.5

    backoff_factor = 0.35 if has_backoff_signal else 1.0
    tuned = base_chance * activity_factor * profile_factor * cooldown_factor * backoff_factor
    return max(0.02, min(0.95, tuned))


async def _proactive_chat_loop() -> None:
    import time
    while True:
        try:
            settings = _CURRENT_SETTINGS
            wait_time = settings.agent.proactive_interval_minutes * 60
            if wait_time <= 0:
                await asyncio.sleep(60)
                continue

            await asyncio.sleep(wait_time)

            now_ts = int(time.time())
            since_ts = now_ts - wait_time

            for ch_id in TARGET_CHANNELS:
                ch = client.get_channel(ch_id)
                if not ch:
                    continue

                guild_id = ch.guild.id if getattr(ch, "guild", None) else None
                scope = EventScope(guild_id=guild_id, channel_id=ch_id, thread_id=None)
                resolved = resolve_channel_config(settings, guild_id, ch_id)
                if not resolved.enabled:
                    continue

                recent_user_count = event_store.count_recent_user_messages(
                    scope=scope,
                    since_ts=since_ts,
                    limit=80,
                )
                if recent_user_count < settings.agent.proactive_min_messages:
                    continue

                db_context = event_store.get_recent_context(scope=scope, limit=settings.ai.history_limit)
                if not db_context:
                    continue

                bot_name = str(client.user.display_name) if client.user else "bot"
                has_backoff_signal = _contains_backoff_signal(db_context, bot_name)
                latest_bot_ts = event_store.latest_bot_reply_ts(scope)
                tuned_chance = _build_proactive_chance(
                    base_chance=settings.agent.proactive_chance,
                    user_messages_recent=recent_user_count,
                    min_messages=settings.agent.proactive_min_messages,
                    latest_bot_reply_ts=latest_bot_ts,
                    now_ts=now_ts,
                    resolved_profile=resolved.profile,
                    settings=settings,
                    has_backoff_signal=has_backoff_signal,
                )
                if random.random() > tuned_chance:
                    continue

                is_crypto_context = _detect_crypto_context(db_context)
                language_hint = _language_hint_from_context(db_context)
                crowd_hint = (
                    "Users recently asked to slow down bot chatter."
                    if has_backoff_signal
                    else "Channel is active; chime in only if it adds value."
                )
                print(
                    f"👁️ [{resolved.profile_name}] Proactive check in "
                    f"#{getattr(ch, 'name', str(ch_id))} | active={recent_user_count} chance={tuned_chance:.2f}"
                )

                system_prompt = build_system_prompt(resolved.skill, is_crypto=is_crypto_context)
                proactive_prompt = build_proactive_prompt(
                    recent_context=db_context,
                    language_hint=language_hint,
                    crowd_hint=crowd_hint,
                )

                generation = await generate_reply(
                    ai=ai,
                    models_to_try=settings.ai.models or ["arcee-ai/trinity-large-preview:free"],
                    system_prompt=system_prompt,
                    user_prompt=proactive_prompt,
                    max_tokens=settings.ai.max_tokens_chime_in,
                    temperature=settings.ai.temperature,
                    retries=2,
                )

                reply_text = generation.text
                normalized_ignore = (
                    re.sub(r"[^A-Za-z]", "", reply_text).upper()
                    if reply_text
                    else ""
                )
                if not reply_text or normalized_ignore in {"IGNORE", "IGNORECHAT"}:
                    print("🔇 Proactive observer decided to stay quiet.")
                    continue

                print(f"💬 [Proactive|{resolved.profile_name}] Chime in -> {reply_text[:50]}...")

                try:
                    await ch.send(reply_text)
                    recent_context.remember(
                        channel_id=scope.channel_id,
                        thread_id=scope.thread_id,
                        author_name=bot_name,
                        content=reply_text,
                    )
                    event_store.add_event(
                        scope=scope,
                        user_id=client.user.id if client.user else None,
                        author_name=bot_name,
                        event_type="bot_reply",
                        content=reply_text,
                        metadata={"mode": "proactive", "delay_type": "proactive"},
                    )
                except Exception as e:
                    print(f"❌ Proactive send failed: {e}")

                break

        except Exception as e:
            print(f"❌ Proactive loop error: {e}")
            await asyncio.sleep(60)


def _quick_smalltalk_reply(message_content: str) -> str | None:
    text = re.sub(r"\s+", " ", message_content.lower()).strip()
    text = text.replace(",", "").replace(".", "").replace("!", "").replace("?", "")
    if not text:
        return None
    greeting_terms = ("good morning", "morning", "gm", "gdonut", "hello", "hi")
    if any(re.search(rf"\b{re.escape(greet)}\b", text) for greet in greeting_terms):
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
    global _CONFIG_RELOAD_TASK, _PROACTIVE_TASK
    await _maybe_reload_settings(force=True)
    settings = _CURRENT_SETTINGS

    if _CONFIG_RELOAD_TASK is None or _CONFIG_RELOAD_TASK.done():
        _CONFIG_RELOAD_TASK = asyncio.create_task(_config_reload_loop())
    
    if _PROACTIVE_TASK is None or _PROACTIVE_TASK.done():
        _PROACTIVE_TASK = asyncio.create_task(_proactive_chat_loop())

    print(f"\n{'='*45}")
    print(f"  ✅ Logged in as : {client.user}")
    print(f"  📡 Watching     : {len(TARGET_CHANNELS)} channel(s)")
    print(f"  🧠 Memory DB    : {settings.memory.db_path}")
    if not TARGET_CHANNELS:
        print("  ⚠️  No channel configured. Set CHANNEL_IDS/CHANNEL_SKILLS in .env")
    for ch_id in TARGET_CHANNELS:
        ch = client.get_channel(ch_id)
        if not ch:
            continue
        slowmode = ch.slowmode_delay
        try:
            resolved = resolve_channel_config(
                settings,
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
    settings = _CURRENT_SETTINGS
    if _is_duplicate_message(message.id):
        print(f"🔁 Skip duplicate message id={message.id}")
        return

    if message.author == client.user:
        return

    scope = _event_scope_from_message(message)
    resolved = resolve_channel_config(settings, scope.guild_id, scope.channel_id)
    if not resolved.enabled:
        return

    is_reference_to_self = await _is_reference_to_self(message)
    is_mentioned = bool(client.user and client.user.mentioned_in(message))

    mode = classify_message(
        content=message.content or "",
        has_reference_to_self=is_reference_to_self,
        is_mentioned=is_mentioned,
        keywords=settings.ai.keywords,
        crypto_terms=CRYPTO_SIGNAL_TERMS,
    )

    ok, reason = passes_basic_filters(
        message,
        settings,
        allow_short_message=mode.is_direct_reply,
    )
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
        latest_bot_reply_ts=event_store.latest_bot_reply_ts(scope),
        agent_settings=settings.agent,
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
        limit=settings.ai.history_limit,
    )
    db_context = event_store.get_recent_context(
        scope=scope,
        limit=settings.ai.history_limit,
    )
    combined_context = (cached_context + db_context)[-settings.ai.history_limit :]
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
        settings.ai.max_tokens_conversation
        if mode.is_direct_reply
        else settings.ai.max_tokens_chime_in
    )

    reply_candidate = None
    if mode.mode == "smalltalk" and not mode.is_crypto:
        reply_candidate = _quick_smalltalk_reply(message.content)

    if not reply_candidate:
        generation = await generate_reply(
            ai=ai,
            models_to_try=settings.ai.models or ["arcee-ai/trinity-large-preview:free"],
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=settings.ai.temperature,
            retries=3,
        )
        reply_candidate = generation.text

    recent_replies = event_store.get_recent_bot_replies(
        scope=scope,
        limit=settings.memory.anti_repeat_window,
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
            models_to_try=settings.ai.models or ["arcee-ai/trinity-large-preview:free"],
            system_prompt=system_prompt,
            user_prompt=retry_prompt,
            max_tokens=min(max_tokens, 36),
            temperature=max(0.35, settings.ai.temperature - 0.15),
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
client.run(_CURRENT_SETTINGS.credentials.discord_token)
