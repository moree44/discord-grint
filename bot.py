import discord
import asyncio
import random
import re
from pathlib import Path
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ───────────────────────────────────────────────
from config import SETTINGS, resolve_channel_config

TARGET_CHANNELS = SETTINGS.routing.watched_channel_ids
PROJECT_TERMS = (
    "donut", "token", "airdrop", "wallet", "testnet", "launch",
    "farming", "wagmi", "ngmi", "whitelist", "funding", "agentic"
)
CRYPTO_SIGNAL_TERMS = (
    "token", "airdrop", "wallet", "testnet", "launch", "farming",
    "whitelist", "funding", "listing", "claim", "xp", "snapshot"
)

# ─── INIT ─────────────────────────────────────────────────
client = discord.Client(self_bot=True)
ai     = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=SETTINGS.credentials.openrouter_key
)

# ─── LOAD SKILL ───────────────────────────────────────────
def load_skill(name: str = "donut_browser") -> str:
    candidates = [
        Path(f"skills/{name}.md"),
        Path(f"skills/{name}/SKILL.md"),
        Path("skills/SKILL.md"),
        Path("skills/donut_browser.md"),
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError("No skill file found in ./skills")

# ─── SHOULD REPLY LOGIC ───────────────────────────────────
def passes_basic_filters(message, allow_short_message=False):
    if message.author.bot:
        return False, None
    if not message.content:
        return False, None
    if not allow_short_message and len(message.content) < SETTINGS.filters.min_message_length:
        return False, None
    if message.content.startswith(SETTINGS.filters.skip_prefixes):
        return False, None
    if re.match(r'^[\W\d\s]+$', message.content):
        return False, None
    return True, None


def should_reply(message, client_user, reply_profile):
    content = message.content.lower()

    ok, reason = passes_basic_filters(message, allow_short_message=False)
    if not ok:
        return ok, reason

    if message.reference:
        try:
            if message.reference.resolved and message.reference.resolved.author == client_user:
                return True, "replied_to_us"
        except AttributeError:
            pass

    if client_user.mentioned_in(message):
        return True, "mentioned"

    if any(kw in content for kw in SETTINGS.ai.keywords):
        if random.random() < reply_profile.chance["keyword_hit"]:
            return True, "keyword_hit"
        return False, None

    if random.random() < reply_profile.chance["random"]:
        return True, "random"

    return False, None

# ─── GET AI REPLY ─────────────────────────────────────────
def _is_crypto_context(message_content: str, context_str: str) -> bool:
    current = message_content.lower()
    if any(term in current for term in CRYPTO_SIGNAL_TERMS):
        return True

    context_lower = context_str.lower()
    if "crypto" in current:
        return True

    # "donut" in greeting ("gdonut") is common in general chat,
    # so treat context as crypto only if strong terms appear repeatedly.
    signal_hits = sum(context_lower.count(term) for term in CRYPTO_SIGNAL_TERMS)
    return signal_hits >= 2


def _mentions_project_terms(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in PROJECT_TERMS)


def _quick_smalltalk_reply(message_content: str) -> str | None:
    text = re.sub(r"\s+", " ", message_content.lower()).strip()
    text = text.replace(",", "").replace(".", "").replace("!", "").replace("?", "")

    if not text:
        return None

    if any(greet in text for greet in ("good morning", "morning", "gm", "gdonut")):
        return random.choice(["gm", "morning bro", "gm fam", "morning"])

    if "how are you" in text or "how you doing" in text or "wby" in text:
        return random.choice(["i dey alright, you?", "doing good, you?", "i'm good bro"])

    if "thanks" in text or "thank you" in text:
        return random.choice(["anytime bro", "no wahala", "you good"])

    if "wassup" in text or "sup" == text:
        return random.choice(["all good bro", "steady here", "chilling fr"])

    return None


async def get_reply(channel, message_content, skill_name, is_conversation=False, retries=3):
    history = []
    async for msg in channel.history(limit=SETTINGS.ai.history_limit, oldest_first=True):
        if msg.content:
            history.append(f"{msg.author.display_name}: {msg.content}")

    context_str = "\n".join(history)
    is_crypto = _is_crypto_context(message_content, context_str)
    quick_reply = _quick_smalltalk_reply(message_content)
    if quick_reply and not is_crypto:
        return quick_reply

    if is_crypto:
        style_guard = (
            "Topic is crypto/project related. Keep reply short and casual, max 12 words. "
            "No long explanations."
        )
    else:
        style_guard = (
            "Topic is casual/non-crypto. Do not mention donut, project, crypto, token, airdrop, wallet, or testnet. "
            "Keep reply 1-8 words, one short sentence, casual human chat."
        )

    if is_conversation:
        user_prompt = f"""Someone is directly replying to you or mentioning you.
Chat context:
---
{context_str}
---
They said: "{message_content}"
Reply naturally as if continuing a real conversation.
{style_guard}"""
    else:
        user_prompt = f"""You're watching the chat and want to casually chime in.
Recent chat:
---
{context_str}
---
Latest message: "{message_content}"
Jump in naturally, like you've been reading along.
{style_guard}"""

    system_prompt = load_skill(skill_name)
    models_to_try = SETTINGS.ai.models or ["arcee-ai/trinity-large-preview:free"]

    for model_name in models_to_try:
        for attempt in range(retries):
            try:
                response = await ai.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt}
                    ],
                    max_tokens=(
                        SETTINGS.ai.max_tokens_conversation
                        if is_conversation
                        else SETTINGS.ai.max_tokens_chime_in
                    ),
                    temperature=SETTINGS.ai.temperature
                )

                content = response.choices[0].message.content
                if content and content.strip():
                    candidate = content.strip()
                    if not is_crypto and _mentions_project_terms(candidate):
                        print(
                            f"⚠️  Non-crypto context but model mentioned project terms, retry {attempt+1}/{retries}..."
                        )
                        await asyncio.sleep(1)
                        continue
                    return candidate

                print(f"⚠️  Empty response from {model_name}, retry {attempt+1}/{retries}...")
                await asyncio.sleep(2)

            except Exception as e:
                print(f"⚠️  Model {model_name} attempt {attempt+1}/{retries} error: {e}")
                await asyncio.sleep(2)

    print("❌ All retries failed, skipping...")
    return None


