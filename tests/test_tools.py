from datetime import datetime
from zoneinfo import ZoneInfo
import asyncio

import pytest

from campuspulse import tools
from campuspulse.agent import run_tool
from campuspulse.calendar_export import to_ics


@pytest.fixture
def clock(monkeypatch):
    instant = datetime(2026, 10, 19, 12, tzinfo=ZoneInfo("Asia/Almaty"))
    monkeypatch.setattr(tools, "now_in", lambda timezone="Asia/Almaty": instant.astimezone(ZoneInfo(timezone)))
    return instant


def test_deadline_uses_timezone_and_end_of_day(clock):
    result = tools.deadline_status("2026-10-19", "Asia/Almaty")
    assert result["minutes_remaining"] == 719
    assert result["due_at"].endswith("23:59:00+05:00")
    assert tools.deadline_status("2026-10-19T07:00:00Z")["minutes_remaining"] == 0


def test_overdue_tasks_never_appear_in_future_schedule(clock):
    result = tools.build_plan([{"title": "Late", "due_at": "2026-10-18", "estimated_minutes": 30}])
    assert result["sessions"] == []
    assert result["unscheduled"][0]["reason"] == "deadline_passed"


def test_schedule_capacity_deadlines_and_order(clock):
    result = tools.build_plan([
        {"title": "Later", "due_at": "2026-10-21", "estimated_minutes": 90},
        {"title": "Urgent", "due_at": "2026-10-19T19:00:00+05:00", "estimated_minutes": 90},
    ], daily_minutes=60, days=2)
    assert result["sessions"][0]["title"] == "Urgent"
    assert result["scheduled_minutes"] == 120
    assert sum(s["minutes"] for s in result["unscheduled"]) == 60
    for s in result["sessions"]:
        assert datetime.fromisoformat(s["end"]) <= datetime.fromisoformat(s["due_at"])
        assert datetime.fromisoformat(s["start"]) >= clock
    for first, second in zip(result["sessions"], result["sessions"][1:]):
        assert first["end"] <= second["start"]


def test_unknown_deadline_and_default_estimate_are_visible(clock):
    result = tools.build_plan([{"title": "Unknown"}])
    assert result["requested_minutes"] == 60
    assert result["sessions"][0]["due_at"] is None
    assert result["sessions"][0]["estimated_by_default"] is True


def test_midnight_window_never_spills_to_next_day(clock):
    result = tools.build_plan([{"title": "Long", "estimated_minutes": 240}], daily_minutes=240, days=1, start_hour=23)
    assert result["scheduled_minutes"] == 60
    assert result["unscheduled"][0]["minutes"] == 180


@pytest.mark.parametrize("repo", ["https://evil.test/x/y", "../../secrets", "a/b/issues", "a/b?token=x", "https://github.com.evil.test/a/b"])
def test_arbitrary_url_rejected(repo):
    with pytest.raises(ValueError):
        tools.normalize_repository(repo)


def test_github_does_not_fabricate_deadlines_and_filters_pr(monkeypatch):
    base = {"number": 1, "title": "Task", "body": None, "html_url": "https://github.com/a/b/issues/1", "updated_at": "2026-10-19", "labels": []}
    monkeypatch.setattr(tools, "github_get", lambda *args: [dict(base, pull_request={}), base,
        dict(base, number=2, body="Due: 2026-10-21\nEstimate: 2h")])
    result = tools.github_issues("a/b")
    assert len(result["issues"]) == 2
    assert result["issues"][0]["due_at"] is None
    assert result["issues"][1]["estimated_minutes"] == 120


def test_ics_uses_utc_and_escapes_text(clock):
    plan = tools.build_plan([{"title": "Тест; с запятой, и\nновой строкой"}])
    text = to_ics(plan).decode("utf-8")
    assert "DTSTART:20261019T130000Z" in text
    assert r"Тест\; с запятой\, и\nновой строкой" in text
    assert text.count("BEGIN:VEVENT") == len(plan["sessions"])
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))


def test_real_mcp_transport_and_material_isolation():
    first = asyncio.run(run_tool("search_study_materials", {"query": "алгоритм"}, [{"name": "lecture.md", "text": "Алгоритм Дейкстры находит кратчайший путь."}]))
    second = asyncio.run(run_tool("search_study_materials", {"query": "алгоритм"}))
    assert first["output"]["matches"][0]["source"] == "lecture.md"
    assert second["output"]["matches"] == []
