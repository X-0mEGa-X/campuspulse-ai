from copy import deepcopy

import pytest

from campuspulse.chats import (DATA_KEYS, MAX_CHATS, MAX_MESSAGES, auto_title_chat,
                              clear_chat, create_chat, delete_chat, initialize_chats,
                              rename_chat, restore_deleted_chat, save_active_chat, select_chat)


def test_existing_session_migrates_once_without_copying_attachments():
    class NoDeepCopy(dict):
        def __deepcopy__(self, memo):
            raise AssertionError("Large attachment data must never be deep-copied")

    images = [NoDeepCopy(name="photo.png", data="base64-data", mime_type="image/png")]
    messages = [{"role": "user", "text": "Existing conversation"}]
    state = {"messages": messages, "images": images, "repository": "org/course"}
    first = initialize_chats(state)
    assert state["chats"][first]["data"]["messages"] is messages
    assert state["chats"][first]["data"]["images"] is images
    assert state["repository"] == "org/course"
    assert state["chats"][first]["title"] == "Existing conversation"
    assert state["chats"][first]["auto_title"] is False
    replacement = [{"role": "user", "text": "Live reassignment"}]
    state["messages"] = replacement
    assert initialize_chats(state) == first
    assert state["messages"] is replacement
    save_active_chat(state)
    assert state["chats"][first]["data"]["messages"] is replacement
    assert state["chats"][first]["data"]["images"][0] is images[0]


def test_switching_isolates_every_chat_data_field():
    state = {}
    first = initialize_chats(state)
    first_values = {"messages": [{"role": "user", "text": "First"}],
                    "tasks": [{"title": "First task"}],
                    "documents": [{"name": "one.txt", "text": "First notes"}],
                    "images": [{"name": "one.png", "data": "one"}],
                    "plan": {"sessions": [{"title": "First task"}]},
                    "last_plan_trace": {"ok": True, "name": "first plan"},
                    "last_result": {"ok": True, "name": "first tool"},
                    "repository": "org/first"}
    state.update(first_values)
    second = create_chat(state)
    assert first != second
    assert all(state[key] == [] for key in ("messages", "tasks", "documents", "images"))
    assert state["plan"] is state["last_plan_trace"] is state["last_result"] is None
    assert state["repository"] == ""
    state["messages"].append({"role": "user", "text": "Second"})
    state["tasks"].append({"title": "Second task"})
    state["repository"] = "org/second"
    select_chat(state, first)
    for key in DATA_KEYS:
        assert state[key] is first_values[key]
    select_chat(state, second)
    assert state["messages"][0]["text"] == "Second"
    assert state["tasks"][0]["title"] == "Second task"
    assert state["repository"] == "org/second"
    assert state["documents"] == state["images"] == []


def test_unknown_selection_has_no_side_effects_even_with_long_unsaved_history():
    state = {}
    active = initialize_chats(state)
    original_saved = state["chats"][active]["data"]
    history = [{"role": "user", "text": str(i)} for i in range(MAX_MESSAGES + 2)]
    state["messages"] = history
    with pytest.raises(ValueError, match="не найден"):
        select_chat(state, "missing")
    assert state["active_chat_id"] == active
    assert state["messages"] is history
    assert state["chats"][active]["data"] is original_saved


def test_rename_and_auto_title_do_not_overwrite_manual_names():
    state = {}
    active = initialize_chats(state)
    auto_title_chat(state, "  First\n question  " + "x" * 80)
    assert len(state["chats"][active]["title"]) == 45
    assert state["chats"][active]["title"].startswith("First question ")
    original = state["chats"][active]["title"]
    auto_title_chat(state, "Second question")
    assert state["chats"][active]["title"] == original
    rename_chat(state, "  Exam preparation  ")
    assert state["chats"][active]["title"] == "Exam preparation"
    auto_title_chat(state, "Another question")
    assert state["chats"][active]["title"] == "Exam preparation"
    for invalid in ("  ", "x" * 61):
        with pytest.raises(ValueError):
            rename_chat(state, invalid)
    assert state["chats"][active]["title"] == "Exam preparation"


