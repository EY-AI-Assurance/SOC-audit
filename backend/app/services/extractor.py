import logging
import json
import re
from pathlib import Path
from typing import Callable

from app.config import settings

logger = logging.getLogger(__name__)
from app.models.extraction import (
    CSOCItem, CUECItem, ExceptionItem, ExtractedFormData,
    ITGCSection, QualifiedOpinion,
    Sheet2Data, Sheet3Data, Sheet6Data, Sheet7Data, Sheet8Data, Sheet9Data,
    SubserviceOrg, TOCData,
)
from app.services.dify_client import dify_client
from app.services.pdf_parser import load_parsed


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

_SHEET8_START_PHRASES = [
    "complementary user entity controls",
    "customer responsibilities",
    "user control considerations",
    "user entity responsibilities",
    "customer control considerations",
]

_SHEET8_STOP_PHRASES = [
    "complementary subservice organization controls",
    "complementary sub-service organization controls",
    "subservice organization controls",
    "sub-service organization controls",
    "section iv - description",
    "section iv – description",
    "section v",
    "other information",
]

_SHEET8_RESPONSIBILITY_PHRASES = [
    "user entities should",
    "user entities are responsible",
    "customers are responsible",
    "customer administrators are responsible",
    "clients should",
]

_SHEET8_BULLET_PATTERN = r"\s*[•▪●◼■\uf06e]\s*"
_SHEET8_CLEAN_CHUNK_SIZE = 12


def _prompt(name: str, **kwargs) -> str:
    return (settings.prompts_dir / name).read_text(encoding="utf-8").format(**kwargs)


def _parse_toc(pages: dict[int, str]) -> TOCData:
    toc_text = "\n\n".join(
        f"[Page {p}]\n{pages[p]}"
        for p in range(1, settings.toc_max_pages + 1)
        if p in pages
    )
    return TOCData(**dify_client.call_json(_prompt("toc.txt", toc_text=toc_text)))


def _detect_report_page_number(text: str) -> int | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    page_number_candidates: list[tuple[int, int]] = []

    for index, line in enumerate(lines):
        match = re.fullmatch(r"-?\s*(\d{1,4})\s*-?", line)
        if match:
            page_number_candidates.append((index, int(match.group(1))))

    for index, page_number in page_number_candidates:
        previous_context = " ".join(lines[max(0, index - 4):index]).lower()
        if (
            "intended solely" in previous_context
            or "should not be, used" in previous_context
            or "should not be used" in previous_context
        ):
            return page_number

    for index, page_number in page_number_candidates:
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if page_number > 5 and next_line.startswith("|"):
            return page_number

    return page_number_candidates[-1][1] if page_number_candidates else None


def _build_page_number_maps(pages: dict[int, str]) -> tuple[dict[int, set[int]], dict[int, int]]:
    report_to_pdf: dict[int, set[int]] = {}
    pdf_to_report: dict[int, int] = {}

    for pdf_page, text in pages.items():
        report_page = _detect_report_page_number(text)
        if report_page is None:
            continue
        report_to_pdf.setdefault(report_page, set()).add(pdf_page)
        pdf_to_report[pdf_page] = report_page

    return report_to_pdf, pdf_to_report


def _pages_from_range(
    page_range: list[int],
    all_pages: set[int],
    report_to_pdf_page: dict[int, set[int]] | None = None,
) -> set[int]:
    if not page_range or len(page_range) != 2 or page_range == [0, 0]:
        return set()
    start, end = page_range
    if start > end:
        start, end = end, start

    if report_to_pdf_page:
        mapped_pages: set[int] = set()
        for report_page in range(start, end + 1):
            mapped_pages.update(
                pdf_page
                for pdf_page in report_to_pdf_page.get(report_page, set())
                if pdf_page in all_pages
            )
        if mapped_pages:
            return mapped_pages

    return {p for p in range(start, end + 1) if p in all_pages}


