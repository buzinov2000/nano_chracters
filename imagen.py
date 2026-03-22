import asyncio
import logging

from google import genai
from google.genai import types

from config import GOOGLE_API_KEY, IMAGE_MODELS

logger = logging.getLogger(__name__)

client = genai.Client(api_key=GOOGLE_API_KEY)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2


class GenerationError(Exception):
    """Ошибка генерации с понятным сообщением для пользователя."""
    pass


async def _generate_single(prompt: str, model: str, sketch_bytes: bytes | None = None) -> bytes | None:
    """Один вызов Gemini Image с retry — возвращает bytes картинки или None."""
    parts = []
    if sketch_bytes:
        parts.append(types.Part.from_bytes(data=sketch_bytes, mime_type="image/jpeg"))
    parts.append(types.Part.from_text(text=prompt))

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )

            if not response.candidates:
                logger.warning("Генерация заблокирована фильтрами (нет candidates)")
                raise GenerationError("safety_filter")

            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    return part.inline_data.data

            logger.warning("Ответ не содержит картинки")
            return None

        except GenerationError:
            raise

        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            is_retryable = "429" in err_str or "rate" in err_str or "timeout" in err_str or "500" in err_str or "503" in err_str or "overloaded" in err_str

            if is_retryable and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("Попытка %d/%d не удалась, retry через %dс: %s", attempt, MAX_RETRIES, delay, e)
                await asyncio.sleep(delay)
            else:
                logger.exception("Ошибка генерации картинки (попытка %d/%d)", attempt, MAX_RETRIES)
                # Определяем тип ошибки для пользователя
                if "429" in err_str or "rate" in err_str or "overloaded" in err_str or "503" in err_str:
                    raise GenerationError("overloaded")
                elif "timeout" in err_str:
                    raise GenerationError("timeout")
                return None

    return None


async def generate_images(
    prompt: str,
    sketch_bytes: bytes | None = None,
    count: int = 4,
    model: str | None = None,
) -> list[bytes]:
    """Генерирует count вариантов картинок параллельно."""
    if model is None:
        model = IMAGE_MODELS["fast"]["model"]

    tasks = [_generate_single(prompt, model, sketch_bytes) for _ in range(count)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    images = []
    last_error = None
    for r in results:
        if isinstance(r, bytes):
            images.append(r)
        elif isinstance(r, GenerationError):
            last_error = r

    logger.info("Сгенерировано %d/%d картинок (модель: %s)", len(images), count, model)

    if not images and last_error:
        raise last_error

    return images
