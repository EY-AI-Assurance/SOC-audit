"""
PDF parsing service.

For each page: extracts plain text and tables (converted to Markdown),
then persists the result as { page_number: content_str } JSON for reuse.
"""
import json
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    raise ImportError("Run: pip install pdfplumber")


def _table_to_markdown(table: list[list]) -> str:
    if not table or not table[0]:
        return ""
    rows = [[str(cell or "").strip() for cell in row] for row in table]
    header    = "| " + " | ".join(rows[0]) + " |"
    separator = "| " + " | ".join(["---"] * len(rows[0])) + " |"
    body      = "\n".join("| " + " | ".join(row) + " |" for row in rows[1:] if any(row))
    return "\n".join(filter(None, [header, separator, body]))


def _parse_page(page) -> str:
    parts: list[str] = []

    found_tables = page.find_tables()
    table_bboxes = [t.bbox for t in found_tables]

    if table_bboxes:
        def outside_tables(obj):
            return not any(
                obj.get("x0", 0) >= bbox[0] and obj.get("top", 0) >= bbox[1]
                and obj.get("x1", 0) <= bbox[2] and obj.get("bottom", 0) <= bbox[3]
                for bbox in table_bboxes
            )
        text = page.filter(outside_tables).extract_text()
    else:
        text = page.extract_text()

    if text:
        parts.append(text.strip())
    for t in found_tables:
        md = _table_to_markdown(t.extract())
        if md:
            parts.append(md)

    return "\n\n".join(parts)


def parse_pdf(pdf_path: Path) -> dict[int, str]:
    """Return { page_number (1-indexed): text + markdown tables }."""
    pages: dict[int, str] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            pages[i] = _parse_page(page)
    return pages


def save_parsed(pages: dict[int, str], output_path: Path) -> None:
    output_path.write_text(
        json.dumps({str(k): v for k, v in pages.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_parsed(parsed_path: Path) -> dict[int, str]:
    raw = json.loads(parsed_path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def extract_section(pages: dict[int, str], page_range: list[int]) -> str:
    """Concatenate pages for [start, end] (inclusive). Returns '' if range is [0,0]."""
    if not page_range or len(page_range) != 2 or page_range == [0, 0]:
        return ""
    start, end = page_range
    return "\n\n---\n\n".join(
        f"[Page {p}]\n{pages[p]}" for p in range(start, end + 1) if p in pages
    )
