"""
FastAPI API boundary schemas — request/response shapes.
Separate from extraction models so the two can evolve independently.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ReportStatus(str, Enum):
    PARSING = "parsing"   # PDF uploaded, background parse running
    READY   = "ready"     # parsed and ready to fill
    FILLING = "filling"   # LLM extraction + Excel generation running
    DONE    = "done"      # Excel ready to download
    FAILED  = "failed"


class UploadResponse(BaseModel):
    report_id: str
    status: ReportStatus
    message: str


class ReportResponse(BaseModel):
    report_id: str
    status: ReportStatus
    filename: str
    system_name: Optional[str] = None
    error: Optional[str] = None


class FillResponse(BaseModel):
    report_id: str
    status: ReportStatus
    message: str