def _expand_pages(page_numbers: set[int], all_pages: set[int], window: int = 1) -> set[int]:
    expanded: set[int] = set()
    for page_number in page_numbers:
        for candidate in range(page_number - window, page_number + window + 1):
            if candidate in all_pages:
                expanded.add(candidate)
    return expanded


def _format_pages(
    pages: dict[int, str],
    page_numbers: list[int],
    pdf_to_report_page: dict[int, int] | None = None,
) -> str:
    formatted_pages = []
    for page_number in page_numbers:
        if page_number not in pages:
            continue
        report_page = (pdf_to_report_page or {}).get(page_number)
        if report_page is None:
            header = f"[PDF Page {page_number}]"
        else:
            header = f"[PDF Page {page_number} / Report Page {report_page}]"
        formatted_pages.append(f"{header}\n{pages[page_number]}")

    return "\n\n---\n\n".join(formatted_pages)


def _detect_report_label(text: str) -> str:
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"\b[a-zA-Z]{3,}\b", text))
    return "CN Report" if cjk_chars > latin_words * 0.35 else "EN Report"


def _normalize_page_refs(page_refs: str, report_label: str) -> str:
    if not page_refs.strip():
        return ""

    lines = [
        line.strip()
        for line in page_refs.replace("\r\n", "\n").split("\n")
        if line.strip()
    ]
    lines = [
        line
        for line in lines
        if not re.fullmatch(r"(CN|EN)\s+Report:?", line, flags=re.IGNORECASE)
    ]
    if not lines:
        return ""
    return f"{report_label}:\n" + "\n".join(lines)


def _collect_candidate_pages(
    pages: dict[int, str],
    toc_range: list[int],
    rules: dict,
    report_to_pdf_page: dict[int, set[int]],
) -> list[int]:
    all_pages = set(pages)
    toc_pages = _pages_from_range(toc_range, all_pages, report_to_pdf_page)
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


def _section_from_toc_range(
    pages: dict[int, str],
    page_range: list[int],
    report_to_pdf_page: dict[int, set[int]],
    pdf_to_report_page: dict[int, int],
) -> str:
    page_numbers = sorted(
        _pages_from_range(page_range, set(pages), report_to_pdf_page)
    )
    return _format_pages(pages, page_numbers, pdf_to_report_page)


def _collect_sheet6_candidate_sections(
    pages: dict[int, str],
    toc: TOCData,
    report_to_pdf_page: dict[int, set[int]],
    pdf_to_report_page: dict[int, int],
) -> tuple[str, str, str]:
    change_pages = _collect_candidate_pages(
        pages, toc.change_mgmt_pages, _SHEET6_RULES["change_mgmt"], report_to_pdf_page
    )
    access_pages = _collect_candidate_pages(
        pages, toc.access_mgmt_pages, _SHEET6_RULES["access_mgmt"], report_to_pdf_page
    )
    job_pages = _collect_candidate_pages(
        pages, toc.job_scheduling_pages, _SHEET6_RULES["job_scheduling"], report_to_pdf_page
    )

    print(
        "[EXTRACTOR] Sheet 6 candidate pages: "
        f"change={change_pages}, access={access_pages}, job={job_pages}",
        flush=True,
    )

    return (
        _format_pages(pages, change_pages, pdf_to_report_page),
        _format_pages(pages, access_pages, pdf_to_report_page),
        _format_pages(pages, job_pages, pdf_to_report_page),
    )


def _collect_sheet8_candidate_section(
    pages: dict[int, str],
    toc: TOCData,
    report_to_pdf_page: dict[int, set[int]],
    pdf_to_report_page: dict[int, int],
) -> str:
    all_pages = set(pages)
    toc_candidates = _pages_from_range(
        toc.cuec_pages, all_pages, report_to_pdf_page
    )
    candidates: set[int] = set()

    sorted_pages = sorted(pages)
    collecting = False
    section_pages: set[int] = set()

    def _is_sheet8_start_page(page_text: str) -> bool:
        lowered_text = page_text.lower()
        lines = [line.strip().lower() for line in page_text.splitlines()]
        has_heading = any(line in _SHEET8_START_PHRASES for line in lines)
        has_table_header = (
            "complementary user entity controls" in lowered_text
            and ("control objective" in lowered_text or "related control objective" in lowered_text)
            and any(phrase in lowered_text for phrase in _SHEET8_RESPONSIBILITY_PHRASES)
        )
        return has_heading or has_table_header

    for page_number in sorted_pages:
        text = pages[page_number]
        lowered = text.lower()
        is_toc_page = page_number <= settings.toc_max_pages and "table of contents" in lowered

        if (
            not collecting
            and not is_toc_page
            and _is_sheet8_start_page(text)
        ):
            collecting = True

        if collecting and page_number not in section_pages:
            if section_pages and any(phrase in lowered for phrase in _SHEET8_STOP_PHRASES):
                break
            section_pages.add(page_number)

    if section_pages:
        candidates.update(section_pages)
    else:
        candidates.update(toc_candidates)

    if not section_pages:
        for page_number, text in pages.items():
            lowered = text.lower()
            has_table_header = (
                "complementary user entity controls" in lowered
                and ("control objective" in lowered or "related control objective" in lowered)
            )
            if has_table_header:
                candidates.add(page_number)

    candidate_pages = sorted(candidates)
    print(
        f"[EXTRACTOR] Sheet 8 candidate pages: {candidate_pages}",
        flush=True,
    )
    return _format_pages(pages, candidate_pages, pdf_to_report_page)


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


def _extract_sheet6(cm: str, am: str, js: str, report_label: str) -> Sheet6Data:
    print(
        f"[EXTRACTOR] Sheet 6 input chars: cm={len(cm)}, am={len(am)}, js={len(js)}",
        flush=True,
    )
    raw = dify_client.call_json(
        _prompt("sheet6_itgc.txt", report_label=report_label, cm_text=cm, am_text=am, js_text=js)
    )
    data = Sheet6Data(
        change_mgmt=ITGCSection(**raw["change_mgmt"]),
        access_mgmt=ITGCSection(**raw["access_mgmt"]),
        job_scheduling=ITGCSection(**raw["job_scheduling"]),
    )
    data.change_mgmt.page_refs = _normalize_page_refs(data.change_mgmt.page_refs, report_label)
    data.access_mgmt.page_refs = _normalize_page_refs(data.access_mgmt.page_refs, report_label)
    data.job_scheduling.page_refs = _normalize_page_refs(data.job_scheduling.page_refs, report_label)
    return data


def _extract_sheet7(text: str) -> Sheet7Data:
    raw  = dify_client.call_json(_prompt("sheet7_subservice.txt", section_text=text))
    orgs = [SubserviceOrg(**o) for o in raw.get("organizations", [])]
    return Sheet7Data(has_subservice=raw["has_subservice"], organizations=orgs)


