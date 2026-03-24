from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import asyncio
import re

from openai import AsyncOpenAI

from memory.user_profile import UserProfile


def _read_first_existing(candidates: list[Path]) -> str | None:
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return None


def load_general_skill() -> str:
    candidates = [
        Path("skills/base/general.md"),
        Path("skills/base/general/SKILL.md"),
    ]
    general = _read_first_existing(candidates)
    if general:
        return general
    return (
        "You are a casual Discord member. Keep replies short, natural, and context-aware. "
        "Do not force crypto/project talk in non-crypto chat."
    )


def load_project_skill(name: str = "donut_browser") -> str | None:
    candidates = [
        Path(f"skills/projects/{name}.md"),
        Path(f"skills/projects/{name}/SKILL.md"),
        Path(f"skills/{name}.md"),
        Path(f"skills/{name}/SKILL.md"),
    ]
    return _read_first_existing(candidates)


def build_system_prompt(skill_name: str, is_crypto: bool) -> str:
    parts = [load_general_skill()]
    project_skill = load_project_skill(skill_name)
    if is_crypto and project_skill:
        parts.append(project_skill)
    if is_crypto:
        parts.append(
            "When topic is project/crypto: stay factual, concise, and avoid speculation."
        )
    else:
        parts.append(
            "When topic is non-crypto: keep it casual and never force project keywords."
        )
    return "\n\n".join(parts)


def detect_message_language(text: str) -> str:
    lowered = text.lower()
    tokens = re.findall(r"[a-zA-Z']+", lowered)
    if not tokens:
        return "mixed"

    id_markers = {
        "aku", "saya", "kamu", "lu", "gue", "gak", "ga", "nggak",
        "bang", "bro", "nih", "udah", "lagi", "hari", "males",
        "tidur", "ngopi", "gimana", "deh",
    }
    en_markers = {
        "you", "your", "why", "what", "today", "outside", "hello",
        "hey", "bro", "man", "dont", "don't", "touch", "grass",
        "how", "are",
    }

    id_hits = sum(1 for t in tokens if t in id_markers)
    en_hits = sum(1 for t in tokens if t in en_markers)
    if id_hits > en_hits:
        return "id"
    if en_hits > id_hits:
        return "en"
    return "mixed"


def build_user_prompt(
    *,
    latest_message: str,
    recent_context: list[str],
    mode: str,
    user_profile: UserProfile | None,
    is_direct_reply: bool,
) -> str:
    detected_lang = detect_message_language(latest_message)
    if detected_lang == "id":
        language_rule = "Reply mostly in Indonesian (casual)."
    elif detected_lang == "en":
        language_rule = "Reply mostly in English (casual)."
    else:
        language_rule = "Mirror the dominant language style of the latest user message."

    profile_text = "none"
    if user_profile:
        profile_text = (
            f"language={user_profile.preferred_language or 'unknown'}, "
            f"style={user_profile.style_hint or 'casual'}, "
            f"topics={','.join(user_profile.topics) or 'none'}"
        )
    context_text = "\n".join(recent_context[-20:]) if recent_context else "(no context)"
    direct_text = "yes" if is_direct_reply else "no"
    return f"""Chat context:
---
{context_text}
---
Latest message: "{latest_message}"
Mode: {mode}
Direct reply to bot: {direct_text}
User profile hint: {profile_text}

Reply naturally as a human community member.
Constraints:
- Keep it concise.
- Plain text only.
- Never wrap full output in quotation marks.
- If non-crypto mode, do not force project/crypto terms.
- {language_rule}
"""


@dataclass(frozen=True)
class GenerationResult:
    text: str | None
    model_used: str | None


async def generate_reply(
    *,
    ai: AsyncOpenAI,
    models_to_try: list[str],
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
    retries: int = 3,
) -> GenerationResult:
    for model_name in models_to_try:
        for attempt in range(retries):
            try:
                response = await ai.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                content = response.choices[0].message.content
                if content and content.strip():
                    return GenerationResult(text=content.strip(), model_used=model_name)
                await asyncio.sleep(1)
            except Exception:
                await asyncio.sleep(1)
                if attempt == retries - 1:
                    continue
    return GenerationResult(text=None, model_used=None)
