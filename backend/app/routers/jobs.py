import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app.config import settings
from app.models.schemas import CreateJobRequest, JobResponse, ReportSummary
from app.routers.templates import get_template_path
from app.services.excel_writer import write_excel
from app.services.extractor import extract
from app.services.pdf_parser import parse_pdf, save_parsed

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ── State helpers ─────────────────────────────────────────────────────────────

def _job_path(job_id: str) -> Path:
    return settings.jobs_dir / f"{job_id}.json"


def _read_job(job_id: str) -> dict:
    p = _job_path(job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    return json.loads(p.read_text(encoding="utf-8"))


def _write_job(job_id: str, state: dict) -> None:
    _job_path(job_id).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _update_report_in_job(job_id: str, report_id: str, **kwargs) -> None:
    state = _read_job(job_id)
    for r in state["reports"]:
        if r["report_id"] == report_id:
            r.update(kwargs)
    _write_job(job_id, state)


def _finalize_job(job_id: str) -> None:
    state = _read_job(job_id)
    statuses = {r["status"] for r in state["reports"]}
    if statuses <= {"DONE", "FAILED"}:
        state["status"] = "failed" if "FAILED" in statuses else "done"
        _write_job(job_id, state)


# ── Background task ───────────────────────────────────────────────────────────

def _bg_job(job_id: str) -> None:
    state = _read_job(job_id)
    template_path = get_template_path(state["template_id"])

    for report_entry in state["reports"]:
        report_id = report_entry["report_id"]
        try:
            parsed_path = settings.parsed_dir / f"{report_id}.json"

            if not parsed_path.exists():
                _update_report_in_job(job_id, report_id,
                                      status="PROCESSING", progress=5,
                                      current_step="Parsing PDF")
                pdf_path = settings.uploads_dir / f"{report_id}.pdf"
                if not pdf_path.exists():
                    raise FileNotFoundError("PDF file not found on disk")
                pages = parse_pdf(pdf_path)
                save_parsed(pages, parsed_path)

            def _cb(step: str, pct: int, _rid: str = report_id) -> None:
                _update_report_in_job(job_id, _rid,
                                      status="PROCESSING", progress=pct,
                                      current_step=step)

            form_data = extract(parsed_path, sheets=state["sheets"], progress_cb=_cb)

            _update_report_in_job(job_id, report_id,
                                  status="PROCESSING", progress=95,
                                  current_step="Writing Excel")

            safe = (form_data.system_name or report_id[:8]).replace("/", "_").replace(" ", "_")
            output_filename = f"Form_107-A_{safe}_{report_id[:8]}.xlsx"
            print(f"[JOB] Writing Excel to {output_filename}", flush=True)
            write_excel(form_data, settings.outputs_dir / output_filename,
                        template_path=template_path)
            print(f"[JOB] Excel written OK", flush=True)

            summary = ReportSummary(
                system_name=form_data.system_name or "",
                period=form_data.sheet2.period if form_data.sheet2 else "",
                has_qualified_opinion=form_data.sheet3.has_qualified_opinion if form_data.sheet3 else False,
                exception_count=len(form_data.sheet3.exceptions) if form_data.sheet3 else 0,
                has_subservice=form_data.sheet7.has_subservice if form_data.sheet7 else False,
                cuec_count=len(form_data.sheet8.cuecs) if form_data.sheet8 else 0,
            )

            print(f"[JOB] Updating status to DONE", flush=True)
            _update_report_in_job(job_id, report_id,
                                  status="DONE", progress=100, current_step="",
                                  output_filename=output_filename,
                                  summary=summary.model_dump())
            print(f"[JOB] Status updated to DONE", flush=True)

        except Exception as exc:
            print(f"[JOB] EXCEPTION: {exc}", flush=True)
            logger.exception("Job %s report %s failed: %s", job_id, report_id, exc)
            _update_report_in_job(job_id, report_id,
                                  status="FAILED", progress=0, current_step="",
                                  error=str(exc))

    print(f"[JOB] Calling _finalize_job", flush=True)
    _finalize_job(job_id)
    print(f"[JOB] Done", flush=True)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
def list_jobs():
    jobs = []
    for p in sorted(settings.jobs_dir.glob("*.json"), reverse=True):
        jobs.append(json.loads(p.read_text(encoding="utf-8")))
    return {"jobs": jobs}


@router.post("", response_model=JobResponse, status_code=202)
def create_job(req: CreateJobRequest, background_tasks: BackgroundTasks):
    template_path = get_template_path(req.template_id)  # validates template exists

    # Load report filenames
    reports = []
    for rid in req.report_ids:
        state_file = settings.parsed_dir / f"{rid}_state.json"
        if not state_file.exists():
            raise HTTPException(status_code=404, detail=f"Report {rid} not found")
        state = json.loads(state_file.read_text(encoding="utf-8"))
        reports.append({
            "report_id": rid,
            "filename": state.get("filename", rid),
            "status": "QUEUED",
            "progress": 0,
            "current_step": "",
            "output_filename": "",
            "summary": None,
            "error": "",
        })

    job_id = str(uuid.uuid4())
    state = {
        "job_id": job_id,
        "template_id": req.template_id,
        "template_name": template_path.name,
        "sheets": req.sheets,
        "status": "processing",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reports": reports,
    }
    _write_job(job_id, state)
    background_tasks.add_task(_bg_job, job_id)
    return JobResponse(**state)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str):
    return JobResponse(**_read_job(job_id))


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: str):
    p = _job_path(job_id)
    if p.exists():
        state = json.loads(p.read_text(encoding="utf-8"))
        for r in state.get("reports", []):
            if r.get("output_filename"):
                output = settings.outputs_dir / r["output_filename"]
                if output.exists():
                    output.unlink()
        p.unlink()


@router.get("/{job_id}/download/{report_id}")
def download_output(job_id: str, report_id: str):
    state = _read_job(job_id)
    report = next((r for r in state["reports"] if r["report_id"] == report_id), None)
    if not report:
        raise HTTPException(status_code=404, detail="Report not in this job")
    if report["status"] != "DONE":
        raise HTTPException(status_code=409, detail="Output not ready yet")
    output_path = settings.outputs_dir / report["output_filename"]
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Output file missing on disk")
    return FileResponse(
        path=output_path,
        filename=report["output_filename"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
