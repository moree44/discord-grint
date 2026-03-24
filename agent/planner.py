from __future__ import annotations

from dataclasses import dataclass
import random
import time

from agent.classifier import ModeResult
from config import AgentSettings, ReplyProfile


@dataclass(frozen=True)
class PlanResult:
    action: str  # reply | ignore
    delay_type: str | None
    reason: str


def _is_on_cooldown(
    *,
    latest_bot_reply_ts: int | None,
    mode: ModeResult,
    agent_settings: AgentSettings,
) -> bool:
    if latest_bot_reply_ts is None:
        return False
    now = int(time.time())
    if mode.is_direct_reply:
        wait = agent_settings.direct_reply_cooldown_seconds
    else:
        wait = agent_settings.random_cooldown_seconds
    return (now - latest_bot_reply_ts) < wait


def plan_reply(
    *,
    mode: ModeResult,
    profile: ReplyProfile,
    latest_bot_reply_ts: int | None,
    agent_settings: AgentSettings,
) -> PlanResult:
    if _is_on_cooldown(
        latest_bot_reply_ts=latest_bot_reply_ts,
        mode=mode,
        agent_settings=agent_settings,
    ):
        return PlanResult(action="ignore", delay_type=None, reason="cooldown")

    if mode.is_direct_reply:
        delay_type = "replied_to_us" if mode.reason == "reply_to_our_message" else "mentioned"
        return PlanResult(action="reply", delay_type=delay_type, reason=mode.reason)

    if mode.has_keyword:
        if random.random() < profile.chance["keyword_hit"]:
            return PlanResult(action="reply", delay_type="keyword_hit", reason="keyword_hit")
        return PlanResult(action="ignore", delay_type=None, reason="keyword_skip")

    # Global smalltalk chance acts as a ceiling, profile chance controls channel behavior.
    # This keeps quiet/slow profiles truly quieter instead of being overridden by global settings.
    smalltalk_chance = agent_settings.smalltalk_reply_chance
    effective_random_chance = min(profile.chance["random"], smalltalk_chance)
    if random.random() < effective_random_chance:
        return PlanResult(action="reply", delay_type="random", reason="random_chime")
    return PlanResult(action="ignore", delay_type=None, reason="random_skip")