def _prepare_sheet8_text(text: str) -> tuple[str, list[CUECItem]]:
    """
    Preserve cross-page CUEC table context for the LLM.

    In SOC reports, CUEC tables often have a left "Control Objective" cell that
    spans multiple rows/pages. pdfplumber converts continuation rows to a blank
    first column, so we explicitly carry forward the last non-empty objective.

    Some reports use the reverse layout:
    "Complementary User Entity Controls" in the left column and "Related Control
    Objectives" in the right column. Those rows are normalized to the standard
    "| Control Objective | Complementary User Entity Controls |" order before
    being sent to the LLM.
    """
    prepared_lines: list[str] = []
    normalized_items: list[tuple[int | None, str, str]] = []
    current_objective = ""
    current_page: int | None = None
    inherited_count = 0
    reversed_rows = 0
    table_orientation = "objective_left"

    def _logical_lines(raw_text: str) -> list[str]:
        logical_lines: list[str] = []
        current_row = ""

        for raw_line in raw_text.splitlines():
            stripped_line = raw_line.strip()
            starts_table_row = stripped_line.startswith("|")
            ends_table_row = stripped_line.endswith("|")
            is_boundary = (
                re.match(r"^\[(?:Page|PDF Page)\s+\d+(?:\s*/\s*Report Page\s+\d+)?\]$", stripped_line)
                or stripped_line == "---"
            )

            if current_row:
                if is_boundary:
                    logical_lines.append(current_row)
                    current_row = ""
                    logical_lines.append(raw_line)
                    continue
                if starts_table_row:
                    logical_lines.append(current_row)
                    current_row = raw_line
                    if ends_table_row:
                        logical_lines.append(current_row)
                        current_row = ""
                    continue

                current_row += "\n" + stripped_line
                if ends_table_row:
                    logical_lines.append(current_row)
                    current_row = ""
                continue

            if starts_table_row and not ends_table_row:
                current_row = raw_line
                continue

            logical_lines.append(raw_line)

        if current_row:
            logical_lines.append(current_row)

        return logical_lines

    def _looks_like_cuec_responsibility(text_part: str) -> bool:
        lowered = text_part.lower()
        lowered = re.sub(r"(?<=[a-z])\d+(?=[a-z])", "", lowered)
        lowered = re.sub(r"\b\d+(?=[a-z])", "", lowered)
        lowered = lowered.replace("entitie-s", "entities")
        return any(phrase in lowered for phrase in _SHEET8_RESPONSIBILITY_PHRASES)

    def _add_cuec_items(page_number: int | None, objective: str, cuec_text: str) -> None:
        normalized_objective = " ".join(objective.split())
        normalized_text = " ".join(cuec_text.split())
        if not normalized_text:
            return

        parts = [
            part.strip()
            for part in re.split(_SHEET8_BULLET_PATTERN, normalized_text)
            if part.strip()
        ]
        if not parts:
            return

        if not re.match(_SHEET8_BULLET_PATTERN, normalized_text.lstrip()) and normalized_items:
            previous_page, previous_objective, previous_text = normalized_items[-1]
            if not re.search(r"[.;。；]$", previous_text):
                normalized_items[-1] = (
                    previous_page,
                    previous_objective,
                    f"{previous_text} {parts[0]}",
                )
                parts = parts[1:]

        for part in parts:
            if _looks_like_cuec_responsibility(part):
                normalized_items.append((page_number, normalized_objective, part))

    for line in _logical_lines(text):
        stripped = line.strip()
        page_match = re.match(
            r"^\[(?:Page|PDF Page)\s+(\d+)(?:\s*/\s*Report Page\s+(\d+))?\]$",
            stripped,
        )
        if page_match:
            current_page = int(page_match.group(2) or page_match.group(1))
            prepared_lines.append(line)
            continue

        if not stripped.startswith("|") or stripped.count("|") < 2:
            prepared_lines.append(line)
            continue

        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            prepared_lines.append(line)
            continue

        first_cell, second_cell = cells[0], cells[1]
        lowered_first = first_cell.lower()
        lowered_second = second_cell.lower()

        if "complementary user entity" in lowered_first and (
            "related control objective" in lowered_second
            or "control objective" in lowered_second
        ):
            table_orientation = "cuec_left"
            prepared_lines.append(
                "| Control Objective | Complementary User Entity Controls |"
            )
            continue

        if "control objective" in lowered_first and "complementary user entity" in lowered_second:
            table_orientation = "objective_left"
            prepared_lines.append(line)
            continue

        is_header = (
            "control objective" in lowered_first
            or "complementary user entity" in lowered_second
            or bool(first_cell) and set(first_cell) <= {"-"}
        )

        if is_header:
            prepared_lines.append(line)
            continue

        if table_orientation == "cuec_left":
            cuec_text, objective = first_cell, second_cell
            if objective:
                current_objective = objective
            elif current_objective and cuec_text:
                objective = f"{current_objective} [continued from previous row/page]"
                inherited_count += 1

            if cuec_text:
                prepared_lines.append(f"| {objective} | {cuec_text} |")
                _add_cuec_items(current_page, objective, cuec_text)
                reversed_rows += 1
            else:
                prepared_lines.append(line)
            continue

        objective, cuec_text = first_cell, second_cell

        if objective:
            current_objective = objective
            prepared_lines.append(line)
            _add_cuec_items(current_page, objective, cuec_text)
            continue

        if current_objective and cuec_text:
            cells[0] = f"{current_objective} [continued from previous row/page]"
            prepared_lines.append("| " + " | ".join(cells) + " |")
            _add_cuec_items(current_page, current_objective, cuec_text)
            inherited_count += 1
        else:
            prepared_lines.append(line)

    note = (
        "CUEC TABLE CONTINUITY NOTE:\n"
        "- Some PDF tables span multiple pages. Rows whose Control Objective was blank "
        "have been filled with the nearest preceding objective and marked as "
        "'[continued from previous row/page]'.\n"
        "- If a bullet sentence starts on one page and continues on the next page, merge "
        "the continuation into the same CUEC item.\n"
        "- Each bullet point under the Complementary User Entity Controls column is one "
        "separate Form 107-A Sheet 8 row.\n"
        "- Some reports put Complementary User Entity Controls in the left column and "
        "Related Control Objectives in the right column. Those rows have been normalized "
        "to objective-first table order.\n"
        f"- Number of rows with inherited objective context: {inherited_count}.\n"
        f"- Number of reversed-layout rows normalized: {reversed_rows}.\n"
    )
    candidate_lines = [
        "NORMALIZED CUEC ITEM CANDIDATES:",
        "The following candidates were deterministically split from parsed tables. "
        "Use them as the primary extraction source, preserving order and wording.",
    ]
    deterministic_cuecs: list[CUECItem] = []
    seen_cuecs: set[tuple[str, str]] = set()
    for index, (page_number, objective, description) in enumerate(normalized_items, start=1):
        page_ref = f"Page {page_number}" if page_number else "Page unknown"
        candidate_lines.append(
            f"{index}. [{page_ref}] [Objective: {objective}] {description}"
        )
        objective_clean = objective.replace("[continued from previous row/page]", "").strip()
        objective_and_page = (
            f"{objective_clean} Page {page_number}"
            if page_number
            else objective_clean
        )
        key = (objective_and_page, description)
        if key not in seen_cuecs:
            deterministic_cuecs.append(
                CUECItem(
                    objective_and_page=objective_and_page,
                    description=description,
                )
            )
            seen_cuecs.add(key)

    prepared_text = (
        note
        + "\n"
        + "\n".join(candidate_lines)
        + "\n\nRAW CUEC SECTION:\n"
        + "\n".join(prepared_lines)
    )
    return prepared_text, deterministic_cuecs


