"""Opt-in live Gemini + MCP smoke test. Uses public data and consumes API quota."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from campuspulse.agent import CampusPulseAgent
import os

load_dotenv(ROOT / ".env")
agent = CampusPulseAgent(model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
result = agent.query(
    "Проверь текущее время и 2 открытые задачи в репозитории google/adk-python. "
    "Кратко перечисли задачи со ссылками. Если дедлайны не указаны, так и скажи.",
    {"timezone": "Asia/Almaty", "repository": "google/adk-python"})
print(json.dumps({"ok": result["ok"], "answer": result["answer"], "tools": [e.get("name") for e in result["events"] if e["kind"] == "tool"]}, ensure_ascii=False, indent=2))
if result["ok"]:
    (ROOT / "docs" / "live-run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
raise SystemExit(0 if result["ok"] else 1)
