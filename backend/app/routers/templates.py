import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.config import settings
from app.models.schemas import TemplateInfo

router = APIRouter(prefix="/api/templates", tags=["templates"])

IMPLEMENTED_SHEETS = {2, 3, 6, 7, 8, 9}


def _meta_path(template_id: str) -> Path:
    return settings.templates_dir / f"{template_id}_meta.json"


def _all_templates() -> list[dict]:
    templates = []
    for p in sorted(settings.templates_dir.glob("*_meta.json")):
        meta = json.loads(p.read_text(encoding="utf-8"))
        template_path = Path(meta.get("path", ""))
        if "available_sheets" not in meta and template_path.exists():
            meta["available_sheets"] = _detect_available_sheets(template_path)
            p.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        templates.append(meta)
    return templates


def _detect_available_sheets(template_path: Path) -> list[int]:
    wb = load_workbook(template_path, read_only=True)
    try:
        detected = {
            int(match.group(1))
            for name in wb.sheetnames
            if (match := re.match(r"^\s*(\d+)(?:\s*[.\-、:]|\s+)", name))
        }
    finally:
        wb.close()
    return sorted(detected & IMPLEMENTED_SHEETS)


@router.get("", response_model=dict)
def list_templates():
    return {"templates": [TemplateInfo(**template).model_dump() for template in _all_templates()]}


@router.post("/upload", response_model=TemplateInfo, status_code=201)
async def upload_template(file: UploadFile):
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted")

    tid = str(uuid.uuid4())
    dest = settings.templates_dir / f"{tid}.xlsx"
    dest.write_bytes(await file.read())

    try:
        available_sheets = _detect_available_sheets(dest)
    except (InvalidFileException, OSError, ValueError, KeyError):
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid .xlsx workbook")

    meta = {
        "template_id": tid,
        "name": file.filename,
        "path": str(dest),
        "available_sheets": available_sheets,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    _meta_path(tid).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return TemplateInfo(**meta)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: str):
    meta_path = _meta_path(template_id)
    if not meta_path.exists():
        return

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    template_path = Path(meta.get("path", ""))

    if template_path.exists() and template_path.is_relative_to(settings.templates_dir):
        template_path.unlink()

    meta_path.unlink()


def get_template_path(template_id: str) -> Path:
    return Path(get_template_meta(template_id)["path"])


def get_template_meta(template_id: str) -> dict:
    mp = _meta_path(template_id)
    if not mp.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    meta = json.loads(mp.read_text(encoding="utf-8"))
    p = Path(meta["path"])
    if not p.exists():
        raise HTTPException(status_code=404, detail="Template file missing on disk")
    if "available_sheets" not in meta:
        meta["available_sheets"] = _detect_available_sheets(p)
        mp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta
