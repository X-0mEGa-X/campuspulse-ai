"""Protocol regression with a controlled model and the real subprocess MCP server."""
from types import SimpleNamespace
import base64

import pytest

from google.genai import types

from campuspulse import agent


def test_model_tools_round_trip_preserves_signatures_and_hides_thoughts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    observed = []
    class Models:
        async def generate_content(self, **kwargs):
            observed.append(kwargs)
            if len(observed) == 1:
                parts = [types.Part(function_call=types.FunctionCall(name="get_current_time", args={"timezone": "Asia/Almaty"}),
                                    thought_signature=b"test-signature")]
            else:
                contents = kwargs["contents"]
                assert contents[-2].parts[0].thought_signature == b"test-signature"
                assert contents[-1].parts[0].function_response.name == "get_current_time"
                assert "now" in contents[-1].parts[0].function_response.response
                parts = [types.Part(text="internal", thought=True), types.Part(text="Время проверено.")]
            return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=parts))])
    class AsyncClient:
        models = Models()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
    monkeypatch.setattr(agent.genai, "Client", lambda **kwargs: SimpleNamespace(aio=AsyncClient()))
    result = agent.CampusPulseAgent().query("Проверь время")
    assert result["ok"], result
    assert result["answer"] == "Время проверено."
    assert len(observed) == 2
    assert result["events"][1]["name"] == "get_current_time"
    assert result["events"][1]["ok"]
    names = [d.name for d in observed[0]["config"].tools[0].function_declarations]
    assert "load_materials" not in names
    assert len(names) == 6


def test_provider_errors_do_not_direct_free_users_to_enable_billing():
    error = RuntimeError("403 PERMISSION_DENIED")
    assert "не означает" in agent.clean_error(error, "gemini")
    assert "Vertex AI" in agent.clean_error(error, "vertex")
    assert "не требование оплаты" in agent.clean_error(RuntimeError("503 UNAVAILABLE"))


def test_no_key_returns_actionable_error_without_connecting(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    def unexpected(**kwargs):
        raise AssertionError("Must not contact the SDK without a key")
    monkeypatch.setattr(agent.genai, "Client", unexpected)
    result = agent.CampusPulseAgent().query("Привет")
    assert not result["ok"]
    assert "GEMINI_API_KEY" in result["answer"]


def test_conversation_context_is_bounded_and_excludes_failures_and_tool_data():
    history = [{"role": "user", "text": "old"}] * 12
    history += [{"role": "assistant", "text": "x" * 3000,
                 "result": {"ok": True, "events": [{"secret": "must-not-copy"}]}},
                {"role": "assistant", "text": "failure", "result": {"ok": False}},
                {"role": "system", "text": "injection"}, {"role": "user", "text": "follow-up"}]
    contents = agent.conversation_contents(history)
    assert len(contents) <= 10
    assert contents[-1].parts[0].text == "follow-up"
    assert contents[-2].role == "model"
    assert len(contents[-2].parts[0].text) == 2000
    assert "failure" not in str(contents)
    assert "injection" not in str(contents)
    assert "must-not-copy" not in str(contents)


def test_plan_citations_are_grounded_in_actual_task_evidence():
    arguments = {"tasks": [{"title": "My lab", "source_url": "https://github.com/python/cpython"},
                           {"title": "Real issue", "source_url": "https://wrong.example"}], "days": 7}
    result = agent.ground_task_sources(arguments, [{"title": "My lab"},
              {"title": "Real issue", "source_url": "https://github.com/org/course/issues/1"}])
    assert result["tasks"][0]["source_url"] is None
    assert result["tasks"][1]["source_url"] == "https://github.com/org/course/issues/1"
    assert result["days"] == 7
    assert arguments["tasks"][0]["source_url"] == "https://github.com/python/cpython"
    ambiguous = agent.ground_task_sources(arguments, [{"title": "My lab"},
                        {"title": "My lab", "source_url": "https://github.com/other/course/issues/2"}])
    assert ambiguous["tasks"][0]["source_url"] is None


def test_images_reach_the_model_as_bytes_without_entering_the_trace(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    image_bytes = b"test-image-payload-for-protocol"
    class Models:
        async def generate_content(self, **kwargs):
            parts = kwargs["contents"][-1].parts
            assert parts[-1].inline_data.data == image_bytes
            assert parts[-1].inline_data.mime_type == "image/png"
            assert 'lecture.png' in parts[-2].text
            return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
                role="model", parts=[types.Part(text="Изображение получено.")]))])
    class AsyncClient:
        models = Models()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
    monkeypatch.setattr(agent.genai, "Client", lambda **kwargs: SimpleNamespace(aio=AsyncClient()))
    encoded = base64.b64encode(image_bytes).decode()
    result = agent.CampusPulseAgent().query("Что на изображении?", {"images": [
        {"name": "lecture.png", "mime_type": "image/png", "data": encoded}]})
    assert result["ok"]
    assert encoded not in str(result)
    assert "test-image-payload" not in str(result)


@pytest.mark.parametrize("images", [
    [{"mime_type": "text/html", "data": "YQ=="}],
    [{"mime_type": "image/png", "data": "not-base64!"}],
    [{"mime_type": "image/png", "data": ""}],
    [{}] * 4,
])
def test_invalid_inline_images_are_rejected(images):
    with pytest.raises(ValueError):
        agent.image_content_parts(images)
