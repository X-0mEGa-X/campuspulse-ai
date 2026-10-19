import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from campuspulse.cloud_client import query_remote

resource = json.loads((ROOT / "deployment.json").read_text(encoding="utf-8"))["resource_name"]
result = query_remote(resource, "Узнай текущее время в Алматы через инструмент и назови дату.", {"timezone": "Asia/Almaty"})
print(json.dumps(result, ensure_ascii=False, indent=2))
if not result.get("ok") or not any(e.get("name") == "get_current_time" and e.get("ok") for e in result.get("events", [])):
    raise SystemExit("Cloud smoke check failed: no successful MCP time call.")
