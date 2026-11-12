"""Text layer of a PDF through pypdfium2 (Apache-2.0/BSD). Spike P81b-07: against the legacy pdfplumber text the word recall is >= 0.9964 on the table PDFs
and 1.0 on the plain ones (one outlier of 0.9698 is a font that puts a gap inside words, letter recall 1.0), 10-30 times faster, so pdfplumber is not needed.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import pypdfium2 as pdfium

if TYPE_CHECKING:
    from pathlib import Path

MAGIC = b"%PDF-"
MAGIC_WINDOW = 1024  # Adobe tolerates junk before the header within the first KiB
SOFT_HYPHEN = chr(0xAD)

# no-break space, figure space, thin space, narrow no-break space (pdfium keeps the ones the PDF uses)
_SPACES_UNICODE = re.compile("[" + "".join(chr(code) for code in (0xA0, 0x2007, 0x2009, 0x202F)) + "]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SPACE_RUN = re.compile(r"[ \t]+")
_TRAILING = re.compile(r"[ \t]+\n")
_BLANK_RUN = re.compile(r"\n{3,}")
_CREATION_DATE = re.compile(r"D:(\d{4})(\d{2})(\d{2})")

# A header/footer page-number line: bare "12", "12/34", "- 12 -", "Strana 12" (port of the legacy ``_PAGE_NO_RE``).
_PAGE_NUMBER = re.compile(
    r"""^\s*(?:
        \d{1,4}
        | \d{1,4}\s*/\s*\d{1,4}
        | [-–—]\s*\d{1,4}\s*[-–—]
        | (?:strana|str\.?|page)\s*(?:č\.?\s*)?\d{1,4}(?:\s*/\s*\d{1,4})?
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


class PdfUnreadable(Exception):  # noqa: N818 - public error name of the class
    """The file has a PDF header but cannot be parsed."""


class NotAPdf(PdfUnreadable):
    """The file is not a PDF (no ``%PDF-`` header): UVO serves octet-stream, a portal may answer an HTML error page with status 200."""


@dataclass(frozen=True)
class PdfFacts:
    """Page count and creation date (``yyyy-mm-dd`` or None) of a PDF."""

    pages: int
    created: str | None


def clean_text(raw: str) -> str:
    """NFC, remove soft hyphens and control characters, no-break spaces to spaces, collapse whitespace runs but keep paragraphs (blank lines)."""
    text = unicodedata.normalize("NFC", raw).replace(SOFT_HYPHEN, "").replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACES_UNICODE.sub(" ", text)
    text = _CONTROL.sub("", text)
    text = _SPACE_RUN.sub(" ", text)
    text = _TRAILING.sub("\n", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


def strip_page_number_lines(page_text: str) -> str:
    """Drop a page-number line when it is the first or the last non-empty line of the page (port of the legacy ``_strip_page_number_lines``).

    A page number lives in the header/footer; elsewhere in the body a number, and list markers such as ``3.`` (they keep the dot), stay.
    """
    lines = page_text.split("\n")
    non_empty = [index for index, line in enumerate(lines) if line.strip()]
    if not non_empty:
        return page_text
    drop = {edge for edge in (non_empty[0], non_empty[-1]) if _PAGE_NUMBER.match(lines[edge].strip())}
    if not drop:
        return page_text
    return "\n".join(line for index, line in enumerate(lines) if index not in drop)


def is_pdf(path: Path) -> bool:
    """True when ``%PDF-`` appears in the first KiB of the file (magic bytes, not the extension or the Content-Type)."""
    try:
        with path.open("rb") as handle:
            return MAGIC in handle.read(MAGIC_WINDOW)
    except OSError:
        return False


def _open(path: Path) -> pdfium.PdfDocument:
    if not is_pdf(path):
        msg = f"{path.name} is not a PDF (no %PDF- header)"
        raise NotAPdf(msg)
    try:
        return pdfium.PdfDocument(str(path))
    except (pdfium.PdfiumError, OSError) as error:
        msg = f"cannot open {path.name}: {error}"
        raise PdfUnreadable(msg) from error


def page_count(path: Path) -> int:
    """Number of pages of the PDF."""
    document = _open(path)
    try:
        return len(document)
    finally:
        document.close()


def pdf_facts(path: Path) -> PdfFacts:
    """Pages and creation date of the PDF (the ``CreationDate`` entry, ``D:yyyymmdd...``)."""
    document = _open(path)
    try:
        pages = len(document)
        created: str | None = None
        match = _CREATION_DATE.match(document.get_metadata_dict().get("CreationDate", "") or "")
        if match:
            try:
                created = date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
            except ValueError:
                created = None
    finally:
        document.close()
    return PdfFacts(pages=pages, created=created)


def extract_pages(path: Path) -> list[str]:
    """The cleaned text layer of every page, page numbers at the page edges stripped. A photographed page gives an empty string."""
    document = _open(path)
    try:
        pages: list[str] = []
        for page in document:
            textpage = page.get_textpage()
            try:
                raw = textpage.get_text_bounded().replace("\r\n", "\n").replace("\r", "\n")
            finally:
                textpage.close()
                page.close()
            pages.append(clean_text(strip_page_number_lines(raw)))
    except pdfium.PdfiumError as error:
        msg = f"cannot read {path.name}: {error}"
        raise PdfUnreadable(msg) from error
    finally:
        document.close()
    return pages


def extract_text(path: Path) -> str:
    """The text layer of the whole PDF, pages joined by a blank line (see ``ocr.needs_ocr`` for the scan fallback)."""
    return clean_text("\n\n".join(extract_pages(path)))
