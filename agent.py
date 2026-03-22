import logging
from pathlib import Path

from google import genai
from google.genai import types

from config import GOOGLE_API_KEY, PROMPT_AGENT_MODEL

logger = logging.getLogger(__name__)

client = genai.Client(
    api_key=GOOGLE_API_KEY,
    http_options=types.HttpOptions(timeout=60_000),  # 60 сек для промпт-агента
)

_prompt_cache: dict[str, str] = {}


def _load_system_prompt(grid: bool = False) -> str:
    key = "grid" if grid else "default"
    if key not in _prompt_cache:
        filename = "prompt_agent_grid.txt" if grid else "prompt_agent.txt"
        path = Path(__file__).parent / "prompts" / filename
        _prompt_cache[key] = path.read_text(encoding="utf-8")
    return _prompt_cache[key]


def _parse_response(text: str) -> tuple[str, list[str]]:
    """Извлекает промпт и подсказки из ответа агента."""
    prompt = ""
    suggestions = []

    if "PROMPT:" in text:
        after_prompt = text.split("PROMPT:", 1)[1]
        if "SUGGESTIONS:" in after_prompt:
            prompt = after_prompt.split("SUGGESTIONS:", 1)[0].strip()
            suggestions_block = after_prompt.split("SUGGESTIONS:", 1)[1].strip()
        else:
            prompt = after_prompt.strip()
            suggestions_block = ""
    else:
        prompt = text.strip()
        suggestions_block = ""

    for line in suggestions_block.splitlines():
        line = line.strip().lstrip("- ").strip()
        if line:
            suggestions.append(line)

    return prompt, suggestions


async def generate_prompt(
    sketch_bytes: bytes,
    hypothesis: str,
    ref_images: list[bytes] | None = None,
    grid: bool = False,
) -> tuple[str, list[str]]:
    """Генерирует промпт для image generation на основе скетча, гипотезы и рефов."""
    system_prompt = _load_system_prompt(grid=grid)

    parts = [
        types.Part.from_text(text=system_prompt),
        types.Part.from_bytes(data=sketch_bytes, mime_type="image/jpeg"),
    ]

    if ref_images:
        parts.append(types.Part.from_text(text="Референсные изображения от арт-директора:"))
        for ref in ref_images:
            parts.append(types.Part.from_bytes(data=ref, mime_type="image/jpeg"))

    parts.append(types.Part.from_text(text=f"Гипотеза арт-директора: {hypothesis}"))

    contents = [types.Content(role="user", parts=parts)]

    try:
        response = await client.aio.models.generate_content(
            model=PROMPT_AGENT_MODEL,
            contents=contents,
        )
        raw_text = response.text
        logger.info("Ответ агента получен (%d символов)", len(raw_text))
        return _parse_response(raw_text)
    except Exception:
        logger.exception("Ошибка при вызове промпт-агента")
        raise
