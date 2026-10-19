"""Small, bounded tools. No model-generated text is executed as code."""
from __future__ import annotations

import base64
import math
import os
import re
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import httpx


def now_in(timezone: str = "Asia/Almaty") -> datetime:
    return datetime.now(ZoneInfo(timezone))


def parse_due(value: str, timezone: str) -> datetime:
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return datetime.combine(datetime.fromisoformat(value).date(), time(23, 59), ZoneInfo(timezone))
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=ZoneInfo(timezone)) if result.tzinfo is None else result.astimezone(ZoneInfo(timezone))


def current_time(timezone: str = "Asia/Almaty") -> dict:
    current = now_in(timezone)
    return {"now": current.isoformat(), "date": current.date().isoformat(), "timezone": timezone}


def deadline_status(due_at: str, timezone: str = "Asia/Almaty") -> dict:
    due = parse_due(due_at, timezone)
    minutes = math.floor((due - now_in(timezone)).total_seconds() / 60)
    return {"due_at": due.isoformat(), "minutes_remaining": minutes,
            "overdue": minutes < 0, "timezone": timezone,
            "date_only_policy": "A date without a time means 23:59 in the selected timezone."}


def normalize_repository(repository: str) -> str:
    repository = repository.strip().rstrip("/")
    if repository.startswith("https://github.com/"):
        repository = repository[len("https://github.com/"):]
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Укажи owner/repo или https://github.com/owner/repo без дополнительных путей.")
    if any(x in {".", ".."} for x in repository.split("/")):
        raise ValueError("Некорректный репозиторий.")
    return repository


def github_get(path: str, params: dict | None = None) -> dict | list:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "CampusPulse-Hackathon",
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Fixed host prevents arbitrary URL requests and redirects to private networks.
    with httpx.Client(timeout=15, follow_redirects=False) as client:
        response = client.get("https://api.github.com" + path, params=params, headers=headers)
    if response.status_code in (403, 429):
        raise ValueError("GitHub ограничил запросы или доступ. Попробуй позже либо настрой read-only GITHUB_TOKEN.")
    if response.status_code == 404:
        raise ValueError("Репозиторий или файл не найден. Проверь имя и доступ.")
    if response.status_code != 200:
        raise ValueError(f"GitHub вернул HTTP {response.status_code}.")
    return response.json()


def github_issues(repository: str, limit: int = 10) -> dict:
    repository = normalize_repository(repository)
    if not 1 <= limit <= 30:
        raise ValueError("limit должен быть от 1 до 30.")
    raw = github_get(f"/repos/{repository}/issues", {"state": "open", "per_page": 100, "sort": "updated"})
    items = []
    for item in raw:
        if "pull_request" in item:
            continue
        body = (item.get("body") or "")[:6000]
        due_match = re.search(r"(?:due|deadline|дедлайн|срок)\s*:\s*(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?)", body, re.I)
        milestone = item.get("milestone") or {}
        due = due_match.group(1) if due_match else milestone.get("due_on")
        estimate_match = re.search(r"(?:estimate|оценка)\s*:\s*(\d+)\s*(h|hours|ч|m|min|мин)\b", body, re.I)
        estimate = None
        if estimate_match:
            estimate = int(estimate_match.group(1)) * (60 if estimate_match.group(2).lower() in {"h", "hours", "ч"} else 1)
        items.append({"number": item["number"], "title": item["title"], "body": body[:2000],
                      "due_at": due, "due_source": "issue body" if due_match else "milestone" if due else "unknown",
                      "estimated_minutes": estimate, "source_url": item["html_url"],
                      "labels": [v["name"] for v in item.get("labels", [])], "updated_at": item["updated_at"]})
        if len(items) >= limit:
            break
    return {"repository": repository, "issues": items, "fetched_at": now_in().isoformat(),
            "source": f"https://github.com/{repository}/issues", "live": True,
            "coverage": "Most recently updated open issues, first API page (up to 100 entries including pull requests).",
            "note": "Unknown deadlines stay unknown. Estimates are only extracted when explicitly provided."}


def github_readme(repository: str) -> dict:
    repository = normalize_repository(repository)
    data = github_get(f"/repos/{repository}/readme")
    if data.get("size", 0) > 1_000_000:
        raise ValueError("README слишком большой для этого прототипа.")
    content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
    return {"repository": repository, "text": content[:16000], "truncated": len(content) > 16000,
            "source_url": data.get("html_url"), "fetched_at": now_in().isoformat(), "live": True}


