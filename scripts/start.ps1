$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$projectPython = Join-Path (Get-Location).Path '.venv\Scripts\python.exe'
try {
    $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/_stcore/health' -TimeoutSec 2 -UseBasicParsing
    if ($health.StatusCode -eq 200) {
        Write-Host 'A Streamlit app is already running. Open http://127.0.0.1:8501'
        return
    }
} catch { }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 and try again.' }
}
$dependencyCheck = @'
import sys
try:
    import streamlit, google.genai, vertexai, mcp, httpx, pypdf, dotenv, tzdata, PIL
except ImportError:
    sys.exit(1)
'@
& $projectPython -c $dependencyCheck
if ($LASTEXITCODE -ne 0) {
    & $projectPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install dependencies. Check your internet connection and retry.' }
}
Write-Host 'CampusPulse: http://127.0.0.1:8501. Keep this window open while using the app.'
& $projectPython -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1