def test_delete_last_chat_preserves_one_empty_chat_and_supports_undo():
    state = {}
    first = initialize_chats(state)
    state["tasks"].append({"title": "Keep on undo"})
    state["messages"].append({"role": "user", "text": "Keep conversation"})
    original_messages = state["messages"]
    blank = delete_chat(state)
    assert blank != first
    assert len(state["chats"]) == 1
    assert state["messages"] == state["tasks"] == []
    assert state["deleted_chat"]["data"]["messages"] is original_messages
    assert restore_deleted_chat(state) == first
    assert len(state["chats"]) == 2
    assert state["messages"] is original_messages
    assert state["tasks"][0]["title"] == "Keep on undo"
    assert state["deleted_chat"] is None
    with pytest.raises(ValueError, match="Нет удалённого"):
        restore_deleted_chat(state)


def test_delete_only_active_chat_and_keep_only_latest_undo():
    state = {}
    first = initialize_chats(state)
    second = create_chat(state)
    third = create_chat(state)
    select_chat(state, second)
    delete_chat(state)
    assert set(state["chats"]) == {first, third}
    assert state["deleted_chat"]["id"] == second
    delete_chat(state)
    assert state["deleted_chat"]["id"] == third
    assert set(state["chats"]) == {first}


def test_create_and_restore_limits_are_atomic():
    state = {}
    initialize_chats(state)
    deleted_id = state["active_chat_id"]
    delete_chat(state)
    for _ in range(MAX_CHATS - 1):
        create_chat(state)
    before = deepcopy(state)
    with pytest.raises(ValueError, match="не более 10"):
        create_chat(state)
    assert state == before
    with pytest.raises(ValueError, match="не более 10"):
        restore_deleted_chat(state)
    assert state == before
    assert state["deleted_chat"]["id"] == deleted_id


def test_clear_only_removes_messages_not_tasks_materials_plan_or_tool_result():
    state = {}
    active = initialize_chats(state)
    state["messages"] = [{"role": "user", "text": "Clear me"}]
    state["tasks"] = [{"title": "Keep"}]
    state["documents"] = [{"name": "keep.txt", "text": "Keep"}]
    state["images"] = [{"name": "keep.png", "data": "Keep"}]
    state["plan"] = {"sessions": []}
    state["last_result"] = {"output": {"keep": True}}
    state["repository"] = "org/keep"
    kept = {key: state[key] for key in DATA_KEYS if key != "messages"}
    clear_chat(state)
    assert state["messages"] == []
    assert state["chats"][active]["data"]["messages"] is state["messages"]
    for key, value in kept.items():
        assert state[key] is value


def test_message_limit_keeps_latest_complete_pairs_and_references():
    state = {}
    initialize_chats(state)
    history = [{"role": "user" if i % 2 == 0 else "assistant", "text": str(i)}
               for i in range(MAX_MESSAGES + 4)]
    state["messages"] = history
    save_active_chat(state)
    assert len(state["messages"]) == MAX_MESSAGES
    assert state["messages"][0] is history[4]
    assert state["messages"][-1] is history[-1]
    assert state["chats"][state["active_chat_id"]]["data"]["messages"] is state["messages"]


def test_rerun_restores_only_missing_flat_keys():
    state = {}
    initialize_chats(state)
    state["repository"] = "org/saved"
    save_active_chat(state)
    del state["repository"]
    state["tasks"] = [{"title": "Live task"}]
    live_tasks = state["tasks"]
    initialize_chats(state)
    assert state["repository"] == "org/saved"
    assert state["tasks"] is live_tasks


def test_separate_user_sessions_never_share_lists_or_chat_registry():
    first, second = {}, {}
    initialize_chats(first)
    initialize_chats(second)
    first["tasks"].append({"title": "Private to first session"})
    first["images"].append({"name": "private.png", "data": "private"})
    assert second["tasks"] == second["images"] == []
    assert first["chats"] is not second["chats"]
    assert first["active_chat_id"] != second["active_chat_id"]
