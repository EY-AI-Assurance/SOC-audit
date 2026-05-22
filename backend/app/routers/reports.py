"""
/api/reports — upload, status check, fill, download.

POST /upload           upload PDF → background parse           → 202
GET  /{id}             check status + metadata                 → 200
POST /{id}/fill        trigger LLM extraction + Excel write    → 202
GET  /{id}/download    stream the generated Excel file         → 200
"""
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.models.schemas import FillResponse, ReportInfo, ReportResponse, ReportStatus, UploadResponse
from app.services.excel_writer import write_excel
from app.services.extractor import extract
from app.services.pdf_parser import parse_pdf, save_parsed

from datetime import datetime, timezone

router = APIRouter(prefix="/api/reports", tags=["reports"])


# ── File-based state store (swap for a DB later) ──────────────────────────────

def _state_path(report_id: str) -> Path:
    return settings.parsed_dir / f"{report_id}_state.json"


def _read_state(report_id: str) -> dict:
    p = _state_path(report_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return json.loads(p.read_text(encoding="utf-8"))


def _write_state(report_id: str, **kwargs) -> None:
    p = _state_path(report_id)
    state = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    state.update(kwargs)
    p.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


# ── Background tasks ──────────────────────────────────────────────────────────

def _bg_parse(report_id: str, pdf_path: Path) -> None:
    try:
        pages = parse_pdf(pdf_path)
        if not _state_path(report_id).exists():
            return
        save_parsed(pages, settings.parsed_dir / f"{report_id}.json")
        _write_state(report_id, status=ReportStatus.READY)
    except Exception as exc:
        if _state_path(report_id).exists():
            _write_state(report_id, status=ReportStatus.FAILED, error=str(exc))


def _bg_fill(report_id: str) -> None:
    try:
        form_data = extract(settings.parsed_dir / f"{report_id}.json")
        filename  = f"Form_107-A_{form_data.system_name}_{report_id}.xlsx"
        write_excel(form_data, settings.outputs_dir / filename)
        _write_state(
            report_id,
            status=ReportStatus.DONE,
            system_name=form_data.system_name,
            output_filename=filename,
        )
    except Exception as exc:
        _write_state(report_id, status=ReportStatus.FAILED, error=str(exc))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
def list_reports():
    reports = []
    for p in settings.parsed_dir.glob("*_state.json"):
        state = json.loads(p.read_text(encoding="utf-8"))
        report_id = p.stem.replace("_state", "")
        reports.append(ReportInfo(
            report_id=report_id,
            filename=state.get("filename", ""),
            status=state.get("status", ""),
            system_name=state.get("system_name", ""),
            uploaded_at=state.get("uploaded_at", ""),
        ).model_dump())
    reports.sort(key=lambda r: r["uploaded_at"], reverse=True)
    return {"reports": reports}


@router.post("/upload", response_model=UploadResponse, status_code=202)
async def upload_report(file: UploadFile, background_tasks: BackgroundTasks):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    report_id = str(uuid.uuid4())
    pdf_path  = settings.uploads_dir / f"{report_id}.pdf"
    pdf_path.write_bytes(await file.read())

    _write_state(
        report_id,
        status=ReportStatus.PARSING,
        filename=file.filename,
        uploaded_at=datetime.now(timezone.utc).isoformat(),
    )
    background_tasks.add_task(_bg_parse, report_id, pdf_path)

    return UploadResponse(
        report_id=report_id,
        status=ReportStatus.PARSING,
        message="PDF uploaded. Parsing started in the background.",
    )


@router.get("/{report_id}", response_model=ReportResponse)
def get_report(report_id: str):
    state = _read_state(report_id)
    return ReportResponse(report_id=report_id, **state)


@router.delete("/{report_id}", status_code=204)
def delete_report(report_id: str):
    state_path = _state_path(report_id)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    for path in [
        settings.uploads_dir / f"{report_id}.pdf",
        settings.parsed_dir / f"{report_id}.json",
        state_path,
    ]:
        if path.exists():
            path.unlink()

    output_filename = state.get("output_filename")
    if output_filename:
        output_path = settings.outputs_dir / output_filename
        if output_path.exists():
            output_path.unlink()


@router.post("/{report_id}/fill", response_model=FillResponse, status_code=202)
def fill_report(report_id: str, background_tasks: BackgroundTasks):
    state = _read_state(report_id)
    if state.get("status") != ReportStatus.READY:
        raise HTTPException(
            status_code=409,
            detail=f"Report not ready (current status: {state.get('status')})",
        )
    _write_state(report_id, status=ReportStatus.FILLING)
    background_tasks.add_task(_bg_fill, report_id)
    return FillResponse(
        report_id=report_id,
        status=ReportStatus.FILLING,
        message="Form filling started. Poll GET /{report_id} for status.",
    )


@router.get("/{report_id}/download")
def download_report(report_id: str):
    state = _read_state(report_id)
    if state.get("status") != ReportStatus.DONE:
        raise HTTPException(status_code=409, detail="Excel file is not ready yet")
    output_path = settings.outputs_dir / state["output_filename"]
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found on disk")
    return FileResponse(
        path=output_path,
        filename=state["output_filename"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
