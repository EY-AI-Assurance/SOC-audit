import json
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks

from app.models.schemas import CreateJobRequest
from app.routers import jobs


def test_create_job_persists_only_public_api_metadata(tmp_path: Path):
    report_id = "report-1"
    (tmp_path / f"{report_id}_state.json").write_text(
        json.dumps({"filename": "report.pdf"}), encoding="utf-8"
    )
    secret_snapshot = {
        "id": "api-1",
        "name": "Production API",
        "provider": "openai",
        "protocol": "openai_compatible",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-secret",
        "model": "audit-model",
        "verify_tls": True,
    }
    written = {}
    background = BackgroundTasks()

    with (
        patch.object(jobs.settings, "parsed_dir", tmp_path),
        patch.object(jobs, "get_template_path", return_value=tmp_path / "template.xlsx"),
        patch.object(jobs.api_config_store, "active_snapshot", return_value=secret_snapshot),
        patch.object(jobs, "_write_job", side_effect=lambda job_id, state: written.update(state)),
    ):
        response = jobs.create_job(
            CreateJobRequest(template_id="template-1", report_ids=[report_id], sheets=[2]),
            background,
        )

    assert response.jobs[0].api_config == {
        "id": "api-1",
        "name": "Production API",
        "provider": "openai",
        "model": "audit-model",
    }
    assert written["api_config"] == response.jobs[0].api_config
    assert "sk-secret" not in json.dumps(written)
    assert background.tasks[0].args[1]["api_key"] == "sk-secret"
