import asyncio
import logging

from google import genai
from google.genai import types

from config import GOOGLE_API_KEY, IMAGE_MODEL

logger = logging.getLogger(__name__)

client = genai.Client(api_key=GOOGLE_API_KEY)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # секунд


async def _generate_single(prompt: str, sketch_bytes: bytes | None = None) -> bytes | None:
    """Один вызов Gemini Image с retry — возвращает bytes картинки или None."""
    parts = []
    if sketch_bytes:
        parts.append(types.Part.from_bytes(data=sketch_bytes, mime_type="image/jpeg"))
    parts.append(types.Part.from_text(text=prompt))

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.aio.models.generate_content(
                model=IMAGE_MODEL,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )

            # Safety filter — нет candidates или finish_reason != STOP
            if not response.candidates:
                logger.warning("Генерация заблокирована фильтрами (нет candidates)")
                return None

            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    return part.inline_data.data

            logger.warning("Ответ не содержит картинки")
            return None

        except Exception as e:
            err_str = str(e).lower()
            is_retryable = "429" in err_str or "rate" in err_str or "timeout" in err_str or "500" in err_str

            if is_retryable and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("Попытка %d/%d не удалась, retry через %dс: %s", attempt, MAX_RETRIES, delay, e)
                await asyncio.sleep(delay)
            else:
                logger.exception("Ошибка генерации картинки (попытка %d/%d)", attempt, MAX_RETRIES)
                return None

    return None


async def generate_images(
    prompt: str,
    sketch_bytes: bytes | None = None,
    count: int = 4,
) -> list[bytes]:
    """Генерирует count вариантов картинок параллельно."""
    tasks = [_generate_single(prompt, sketch_bytes) for _ in range(count)]
    results = await asyncio.gather(*tasks)
    images = [r for r in results if r is not None]
    logger.info("Сгенерировано %d/%d картинок", len(images), count)
    return images
