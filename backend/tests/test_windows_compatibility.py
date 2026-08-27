import json
from pathlib import Path

from app.routers import templates
from app.routers.jobs import _safe_filename_component


def test_windows_reserved_characters_are_removed_from_output_filename():
    assert _safe_filename_component('Finance: Q4/2026\\APAC?*', "fallback") == "Finance__Q4_2026_APAC"
    assert _safe_filename_component("CON", "fallback") == "fallback"
    assert _safe_filename_component("name. ", "fallback") == "name"


def test_legacy_macos_template_path_resolves_after_copy_to_windows_style_storage(
    tmp_path: Path,
    monkeypatch,
):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    template_file = template_dir / "template-id.xlsx"
    template_file.write_bytes(b"test")
    meta_file = template_dir / "template-id_meta.json"
    meta_file.write_text(json.dumps({
        "template_id": "template-id",
        "name": "template.xlsx",
        "path": "/Users/example/SOC-audit/backend/storage/templates/template-id.xlsx",
        "available_sheets": [],
        "uploaded_at": "2026-01-01T00:00:00+00:00",
    }), encoding="utf-8")
    monkeypatch.setattr(templates.settings, "templates_dir", template_dir)

    assert templates.get_template_path("template-id") == template_file
    listed = templates._all_templates()
    assert listed[0]["path"] == "template-id.xlsx"
    assert json.loads(meta_file.read_text(encoding="utf-8"))["path"] == "template-id.xlsx"


def test_legacy_windows_template_path_resolves_on_other_platforms(tmp_path: Path, monkeypatch):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    template_file = template_dir / "template-id.xlsx"
    template_file.write_bytes(b"test")
    monkeypatch.setattr(templates.settings, "templates_dir", template_dir)

    resolved = templates._resolve_template_path({
        "path": r"C:\Users\example\SOC-audit\backend\storage\templates\template-id.xlsx",
    })

    assert resolved == template_file
