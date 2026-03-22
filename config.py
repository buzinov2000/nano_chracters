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
