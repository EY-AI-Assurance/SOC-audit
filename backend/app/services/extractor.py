import logging
import json
import re
from difflib import SequenceMatcher
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
from app.services.dify_client import LLMClient
from app.services.pdf_parser import load_parsed
from app.services.retrieval import (
    LoadedSearchProfile,
    RetrievalContext,
    RetrievalResult,
    load_search_profiles,
    normalize_text,
)

_SHEET8_START_PHRASES = [
    "complementary user entity controls",
    "customer responsibilities",
    "user control considerations",
    "user entity responsibilities",
    "customer control considerations",
    "cuec",
    "cuecs",
    "补充性用户实体控制",
    "补偿性用户实体控制",
    "用户实体控制",
    "客户责任",
    "用户实体责任",
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
    "补充性子服务机构控制",
    "补偿性子服务机构控制",
    "其他信息",
]

_SHEET8_RESPONSIBILITY_SUBJECTS = [
    "user entity",
    "user entities",
    "customer",
    "customers",
    "client",
    "clients",
    "customer administrator",
    "customer administrators",
    "用户实体",
    "客户",
    "客户管理员",
]

_SHEET8_RESPONSIBILITY_ACTIONS = [
    "should",
    "must",
    "responsible",
    "expected to",
    "required to",
    "ensure",
    "implement",
    "maintain",
    "establish",
    "review",
    "monitor",
    "approve",
    "configure",
    "应当",
    "应该",
    "必须",
    "负责",
    "确保",
    "实施",
    "维护",
    "建立",
    "审查",
    "监控",
    "批准",
    "配置",
]

_SHEET8_BULLET_PATTERN = (
    r"(?:"
    r"\s*[•▪●◼■\uf06e]\s*|"
    r"(?:^|\s+)(?:\(?\d{1,3}[.)]|[A-Za-z][.)])\s+|"
    r"(?:^|\s+)[（(]?[一二三四五六七八九十]+[、.)）]\s*"
    r")"
)
_SHEET8_LIST_LINE_PATTERN = re.compile(
    r"^\s*(?:"
    r"[•▪●◼■\uf06e*-]\s*|"
    r"\(?\d{1,3}[.)]\s+|"
    r"[A-Za-z][.)]\s+|"
    r"[（(]?[一二三四五六七八九十]+[、.)）]\s*"
    r")"
)
_SHEET8_HEADING_PREFIX_PATTERN = re.compile(
    r"^(?:(?:section|chapter|part)\s+)?"
    r"(?:[ivxlcdm]+|\d+(?:\.\d+)*)"
    r"(?:\s*[.):\-–—]\s*|\s+)",
    flags=re.IGNORECASE,
)
_SHEET8_CHINESE_HEADING_PREFIX_PATTERN = re.compile(
    r"^(?:"
    r"[（(]?[一二三四五六七八九十百]+[、.)）]\s*|"
    r"第[一二三四五六七八九十百\d]+(?:章|节|部分)\s*"
    r")"
)
_SHEET8_CLEAN_CHUNK_SIZE = 12
_SHEET8_STRUCTURAL_LABELS = {
    "complementary user entity controls",
    "control objective",
    "related control objective",
    "responsibilities of user entities",
}


def _prompt(name: str, **kwargs) -> str:
    return (settings.prompts_dir / name).read_text(encoding="utf-8").format(**kwargs)


def _parse_toc(llm_client: LLMClient, pages: dict[int, str]) -> TOCData:
    toc_text = "\n\n".join(
        f"[Page {p}]\n{pages[p]}"
        for p in range(1, settings.toc_max_pages + 1)
        if p in pages
    )
    return TOCData(**llm_client.call_json(_prompt("toc.txt", toc_text=toc_text)))


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


def _cover_pages_text(
    pages: dict[int, str],
    pdf_to_report_page: dict[int, int],
    max_pages: int = 3,
) -> str:
    page_numbers = [page for page in range(1, max_pages + 1) if page in pages]
    return _format_pages(pages, page_numbers, pdf_to_report_page)


