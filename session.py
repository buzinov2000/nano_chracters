import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from config import DEFAULT_IMAGE_MODE, IMAGE_MODELS, USER_DATA_FILE

logger = logging.getLogger(__name__)

_user_data_path = Path(__file__).parent / USER_DATA_FILE
_file_lock = asyncio.Lock()


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_default_model() -> str:
    try:
        data = json.loads(_user_data_path.read_text(encoding="utf-8"))
        mode = data.get("default_model", DEFAULT_IMAGE_MODE)
        if mode in IMAGE_MODELS:
            return mode
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return DEFAULT_IMAGE_MODE


async def save_default_model(mode: str) -> None:
    async with _file_lock:
        try:
            data = json.loads(await asyncio.to_thread(
                _user_data_path.read_text, encoding="utf-8"
            ))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data["default_model"] = mode
        await asyncio.to_thread(_write_json, _user_data_path, data)
    logger.info("Дефолтная модель сохранена: %s", mode)


@dataclass
class Session:
    sketch_bytes: bytes | None = None
    ref_images: list[bytes] = field(default_factory=list)
    current_prompt: str | None = None
    suggestions: list[str] = field(default_factory=list)
    images: list[bytes] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    image_mode: str = field(default_factory=load_default_model)
    awaiting_prompt_edit: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    generations_today: int = 0
    last_generation_date: date | None = None

    def check_daily_limit(self, limit: int) -> bool:
        """True = можно генерировать."""
        today = date.today()
        if self.last_generation_date != today:
            self.generations_today = 0
            self.last_generation_date = today
        if self.generations_today >= limit:
            return False
        self.generations_today += 1
        return True


_sessions: dict[int, Session] = {}


def get_session(chat_id: int) -> Session:
    if chat_id not in _sessions:
        _sessions[chat_id] = Session()
    return _sessions[chat_id]


def reset_session(chat_id: int) -> Session:
    _sessions[chat_id] = Session()
    return _sessions[chat_id]
