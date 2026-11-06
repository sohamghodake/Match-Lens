"""Text extraction from PDF and DOCX, plus layout facts the ATS scorer needs later.

File type comes from the bytes, not the filename or Content-Type header.
"""

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from typing import Any, Literal

import pdfplumber
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

log = logging.getLogger(__name__)

FileKind = Literal["pdf", "docx"]


class UnsupportedFile(ValueError):
    """Not a PDF or DOCX (or a legacy .doc, or a corrupt file)."""


@dataclass(frozen=True)
class Extracted:
    kind: FileKind
    text: str
    pages: int | None  # DOCX has no fixed pagination
    columns: int  # max text columns found on any page / section
    tables: int


def detect_kind(data: bytes) -> FileKind:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" in archive.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        raise UnsupportedFile("Legacy .doc files aren't supported; save it as PDF or DOCX.")
    raise UnsupportedFile("Upload a PDF or DOCX file.")


def extract(data: bytes) -> Extracted:
    kind = detect_kind(data)
    try:
        result = _extract_pdf(data) if kind == "pdf" else _extract_docx(data)
    except UnsupportedFile:
        raise
    except Exception as exc:  # pdfminer / python-docx raise many exception types
        log.info("could not read %s: %r", kind, exc)
        raise UnsupportedFile(f"Couldn't read this {kind.upper()}; is it corrupt?") from exc
    return Extracted(
        kind=kind,
        text=_tidy(result["text"]),
        pages=result["pages"],
        columns=result["columns"],
        tables=result["tables"],
    )


def _tidy(text: str) -> str:
    # pdfminer emits "(cid:N)" for glyphs without a Unicode mapping; in resumes these
    # are almost always bullet symbols.
    text = re.sub(r"\(cid:\d+\)", "\u2022", text)
    text = text.replace("\u00a0", " ").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ── PDF ───────────────────────────────────────────────────────────────────────────

X_TOLERANCE = 1.5  # tighter than pdfplumber's default 3, so tightly-set fonts keep spaces
MAX_PAGES = 10  # resumes are 1-3 pages; don't spend CPU on a 500-page upload


def _extract_pdf(data: bytes) -> dict[str, Any]:
    texts, columns, tables = [], 1, 0
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:MAX_PAGES]:
            split = _find_column_split(page)
            if split is None:
                texts.append(page.extract_text(x_tolerance=X_TOLERANCE) or "")
            else:
                columns = 2
                texts.append(_extract_columns(page, *split))
            tables += len(page.find_tables())
        pages = len(pdf.pages)
    return {"text": "\n\n".join(texts), "pages": pages, "columns": columns, "tables": tables}


def _extract_columns(page: Any, gutter_x: float, header_bottom: float) -> str:
    x0, top, x1, bottom = page.bbox
    regions = [(x0, header_bottom, gutter_x, bottom), (gutter_x, header_bottom, x1, bottom)]
    if header_bottom > top:
        regions.insert(0, (x0, top, x1, header_bottom))
    return "\n".join(page.crop(r).extract_text(x_tolerance=X_TOLERANCE) or "" for r in regions)


def _find_column_split(page: Any) -> tuple[float, float] | None:
    """Find a vertical gutter separating two text columns.

    Returns (gutter_x, header_bottom): a full-width header may sit above the columns.
    Each column must hold at least 15% of the text, which rules out single-column
    resumes whose right-aligned dates leave a gap down the page (splitting those would
    separate every job title from its dates).
    """
    words = page.extract_words(x_tolerance=X_TOLERANCE)
    if len(words) < 40:
        return None
    x0, top, x1, bottom = (float(v) for v in page.bbox)
    width, height = x1 - x0, bottom - top
    total_chars = sum(len(w["text"]) for w in words)

    candidates: list[tuple[float, float]] = []  # (header_bottom, x)
    x = x0 + width * 0.2
    while x <= x0 + width * 0.8:
        crossing = [w for w in words if w["x0"] < x < w["x1"]]
        header_bottom = max((float(w["bottom"]) for w in crossing), default=top)
        if header_bottom <= top + height * 0.35:
            below = [w for w in words if w["top"] >= header_bottom]
            left = sum(len(w["text"]) for w in below if w["x1"] <= x)
            right = sum(len(w["text"]) for w in below if w["x0"] >= x)
            if min(left, right) >= 0.15 * total_chars:
                candidates.append((header_bottom, x))
        x += 2.0
    if not candidates:
        return None
    best_header = min(h for h, _ in candidates)
    xs = [x for h, x in candidates if h == best_header]
    # The middle of the widest run of gutter positions.
    runs: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - runs[-1][-1] <= 2.0 + 1e-6:
            runs[-1].append(x)
        else:
            runs.append([x])
    widest = max(runs, key=len)
    return (widest[0] + widest[-1]) / 2, best_header


# ── DOCX ──────────────────────────────────────────────────────────────────────────


def _extract_docx(data: bytes) -> dict[str, Any]:
    doc = Document(io.BytesIO(data))
    lines: list[str] = []

    # Contact details often live in the page header.
    for section in doc.sections:
        for part in (section.header, section.footer):
            if part.is_linked_to_previous:
                continue
            part_lines = _block_lines(part._element, part)
            if not set(part_lines) <= set(lines):  # sections often repeat one header
                lines += part_lines

    lines += _block_lines(doc.element.body, doc)

    columns = 1
    for section in doc.sections:
        cols = section._sectPr.find(qn("w:cols"))
        if cols is not None and int(cols.get(qn("w:num"), "1")) > 1:
            columns = 2
    return {"text": "\n".join(lines), "pages": None, "columns": columns, "tables": len(doc.tables)}


def _block_lines(container: Any, parent: Any) -> list[str]:
    """Paragraphs and tables in document order. Table rows become "cell | cell" so a
    role and its dates stay on one line; text boxes follow their anchor paragraph."""
    lines: list[str] = []
    for child in container.iterchildren():
        if child.tag == qn("w:p"):
            lines.append(Paragraph(child, parent).text)
            for box in _text_boxes(child):
                lines += _block_lines(box, parent)
        elif child.tag == qn("w:tbl"):
            for row in Table(child, parent).rows:
                cells, seen = [], set()
                for cell in row.cells:
                    if id(cell._tc) in seen:  # merged cells repeat
                        continue
                    seen.add(id(cell._tc))
                    text = " ".join(cell.text.split())
                    if text:
                        cells.append(text)
                lines.append(" | ".join(cells))
        elif child.tag == qn("w:sdt"):  # content controls wrap ordinary blocks
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                lines += _block_lines(content, parent)
    return lines


def _text_boxes(paragraph: Any) -> list[Any]:
    # Word stores each text box twice (modern + VML fallback); skip the fallback copy.
    boxes = []
    for box in paragraph.iter(qn("w:txbxContent")):
        if not any(a.tag.endswith("}Fallback") for a in box.iterancestors()):
            boxes.append(box)
    return boxes
