import re
import google.auth
from google.auth.transport.requests import AuthorizedSession


def query_remote(resource: str, message: str, context: dict) -> dict:
    match = re.fullmatch(r"projects/([a-zA-Z0-9-]+)/locations/([a-z0-9-]+)/reasoningEngines/([a-zA-Z0-9-]+)", resource)
    if not match:
        raise ValueError("Неверный AGENT_ENGINE_RESOURCE.")
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    with AuthorizedSession(credentials) as session:
        response = session.post(f"https://{match.group(2)}-aiplatform.googleapis.com/v1/{resource}:query",
                                json={"class_method": "query", "input": {"message": message, "context": context}}, timeout=180)
        response.raise_for_status()
        return response.json().get("output", response.json())