def _retrieve_topic(
    context: RetrievalContext,
    profile: LoadedSearchProfile,
    topic: str,
    toc_range: list[int],
    report_to_pdf_page: dict[int, set[int]],
) -> RetrievalResult:
    try:
        topic_profile = profile.topics[topic]
    except KeyError as exc:
        raise ValueError(
            f"Search profile '{profile.name}' is missing topic '{topic}'"
        ) from exc

    toc_pages = _pages_from_range(
        toc_range,
        set(context.pages),
        report_to_pdf_page,
    )
    return context.retrieve(topic, topic_profile, toc_pages, profile)


def _format_retrieval_batches(
    pages: dict[int, str],
    retrieval: RetrievalResult,
    pdf_to_report_page: dict[int, int],
) -> list[str]:
    return [
        _format_pages(pages, batch, pdf_to_report_page)
        for batch in retrieval.batches
    ]


def _sheet8_heading_key(value: str) -> str:
    normalized = normalize_text(value).strip(" .:;|\t-–—")
    normalized = _SHEET8_HEADING_PREFIX_PATTERN.sub("", normalized, count=1)
    normalized = _SHEET8_CHINESE_HEADING_PREFIX_PATTERN.sub("", normalized, count=1)
    return re.sub(
        r"[^a-z0-9\u3400-\u4dbf\u4e00-\u9fff]+",
        " ",
        normalized,
    ).strip()


def _sheet8_heading_candidates(text: str) -> list[str]:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not re.match(r"^\[(?:Page|PDF Page)\s+\d+", line.strip())
    ]
    candidates = list(lines)
    for width in (2, 3):
        candidates.extend(
            " ".join(lines[index:index + width])
            for index in range(len(lines) - width + 1)
        )
    return candidates


def _has_sheet8_heading(text: str, phrases: list[str]) -> bool:
    phrase_keys = {_sheet8_heading_key(phrase) for phrase in phrases}
    phrase_raw = {
        normalize_text(phrase).strip(" .:;|\t-–—")
        for phrase in phrases
    }
    for candidate in _sheet8_heading_candidates(text):
        candidate_raw = normalize_text(candidate).strip(" .:;|\t-–—")
        candidate_key = _sheet8_heading_key(candidate)
        if candidate_raw in phrase_raw or candidate_key in phrase_keys:
            return True
        if any(
            candidate_key == f"{phrase_key} {suffix}"
            for phrase_key in phrase_keys
            for suffix in ("cuec", "cuecs", "csoc", "csocs")
        ):
            return True
    return False


def _sheet8_table_row_count(text: str) -> int:
    return sum(
        1
        for line in text.splitlines()
        if line.strip().startswith("|")
        and line.strip().count("|") >= 2
        and not re.fullmatch(r"[|:\-\s]+", line.strip())
    )


def _is_sheet8_responsibility_line(line: str) -> bool:
    normalized = normalize_text(line)
    return (
        any(subject in normalized for subject in _SHEET8_RESPONSIBILITY_SUBJECTS)
        and any(action in normalized for action in _SHEET8_RESPONSIBILITY_ACTIONS)
    )


def _sheet8_list_line_count(text: str) -> int:
    return sum(
        1 for line in text.splitlines()
        if _SHEET8_LIST_LINE_PATTERN.match(line)
    )


def _is_sheet8_table_header_page(text: str) -> bool:
    objective_headers = (
        "control objective",
        "related control objective",
        "控制目标",
        "相关控制目标",
    )
    cuec_headers = (
        "complementary user entity control",
        "customer responsibilities",
        "user entity responsibilities",
        "customer control considerations",
        "user control considerations",
        "补充性用户实体控制",
        "补偿性用户实体控制",
        "客户责任",
        "用户实体责任",
    )
    for line in text.splitlines():
        normalized_line = normalize_text(line)
        if (
            any(header in normalized_line for header in objective_headers)
            and any(header in normalized_line for header in cuec_headers)
        ):
            return True
    return False


def _is_sheet8_dense_responsibility_list(text: str) -> bool:
    responsibility_items = sum(
        1
        for line in text.splitlines()
        if _SHEET8_LIST_LINE_PATTERN.match(line)
        and _is_sheet8_responsibility_line(line)
    )
    return responsibility_items >= 2


