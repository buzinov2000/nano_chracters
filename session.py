import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from config import DEFAULT_IMAGE_MODE, IMAGE_MODELS, USER_DATA_FILE

logger = logging.getLogger(__name__)

_user_data_path = Path(__file__).parent / USER_DATA_FILE


def load_default_model() -> str:
    try:
        data = json.loads(_user_data_path.read_text(encoding="utf-8"))
        mode = data.get("default_model", DEFAULT_IMAGE_MODE)
        if mode in IMAGE_MODELS:
            return mode
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return DEFAULT_IMAGE_MODE


def save_default_model(mode: str) -> None:
    try:
        data = json.loads(_user_data_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data["default_model"] = mode
    _user_data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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


_sessions: dict[int, Session] = {}


def get_session(chat_id: int) -> Session:
    if chat_id not in _sessions:
        _sessions[chat_id] = Session()
    return _sessions[chat_id]


def reset_session(chat_id: int) -> Session:
    _sessions[chat_id] = Session()
    return _sessions[chat_id]
