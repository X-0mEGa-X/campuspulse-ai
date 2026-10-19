from streamlit.testing.v1 import AppTest
from pathlib import Path
from io import BytesIO

from PIL import Image

from campuspulse.agent import CampusPulseAgent

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
