"""Create a Gemini-only API key with ADC; never print the secret or enable billing."""
import argparse
import time
from pathlib import Path

import google.auth
from google.auth.transport.requests import AuthorizedSession
from dotenv import set_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    with AuthorizedSession(credentials) as session:
        def checked(response):
            if not response.ok:
                error = response.json().get("error", {})
                raise RuntimeError(f"Google API: {response.status_code} {error.get('message', 'Request failed')}")
            return response.json()

        def wait(operation, base):
            for _ in range(45):
                if operation.get("done"):
                    if operation.get("error"):
                        raise RuntimeError(operation["error"].get("message", "Operation failed"))
                    return operation.get("response", {})
                time.sleep(2)
                operation = checked(session.get(base + operation["name"], timeout=30))
            raise TimeoutError("Google operation did not finish")

        operation = checked(session.post(f"https://serviceusage.googleapis.com/v1/projects/{args.project}/services:batchEnable",
                            json={"serviceIds": ["generativelanguage.googleapis.com", "apikeys.googleapis.com", "cloudresourcemanager.googleapis.com"]}, timeout=60))
        wait(operation, "https://serviceusage.googleapis.com/v1/")
        print("Gemini and API Keys APIs enabled; billing unchanged.", flush=True)
        project = checked(session.get(f"https://cloudresourcemanager.googleapis.com/v1/projects/{args.project}", timeout=30))
        number = project["projectNumber"]
        base = f"https://apikeys.googleapis.com/v2/projects/{number}/locations/global/keys"
        key_id = "campuspulse-gemini-demo"
        existing = session.get(base + "/" + key_id, timeout=30)
        if existing.status_code == 404:
            operation = checked(session.post(base, params={"keyId": key_id}, json={
                "displayName": "CampusPulse local Gemini demo",
                "restrictions": {"apiTargets": [{"service": "generativelanguage.googleapis.com"}]}
            }, timeout=60))
            key = wait(operation, "https://apikeys.googleapis.com/v2/")
        else:
            key = checked(existing)
        secret = checked(session.get("https://apikeys.googleapis.com/v2/" + key["name"] + "/keyString", timeout=30))["keyString"]
        env_file = Path(__file__).resolve().parents[1] / ".env"
        set_key(env_file, "GEMINI_API_KEY", secret)
        print("Restricted Gemini key saved in ignored .env; secret not printed.")


if __name__ == "__main__":
    main()
