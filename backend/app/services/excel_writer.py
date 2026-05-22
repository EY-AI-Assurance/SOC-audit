"""
Excel writer.

Copies the Form 107-A template and fills in all target sheets while
preserving formatting, styles, and data validations.

The Sheet 7 "no subservice" checkbox is a VML Form Control that openpyxl
cannot touch, so it is toggled via direct ZIP/XML manipulation.
"""
import shutil
import zipfile
from pathlib import Path

import openpyxl
from openpyxl.cell.cell import MergedCell

from app.models.extraction import ExtractedFormData, ITGCSection


def _cell(ws, row: int, col: int):
    """Return a writable cell, resolving merged ranges to their top-left cell."""
    c = ws.cell(row, col)
    if isinstance(c, MergedCell):
        for rng in ws.merged_cells.ranges:
            if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
                return ws.cell(rng.min_row, rng.min_col)
    return c


# ── Sheet 6 row map ───────────────────────────────────────────────────────────

_S6 = {
    "change_mgmt":    {"has_desc": 6,  "page_refs": 7,  "sec_b": 10, "sec_c": 12, "risks": [13, 15]},
    "access_mgmt":    {"has_desc": 19, "page_refs": 20, "sec_b": 23, "sec_c": 25, "risks": [26, 28, 30]},
    "job_scheduling": {"has_desc": 34, "page_refs": 35, "sec_b": 38, "sec_c": 40, "risks": [41, 43, 45]},
}
_COL_D = 4  # (X)  dropdown "See col (XI)" / "None"
_COL_E = 5  # (XI) free-text reply / control IDs


# ── Sheet writers ─────────────────────────────────────────────────────────────

def _write_sheet2(ws, data: ExtractedFormData) -> None:
    ws["C3"] = data.sheet2.report_name
    ws["D5"] = data.sheet2.period


def _write_sheet3(ws, data: ExtractedFormData) -> None:
    s3 = data.sheet3
    if s3.has_qualified_opinion and s3.opinion:
        _cell(ws, 4, 1).value = s3.opinion.description
        _cell(ws, 4, 4).value = s3.opinion.explanation
    for i, exc in enumerate(s3.exceptions):
        r = 12 + i
        _cell(ws, r, 1).value = exc.index
        _cell(ws, r, 2).value = exc.control
        _cell(ws, r, 3).value = exc.exception_desc
        _cell(ws, r, 4).value = exc.mgmt_response
        _cell(ws, r, 5).value = exc.is_audited
        _cell(ws, r, 6).value = exc.audit_relevant


def _write_itgc_section(ws, section: ITGCSection, rows: dict) -> None:
    def _set_if_empty(row: int, col: int, value) -> None:
        c = _cell(ws, row, col)
        if not c.value:
            c.value = value

    # Preserve all pre-filled template values; only fill blank cells
    _set_if_empty(rows["has_desc"], _COL_E, section.has_process_description)
    _set_if_empty(rows["sec_b"],    _COL_E, section.section_b_applicable)
    _set_if_empty(rows["sec_c"],    _COL_E, section.section_c_applicable)

    # Page refs: write when either LLM or template says "Yes"
    effective_has_desc = _cell(ws, rows["has_desc"], _COL_E).value or section.has_process_description
    if effective_has_desc == "Yes" and section.page_refs:
        _set_if_empty(rows["page_refs"], _COL_E, section.page_refs)

    # Control IDs: write whenever section_c is Applicable (template always pre-fills this)
    effective_sec_c = _cell(ws, rows["sec_c"], _COL_E).value or section.section_c_applicable
    if effective_sec_c == "Applicable":
        for risk_row, ids in zip(rows["risks"], section.risk_control_ids):
            _set_if_empty(risk_row, _COL_D, "See col (XI)")
            if ids:
                _cell(ws, risk_row, _COL_E).value = ids


def _write_sheet6(ws, data: ExtractedFormData) -> None:
    _write_itgc_section(ws, data.sheet6.change_mgmt,   _S6["change_mgmt"])
    _write_itgc_section(ws, data.sheet6.access_mgmt,   _S6["access_mgmt"])
    _write_itgc_section(ws, data.sheet6.job_scheduling, _S6["job_scheduling"])


def _write_sheet7(ws, data: ExtractedFormData) -> None:
    for i, org in enumerate(data.sheet7.organizations):
        _cell(ws, 4 + i, 1).value = org.name
        _cell(ws, 4 + i, 2).value = org.services


def _write_sheet8(ws, data: ExtractedFormData) -> None:
    for i, cuec in enumerate(data.sheet8.cuecs):
        _cell(ws, 5 + i, 1).value = cuec.objective_and_page
        _cell(ws, 5 + i, 2).value = cuec.description


# ── VML checkbox helper ───────────────────────────────────────────────────────

def _tick_no_subservice_checkbox(output_path: Path) -> None:
    """Tick the Sheet 7 'no subservice organisations' checkbox via ZIP XML."""
    with zipfile.ZipFile(output_path, "r") as zin:
        files = {name: zin.read(name) for name in zin.namelist()}

    target = "xl/ctrlProps/ctrlProp14.xml"  # TODO: verify index against template
    if target in files:
        xml = files[target].decode("utf-8").replace(
            'objectType="CheckBox"',
            'objectType="CheckBox" checked="Checked"',
        )
        files[target] = xml.encode("utf-8")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, content in files.items():
            zout.writestr(name, content)


# ── Main entry ────────────────────────────────────────────────────────────────

def write_excel(
    data: ExtractedFormData,
    output_path: Path,
    template_path: Path,
) -> Path:
    shutil.copy2(template_path, output_path)
    wb = openpyxl.load_workbook(output_path)

    ws = {name.strip(): wb[name] for name in wb.sheetnames}

    if data.sheet2:
        _write_sheet2(ws["2.索引信息"], data)
    if data.sheet3:
        _write_sheet3(ws["3.报告保留意见和测试异常情况"], data)
    if data.sheet6:
        _write_sheet6(ws["6.IT流程和IT一般控制"], data)
    if data.sheet7:
        _write_sheet7(ws["7.子服务机构"], data)
    if data.sheet8:
        _write_sheet8(ws["8.补偿性用户实体控制"], data)

    wb.save(output_path)

    if data.sheet7 and not data.sheet7.has_subservice:
        _tick_no_subservice_checkbox(output_path)

    return output_path