def _extract_sheet8(text: str) -> Sheet8Data:
    prepared_text, deterministic_cuecs = _prepare_sheet8_text(text)
    print(
        "[EXTRACTOR] Sheet 8 input chars: "
        f"raw={len(text)}, prepared={len(prepared_text)}, "
        f"deterministic_cuecs={len(deterministic_cuecs)}",
        flush=True,
    )

    if len(deterministic_cuecs) >= 2:
        return Sheet8Data(cuecs=_clean_sheet8_cuecs(deterministic_cuecs))

    raw   = dify_client.call_json(_prompt("sheet8_cuec.txt", section_text=prepared_text))
    cuecs = [CUECItem(**c) for c in raw.get("cuecs", [])]
    return Sheet8Data(cuecs=_clean_sheet8_cuecs(cuecs) if len(cuecs) >= 2 else cuecs)


def _clean_sheet8_cuecs(cuecs: list[CUECItem]) -> list[CUECItem]:
    cleaned: list[CUECItem] = []

    for start in range(0, len(cuecs), _SHEET8_CLEAN_CHUNK_SIZE):
        chunk = cuecs[start:start + _SHEET8_CLEAN_CHUNK_SIZE]
        payload = [
            {
                "index": start + offset + 1,
                "objective_and_page": item.objective_and_page,
                "description": item.description,
            }
            for offset, item in enumerate(chunk)
        ]

        try:
            raw = dify_client.call_json(
                _prompt(
                    "sheet8_clean_cuec.txt",
                    items_json=json.dumps(payload, ensure_ascii=False, indent=2),
                )
            )
            returned = raw.get("cuecs", []) if isinstance(raw, dict) else raw
            if not isinstance(returned, list):
                raise ValueError("Sheet 8 clean response must be a JSON object or array")
        except Exception as exc:
            print(f"[EXTRACTOR] Sheet 8 clean failed, keeping original chunk: {exc}", flush=True)
            cleaned.extend(chunk)
            continue

        if len(returned) != len(chunk):
            print(
                "[EXTRACTOR] Sheet 8 clean count mismatch, keeping original chunk: "
                f"expected={len(chunk)}, got={len(returned)}",
                flush=True,
            )
            cleaned.extend(chunk)
            continue

        chunk_cleaned: list[CUECItem] = []
        valid = True
        for original, returned_item, expected in zip(chunk, returned, payload):
            if returned_item.get("index") != expected["index"]:
                valid = False
                break
            chunk_cleaned.append(
                CUECItem(
                    objective_and_page=returned_item.get(
                        "objective_and_page",
                        original.objective_and_page,
                    ),
                    description=returned_item.get("description", original.description),
                )
            )

        if valid:
            cleaned.extend(chunk_cleaned)
        else:
            print("[EXTRACTOR] Sheet 8 clean index mismatch, keeping original chunk", flush=True)
            cleaned.extend(chunk)

    print(
        f"[EXTRACTOR] Sheet 8 cleaned CUECs: input={len(cuecs)}, output={len(cleaned)}",
        flush=True,
    )
    return cleaned


