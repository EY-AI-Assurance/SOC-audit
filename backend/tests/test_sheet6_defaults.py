from types import SimpleNamespace

from openpyxl import Workbook

from app.models.extraction import ITGCSection
from app.services.excel_writer import _write_sheet6


def _section(has_description: str = "Yes") -> ITGCSection:
    return ITGCSection(
        has_process_description=has_description,
        page_refs="",
        section_b_applicable="Not applicable",
        section_c_applicable="Not applicable",
        risk_control_ids=[],
    )


def test_sheet6_job_scheduling_not_applicable_defaults_and_fixed_cells():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet["E6"] = "Yes"
    worksheet["E19"] = "Yes"
    worksheet["E34"] = "Yes"  # template default must be replaced
    data = SimpleNamespace(sheet6=SimpleNamespace(
        change_mgmt=_section(),
        access_mgmt=_section(),
        job_scheduling=_section("Not applicable"),
    ))

    _write_sheet6(worksheet, data)

    assert worksheet["E34"].value == "Not applicable"
    assert worksheet["E37"].value == "不存在由服务机构控制及负责的计划任务。"
    for coordinate in ("F6", "G6", "F19", "G19", "F34", "G34"):
        assert worksheet[coordinate].value == "N/A"


def test_sheet6_defaults_do_not_overwrite_existing_template_values():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet["F6"] = "Existing scope note"
    data = SimpleNamespace(sheet6=SimpleNamespace(
        change_mgmt=_section(),
        access_mgmt=_section(),
        job_scheduling=_section(),
    ))

    _write_sheet6(worksheet, data)

    assert worksheet["F6"].value == "Existing scope note"
