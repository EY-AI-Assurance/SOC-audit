from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM API (currently Bailian; swap dify_client.py to switch providers) ──
    bailian_api_key: str = ""
    bailian_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_model: str = "qwen-turbo"

    # ── Paths ─────────────────────────────────────────────────────────────────
    root_dir: Path = Path(__file__).parent.parent
    storage_dir: Path = root_dir / "storage"
    uploads_dir: Path = storage_dir / "uploads"
    parsed_dir: Path = storage_dir / "parsed"
    outputs_dir: Path = storage_dir / "outputs"
    template_path: Path = (
        root_dir.parent.parent / "Form 107-A Appendices (CN).xlsx"
    )
    prompts_dir: Path = Path(__file__).parent / "prompts"
    jobs_dir: Path = storage_dir / "jobs"
    templates_dir: Path = storage_dir / "templates"

    # ── PDF parsing ───────────────────────────────────────────────────────────
    toc_max_pages: int = 6  # pages to scan for the table of contents

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {
        "env_file": str(Path(__file__).parent.parent / ".env"),
        "env_file_encoding": "utf-8",
    }


settings = Settings()

# Ensure storage directories exist at startup
for _d in [settings.uploads_dir, settings.parsed_dir, settings.outputs_dir,
           settings.jobs_dir, settings.templates_dir]:
    _d.mkdir(parents=True, exist_ok=True)
