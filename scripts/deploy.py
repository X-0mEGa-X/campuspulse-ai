"""Deploy the tested application to Vertex AI Reasoning/Agent Engine."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
import vertexai
from vertexai.preview import reasoning_engines
from google.cloud import storage
from campuspulse.agent import CampusPulseAgent


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--region", default=os.getenv("AGENT_ENGINE_LOCATION", "us-central1"))
    parser.add_argument("--bucket", default=os.getenv("STAGING_BUCKET"))
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.project:
        parser.error("Set GOOGLE_CLOUD_PROJECT or --project.")
    bucket_name = (args.bucket or f"{args.project}-campuspulse-agent").removeprefix("gs://").rstrip("/")
    requirements = ["google-cloud-aiplatform==1.165.1", "google-genai==1.75.0", "cloudpickle==3.1.2",
                    "mcp==1.30.0", "httpx==0.28.1", "tzdata==2026.5"]
    configuration = {"project": args.project, "region": args.region, "staging_bucket": f"gs://{bucket_name}",
                     "model": args.model, "requirements": requirements, "extra_packages": ["campuspulse"], "python": "3.12"}
    if args.dry_run:
        print(json.dumps(configuration, indent=2))
        return
    # Fail early before creating billable cloud resources if credentials are unavailable.
    client = storage.Client(project=args.project)
    bucket = client.bucket(bucket_name)
    if not bucket.exists():
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        bucket = client.create_bucket(bucket, location=args.region)
    os.chdir(ROOT)
    vertexai.init(project=args.project, location=args.region, staging_bucket=f"gs://{bucket_name}")
    local_agent = CampusPulseAgent(project=args.project, location="global", model=args.model)
    remote = reasoning_engines.ReasoningEngine.create(
        local_agent, requirements=requirements, extra_packages=["campuspulse"], sys_version="3.12",
        display_name="CampusPulse AI", description="Student planning assistant using Gemini and six real MCP tools.")
    deployment = {**configuration, "resource_name": remote.resource_name}
    (ROOT / "deployment.json").write_text(json.dumps(deployment, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DEPLOYED:", remote.resource_name)
    print("Saved deployment.json. Run scripts/smoke_cloud.py to verify the endpoint.")


if __name__ == "__main__":
    main()
