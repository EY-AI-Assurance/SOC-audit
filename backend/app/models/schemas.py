from enum import Enum
from typing import Optional

from pydantic import BaseModel


# ── Report ────────────────────────────────────────────────────────────────────

class ReportStatus(str, Enum):
    PARSING = "parsing"
    READY   = "ready"
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


class ReportInfo(BaseModel):
    report_id: str
    filename: str
    status: str
    system_name: str = ""
    uploaded_at: str = ""


# ── Template ──────────────────────────────────────────────────────────────────

class TemplateInfo(BaseModel):
    template_id: str
    name: str
    uploaded_at: str


# ── Job ───────────────────────────────────────────────────────────────────────

class JobReportStatus(str, Enum):
    QUEUED     = "QUEUED"
    PROCESSING = "PROCESSING"
    DONE       = "DONE"
    FAILED     = "FAILED"


class ReportSummary(BaseModel):
    system_name: str = ""
    period: str = ""
    has_qualified_opinion: bool = False
    exception_count: int = 0
    has_subservice: bool = False
    cuec_count: int = 0


class JobReportResult(BaseModel):
    report_id: str
    filename: str
    status: str = "QUEUED"
    progress: int = 0
    current_step: str = ""
    output_filename: str = ""
    summary: Optional[ReportSummary] = None
    error: str = ""


class JobResponse(BaseModel):
    job_id: str
    template_id: str
    template_name: str
    sheets: list[int]
    status: str
    created_at: str
    reports: list[JobReportResult]


class CreateJobRequest(BaseModel):
    template_id: str
    report_ids: list[str]
    sheets: list[int]
