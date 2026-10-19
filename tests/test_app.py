from streamlit.testing.v1 import AppTest
from pathlib import Path

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
