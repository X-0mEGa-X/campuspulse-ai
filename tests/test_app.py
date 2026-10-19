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
