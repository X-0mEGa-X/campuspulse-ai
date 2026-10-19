from streamlit.testing.v1 import AppTest
from pathlib import Path
from io import BytesIO
from copy import deepcopy
import base64

from PIL import Image
import pytest

from campuspulse.agent import CampusPulseAgent
from campuspulse.chats import DATA_KEYS

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_task_form_and_mcp_schedule():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.radio(key="section").set_value("Учебный план").run()
    assert not at.exception
    at.text_input[0].set_value("Лабораторная работа")
    at.form_submit_button[0].click().run()
    assert len(at.session_state["tasks"]) == 1
    next(b for b in at.button if b.label == "Составить план через MCP").click().run(timeout=30)
    assert not at.exception
    assert at.session_state["plan"]["scheduled_minutes"] == 90


def test_all_sections_render():
    at = AppTest.from_file(APP, default_timeout=20).run()
    for name in ["Материалы", "Подключение", "Агент"]:
        at.radio(key="section").set_value(name).run()
        assert not at.exception


def test_free_mode_is_default_and_cloud_requires_explicit_selection():
    at = AppTest.from_file(APP, default_timeout=20).run()
    backend = at.selectbox(key="backend")
    assert backend.value in {"Gemini API", "Только инструменты"}
    assert "Vertex AI" not in backend.options
    next(t for t in at.toggle if t.label == "Показать режимы Google Cloud").set_value(True).run()
    at.selectbox(key="backend").set_value("Agent Engine").run()
    assert not at.exception
    assert at.chat_input[0].disabled
    assert any("ещё не развёрнут" in warning.value for warning in at.warning)


def test_materials_upload_and_text_chat_forward_documents_and_photos(monkeypatch):
    observed = []
    def query(self, message, context):
        observed.append(context)
        return {"ok": True, "answer": "Вложения получены.", "events": []}
    monkeypatch.setattr(CampusPulseAgent, "query", query)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    photo = BytesIO()
    Image.new("RGB", (16, 16), "white").save(photo, format="PNG")
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.radio(key="section").set_value("Материалы").run()
    at.file_uploader[0].set_value([
        ("notes.txt", "Конспект: алгоритм Дейкстры ищет кратчайшие пути.".encode(), "text/plain"),
        ("photo.png", photo.getvalue(), "image/png")]).run()
    next(button for button in at.button if button.label == "Использовать выбранные материалы").click().run()
    assert not at.exception
    assert at.session_state["documents"][0]["name"] == "notes.txt"
    assert at.session_state["images"][0]["mime_type"] == "image/png"
    at.radio(key="section").set_value("Агент").run()
    at.chat_input[0].set_value("Что в приложенных материалах?").run()
    assert not at.exception
    assert len(observed) == 1
    assert observed[0]["documents"][0]["name"] == "notes.txt"
    assert observed[0]["images"][0]["name"] == "photo.png"
    next(button for button in at.button if button.label == "Убрать все вложения").click().run()
    assert at.session_state["documents"] == []
    assert at.session_state["images"] == []


def test_invalid_upload_does_not_replace_existing_materials():
    at = AppTest.from_file(APP, default_timeout=30).run()
    existing = [{"name": "old.txt", "text": "Existing lecture materials with sufficient text.", "truncated": False}]
    at.session_state["documents"] = existing
    at.radio(key="section").set_value("Материалы").run()
    at.file_uploader[0].set_value(("broken.png", b"not an image", "image/png")).run()
    next(button for button in at.button if button.label == "Использовать выбранные материалы").click().run()
    assert not at.exception
    assert at.error
    assert at.session_state["documents"] == existing
    assert at.session_state["images"] == []


@pytest.fixture
def fake_agent(monkeypatch):
    """Record the actual UI-to-agent boundary without making model requests."""
    calls = []

    def query(self, message, context):
        calls.append({"message": message, "context": deepcopy(context)})
        return {"ok": True, "answer": f"Ответ на: {message}", "events": []}

    monkeypatch.setattr(CampusPulseAgent, "query", query)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    return calls


