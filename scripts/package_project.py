"""Build the deliverable from an explicit allowlist. Never include credentials."""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
files = [ROOT / name for name in (
    "README.md", ".env.example", ".gitignore", ".dockerignore", "Dockerfile",
    "app.py", "requirements.txt", "requirements-dev.txt", "pytest.ini", "mcp.json", "START-CampusPulse.cmd")]
for directory in ("campuspulse", "scripts", "tests", "docs", ".streamlit", "output/presentation"):
    for file in (ROOT / directory).rglob("*"):
        if file.is_file() and not file.is_symlink() and "__pycache__" not in file.parts and file.name != "secrets.toml":
            files.append(file)
output = ROOT / "output" / "CampusPulse-AI.zip"
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for file in sorted(set(files)):
        archive.write(file, Path("CampusPulse-AI") / file.relative_to(ROOT))
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
    assert not any(Path(name).name in {".env", "secrets.toml", "application_default_credentials.json"} for name in archive.namelist())
print(f"PACKAGED {len(set(files))} files: {output}")
print("SHA256", hashlib.sha256(output.read_bytes()).hexdigest())
