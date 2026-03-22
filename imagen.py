import asyncio
import io
import logging

from google import genai
from google.genai import types
from PIL import Image

from config import GOOGLE_API_KEY, IMAGE_MODELS

logger = logging.getLogger(__name__)

_clients: dict[int, genai.Client] = {}


def _get_client(timeout_ms: int) -> genai.Client:
    if timeout_ms not in _clients:
        _clients[timeout_ms] = genai.Client(
            api_key=GOOGLE_API_KEY,
            http_options=types.HttpOptions(timeout=timeout_ms),
        )
    return _clients[timeout_ms]


MAX_RETRIES = 3
RETRY_BASE_DELAY = 2


class GenerationError(Exception):
    """Ошибка генерации с понятным сообщением для пользователя."""
    pass


def _split_grid(image_bytes: bytes, columns: int = 2, rows: int = 2) -> list[bytes]:
    """Разрезает grid-картинку на отдельные варианты."""
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    cell_w = w // columns
    cell_h = h // rows

    parts = []
    for row in range(rows):
        for col in range(columns):
            box = (col * cell_w, row * cell_h, (col + 1) * cell_w, (row + 1) * cell_h)
            cell = img.crop(box)
            buf = io.BytesIO()
            cell.save(buf, format="JPEG", quality=90)
            parts.append(buf.getvalue())

    return parts


async def _generate_single(
    prompt: str,
    model: str,
    sketch_bytes: bytes | None = None,
    image_size: str = "1K",
    timeout_ms: int = 300_000,
    extra_image_config: dict | None = None,
) -> bytes | None:
    """Один вызов Gemini Image с retry — возвращает bytes картинки или None."""
    client = _get_client(timeout_ms)

    parts = []
    if sketch_bytes:
        parts.append(types.Part.from_bytes(data=sketch_bytes, mime_type="image/jpeg"))
    parts.append(types.Part.from_text(text=prompt))

    image_cfg = {"image_size": image_size}
    if extra_image_config:
        image_cfg.update(extra_image_config)

    config = types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(**image_cfg),
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=parts)],
                config=config,
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
            err_str = str(e).lower()
            is_retryable = "429" in err_str or "rate" in err_str or "timeout" in err_str or "500" in err_str or "503" in err_str or "overloaded" in err_str

            if is_retryable and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("Попытка %d/%d не удалась, retry через %dс: %s", attempt, MAX_RETRIES, delay, e)
                await asyncio.sleep(delay)
            else:
                logger.exception("Ошибка генерации картинки (попытка %d/%d)", attempt, MAX_RETRIES)
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
    image_size: str = "1K",
    grid: bool = False,
    timeout_ms: int = 300_000,
) -> list[bytes]:
    """Генерирует варианты картинок.

    grid=True — один вызов с промптом "grid 2x2", результат разрезается на 4 картинки.
    grid=False — count параллельных вызовов, каждый возвращает одну картинку.
    """
    if model is None:
        model = IMAGE_MODELS["fast"]["model"]

    if grid:
        image_bytes = await _generate_single(
            prompt, model, sketch_bytes,
            image_size=image_size, timeout_ms=timeout_ms,
        )
        if image_bytes:
            images = _split_grid(image_bytes, columns=2, rows=2)
            logger.info("Grid 2x2 сгенерирован и разрезан на %d картинок (модель: %s)", len(images), model)
            return images
        return []

    tasks = [
        _generate_single(prompt, model, sketch_bytes,
                         image_size=image_size, timeout_ms=timeout_ms)
        for _ in range(count)
    ]
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
