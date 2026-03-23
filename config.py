import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

PROMPT_AGENT_MODEL = "gemini-2.5-flash"

IMAGE_MODELS = {
    "fast": {
        "model": "gemini-2.5-flash-image",
        "count": 4,
        "image_size": "1K",
        "grid": False,
        "timeout": 300_000,
        "label": "Nano Banana (быстрая)",
    },
    "pro": {
        "model": "gemini-3-pro-image-preview",
        "count": 4,
        "image_size": "2K",
        "grid": True,           # grid 2x2 при 2K — каждая картинка ~1K
        "timeout": 300_000,
        "label": "Nano Banana Pro",
    },
    "quality": {
        "model": "gemini-3.1-flash-image-preview",
        "count": 4,
        "image_size": "2K",
        "grid": True,           # grid 2x2 при 2K — каждая картинка ~1K
        "timeout": 600_000,     # 600 сек — preview-модель может быть медленной
        "label": "Nano Banana 2 (качество)",
    },
}

DEFAULT_IMAGE_MODE = "fast"
USER_DATA_FILE = "user_data.json"

# Параллельность
MAX_CONCURRENT_API_CALLS = 8  # максимум одновременных вызовов к Image API

# Whitelist (пустой = открыт для всех)
ALLOWED_USERS: set[int] = set()
_raw = os.getenv("ALLOWED_USERS", "")
if _raw:
    ALLOWED_USERS = {int(uid.strip()) for uid in _raw.split(",") if uid.strip()}

# Rate limiting
DAILY_LIMIT_PER_USER = int(os.getenv("DAILY_LIMIT_PER_USER", "50"))
