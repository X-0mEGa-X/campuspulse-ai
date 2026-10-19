"""Protocol regression with a controlled model and the real subprocess MCP server."""
from types import SimpleNamespace

from google.genai import types

from campuspulse import agent


def test_model_tools_round_trip_preserves_signatures_and_hides_thoughts(monkeypatch):
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
