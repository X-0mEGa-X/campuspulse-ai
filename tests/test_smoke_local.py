"""Controlled smoke-script checks; these fixtures never call Gemini or GitHub."""
import json
import sys

import pytest

from scripts import smoke_local


def controlled_result():
    return {"ok": True, "model": "controlled-test-model", "answer": "Controlled test result",
            "events": [
                {"kind": "tool", "name": "get_current_time", "ok": True, "output": {"now": "2026-10-20T12:00:00Z"}},
                {"kind": "tool", "name": "read_github_readme", "ok": True,
                 "output": {"live": True, "repository": "python/cpython", "text": "Controlled README fixture"}},
                {"kind": "tool", "name": "search_study_materials", "ok": True,
                 "output": {"matches": [{"source": "smoke-test-notes.txt", "excerpt": "MCP test fixture"}]}},
                {"kind": "tool", "name": "plan_study_week", "ok": True, "output": {}}],
            "plan": {"scheduled_minutes": 120, "unscheduled": []}}


def run_controlled(monkeypatch, tmp_path, result):
    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def query(self, *args):
            return result

    monkeypatch.setattr(smoke_local, "CampusPulseAgent", FakeAgent)
    monkeypatch.setattr(smoke_local, "load_dotenv", lambda *args: None)
    monkeypatch.setattr(smoke_local, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["smoke_local.py", "--output", "requested/run.json"])
    return smoke_local.main()


@pytest.mark.parametrize("missing_evidence", ["readme", "material"])
def test_smoke_rejects_successful_tools_without_retrieved_evidence(monkeypatch, tmp_path, missing_evidence):
    result = controlled_result()
    if missing_evidence == "readme":
        result["events"][1]["output"]["text"] = ""
    else:
        result["events"][2]["output"]["matches"] = []
    assert run_controlled(monkeypatch, tmp_path, result) == 1
    saved = json.loads((tmp_path / "requested/run.json").read_text(encoding="utf-8"))
    assert saved["verification"]["passed"] is False
    assert saved["verification"]["missing_successful_tools"] == []


def test_smoke_saves_only_the_requested_log_path(monkeypatch, tmp_path):
    assert run_controlled(monkeypatch, tmp_path, controlled_result()) == 0
    saved = json.loads((tmp_path / "requested/run.json").read_text(encoding="utf-8"))
    assert saved["verification"]["passed"] is True
    assert not (tmp_path / "docs").exists()
