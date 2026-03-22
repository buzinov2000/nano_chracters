from dataclasses import dataclass, field

from config import DEFAULT_IMAGE_MODE


@dataclass
class Session:
    sketch_bytes: bytes | None = None
    ref_images: list[bytes] = field(default_factory=list)
    current_prompt: str | None = None
    suggestions: list[str] = field(default_factory=list)
    images: list[bytes] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    image_mode: str = DEFAULT_IMAGE_MODE
    awaiting_prompt_edit: bool = False


_sessions: dict[int, Session] = {}


def get_session(chat_id: int) -> Session:
    if chat_id not in _sessions:
        _sessions[chat_id] = Session()
    return _sessions[chat_id]


def reset_session(chat_id: int) -> Session:
    _sessions[chat_id] = Session()
    return _sessions[chat_id]
