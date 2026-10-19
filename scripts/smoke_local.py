"""Opt-in live free Gemini + actual MCP smoke; fails on missing/failed tools."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from campuspulse.agent import CampusPulseAgent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save this actual run as JSON (default: tmp/smoke-local.json).")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    agent = CampusPulseAgent(model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    result = agent.query(
        "Проверь текущее время. Прочитай README репозитория python/cpython и дай краткое описание со ссылкой. "
        "Найди в моём конспекте определение MCP. Составь план на неделю для двух добавленных задач "
        "с учётом настроек. Используй соответствующие инструменты для всех четырёх действий.",
        {"timezone": "Asia/Almaty", "repository": "python/cpython", "days": 7,
         "daily_minutes": 60, "start_hour": 18,
         "tasks": [{"title": "Подготовить лабораторную", "due_at": None, "estimated_minutes": 90},
                   {"title": "Повторить протокол MCP", "due_at": None, "estimated_minutes": 30}],
         "documents": [{"name": "smoke-test-notes.txt",
                        "text": "Учебный тестовый конспект. MCP — Model Context Protocol: протокол подключения инструментов и данных к AI-приложениям."}]})
    tools = [event for event in result.get("events", []) if event["kind"] == "tool"]
    required = {"get_current_time", "read_github_readme", "search_study_materials", "plan_study_week"}
    successful = {event["name"] for event in tools if event["ok"]}
    plan = result.get("plan") or {}
    readme_verified = any(event["name"] == "read_github_readme" and event["ok"]
                          and event["output"].get("live") is True
                          and event["output"].get("repository") == "python/cpython"
                          and bool(event["output"].get("text", "").strip()) for event in tools)
    material_verified = any(event["name"] == "search_study_materials" and event["ok"]
                            and any(match.get("source") == "smoke-test-notes.txt" and "MCP" in match.get("excerpt", "")
                                    for match in event["output"].get("matches", [])) for event in tools)
    passed = bool(result.get("ok") and required <= successful and all(event["ok"] for event in tools)
                  and readme_verified and material_verified
                  and plan.get("scheduled_minutes") == 120 and not plan.get("unscheduled"))
    result["verification"] = {"passed": passed, "required_tools": sorted(required),
                              "missing_successful_tools": sorted(required - successful),
                              "live_readme_verified": readme_verified, "material_excerpt_verified": material_verified,
                              "test_data": "Two explicit smoke-test tasks and a short test note; README is fetched live."}
    print(json.dumps({"passed": passed, "model": result.get("model"), "answer": result["answer"],
                      "tools": [{"name": e["name"], "ok": e["ok"]} for e in tools]}, ensure_ascii=False, indent=2))
    destination = args.output or ROOT / "tmp" / "smoke-local.json"
    if not destination.is_absolute():
        destination = ROOT / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
