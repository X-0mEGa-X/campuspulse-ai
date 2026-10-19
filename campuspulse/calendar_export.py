"""Export an existing plan to an ICS file without writing to a calendar account."""
from datetime import datetime, timezone
import hashlib


def escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold(line: str) -> str:
    chunks, current = [], ""
    for char in line:
        if len((current + char).encode("utf-8")) > 73:
            chunks.append(current)
            current = " "
        current += char
    return "\r\n".join(chunks + [current])


def to_ics(plan: dict) -> bytes:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CampusPulse//Study Plan//RU", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for session in plan.get("sessions", []):
        start = datetime.fromisoformat(session["start"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        end = datetime.fromisoformat(session["end"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        uid = hashlib.sha256(f"{start}-{session['title']}".encode()).hexdigest()[:24]
        lines += ["BEGIN:VEVENT", f"UID:{uid}@campuspulse", f"DTSTAMP:{stamp}", f"DTSTART:{start}", f"DTEND:{end}",
                  "SUMMARY:" + escape(session["title"]), "DESCRIPTION:" + escape("Учебный план CampusPulse. " + (session.get("source_url") or "Введено пользователем.")), "END:VEVENT"]
    return ("\r\n".join(fold(line) for line in lines + ["END:VCALENDAR"]) + "\r\n").encode("utf-8")
