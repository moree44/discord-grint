# ═══════════════════════════════════════════
#           DISCORD GRIND BOT CONFIG
# ═══════════════════════════════════════════

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

# ─── CREDENTIALS (dari .env) ────────────────
DISCORD_TOKEN    = os.getenv("DISCORD_TOKEN")
OPENROUTER_KEY   = os.getenv("OPENROUTER_API_KEY")

# ─── TARGET CHANNELS ────────────────────────
# Isi CHANNEL_IDS di .env dengan format: 123456789,987654321
CHANNEL_IDS = _parse_channel_ids(os.getenv("CHANNEL_IDS"))
DEFAULT_SKILL = os.getenv("DEFAULT_SKILL", "donut_browser")
CHANNEL_SKILLS = {channel_id: DEFAULT_SKILL for channel_id in CHANNEL_IDS}

# ─── AI MODELS ──────────────────────────────
# Urutan = prioritas, kalau model 1 ratelimit → otomatis ke model 2, dst
MODELS = [
    "arcee-ai/trinity-large-preview:free",
]

# ─── REPLY SETTINGS ─────────────────────────
# Chance bot reply (0.0 - 1.0)
REPLY_CHANCE = {
    "keyword_hit": 0.50,   # pesan contain keyword project
    "random":      0.20,   # pesan random
}

# Delay sebelum reply (detik) — sesuaikan dengan slowmode server
DELAYS = {
    "replied_to_us": (16, 30),    # ada yang reply ke bot
    "mentioned":     (16, 25),    # bot di-mention
    "keyword_hit":   (30, 90),    # pesan contain keyword
    "random":        (45, 120),   # random chime in
}

# ─── AI BEHAVIOR ────────────────────────────
MAX_TOKENS_CONVERSATION = 55   # lebih ringkas biar ngobrol terasa natural
MAX_TOKENS_CHIME_IN     = 40   # chime in pendek, ga kepanjangan
TEMPERATURE             = 0.72 # turunin noise biar ga terlalu halu/random
HISTORY_LIMIT           = 15   # berapa pesan terakhir dibaca sebagai konteks

# ─── KEYWORDS TRIGGER ───────────────────────
# Bot akan lebih sering reply kalau pesan mengandung kata ini
KEYWORDS = [
    "donut", "agent", "token", "airdrop", "wen",
    "wallet", "browser", "launch", "testnet", "og glazer",
    "wagmi", "ngmi", "raise", "funding", "whitelist"
]

# ─── FILTER ─────────────────────────────────
MIN_MESSAGE_LENGTH = 8   # skip pesan terlalu pendek
SKIP_PREFIXES = ("http", "!", "/", ".", "$", "@")  # skip link & command