def chat_context(label):
    photo = BytesIO()
    Image.new("RGB", (16, 16), "white").save(photo, format="PNG")
    plan = {
        "timezone": "Asia/Almaty", "scheduled_minutes": 30, "unscheduled": [],
        "sessions": [{"title": f"Задача {label}", "minutes": 30,
                      "start": "2030-01-01T18:00:00+05:00", "end": "2030-01-01T18:30:00+05:00",
                      "due_at": None, "estimated_by_default": False, "source_url": None}],
    }
    trace = {"ok": True, "answer": f"План {label}", "events": []}
    return {
        "messages": [{"role": "user", "text": f"История {label}"},
                     {"role": "assistant", "text": f"Предыдущий ответ {label}"}],
        "documents": [{"name": f"{label}.txt", "text": f"Конспект курса {label} с учебными материалами.",
                       "truncated": False}],
        "images": [{"name": f"{label}.png", "mime_type": "image/png",
                    "data": base64.b64encode(photo.getvalue()).decode()}],
        "tasks": [{"title": f"Задача {label}", "due_at": None,
                   "estimated_minutes": 30, "source_url": None}],
        "plan": plan, "repository": f"https://github.com/example/course-{label.lower()}",
        "last_result": deepcopy(trace), "last_plan_trace": deepcopy(trace),
    }


def seed_chat(at, data):
    for key, value in data.items():
        at.session_state[key] = deepcopy(value)


def current_context(at):
    return {key: deepcopy(at.session_state[key]) for key in DATA_KEYS}


def switch_chat(at, chat_id):
    at.sidebar.selectbox(key=at.session_state["chat_selector_key"]).set_value(chat_id).run()
    assert not at.exception
    assert at.session_state["active_chat_id"] == chat_id


def test_existing_session_migrates_once_and_chat_controls_stay_in_sidebar(fake_agent):
    at = AppTest.from_file(APP, default_timeout=30)
    original = chat_context("Legacy")
    seed_chat(at, original)
    at.run()
    assert not at.exception
    chat_id = at.session_state["active_chat_id"]
    assert list(at.session_state["chats"]) == [chat_id]
    assert current_context(at) == original
    at.run()
    assert not at.exception
    assert list(at.session_state["chats"]) == [chat_id]
    assert current_context(at) == original
    assert at.sidebar.button(key="new_chat").label == "Новый чат"
    assert at.sidebar.button(key="clear_chat").label == "Очистить чат"
    assert at.sidebar.menu_button(key="chat_actions").options == ["Переименовать", "Удалить чат"]
    assert not any("Очистить" in button.label for button in at.main.button)
    assert not at.main.dataframe
    assert not at.main.metric
    assert not any(".ics" in button.label for button in at.main.download_button)
    at.radio(key="section").set_value("Учебный план").run()
    assert not at.exception
    assert at.main.metric[0].value == "30 мин"
    assert any(".ics" in button.label for button in at.main.download_button)
    assert not fake_agent