def search_materials(query: str, documents: list[dict]) -> dict:
    terms = set(re.findall(r"[\w-]{3,}", query.lower()))
    passages = []
    for document in documents:
        for offset in range(0, len(document["text"]), 900):
            passage = document["text"][offset:offset + 1200]
            score = sum(passage.lower().count(term) for term in terms)
            if score:
                passages.append({"source": document["name"], "excerpt": passage, "score": score,
                                 "character_offset": offset})
    passages.sort(key=lambda x: x["score"], reverse=True)
    return {"matches": passages[:5], "method": "lexical keyword retrieval", "documents_count": len(documents),
            "note": "No matches means no evidence. Do not invent document contents."}


def build_plan(tasks: list[dict], daily_minutes: int = 120, days: int = 7,
               timezone: str = "Asia/Almaty", start_hour: int = 18) -> dict:
    if not 1 <= len(tasks) <= 30:
        raise ValueError("Добавь от 1 до 30 задач.")
    if not 15 <= daily_minutes <= 480 or not 1 <= days <= 14 or not 0 <= start_hour <= 23:
        raise ValueError("Некорректный бюджет времени, горизонт или час начала.")
    current = now_in(timezone)
    prepared = []
    for index, task in enumerate(tasks):
        title = str(task.get("title", "")).strip()[:200]
        if not title:
            raise ValueError("У каждой задачи должно быть название.")
        estimate = task.get("estimated_minutes")
        estimate_default = estimate is None
        estimate = 60 if estimate_default else int(estimate)
        if not 1 <= estimate <= 10080:
            raise ValueError("Оценка задачи должна быть от 1 до 10080 минут.")
        due = parse_due(str(task["due_at"]), timezone) if task.get("due_at") else None
        prepared.append({"id": index, "title": title, "due": due, "estimate": estimate,
                         "estimated_by_default": estimate_default, "source_url": task.get("source_url")})
    prepared.sort(key=lambda t: (t["due"] or datetime.max.replace(tzinfo=current.tzinfo), t["id"]))
    slots = []
    for offset in range(days):
        date = current.date() + timedelta(days=offset)
        start = datetime.combine(date, time(start_hour), current.tzinfo)
        end = min(start + timedelta(minutes=daily_minutes), datetime.combine(date + timedelta(days=1), time(), current.tzinfo))
        if start < current:
            start = current.replace(second=0, microsecond=0) + timedelta(minutes=1)
            start += timedelta(minutes=(-start.minute) % 15)
        if start < end:
            slots.append([start, end])
    sessions, unscheduled = [], []
    for task in prepared:
        remaining = task["estimate"]
        due = task["due"]
        if due and due <= current:
            unscheduled.append({"title": task["title"], "minutes": remaining, "reason": "deadline_passed"})
            continue
        for slot in slots:
            effective_end = min(slot[1], due) if due else slot[1]
            while remaining > 0 and slot[0] < effective_end:
                available = math.floor((effective_end - slot[0]).total_seconds() / 60)
                duration = min(remaining, available, 60)
                if duration <= 0:
                    break
                end = slot[0] + timedelta(minutes=duration)
                sessions.append({"title": task["title"], "start": slot[0].isoformat(), "end": end.isoformat(),
                                 "minutes": duration, "source_url": task["source_url"],
                                 "due_at": due.isoformat() if due else None,
                                 "estimated_by_default": task["estimated_by_default"]})
                slot[0] = end
                remaining -= duration
            if remaining == 0:
                break
        if remaining:
            unscheduled.append({"title": task["title"], "minutes": remaining, "reason": "not_enough_time_before_deadline_or_horizon"})
    sessions.sort(key=lambda s: s["start"])
    return {"sessions": sessions, "unscheduled": unscheduled, "timezone": timezone,
            "scheduled_minutes": sum(x["minutes"] for x in sessions),
            "requested_minutes": sum(x["estimate"] for x in prepared),
            "generated_at": current.isoformat(), "days": days, "daily_minutes": daily_minutes,
            "assumptions": ["Earliest known deadline first; undated tasks follow.",
                            "Missing effort defaults to 60 minutes and is marked as an estimate.",
                            "Study windows start at the selected hour. Existing calendar events and breaks are not imported.",
                            "Date-only deadlines mean 23:59 in the chosen timezone."]}
