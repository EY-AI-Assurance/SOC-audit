"""
Pydantic models for structured data extracted from a SOC 1 report.
These are validated outputs from LLM calls before writing to Excel.
"""
from typing import Literal, Optional

from pydantic import BaseModel


# ── LLM call #0: TOC ──────────────────────────────────────────────────────────

class TOCData(BaseModel):
    system_name: str            # e.g. "Alibaba Cloud", "阿里云"
    opinion_pages: list[int]    # [start, end]
    change_mgmt_pages: list[int]
    access_mgmt_pages: list[int]
    job_scheduling_pages: list[int]
    subservice_pages: list[int]
    cuec_pages: list[int]


# ── Sheet 2 ───────────────────────────────────────────────────────────────────

class Sheet2Data(BaseModel):
    report_name: str  # → C3
    period: str       # → D5  e.g. "October 1, 2024 to September 30, 2025"


# ── Sheet 3 ───────────────────────────────────────────────────────────────────

class QualifiedOpinion(BaseModel):
    description: str   # (I)
    explanation: str = ""  # (II) why not relevant to audit scope, if applicable


class ExceptionItem(BaseModel):
    index: str          # (III) control ID or page ref
    control: str        # (IV)  control name/description
    exception_desc: str # (V)   test exception description
    mgmt_response: str = ""                                    # (VI)
    is_audited: Literal["Audited", "Unaudited"] = "Audited"    # (VII)
    audit_relevant: Literal["Yes", "No"] = "Yes"               # (VIII)


class Sheet3Data(BaseModel):
    has_qualified_opinion: bool
    opinion: Optional[QualifiedOpinion] = None
    exceptions: list[ExceptionItem] = []


# ── Sheet 6 ───────────────────────────────────────────────────────────────────

class ITGCSection(BaseModel):
    """
    One ITGC section (Change Mgmt / Access Mgmt / Job Scheduling).

    risk_control_ids: one entry per risk row, control IDs joined by \\n.
      Change Mgmt  → 2 risks
      Access Mgmt  → 3 risks
      Job Sched    → 3 risks
    """
    has_process_description: Literal["Yes", "No", "Not applicable"]
    page_refs: str = ""
    section_b_applicable: Literal["Applicable", "Not applicable"] = "Not applicable"
    section_c_applicable: Literal["Applicable", "Not applicable"] = "Not applicable"
    risk_control_ids: list[str] = []  # e.g. ["CCC_01\nCCC_03", "APD_11"]


class Sheet6Data(BaseModel):
    change_mgmt: ITGCSection
    access_mgmt: ITGCSection
    job_scheduling: ITGCSection


# ── Sheet 7 ───────────────────────────────────────────────────────────────────

class SubserviceOrg(BaseModel):
    name: str      # (I)
    services: str  # (II)


class Sheet7Data(BaseModel):
    has_subservice: bool  # False → tick the "no SSO" checkbox
    organizations: list[SubserviceOrg] = []


# ── Sheet 8 ───────────────────────────────────────────────────────────────────

class CUECItem(BaseModel):
    objective_and_page: str  # (I) e.g. "Organizational Controls Page 44"
    description: str         # (II)


class Sheet8Data(BaseModel):
    cuecs: list[CUECItem] = []


# ── Assembled result ──────────────────────────────────────────────────────────

class ExtractedFormData(BaseModel):
    system_name: str
    sheet2: Optional[Sheet2Data] = None
    sheet3: Optional[Sheet3Data] = None
    sheet6: Optional[Sheet6Data] = None
    sheet7: Optional[Sheet7Data] = None
    sheet8: Optional[Sheet8Data] = None
