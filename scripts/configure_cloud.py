"""Enable deployment APIs in the explicitly selected project using ADC."""
import argparse
import time
import google.auth
from google.auth.transport.requests import AuthorizedSession

parser = argparse.ArgumentParser()
parser.add_argument("--project", required=True)
args = parser.parse_args()
credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
with AuthorizedSession(credentials) as session:
    def wait_operation(response):
        response.raise_for_status()
        operation = response.json()
        for _ in range(30):
            if operation.get("done"):
                if operation.get("error"):
                    raise RuntimeError(operation["error"].get("message"))
                return
            if not operation.get("name"):
                return
            time.sleep(2)
            poll = session.get("https://serviceusage.googleapis.com/v1/" + operation["name"], timeout=30)
            poll.raise_for_status()
            operation = poll.json()
        raise TimeoutError("API activation did not finish in time. Try again in a minute.")
    # Billing inspection is its own API and may be disabled in a brand-new project.
    response = session.post(f"https://serviceusage.googleapis.com/v1/projects/{args.project}/services/cloudbilling.googleapis.com:enable", timeout=60)
    wait_operation(response)
    billing = session.get(f"https://cloudbilling.googleapis.com/v1/projects/{args.project}/billingInfo", timeout=30)
    billing.raise_for_status()
    print("BILLING_ENABLED:", billing.json().get("billingEnabled", False))
    if not billing.json().get("billingEnabled"):
        raise SystemExit("Project has no active billing account. Link an active billing account in the Cloud console.")
    project = session.get(f"https://cloudresourcemanager.googleapis.com/v1/projects/{args.project}", timeout=30)
    project.raise_for_status()
    number = project.json()["projectNumber"]
    response = session.post(f"https://serviceusage.googleapis.com/v1/projects/{number}/services:batchEnable", json={"serviceIds": [
        "aiplatform.googleapis.com", "storage.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com"]}, timeout=60)
    response.raise_for_status()
    print("API_ENABLE_OPERATION:", response.json().get("name", "done"))
    wait_operation(response)
    print("APIS_READY")