def _is_sheet8_continuation_page(text: str) -> bool:
    if _has_sheet8_heading(text, _SHEET8_START_PHRASES):
        return True
    if _is_sheet8_table_header_page(text):
        return True
    if _is_sheet8_dense_responsibility_list(text):
        return True
    if _sheet8_table_row_count(text) >= 2:
        return True
    if any(_is_sheet8_responsibility_line(line) for line in text.splitlines()):
        return True
    return _sheet8_list_line_count(text) >= 2


def _collect_sheet8_candidate_section(
    pages: dict[int, str],
    toc: TOCData,
    report_to_pdf_page: dict[int, set[int]],
    pdf_to_report_page: dict[int, int],
) -> str:
    """Locate the dedicated CUEC section without broad full-report retrieval."""
    all_pages = set(pages)
    toc_candidates = _pages_from_range(
        toc.cuec_pages, all_pages, report_to_pdf_page
    )
    if toc_candidates:
        candidate_pages = sorted(toc_candidates)
        print(
            "[EXTRACTOR] Sheet 8 dedicated candidate pages: "
            f"source=toc pages={candidate_pages}",
            flush=True,
        )
        return _format_pages(pages, candidate_pages, pdf_to_report_page)

    start_page: int | None = None
    start_reason = ""
    for page_number in sorted(pages):
        text = pages[page_number]
        normalized = normalize_text(text)
        is_toc_page = (
            page_number <= settings.toc_max_pages
            and ("table of contents" in normalized or "目录" in normalized)
        )
        if is_toc_page:
            continue
        if _has_sheet8_heading(text, _SHEET8_START_PHRASES):
            start_page = page_number
            start_reason = "heading"
            break
        if _is_sheet8_table_header_page(text):
            start_page = page_number
            start_reason = "table_header"
            break
        if _is_sheet8_dense_responsibility_list(text):
            start_page = page_number
            start_reason = "dense_responsibility_list"
            break

    candidate_pages: list[int] = []
    if start_page is not None:
        pending_weak_pages: list[int] = []
        for page_number in sorted(page for page in pages if page >= start_page):
            text = pages[page_number]
            if (
                candidate_pages
                and _has_sheet8_heading(text, _SHEET8_STOP_PHRASES)
            ):
                break

            if page_number == start_page or _is_sheet8_continuation_page(text):
                candidate_pages.extend(pending_weak_pages)
                pending_weak_pages = []
                candidate_pages.append(page_number)
                continue

            pending_weak_pages.append(page_number)
            if len(pending_weak_pages) >= 2:
                break

    print(
        "[EXTRACTOR] Sheet 8 dedicated candidate pages: "
        f"source={start_reason or 'not_found'} pages={candidate_pages}",
        flush=True,
    )
    return _format_pages(pages, candidate_pages, pdf_to_report_page)


def _extract_sheet2(llm_client: LLMClient, cover_text: str, opinion_text: str) -> Sheet2Data:
    return Sheet2Data(**llm_client.call_json(
        _prompt("sheet2_meta.txt", cover_text=cover_text, opinion_text=opinion_text)
    ))


def _extract_sheet3(llm_client: LLMClient, text: str) -> Sheet3Data:
    raw = llm_client.call_json(_prompt("sheet3_opinion.txt", section_text=text))
    opinion    = QualifiedOpinion(**raw["opinion"]) if raw.get("opinion") else None
    exceptions = [ExceptionItem(**e) for e in raw.get("exceptions", [])]
    return Sheet3Data(
        has_qualified_opinion=raw["has_qualified_opinion"],
        opinion=opinion,
        exceptions=exceptions,
    )


