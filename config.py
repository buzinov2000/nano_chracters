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
        "label": "Nano Banana (быстрая)",
    },
    "pro": {
        "model": "gemini-3.0-pro-image",
        "count": 2,
        "label": "Nano Banana Pro",
    },
    "quality": {
        "model": "gemini-3.1-flash-image-preview",
        "count": 2,
        "label": "Nano Banana 2 (качество)",
    },
}

DEFAULT_IMAGE_MODE = "fast"
