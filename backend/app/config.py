from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Dify API ──────────────────────────────────────────────────────────────
    # Fill these in once the EY Dify endpoint is confirmed.
    dify_api_url: str = "https://your-dify-endpoint/v1"
    dify_api_key: str = ""
    dify_call_mode: str = "completion"  # "completion" | "chat" | "workflow"

    # ── Paths ─────────────────────────────────────────────────────────────────
    root_dir: Path = Path(__file__).parent.parent
    storage_dir: Path = root_dir / "storage"
    uploads_dir: Path = storage_dir / "uploads"
    parsed_dir: Path = storage_dir / "parsed"
    outputs_dir: Path = storage_dir / "outputs"
    template_path: Path = (
        root_dir.parent / "Form107 example" / "Form 107-A Appendices (CN) (1).xlsx"
    )
    prompts_dir: Path = Path(__file__).parent / "prompts"

    # ── PDF parsing ───────────────────────────────────────────────────────────
    toc_max_pages: int = 6  # pages to scan for the table of contents

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

# Ensure storage directories exist at startup
for _d in [settings.uploads_dir, settings.parsed_dir, settings.outputs_dir]:
    _d.mkdir(parents=True, exist_ok=True)
