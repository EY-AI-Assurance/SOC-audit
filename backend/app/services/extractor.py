import logging
from pathlib import Path
from typing import Callable

from app.config import settings

logger = logging.getLogger(__name__)
from app.models.extraction import (
    CUECItem, ExceptionItem, ExtractedFormData,
    ITGCSection, QualifiedOpinion,
    Sheet2Data, Sheet3Data, Sheet6Data, Sheet7Data, Sheet8Data,
    SubserviceOrg, TOCData,
)
from app.services.dify_client import dify_client
from app.services.pdf_parser import extract_section, load_parsed


_SHEET6_RULES = {
    "change_mgmt": {
        "anchors": ["ccc_"],
        "conditional_anchors": {
            "apd_": ["change", "program", "release", "deployment", "production"],
        },
        "phrases": ["change management", "program change", "software change"],
    },
    "access_mgmt": {
        "anchors": ["ivs_", "tvm_"],
        "conditional_anchors": {
            "apd_": ["access", "privileged", "permission", "account", "role"],
        },
        "phrases": [
            "access management",
            "logical access",
            "privileged access",
            "user access",
            "vulnerability management",
            "security configuration",
        ],
    },
    "job_scheduling": {
        "anchors": [],
        "conditional_anchors": {},
        "phrases": [
            "job scheduling",
            "job monitoring",
            "scheduled job",
            "batch job",
            "job scheduler",
        ],
    },
}


def _prompt(name: str, **kwargs) -> str:
    return (settings.prompts_dir / name).read_text(encoding="utf-8").format(**kwargs)


def _parse_toc(pages: dict[int, str]) -> TOCData:
    toc_text = "\n\n".join(
        f"[Page {p}]\n{pages[p]}"
        for p in range(1, settings.toc_max_pages + 1)
        if p in pages
    )
    return TOCData(**dify_client.call_json(_prompt("toc.txt", toc_text=toc_text)))


def _pages_from_range(page_range: list[int], all_pages: set[int]) -> set[int]:
    if not page_range or len(page_range) != 2 or page_range == [0, 0]:
        return set()
    start, end = page_range
    if start > end:
        start, end = end, start
    return {p for p in range(start, end + 1) if p in all_pages}


def _expand_pages(page_numbers: set[int], all_pages: set[int], window: int = 1) -> set[int]:
    expanded: set[int] = set()
    for page_number in page_numbers:
        for candidate in range(page_number - window, page_number + window + 1):
            if candidate in all_pages:
                expanded.add(candidate)
    return expanded


def _format_pages(pages: dict[int, str], page_numbers: list[int]) -> str:
    return "\n\n---\n\n".join(f"[Page {p}]\n{pages[p]}" for p in page_numbers if p in pages)


def _collect_candidate_pages(
    pages: dict[int, str],
    toc_range: list[int],
    rules: dict,
) -> list[int]:
    all_pages = set(pages)
    toc_pages = _pages_from_range(toc_range, all_pages)
    candidates = _expand_pages(toc_pages, all_pages)
    anchors = [anchor.lower() for anchor in rules["anchors"]]
    conditional_anchors = {
        anchor.lower(): [keyword.lower() for keyword in keywords]
        for anchor, keywords in rules["conditional_anchors"].items()
    }
    phrases = [phrase.lower() for phrase in rules["phrases"]]

    for page_number, text in pages.items():
        lowered_text = text.lower()
        if any(anchor in lowered_text for anchor in anchors):
            candidates.add(page_number)
            continue
        if any(phrase in lowered_text for phrase in phrases):
            candidates.add(page_number)
            continue
        if any(
            anchor in lowered_text and any(keyword in lowered_text for keyword in keywords)
            for anchor, keywords in conditional_anchors.items()
        ):
            candidates.add(page_number)

    return sorted(candidates)


