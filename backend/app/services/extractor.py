"""
Extraction orchestrator.

Reads parsed pages → locates sections via TOC → calls Dify once per sheet
→ returns a validated ExtractedFormData ready for Excel writing.
"""
from pathlib import Path

from app.config import settings
from app.models.extraction import (
    CUECItem, ExceptionItem, ExtractedFormData,
    ITGCSection, QualifiedOpinion,
    Sheet2Data, Sheet3Data, Sheet6Data, Sheet7Data, Sheet8Data,
    SubserviceOrg, TOCData,
)
from app.services.dify_client import dify_client
from app.services.pdf_parser import extract_section, load_parsed


def _prompt(name: str, **kwargs) -> str:
    return (settings.prompts_dir / name).read_text(encoding="utf-8").format(**kwargs)


# ── Per-sheet extractors ──────────────────────────────────────────────────────

def _parse_toc(pages: dict[int, str]) -> TOCData:
    toc_text = "\n\n".join(
        f"[Page {p}]\n{pages[p]}"
        for p in range(1, settings.toc_max_pages + 1)
        if p in pages
    )
    return TOCData(**dify_client.call_json(_prompt("toc.txt", toc_text=toc_text)))


def _extract_sheet2(text: str) -> Sheet2Data:
    return Sheet2Data(**dify_client.call_json(_prompt("sheet2_meta.txt", section_text=text)))


def _extract_sheet3(text: str) -> Sheet3Data:
    raw = dify_client.call_json(_prompt("sheet3_opinion.txt", section_text=text))
    opinion    = QualifiedOpinion(**raw["opinion"]) if raw.get("opinion") else None
    exceptions = [ExceptionItem(**e) for e in raw.get("exceptions", [])]
    return Sheet3Data(
        has_qualified_opinion=raw["has_qualified_opinion"],
        opinion=opinion,
        exceptions=exceptions,
    )


def _extract_sheet6(cm: str, am: str, js: str) -> Sheet6Data:
    raw = dify_client.call_json(
        _prompt("sheet6_itgc.txt", cm_text=cm, am_text=am, js_text=js)
    )
    return Sheet6Data(
        change_mgmt=ITGCSection(**raw["change_mgmt"]),
        access_mgmt=ITGCSection(**raw["access_mgmt"]),
        job_scheduling=ITGCSection(**raw["job_scheduling"]),
    )


def _extract_sheet7(text: str) -> Sheet7Data:
    raw  = dify_client.call_json(_prompt("sheet7_subservice.txt", section_text=text))
    orgs = [SubserviceOrg(**o) for o in raw.get("organizations", [])]
    return Sheet7Data(has_subservice=raw["has_subservice"], organizations=orgs)


def _extract_sheet8(text: str) -> Sheet8Data:
    raw   = dify_client.call_json(_prompt("sheet8_cuec.txt", section_text=text))
    cuecs = [CUECItem(**c) for c in raw.get("cuecs", [])]
    return Sheet8Data(cuecs=cuecs)


# ── Main pipeline ─────────────────────────────────────────────────────────────

def extract(parsed_path: Path) -> ExtractedFormData:
    """Full extraction pipeline. Raises on LLM errors or validation failures."""
    pages = load_parsed(parsed_path)

    toc = _parse_toc(pages)  # LLM call #0

    return ExtractedFormData(
        system_name=toc.system_name,
        sheet2=_extract_sheet2(extract_section(pages, toc.opinion_pages)),
        sheet3=_extract_sheet3(extract_section(pages, toc.opinion_pages)),
        sheet6=_extract_sheet6(
            extract_section(pages, toc.change_mgmt_pages),
            extract_section(pages, toc.access_mgmt_pages),
            extract_section(pages, toc.job_scheduling_pages),
        ),
        sheet7=_extract_sheet7(extract_section(pages, toc.subservice_pages)),
        sheet8=_extract_sheet8(extract_section(pages, toc.cuec_pages)),
    )
