"""Extraction tests against the generated sample resumes in eval/samples/."""

import io
import zipfile
from pathlib import Path

import pytest
from docx import Document

from app.parsing.extract import UnsupportedFile, detect_kind, extract

SAMPLES = Path(__file__).parents[1] / "eval" / "samples"


def sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


def test_single_column_keeps_title_and_right_aligned_dates_together() -> None:
    result = extract(sample("alex_chen_backend.pdf"))
    assert (result.kind, result.pages, result.columns) == ("pdf", 1, 1)
    assert "Senior Backend Engineer, Ledgerly · Seattle, WA Mar 2022 – Present" in result.text
    assert "(cid:" not in result.text and "•" in result.text


def test_two_column_pdf_reads_each_column_in_order() -> None:
    result = extract(sample("maria_gonzalez_data.pdf"))
    assert result.columns == 2
    text = result.text
    # Sidebar first, then the main column; no line mixes the two.
    assert text.index("Skills") < text.index("Experience")
    assert "Brightwave Health, Austin, TX | 07/2023 - present" in text
    assert "Data Scientist\nBrightwave Health" in text


def test_docx_reads_header_and_table_rows() -> None:
    result = extract(sample("sam_okafor_frontend.docx"))
    assert (result.kind, result.pages, result.tables) == ("docx", None, 1)
    lines = result.text.splitlines()
    assert lines[0] == "Sam Okafor · Frontend Developer"  # from the page header
    row = next(line for line in lines if line.startswith("Frontend Developer"))
    assert row.endswith("| Sept 2024 – Present")


def test_docx_text_box_content_is_extracted_once() -> None:
    doc = Document()
    doc.add_paragraph("Experience")
    buffer = io.BytesIO()
    doc.save(buffer)
    # Inject a text box (with Word's VML fallback copy) into the first paragraph.
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as src:
        files = {name: src.read(name) for name in src.namelist()}
    xml = files["word/document.xml"].decode()
    box = (
        '<w:r><mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        '<mc:Choice Requires="wps"><w:drawing><wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData>'
        '<wps:wsp xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><wps:txbx>'
        "<w:txbxContent><w:p><w:r><w:t>Key skills: Python, Go</w:t></w:r></w:p></w:txbxContent>"
        "</wps:txbx></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>"
        '<mc:Fallback><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml"><v:textbox>'
        "<w:txbxContent><w:p><w:r><w:t>Key skills: Python, Go</w:t></w:r></w:p></w:txbxContent>"
        "</v:textbox></v:shape></w:pict></mc:Fallback></mc:AlternateContent></w:r>"
    )
    xml = xml.replace("<w:t>Experience</w:t></w:r>", "<w:t>Experience</w:t></w:r>" + box, 1)
    files["word/document.xml"] = xml.encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        for name, data in files.items():
            dst.writestr(name, data)

    text = extract(out.getvalue()).text
    assert text.count("Key skills: Python, Go") == 1
    assert text.index("Experience") < text.index("Key skills")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"hello", "Upload a PDF or DOCX"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "Legacy .doc"),
        (b"PK\x03\x04not really a zip", "Upload a PDF or DOCX"),
    ],
)
def test_rejects_other_files_by_content(data: bytes, message: str) -> None:
    with pytest.raises(UnsupportedFile, match=message):
        detect_kind(data)


def test_zip_that_is_not_docx_is_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(UnsupportedFile):
        extract(buffer.getvalue())


def test_corrupt_pdf_is_reported_cleanly() -> None:
    with pytest.raises(UnsupportedFile, match="Couldn't read this PDF"):
        extract(b"%PDF-1.4\n" + b"\x00" * 100)
