param([Parameter(Mandatory=$true)][string]$ProjectId)
$ErrorActionPreference = 'Stop'
gcloud services enable aiplatform.googleapis.com storage.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project $ProjectId
if ($LASTEXITCODE -ne 0) { throw 'API setup failed. Check billing and permissions.' }
gcloud auth application-default set-quota-project $ProjectId
if ($LASTEXITCODE -ne 0) { throw 'Set up application-default credentials first.' }
Write-Output 'Cloud APIs are enabled. Deploy with python scripts/deploy.py --project YOUR_PROJECT_ID.'