def _extract_sheet6(llm_client: LLMClient, cm: str, am: str, js: str, report_label: str) -> Sheet6Data:
    print(
        f"[EXTRACTOR] Sheet 6 input chars: cm={len(cm)}, am={len(am)}, js={len(js)}",
        flush=True,
    )
    raw = llm_client.call_json(
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


def _merge_page_refs(left: str, right: str, report_label: str) -> str:
    entries: list[str] = []
    seen: set[str] = set()
    for value in (left, right):
        for line in value.replace("\r\n", "\n").splitlines():
            stripped = line.strip()
            if not stripped or re.fullmatch(r"(?:CN|EN)\s+Report:?", stripped, re.IGNORECASE):
                continue
            key = normalize_text(stripped)
            if key not in seen:
                entries.append(stripped)
                seen.add(key)
    return f"{report_label}:\n" + "\n".join(entries) if entries else ""


def _merge_control_id_rows(left: list[str], right: list[str]) -> list[str]:
    merged_rows: list[str] = []
    for index in range(max(len(left), len(right))):
        values: list[str] = []
        seen: set[str] = set()
        for rows in (left, right):
            if index >= len(rows):
                continue
            for value in rows[index].splitlines():
                stripped = value.strip()
                key = normalize_text(stripped)
                if stripped and key not in seen:
                    values.append(stripped)
                    seen.add(key)
        merged_rows.append("\n".join(values))
    return merged_rows


def _merge_itgc_sections(
    left: ITGCSection,
    right: ITGCSection,
    report_label: str,
) -> ITGCSection:
    status_priority = {"Not applicable": 0, "No": 1, "Yes": 2}
    has_process_description = max(
        (left.has_process_description, right.has_process_description),
        key=lambda value: status_priority[value],
    )
    return ITGCSection(
        has_process_description=has_process_description,
        page_refs=_merge_page_refs(left.page_refs, right.page_refs, report_label),
        section_b_applicable=(
            "Applicable"
            if "Applicable" in (left.section_b_applicable, right.section_b_applicable)
            else "Not applicable"
        ),
        section_c_applicable=(
            "Applicable"
            if "Applicable" in (left.section_c_applicable, right.section_c_applicable)
            else "Not applicable"
        ),
        risk_control_ids=_merge_control_id_rows(
            left.risk_control_ids,
            right.risk_control_ids,
        ),
    )


def _extract_sheet6_batches(
    llm_client: LLMClient,
    batches: dict[str, list[str]],
    report_label: str,
) -> Sheet6Data:
    field_names = {
        "change_mgmt": "change_mgmt",
        "access_mgmt": "access_mgmt",
        "job_scheduling": "job_scheduling",
    }
    first_text = {
        topic: values[0] if values else ""
        for topic, values in batches.items()
    }
    data = _extract_sheet6(
        llm_client,
        first_text.get("change_mgmt", ""),
        first_text.get("access_mgmt", ""),
        first_text.get("job_scheduling", ""),
        report_label,
    )

    for topic, values in batches.items():
        for extra_text in values[1:]:
            partial = _extract_sheet6(
                llm_client,
                extra_text if topic == "change_mgmt" else "",
                extra_text if topic == "access_mgmt" else "",
                extra_text if topic == "job_scheduling" else "",
                report_label,
            )
            field_name = field_names[topic]
            setattr(
                data,
                field_name,
                _merge_itgc_sections(
                    getattr(data, field_name),
                    getattr(partial, field_name),
                    report_label,
                ),
            )
    return data


def _extract_sheet7(llm_client: LLMClient, text: str) -> Sheet7Data:
    raw  = llm_client.call_json(_prompt("sheet7_subservice.txt", section_text=text))
    orgs = [SubserviceOrg(**o) for o in raw.get("organizations", [])]
    return Sheet7Data(has_subservice=raw["has_subservice"], organizations=orgs)


def _extract_sheet7_batches(llm_client: LLMClient, batches: list[str]) -> Sheet7Data:
    if not batches:
        return Sheet7Data(has_subservice=False, organizations=[])

    organizations: list[SubserviceOrg] = []
    by_name: dict[str, SubserviceOrg] = {}
    has_subservice = False
    for text in batches:
        partial = _extract_sheet7(llm_client, text)
        has_subservice = has_subservice or partial.has_subservice
        for organization in partial.organizations:
            key = normalize_text(organization.name).strip(" .,:;，。；：")
            if not key:
                continue
            existing = by_name.get(key)
            if existing is None:
                by_name[key] = organization
                organizations.append(organization)
                continue
            if (
                normalize_text(organization.services)
                and normalize_text(organization.services) not in normalize_text(existing.services)
            ):
                existing.services = "\n".join(
                    value for value in (existing.services, organization.services) if value.strip()
                )

    return Sheet7Data(
        has_subservice=has_subservice or bool(organizations),
        organizations=organizations,
    )


def _is_sheet8_structural_noise(text: str) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", normalized):
        return True

    label = normalized.lower().strip(" .:;|-")
    return label in _SHEET8_STRUCTURAL_LABELS


def _dedupe_sheet8_cuecs(cuecs: list[CUECItem]) -> list[CUECItem]:
    deduped: list[CUECItem] = []

    for item in cuecs:
        normalized_description = re.sub(
            r"\s+",
            " ",
            item.description.lower(),
        ).strip()
        is_duplicate = False

        for existing in deduped:
            if normalize_text(existing.objective_and_page) != normalize_text(item.objective_and_page):
                continue

            normalized_existing = re.sub(
                r"\s+",
                " ",
                existing.description.lower(),
            ).strip()
            if normalized_existing == normalized_description:
                is_duplicate = True
                break
            if min(len(normalized_existing), len(normalized_description)) < 80:
                continue

            similarity = SequenceMatcher(
                None,
                normalized_existing,
                normalized_description,
            ).ratio()
            if similarity >= 0.95:
                is_duplicate = True
                break

        if not is_duplicate:
            deduped.append(item)

    return deduped


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
            if not _is_sheet8_structural_noise(part):
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


def _extract_sheet8(llm_client: LLMClient, text: str) -> Sheet8Data:
    prepared_text, deterministic_cuecs = _prepare_sheet8_text(text)
    print(
        "[EXTRACTOR] Sheet 8 input chars: "
        f"raw={len(text)}, prepared={len(prepared_text)}, "
        f"deterministic_cuecs={len(deterministic_cuecs)}",
        flush=True,
    )

    if len(deterministic_cuecs) >= 2:
        cleaned_cuecs = _clean_sheet8_cuecs(llm_client, deterministic_cuecs)
        return Sheet8Data(cuecs=_dedupe_sheet8_cuecs(cleaned_cuecs))

    raw   = llm_client.call_json(_prompt("sheet8_cuec.txt", section_text=prepared_text))
    cuecs = [CUECItem(**c) for c in raw.get("cuecs", [])]
    cleaned_cuecs = _clean_sheet8_cuecs(llm_client, cuecs) if len(cuecs) >= 2 else cuecs
    return Sheet8Data(cuecs=_dedupe_sheet8_cuecs(cleaned_cuecs))


def _clean_sheet8_cuecs(llm_client: LLMClient, cuecs: list[CUECItem]) -> list[CUECItem]:
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
            raw = llm_client.call_json(
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


def _extract_sheet9(llm_client: LLMClient, text: str) -> Sheet9Data:
    raw = llm_client.call_json(_prompt("sheet9_csoc.txt", section_text=text))
    raw_csocs = raw.get("csocs", []) if isinstance(raw, dict) else raw
    if not isinstance(raw_csocs, list):
        raise ValueError("Sheet 9 response must be a JSON object with 'csocs' or a JSON array")
    csocs = [CSOCItem(**c) for c in raw_csocs]
    return Sheet9Data(csocs=csocs)


def _extract_sheet9_batches(llm_client: LLMClient, batches: list[str]) -> Sheet9Data:
    csocs: list[CSOCItem] = []
    seen: set[tuple[str, str, str]] = set()
    for text in batches:
        for item in _extract_sheet9(llm_client, text).csocs:
            key = (
                normalize_text(item.subservice_org),
                normalize_text(item.objective_and_page),
                normalize_text(item.description),
            )
            if key not in seen:
                csocs.append(item)
                seen.add(key)
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
    llm_client: LLMClient,
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
    # Sheet 8 intentionally uses its dedicated contiguous CUEC-section locator.
    # Broad full-report retrieval produced unrelated customer-responsibility rows.
    retrieval_sheet_numbers = set(sheets) & {6, 7, 9}
    search_profiles = load_search_profiles(
        settings.search_terms_dir,
        retrieval_sheet_numbers,
    )
    retrieval_context = (
        RetrievalContext(pages, toc_max_pages=settings.toc_max_pages)
        if retrieval_sheet_numbers
        else None
    )

    _cb("Locating sections (TOC)", _STEP_PCT["toc"][0])
    toc = _parse_toc(llm_client, pages)
    print(f"[EXTRACTOR] TOC: system={toc.system_name}, opinion={toc.opinion_pages}, cm={toc.change_mgmt_pages}", flush=True)
    print(
        "[EXTRACTOR] Page map sample: "
        f"{dict(list(sorted(report_to_pdf_page.items()))[:8])}",
        flush=True,
    )
    _cb("Sections located", _STEP_PCT["toc"][1])

    retrievals: dict[tuple[int, str], RetrievalResult] = {}
    if retrieval_context is not None:
        retrieval_specs = {
            (6, "change_mgmt"): toc.change_mgmt_pages,
            (6, "access_mgmt"): toc.access_mgmt_pages,
            (6, "job_scheduling"): toc.job_scheduling_pages,
            (7, "subservice"): toc.subservice_pages,
            (9, "csoc"): toc.csoc_pages,
        }
        for (sheet_number, topic), toc_range in retrieval_specs.items():
            if sheet_number not in retrieval_sheet_numbers:
                continue
            retrievals[(sheet_number, topic)] = _retrieve_topic(
                retrieval_context,
                search_profiles[sheet_number],
                topic,
                toc_range,
                report_to_pdf_page,
            )

    result = ExtractedFormData(system_name=toc.system_name)

    if 2 in sheets:
        logger.info("Starting Sheet 2 extraction")
        _cb("Extracting report metadata (Sheet 2)", _STEP_PCT[2][0])
        result.sheet2 = _extract_sheet2(
            llm_client,
            _cover_pages_text(pages, pdf_to_report_page),
            _section_from_toc_range(
                pages, toc.opinion_pages, report_to_pdf_page, pdf_to_report_page
            ),
        )
        logger.info("Sheet 2 done: %s", result.sheet2)
        _cb("Sheet 2 done", _STEP_PCT[2][1])

    if 3 in sheets:
        logger.info("Starting Sheet 3 extraction")
        _cb("Extracting opinion & exceptions (Sheet 3)", _STEP_PCT[3][0])
        result.sheet3 = _extract_sheet3(
            llm_client,
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
        sheet6_batches = {
            topic: _format_retrieval_batches(
                pages,
                retrievals[(6, topic)],
                pdf_to_report_page,
            )
            for topic in ("change_mgmt", "access_mgmt", "job_scheduling")
        }
        sheet6_report_label = _detect_report_label(
            "\n\n".join(
                text
                for batches in sheet6_batches.values()
                for text in batches
            )
        )
        result.sheet6 = _extract_sheet6_batches(
            llm_client,
            sheet6_batches,
            sheet6_report_label,
        )
        logger.info("Sheet 6 done")
        _cb("Sheet 6 done", _STEP_PCT[6][1])

    if 7 in sheets:
        logger.info("Starting Sheet 7 extraction")
        _cb("Identifying subservice organizations (Sheet 7)", _STEP_PCT[7][0])
        result.sheet7 = _extract_sheet7_batches(
            llm_client,
            _format_retrieval_batches(
                pages,
                retrievals[(7, "subservice")],
                pdf_to_report_page,
            ),
        )
        logger.info("Sheet 7 done: has_subservice=%s", result.sheet7.has_subservice)
        _cb("Sheet 7 done", _STEP_PCT[7][1])

    if 8 in sheets:
        logger.info("Starting Sheet 8 extraction")
        _cb("Extracting CUECs (Sheet 8)", _STEP_PCT[8][0])
        result.sheet8 = _extract_sheet8(
            llm_client,
            _collect_sheet8_candidate_section(
                pages,
                toc,
                report_to_pdf_page,
                pdf_to_report_page,
            ),
        )
        logger.info("Sheet 8 done: cuecs=%d", len(result.sheet8.cuecs))
        _cb("Sheet 8 done", _STEP_PCT[8][1])

    if 9 in sheets:
        logger.info("Starting Sheet 9 extraction")
        _cb("Extracting CSOCs (Sheet 9)", _STEP_PCT[9][0])
        result.sheet9 = _extract_sheet9_batches(
            llm_client,
            _format_retrieval_batches(
                pages,
                retrievals[(9, "csoc")],
                pdf_to_report_page,
            ),
        )
        logger.info("Sheet 9 done: csocs=%d", len(result.sheet9.csocs))
        _cb("Sheet 9 done", _STEP_PCT[9][1])

    return result
