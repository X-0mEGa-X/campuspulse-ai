"""Session-local chat storage with an active buffer for Streamlit widgets."""
from collections.abc import MutableMapping
from typing import Any
from uuid import uuid4


MAX_CHATS = 10
MAX_MESSAGES = 100
DATA_KEYS = ("messages", "tasks", "documents", "images", "plan", "last_plan_trace", "last_result", "repository")
_LIST_KEYS = ("messages", "tasks", "documents", "images")


def _empty_data() -> dict:
    return {"messages": [], "tasks": [], "documents": [], "images": [],
            "plan": None, "last_plan_trace": None, "last_result": None, "repository": ""}


def _validate_data(data: dict) -> None:
    if not isinstance(data, dict) or any(key not in data for key in DATA_KEYS):
        raise ValueError("Данные чата неполные. Обнови страницу приложения.")
    if any(not isinstance(data[key], list) for key in _LIST_KEYS):
        raise ValueError("Сообщения, задачи и вложения чата должны быть списками.")
    if not isinstance(data["repository"], str):
        raise ValueError("Репозиторий чата должен быть строкой.")
    if any(data[key] is not None and not isinstance(data[key], dict)
           for key in ("plan", "last_plan_trace", "last_result")):
        raise ValueError("Некорректные результаты инструментов в чате.")


def _registry(state: MutableMapping[str, Any]) -> dict:
    chats = state.get("chats")
    if not isinstance(chats, dict) or not 1 <= len(chats) <= MAX_CHATS:
        raise ValueError("Сначала инициализируй чаты; в сессии доступно от 1 до 10 чатов.")
    for chat_id, chat in chats.items():
        if not isinstance(chat_id, str) or not isinstance(chat, dict) or chat.get("id") != chat_id:
            raise ValueError("Некорректный идентификатор чата.")
        if not isinstance(chat.get("title"), str) or not isinstance(chat.get("auto_title"), bool):
            raise ValueError("Некорректное название чата.")
        _validate_data(chat.get("data"))
    active_id = state.get("active_chat_id")
    if not isinstance(active_id, str) or active_id not in chats:
        raise ValueError("Активный чат не найден.")
    return chats


def _new_chat(chats: dict, data: dict | None = None) -> dict:
    chat_id = uuid4().hex
    while chat_id in chats:
        chat_id = uuid4().hex
    return {"id": chat_id, "title": "Новый чат", "data": _empty_data() if data is None else data,
            "auto_title": True}


def _activate(state: MutableMapping[str, Any], chat: dict) -> str:
    # Keep attachment strings and mutable per-chat objects by reference, never deep-copy.
    for key in DATA_KEYS:
        state[key] = chat["data"][key]
    state["active_chat_id"] = chat["id"]
    return chat["id"]


def initialize_chats(state: MutableMapping[str, Any]) -> str:
    """Migrate the pre-chat session once; preserve the live buffer on later reruns."""
    if "chats" not in state:
        data = _empty_data()
        data.update({key: state[key] for key in DATA_KEYS if key in state})
        _validate_data(data)
        first_message = next((item["text"] for item in data["messages"]
                              if isinstance(item, dict) and item.get("role") == "user"
                              and isinstance(item.get("text"), str) and item["text"].strip()), None)
        if len(data["messages"]) > MAX_MESSAGES:
            data["messages"] = data["messages"][-MAX_MESSAGES:]
        chat = _new_chat({}, data)
        state["chats"] = {chat["id"]: chat}
        _activate(state, chat)
        if first_message is not None:
            auto_title_chat(state, first_message)
    else:
        chats = _registry(state)
        chat = chats[state["active_chat_id"]]
        # A widget key may be absent when its page was not rendered. Restore only
        # missing keys; a reassigned live value must not be replaced by saved data.
        for key in DATA_KEYS:
            if key not in state:
                state[key] = chat["data"][key]
    state.setdefault("deleted_chat", None)
    return state["active_chat_id"]


def save_active_chat(state: MutableMapping[str, Any]) -> None:
    chats = _registry(state)
    data = {key: state.get(key, chats[state["active_chat_id"]]["data"][key]) for key in DATA_KEYS}
    _validate_data(data)
    if len(data["messages"]) > MAX_MESSAGES:
        data["messages"] = data["messages"][-MAX_MESSAGES:]
        state["messages"] = data["messages"]
    chats[state["active_chat_id"]]["data"] = data


def select_chat(state: MutableMapping[str, Any], chat_id: str) -> str:
    chats = _registry(state)
    # Validate before saving so a stale UI selection cannot change any live data.
    if not isinstance(chat_id, str) or chat_id not in chats:
        raise ValueError("Выбранный чат не найден.")
    save_active_chat(state)
    return _activate(state, chats[chat_id])


def create_chat(state: MutableMapping[str, Any]) -> str:
    chats = _registry(state)
    if len(chats) >= MAX_CHATS:
        raise ValueError("В сессии можно создать не более 10 чатов. Удали ненужный чат.")
    save_active_chat(state)
    chat = _new_chat(chats)
    chats[chat["id"]] = chat
    return _activate(state, chat)


def rename_chat(state: MutableMapping[str, Any], title: str) -> None:
    chats = _registry(state)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Введи название чата.")
    title = title.strip()
    if len(title) > 60:
        raise ValueError("Название чата должно содержать не более 60 символов.")
    chat = chats[state["active_chat_id"]]
    chat["title"], chat["auto_title"] = title, False


def delete_chat(state: MutableMapping[str, Any]) -> str:
    chats = _registry(state)
    save_active_chat(state)
    state["deleted_chat"] = chats.pop(state["active_chat_id"])
    if not chats:
        chat = _new_chat(chats)
        chats[chat["id"]] = chat
    else:
        chat = chats[next(reversed(chats))]
    return _activate(state, chat)


def restore_deleted_chat(state: MutableMapping[str, Any]) -> str:
    chats = _registry(state)
    deleted = state.get("deleted_chat")
    if not isinstance(deleted, dict) or not isinstance(deleted.get("id"), str):
        raise ValueError("Нет удалённого чата для восстановления.")
    if deleted["id"] in chats:
        raise ValueError("Этот чат уже восстановлен.")
    if len(chats) >= MAX_CHATS:
        raise ValueError("Для восстановления освободи место: в сессии доступно не более 10 чатов.")
    _validate_data(deleted.get("data"))
    if not isinstance(deleted.get("title"), str) or not isinstance(deleted.get("auto_title"), bool):
        raise ValueError("Данные удалённого чата некорректны.")
    save_active_chat(state)
    chats[deleted["id"]] = deleted
    state["deleted_chat"] = None
    return _activate(state, deleted)


def clear_chat(state: MutableMapping[str, Any]) -> None:
    save_active_chat(state)
    state["messages"] = []
    state["chats"][state["active_chat_id"]]["data"]["messages"] = state["messages"]


def auto_title_chat(state: MutableMapping[str, Any], message: str) -> None:
    chats = _registry(state)
    chat = chats[state["active_chat_id"]]
    if not chat["auto_title"]:
        return
    if not isinstance(message, str):
        raise ValueError("Сообщение для названия чата должно быть текстом.")
    title = " ".join(message.split())[:45].rstrip()
    if title:
        chat["title"], chat["auto_title"] = title, False
