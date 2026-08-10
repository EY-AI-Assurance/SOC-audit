import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings


IS_FROZEN = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

# Read-only resources are collected inside the PyInstaller bundle. During
# normal development they continue to resolve from the repository root.
RESOURCE_ROOT = (
    Path(sys._MEIPASS)  # type: ignore[attr-defined]
    if IS_FROZEN
    else Path(__file__).resolve().parents[2]
)

# A one-file executable is unpacked to a temporary directory on every launch,
# so user uploads and generated workbooks must live outside the bundle.
if IS_FROZEN:
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    )
    WRITABLE_ROOT = local_app_data / "SOC-Audit"
    ENV_FILE = RESOURCE_ROOT / ".env"
else:
    WRITABLE_ROOT = RESOURCE_ROOT / "backend"
    ENV_FILE = WRITABLE_ROOT / ".env"


class Settings(BaseSettings):
    # ── LLM API ────────────────────────────────────────────────────────────────
    llm_provider: str = "openai_compatible"

    # OpenAI-compatible provider, e.g. Bailian / iFlytek MaaS
    bailian_api_key: str = ""
    bailian_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_model: str = "qwen-turbo"

    # Dify Chatflow API
    dify_base_url: str = ""
    dify_api_key: str = ""
    dify_user: str = "soc-audit-local"

    # ── Paths ─────────────────────────────────────────────────────────────────
    root_dir: Path = WRITABLE_ROOT
    storage_dir: Path = root_dir / "storage"
    uploads_dir: Path = storage_dir / "uploads"
    parsed_dir: Path = storage_dir / "parsed"
    outputs_dir: Path = storage_dir / "outputs"
    jobs_dir: Path = storage_dir / "jobs"
    templates_dir: Path = storage_dir / "templates"
    api_configs_dir: Path = storage_dir / "api_configs"
    prompts_dir: Path = RESOURCE_ROOT / "backend" / "app" / "prompts"
    search_terms_dir: Path = RESOURCE_ROOT / "backend" / "app" / "search_terms"
    frontend_dir: Path = RESOURCE_ROOT / "frontend" / "dist"

    # ── PDF parsing ───────────────────────────────────────────────────────────
    toc_max_pages: int = 6  # pages to scan for the table of contents

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    model_config = {
        "env_file": str(ENV_FILE),
        "env_file_encoding": "utf-8",
    }


settings = Settings()

# Ensure persistent storage directories exist at startup.
for _directory in [
    settings.uploads_dir,
    settings.parsed_dir,
    settings.outputs_dir,
    settings.jobs_dir,
    settings.templates_dir,
    settings.api_configs_dir,
]:
    _directory.mkdir(parents=True, exist_ok=True)
