import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from app.config import settings
from app.models.schemas import TemplateInfo

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _meta_path(template_id: str) -> Path:
    return settings.templates_dir / f"{template_id}_meta.json"


def _all_templates() -> list[dict]:
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(settings.templates_dir.glob("*_meta.json"))
    ]


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

    meta = {
        "template_id": tid,
        "name": file.filename,
        "path": str(dest),
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
    mp = _meta_path(template_id)
    if not mp.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    meta = json.loads(mp.read_text(encoding="utf-8"))
    p = Path(meta["path"])
    if not p.exists():
        raise HTTPException(status_code=404, detail="Template file missing on disk")
    return p
