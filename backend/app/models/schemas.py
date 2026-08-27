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
    available_sheets: list[int] = []


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
    csoc_count: int = 0


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
    api_config: Optional[dict] = None


class CreatedJobsResponse(BaseModel):
    jobs: list[JobResponse]


class CreateJobRequest(BaseModel):
    template_id: str
    report_ids: list[str]
    sheets: list[int]


# ── API configuration ────────────────────────────────────────────────────────

class ApiConfigCreate(BaseModel):
    name: str
    provider: str
    base_url: str = ""
    api_key: str
    model: str = ""
    dify_user: str = "soc-audit-local"
    verify_tls: bool = True


class ApiConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    dify_user: Optional[str] = None
    verify_tls: Optional[bool] = None


class ApiConfigSummary(BaseModel):
    id: str
    name: str
    provider: str
    protocol: str
    base_url: str
    model: str = ""
    dify_user: str = ""
    verify_tls: bool = True
    masked_api_key: str
    status: str
    revision: int
    is_active: bool
    last_tested_at: Optional[str] = None
    last_test_error: str = ""
    created_at: str
    updated_at: str


class DiscoverModelsRequest(BaseModel):
    config_id: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    verify_tls: bool = True
