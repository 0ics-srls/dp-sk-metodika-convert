"""PDF text layer through pypdfium2 (P81b-07, spike numbers in tasks/81b-dp-sk-metodika/spike-p81b-07.md)."""
from __future__ import annotations

import unicodedata
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from dp_sk_metodika_convert import pdftext
from dp_sk_metodika_convert.ocr import needs_ocr


def blank_pdf(path: Path, pages: int = 1) -> Path:
    document = pdfium.PdfDocument.new()
    for _ in range(pages):
        document.new_page(595, 842)
    document.save(str(path))
    document.close()
    return path


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "phrase"),
    [
        ("fs-zapis-2014.pdf", "príjmov"),
        ("fs-prehlad-zdz.pdf", "zdanenia"),
        ("mfsr-poucenie.pdf", "Poučenie"),
        ("nbs-stanovisko.pdf", "NBS"),
    ],
)
def test_text_layer_gives_text_above_the_threshold_with_diacritics_in_nfc(fixtures: Path, name: str, phrase: str) -> None:
    text = pdftext.extract_text(fixtures / name)

    assert not needs_ocr(text)
    assert phrase in text
    assert unicodedata.normalize("NFC", text) == text


@pytest.mark.unit
def test_a_blank_page_pdf_gives_less_than_200_characters(tmp_path: Path) -> None:
    text = pdftext.extract_text(blank_pdf(tmp_path / "blank.pdf", pages=2))

    assert len(text) < 200
    assert needs_ocr(text)


@pytest.mark.unit
def test_an_image_only_scan_has_no_text_layer(fixtures: Path) -> None:
    assert needs_ocr(pdftext.extract_text(fixtures / "scan-sk.pdf"))


@pytest.mark.unit
def test_no_break_spaces_and_soft_hyphens_are_normalised() -> None:
    dirty = "Finančná správa SR a MF con­tri\x07buent  \t e\r\nx"

    assert pdftext.clean_text(dirty) == "Finančná správa SR a MF contribuent e\nx"


@pytest.mark.unit
def test_clean_text_composes_decomposed_diacritics() -> None:
    assert pdftext.clean_text("Poučenie") == "Poučenie"


@pytest.mark.unit
def test_clean_text_keeps_paragraphs_and_collapses_blank_runs() -> None:
    assert pdftext.clean_text("a\n\n\n\n\nb \n c") == "a\n\nb\n c"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("page", "expected"),
    [
        ("Text prvej strany\n3", "Text prvej strany"),
        ("12\nText druhej strany", "Text druhej strany"),
        ("Text\n12/34", "Text"),
        ("Text\n- 3 -", "Text"),
        ("Text\n– 3 –", "Text"),
        ("Strana 3\nText", "Text"),
        ("Text\nstr. 4", "Text"),
        ("7\nText\n8", "Text"),
        ("\n\nText\n  5  \n\n", "\n\nText\n\n"),
    ],
)
def test_page_number_lines_are_stripped_at_the_page_edges(page: str, expected: str) -> None:
    assert pdftext.strip_page_number_lines(page) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "page",
    [
        "Text\n3.\nviac textu",
        "Text\n5\nviac textu",
        "Zoznam:\n1. prvy\n2. druhy\n3.",
        "Text o roku 2014 a 3 veciach",
        "Poznamka\n2014\nSuma",
    ],
)
def test_list_markers_and_body_numbers_are_kept(page: str) -> None:
    assert pdftext.strip_page_number_lines(page) == page


@pytest.mark.unit
def test_extract_strips_the_page_numbers_of_every_page(fixtures: Path) -> None:
    pages = pdftext.extract_pages(fixtures / "fs-zapis-2014.pdf")

    assert len(pages) == pdftext.page_count(fixtures / "fs-zapis-2014.pdf") == 8
    assert all(page.strip().splitlines()[0].strip() != str(index + 1) for index, page in enumerate(pages))


@pytest.mark.unit
@pytest.mark.parametrize("content", [b"<html><body>Not found</body></html>", b"", b"PK\x03\x04zip", b"%PD"])
def test_a_file_that_is_not_a_pdf_raises_not_a_pdf(tmp_path: Path, content: bytes) -> None:
    fake = tmp_path / "x.pdf"
    fake.write_bytes(content)

    with pytest.raises(pdftext.NotAPdf):
        pdftext.extract_text(fake)
    assert not pdftext.is_pdf(fake)


@pytest.mark.unit
def test_a_pdf_header_with_a_broken_body_is_unreadable_not_a_crash(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\nthis is not a real body")

    assert pdftext.is_pdf(broken)
    with pytest.raises(pdftext.PdfUnreadable):
        pdftext.extract_text(broken)


@pytest.mark.unit
def test_not_a_pdf_is_an_unreadable_pdf_for_callers_that_do_not_care_why() -> None:
    assert issubclass(pdftext.NotAPdf, pdftext.PdfUnreadable)


@pytest.mark.unit
def test_pdf_facts_pages_and_created(fixtures: Path) -> None:
    facts = pdftext.pdf_facts(fixtures / "fs-zapis-2014.pdf")

    assert facts.pages == 8
    assert facts.created is None or len(facts.created) == 10