def test_switching_chats_isolates_history_materials_tasks_plan_and_repository(fake_agent):
    at = AppTest.from_file(APP, default_timeout=30)
    first = chat_context("A")
    seed_chat(at, first)
    at.run()
    assert not at.exception
    first_id = at.session_state["active_chat_id"]
    at.chat_input[0].set_value("Продолжи тему A").run()
    assert not at.exception
    assert len(fake_agent) == 1
    assert fake_agent[0]["context"]["history"] == first["messages"]
    first_saved = current_context(at)

    at.sidebar.button(key="new_chat").click().run()
    assert not at.exception
    second_id = at.session_state["active_chat_id"]
    assert second_id != first_id
    for key in ("messages", "documents", "images", "tasks"):
        assert at.session_state[key] == []
    assert at.session_state["repository"] == ""
    assert at.session_state["plan"] is None

    second = chat_context("B")
    seed_chat(at, {key: value for key, value in second.items() if key != "repository"})
    at.text_input(key="repository").set_value(second["repository"]).run()
    assert not at.exception
    at.chat_input[0].set_value("Продолжи тему B").run()
    assert not at.exception
    assert len(fake_agent) == 2
    for key in ("documents", "images", "tasks", "repository"):
        assert fake_agent[1]["context"][key] == second[key]
    assert fake_agent[1]["context"]["history"] == second["messages"]
    second_saved = current_context(at)

    switch_chat(at, first_id)
    assert current_context(at) == first_saved
    assert at.text_input(key="repository").value == first["repository"]
    at.chat_input[0].set_value("Ещё один вопрос A").run()
    assert not at.exception
    assert len(fake_agent) == 3  # The post-answer rerun must not resend a request.
    for key in ("documents", "images", "tasks", "repository"):
        assert fake_agent[2]["context"][key] == first[key]
    assert fake_agent[2]["context"]["history"] == first_saved["messages"]
    switch_chat(at, second_id)
    assert current_context(at) == second_saved


def test_pending_upload_and_chat_input_widgets_do_not_leak_to_new_chat(fake_agent):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    first_id = at.session_state["active_chat_id"]
    first_input_key = at.chat_input[0].key
    first_input_id = at.chat_input[0].id
    at.radio(key="section").set_value("Материалы").run()
    first_upload_key = at.file_uploader[0].key
    first_upload_id = at.file_uploader[0].id
    at.file_uploader[0].set_value(("private-a.txt", b"Private course A lecture notes.", "text/plain")).run()
    assert not at.exception
    assert at.file_uploader[0].value

    # Leave a selected but unsubmitted file in A, then open a genuinely blank B.
    at.sidebar.button(key="new_chat").click().run()
    assert not at.exception
    assert at.session_state["active_chat_id"] != first_id
    assert at.chat_input[0].key != first_input_key
    assert at.chat_input[0].id != first_input_id
    at.radio(key="section").set_value("Материалы").run()
    assert not at.exception
    assert at.file_uploader[0].key != first_upload_key
    assert at.file_uploader[0].id != first_upload_id
    assert not at.file_uploader[0].value
    assert next(button for button in at.button if button.label == "Использовать выбранные материалы").disabled
    at.radio(key="section").set_value("Агент").run()
    at.chat_input[0].set_value("Первый вопрос B").run()
    assert not at.exception
    assert len(fake_agent) == 1
    assert fake_agent[0]["context"]["documents"] == []
    assert fake_agent[0]["context"]["images"] == []
    assert fake_agent[0]["context"]["history"] == []


def test_clear_chat_removes_only_current_history_and_preserves_other_chat(fake_agent):
    at = AppTest.from_file(APP, default_timeout=30)
    first = chat_context("A")
    seed_chat(at, first)
    at.run()
    first_id = at.session_state["active_chat_id"]
    at.sidebar.button(key="new_chat").click().run()
    second = chat_context("B")
    seed_chat(at, {key: value for key, value in second.items() if key != "repository"})
    at.text_input(key="repository").set_value(second["repository"]).run()
    assert not at.exception
    second_id = at.session_state["active_chat_id"]
    at.sidebar.button(key="clear_chat").click().run()
    assert not at.exception
    assert at.session_state["active_chat_id"] == second_id
    assert at.session_state["messages"] == []
    for key in DATA_KEYS:
        if key != "messages":
            assert at.session_state[key] == second[key]
    assert at.sidebar.button(key="clear_chat").disabled
    switch_chat(at, first_id)
    assert current_context(at) == first
    switch_chat(at, second_id)
    assert at.session_state["messages"] == []
    at.chat_input[0].set_value("Начнём новую тему B").run()
    assert not at.exception
    assert len(fake_agent) == 1
    assert fake_agent[0]["context"]["history"] == []
    assert fake_agent[0]["context"]["documents"] == second["documents"]