# ─── SAFE REPLY ───────────────────────────────────────────
async def safe_reply(message, text):
    if not text:
        print("⚠️  AI returned empty, skipping...")
        return
    try:

        await message.reply(text, mention_author=False)
        print(f"✅ Replied: {text[:70]}")

    except discord.errors.HTTPException as e:
        if e.status == 429:
            wait = getattr(e, 'retry_after', 16) + 1
            print(f"⏳ Slowmode! Waiting {wait:.1f}s then retry...")
            await asyncio.sleep(wait)
            try:
                await message.reply(text, mention_author=False)
                print(f"✅ Retry replied: {text[:70]}")
            except Exception as retry_err:
                print(f"❌ Retry failed: {retry_err}")
        else:
            print(f"❌ HTTP {e.status}: {e.text}")

    except discord.errors.Forbidden:
        print("❌ No permission in this channel")

    except Exception as e:
        print(f"❌ Error: {e}")

# ─── EVENTS ───────────────────────────────────────────────
@client.event
async def on_ready():
    print(f"\n{'='*45}")
    print(f"  ✅ Logged in as : {client.user}")
    print(f"  📡 Watching     : {len(TARGET_CHANNELS)} channel(s)")
    if not TARGET_CHANNELS:
        print("  ⚠️  No channel configured. Set CHANNEL_IDS in .env")
    for ch_id in TARGET_CHANNELS:
        ch = client.get_channel(ch_id)
        if ch:
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
                    f"  {status} #{ch.name} — slowmode: {slowmode}s, profile: {resolved.profile_name}"
                )
            except Exception as e:
                print(f"  ⚠️  #{ch.name} config error: {e}")
    print(f"{'='*45}\n")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    guild_id = message.guild.id if message.guild else None
    resolved = resolve_channel_config(SETTINGS, guild_id, message.channel.id)
    if not resolved.enabled:
        return

    is_convo = False
    if message.reference:
        try:
            ref = await message.channel.fetch_message(message.reference.message_id)
            if ref.author == client.user:
                is_convo = True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            print(f"⚠️  Failed to resolve reply reference: {e}")

    skill_name = resolved.skill

    if is_convo:
        do_reply, _ = passes_basic_filters(message, allow_short_message=True)
        if not do_reply:
            return
        delay_type = "replied_to_us"
    else:
        do_reply, delay_type = should_reply(message, client.user, resolved.profile)
        if not do_reply:
            return

    delay = random.randint(*resolved.profile.delays[delay_type])
    print(
        f"💬 [{delay_type}|{resolved.profile_name}] Replying in {delay}s → {message.content[:50]}..."
    )
    await asyncio.sleep(delay)

    reply_text = await get_reply(message.channel, message.content, skill_name, is_convo)
    await safe_reply(message, reply_text)

# ─── RUN ──────────────────────────────────────────────────
client.run(SETTINGS.credentials.discord_token)
