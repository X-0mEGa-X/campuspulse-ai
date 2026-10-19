$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
}
& '.\.venv\Scripts\python.exe' -m streamlit run app.py --server.port 8501