def test_delete_and_restore_chat_keep_its_full_context(fake_agent):
    at = AppTest.from_file(APP, default_timeout=30)
    first = chat_context("A")
    seed_chat(at, first)
    at.run()
    first_id = at.session_state["active_chat_id"]
    at.sidebar.button(key="new_chat").click().run()
    second_id = at.session_state["active_chat_id"]
    at.chat_input[0].set_value("Разговор B").run()
    assert not at.exception
    second_saved = current_context(at)
    at.sidebar.menu_button(key="chat_actions").click("Удалить чат").run()
    assert not at.exception
    assert second_id not in at.session_state["chats"]
    assert at.session_state["active_chat_id"] == first_id
    assert current_context(at) == first
    at.sidebar.button(key="restore_chat").click().run()
    assert not at.exception
    assert at.session_state["active_chat_id"] == second_id
    assert current_context(at) == second_saved
    assert len(at.session_state["chats"]) == 2
    assert not any(button.key == "restore_chat" for button in at.sidebar.button)
    assert len(fake_agent) == 1


def test_rename_dialog_changes_title_without_resetting_chat(fake_agent):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value("Разобрать лабораторную").run()
    assert not at.exception
    chat_id = at.session_state["active_chat_id"]
    saved = current_context(at)
    old_selector_key = at.session_state["chat_selector_key"]
    at.sidebar.menu_button(key="chat_actions").click("Переименовать").run()
    assert not at.exception
    next(field for field in at.text_input if field.label == "Новое название").set_value("Моя лабораторная")
    next(button for button in at.form_submit_button if button.label == "Сохранить название").click().run()
    assert not at.exception
    assert at.session_state["active_chat_id"] == chat_id
    assert current_context(at) == saved
    assert at.session_state["chats"][chat_id]["title"] == "Моя лабораторная"
    # Renaming invalidates the old label-to-ID transport state in the browser.
    assert at.session_state["chat_selector_key"] != old_selector_key
    selector = at.sidebar.selectbox(key=at.session_state["chat_selector_key"])
    assert selector.value == chat_id
    assert selector.options == ["1. Моя лабораторная"]
    at.radio(key="section").set_value("Материалы").run()
    assert not at.exception
    assert at.session_state["active_chat_id"] == chat_id
    at.radio(key="section").set_value("Агент").run()
    assert not at.exception
    at.chat_input[0].set_value("Продолжим").run()
    assert not at.exception
    assert at.session_state["chats"][chat_id]["title"] == "Моя лабораторная"
    assert len(fake_agent) == 2


def test_two_chats_with_same_manual_title_remain_independently_selectable(fake_agent):
    at = AppTest.from_file(APP, default_timeout=30).run()

    def rename_to_same_title():
        at.sidebar.menu_button(key="chat_actions").click("Переименовать").run()
        assert not at.exception
        next(field for field in at.text_input if field.label == "Новое название").set_value("Лабораторная")
        next(button for button in at.form_submit_button if button.label == "Сохранить название").click().run()
        assert not at.exception

    first_id = at.session_state["active_chat_id"]
    at.chat_input[0].set_value("Контекст первого курса").run()
    assert not at.exception
    rename_to_same_title()
    first_saved = current_context(at)
    at.sidebar.button(key="new_chat").click().run()
    assert not at.exception
    second_id = at.session_state["active_chat_id"]
    at.chat_input[0].set_value("Контекст второго курса").run()
    assert not at.exception
    rename_to_same_title()
    second_saved = current_context(at)

    selector = at.sidebar.selectbox(key=at.session_state["chat_selector_key"])
    assert selector.options == ["1. Лабораторная", "2. Лабораторная"]
    assert selector.value == second_id
    switch_chat(at, first_id)
    assert current_context(at) == first_saved
    switch_chat(at, second_id)
    assert current_context(at) == second_saved
    at.radio(key="section").set_value("Материалы").run()
    assert not at.exception
    switch_chat(at, first_id)
    assert current_context(at) == first_saved
    assert len(fake_agent) == 2