def _collect_sheet6_candidate_sections(pages: dict[int, str], toc: TOCData) -> tuple[str, str, str]:
    change_pages = _collect_candidate_pages(
        pages, toc.change_mgmt_pages, _SHEET6_RULES["change_mgmt"]
    )
    access_pages = _collect_candidate_pages(
        pages, toc.access_mgmt_pages, _SHEET6_RULES["access_mgmt"]
    )
    job_pages = _collect_candidate_pages(
        pages, toc.job_scheduling_pages, _SHEET6_RULES["job_scheduling"]
    )

    print(
        "[EXTRACTOR] Sheet 6 candidate pages: "
        f"change={change_pages}, access={access_pages}, job={job_pages}",
        flush=True,
    )

    return (
        _format_pages(pages, change_pages),
        _format_pages(pages, access_pages),
        _format_pages(pages, job_pages),
    )


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
    print(
        f"[EXTRACTOR] Sheet 6 input chars: cm={len(cm)}, am={len(am)}, js={len(js)}",
        flush=True,
    )
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


# Progress percentages: (start, end) for each step
_STEP_PCT = {
    "toc": (5, 15),
    2:     (15, 30),
    3:     (30, 45),
    6:     (45, 65),
    7:     (65, 80),
    8:     (80, 95),
}


def extract(
    parsed_path: Path,
    sheets: list[int] | None = None,
    progress_cb: Callable[[str, int], None] | None = None,
) -> ExtractedFormData:
    if sheets is None:
        sheets = [2, 3, 6, 7, 8]

    def _cb(step: str, pct: int) -> None:
        if progress_cb:
            progress_cb(step, pct)

    pages = load_parsed(parsed_path)

    _cb("Locating sections (TOC)", _STEP_PCT["toc"][0])
    toc = _parse_toc(pages)
    print(f"[EXTRACTOR] TOC: system={toc.system_name}, opinion={toc.opinion_pages}, cm={toc.change_mgmt_pages}", flush=True)
    _cb("Sections located", _STEP_PCT["toc"][1])

    result = ExtractedFormData(system_name=toc.system_name)

    if 2 in sheets:
        logger.info("Starting Sheet 2 extraction")
        _cb("Extracting report metadata (Sheet 2)", _STEP_PCT[2][0])
        result.sheet2 = _extract_sheet2(extract_section(pages, toc.opinion_pages))
        logger.info("Sheet 2 done: %s", result.sheet2)
        _cb("Sheet 2 done", _STEP_PCT[2][1])

    if 3 in sheets:
        logger.info("Starting Sheet 3 extraction")
        _cb("Extracting opinion & exceptions (Sheet 3)", _STEP_PCT[3][0])
        result.sheet3 = _extract_sheet3(extract_section(pages, toc.opinion_pages))
        logger.info("Sheet 3 done: qualified=%s, exceptions=%d",
                    result.sheet3.has_qualified_opinion, len(result.sheet3.exceptions))
        _cb("Sheet 3 done", _STEP_PCT[3][1])

    if 6 in sheets:
        logger.info("Starting Sheet 6 extraction")
        _cb("Extracting ITGC controls (Sheet 6)", _STEP_PCT[6][0])
        cm_text, am_text, js_text = _collect_sheet6_candidate_sections(pages, toc)
        result.sheet6 = _extract_sheet6(
            cm_text,
            am_text,
            js_text,
        )
        logger.info("Sheet 6 done")
        _cb("Sheet 6 done", _STEP_PCT[6][1])

    if 7 in sheets:
        logger.info("Starting Sheet 7 extraction")
        _cb("Identifying subservice organizations (Sheet 7)", _STEP_PCT[7][0])
        result.sheet7 = _extract_sheet7(extract_section(pages, toc.subservice_pages))
        logger.info("Sheet 7 done: has_subservice=%s", result.sheet7.has_subservice)
        _cb("Sheet 7 done", _STEP_PCT[7][1])

    if 8 in sheets:
        logger.info("Starting Sheet 8 extraction")
        _cb("Extracting CUECs (Sheet 8)", _STEP_PCT[8][0])
        result.sheet8 = _extract_sheet8(extract_section(pages, toc.cuec_pages))
        logger.info("Sheet 8 done: cuecs=%d", len(result.sheet8.cuecs))
        _cb("Sheet 8 done", _STEP_PCT[8][1])

    return result