def _extract_sheet9(text: str) -> Sheet9Data:
    raw = dify_client.call_json(_prompt("sheet9_csoc.txt", section_text=text))
    raw_csocs = raw.get("csocs", []) if isinstance(raw, dict) else raw
    if not isinstance(raw_csocs, list):
        raise ValueError("Sheet 9 response must be a JSON object with 'csocs' or a JSON array")
    csocs = [CSOCItem(**c) for c in raw_csocs]
    return Sheet9Data(csocs=csocs)


# Progress percentages: (start, end) for each step
_STEP_PCT = {
    "toc": (5, 15),
    2:     (15, 30),
    3:     (30, 45),
    6:     (45, 65),
    7:     (65, 80),
    8:     (80, 95),
    9:     (95, 98),
}


def extract(
    parsed_path: Path,
    sheets: list[int] | None = None,
    progress_cb: Callable[[str, int], None] | None = None,
) -> ExtractedFormData:
    if sheets is None:
        sheets = [2, 3, 6, 7, 8, 9]

    def _cb(step: str, pct: int) -> None:
        if progress_cb:
            progress_cb(step, pct)

    pages = load_parsed(parsed_path)
    report_to_pdf_page, pdf_to_report_page = _build_page_number_maps(pages)

    _cb("Locating sections (TOC)", _STEP_PCT["toc"][0])
    toc = _parse_toc(pages)
    print(f"[EXTRACTOR] TOC: system={toc.system_name}, opinion={toc.opinion_pages}, cm={toc.change_mgmt_pages}", flush=True)
    print(
        "[EXTRACTOR] Page map sample: "
        f"{dict(list(sorted(report_to_pdf_page.items()))[:8])}",
        flush=True,
    )
    _cb("Sections located", _STEP_PCT["toc"][1])

    result = ExtractedFormData(system_name=toc.system_name)

    if 2 in sheets:
        logger.info("Starting Sheet 2 extraction")
        _cb("Extracting report metadata (Sheet 2)", _STEP_PCT[2][0])
        result.sheet2 = _extract_sheet2(
            _section_from_toc_range(
                pages, toc.opinion_pages, report_to_pdf_page, pdf_to_report_page
            )
        )
        logger.info("Sheet 2 done: %s", result.sheet2)
        _cb("Sheet 2 done", _STEP_PCT[2][1])

    if 3 in sheets:
        logger.info("Starting Sheet 3 extraction")
        _cb("Extracting opinion & exceptions (Sheet 3)", _STEP_PCT[3][0])
        result.sheet3 = _extract_sheet3(
            _section_from_toc_range(
                pages, toc.opinion_pages, report_to_pdf_page, pdf_to_report_page
            )
        )
        logger.info("Sheet 3 done: qualified=%s, exceptions=%d",
                    result.sheet3.has_qualified_opinion, len(result.sheet3.exceptions))
        _cb("Sheet 3 done", _STEP_PCT[3][1])

    if 6 in sheets:
        logger.info("Starting Sheet 6 extraction")
        _cb("Extracting ITGC controls (Sheet 6)", _STEP_PCT[6][0])
        cm_text, am_text, js_text = _collect_sheet6_candidate_sections(
            pages, toc, report_to_pdf_page, pdf_to_report_page
        )
        sheet6_report_label = _detect_report_label("\n\n".join([cm_text, am_text, js_text]))
        result.sheet6 = _extract_sheet6(
            cm_text,
            am_text,
            js_text,
            sheet6_report_label,
        )
        logger.info("Sheet 6 done")
        _cb("Sheet 6 done", _STEP_PCT[6][1])

    if 7 in sheets:
        logger.info("Starting Sheet 7 extraction")
        _cb("Identifying subservice organizations (Sheet 7)", _STEP_PCT[7][0])
        result.sheet7 = _extract_sheet7(
            _section_from_toc_range(
                pages, toc.subservice_pages, report_to_pdf_page, pdf_to_report_page
            )
        )
        logger.info("Sheet 7 done: has_subservice=%s", result.sheet7.has_subservice)
        _cb("Sheet 7 done", _STEP_PCT[7][1])

    if 8 in sheets:
        logger.info("Starting Sheet 8 extraction")
        _cb("Extracting CUECs (Sheet 8)", _STEP_PCT[8][0])
        result.sheet8 = _extract_sheet8(
            _collect_sheet8_candidate_section(
                pages, toc, report_to_pdf_page, pdf_to_report_page
            )
        )
        logger.info("Sheet 8 done: cuecs=%d", len(result.sheet8.cuecs))
        _cb("Sheet 8 done", _STEP_PCT[8][1])

    if 9 in sheets:
        logger.info("Starting Sheet 9 extraction")
        _cb("Extracting CSOCs (Sheet 9)", _STEP_PCT[9][0])
        sheet7_for_dependency = result.sheet7 or _extract_sheet7(
            _section_from_toc_range(
                pages, toc.subservice_pages, report_to_pdf_page, pdf_to_report_page
            )
        )
        if sheet7_for_dependency.has_subservice:
            result.sheet9 = _extract_sheet9(
                _section_from_toc_range(
                    pages, toc.csoc_pages, report_to_pdf_page, pdf_to_report_page
                )
            )
        else:
            result.sheet9 = Sheet9Data(csocs=[])
        logger.info("Sheet 9 done: csocs=%d", len(result.sheet9.csocs))
        _cb("Sheet 9 done", _STEP_PCT[9][1])

    return result
