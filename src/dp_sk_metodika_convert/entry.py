"""The corpus entry of one document: port of the legacy ``_to_entry`` with P81b-05/06/08/25.

Differences from the legacy, all deliberate: ``numero`` is the code or the number as text or NULL (the legacy filled the source id); ``anno`` is NULL when
unknown (the legacy wrote 0); a blank title gives a NULL ``oggetto`` (not an empty string).

Metadata wins (D139, lesson 80b F2): the sidecar of the grab is the truth for ``numero``/``number``/``anno``/``data``/``oggetto``. The text (text layer or
OCR) can fill ONLY a year the sidecar left empty and never overwrites; when it names another number or year the entry keeps the sidecar value and carries a
warning that ends in the plan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from dp_sk_metodika_convert import ids

if TYPE_CHECKING:
    from dp_sk_metodika_convert.sidecar import Sidecar

# Issuing body per fonte (the legacy FONTE_ENTE, with the Slovak diacritics).
FONTE_ENTE = {
    "financnasprava": "Finančná správa SR",
    "mfsr-spravodajca": "Ministerstvo financií SR",
    "nbs-metodicke": "Národná banka Slovenska",
    "uvo-metodicke": "Úrad pre verejné obstarávanie",
}
FS_FONTE = "financnasprava"
DEFAULT_TIPO = "dokument"
HEAD_CHARS = 3000
_MIN_YEAR, _MAX_YEAR = 1900, 2200

_DATE_LINE = re.compile(r"(?<!\d)(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*((?:19|20)\d{2})(?!\d)")
_NAMED_NUMBER = re.compile(
    r"(?:pokyn|usmernenie|usmernenia|stanovisko|smernica|opatrenie|oznamenie|oznámenie)\w*\s+(?:č|c)\s*\.\s*(\d{1,6})\s*/\s*(?:[A-Za-z]+\s*/\s*)*((?:19|20)\d{2})",
    re.IGNORECASE,
)
_LEADING_INT = re.compile(r"^\s*(\d{1,6})(?!\d)")


@dataclass(frozen=True)
class Rejected:
    """A document that cannot become an entry; it is declared in ``skipped`` with this reason."""

    reason: str
    item_ref: str


@dataclass
class Entry:
    """One document of the plan (contract keys of ``documents[]``) plus the warnings of the metadata-wins check."""

    fonte: str
    source_id: str
    legacy_doc_id: str | None
    ente: str
    tipo: str
    section: str | None
    group_label: str | None
    numero: str | None
    number: int | None
    dept: str | None
    anno: int | None
    data: str | None
    oggetto: str | None
    text_raw: str
    text_source: str
    source_url: str | None
    pdf_bytes: int | None
    pdf_pages: int | None
    pdf_created: str | None
    warnings: list[str] = field(default_factory=list)

    def to_document(self) -> dict[str, Any]:
        """The ``documents[]`` object of the plan, keys sorted."""
        document = {name: getattr(self, name) for name in self.__dataclass_fields__ if name != "warnings"}
        return dict(sorted(document.items()))


def _first_head(text: str) -> str:
    return text[:HEAD_CHARS]


def _year_from_text(text: str) -> int | None:
    """The year of the first date line (``14. 3. 2023``) in the head of the text, else of a named number (``pokyn c. 5/2021``)."""
    head = _first_head(text)
    for match in _DATE_LINE.finditer(head):
        year = int(match.group(3))
        if _MIN_YEAR <= year <= _MAX_YEAR:
            return year
    named = _NAMED_NUMBER.search(head)
    return int(named.group(2)) if named else None


def _year_of(side: Sidecar, text: str) -> int | None:
    """Order: sidecar year, group year (MF SR), year of ``published``, year of the text."""
    if side.year is not None:
        return side.year
    if side.group is not None and re.fullmatch(r"(?:19|20)\d{2}", side.group):
        return int(side.group)
    if side.published is not None:
        return date.fromisoformat(side.published).year
    return _year_from_text(text)


def _source_number(side: Sidecar) -> int | None:
    if side.number is not None:
        return side.number
    head = _LEADING_INT.match(side.code) if side.code else None
    return int(head.group(1)) if head else None


def _warnings(side: Sidecar, text: str, text_source: str) -> list[str]:
    named = _NAMED_NUMBER.search(_first_head(text))
    if named is None:
        return []
    found_number, found_year = int(named.group(1)), int(named.group(2))
    warnings: list[str] = []
    source_number = _source_number(side)
    if source_number is not None and source_number != found_number:
        warnings.append(f"number {found_number} read from the text ({text_source}) differs from the source number {source_number}; the source value is kept")
    if side.year is not None and side.year != found_year:
        warnings.append(f"year {found_year} read from the text ({text_source}) differs from the source year {side.year}; the source value is kept")
    return warnings


def build_entry(  # noqa: PLR0913 - the pdf facts are keyword-only
    side: Sidecar,
    text: str,
    text_source: str,
    *,
    pdf_pages: int | None = None,
    pdf_created: str | None = None,
    pdf_bytes: int | None = None,
) -> Entry | Rejected:
    """The entry of one document, or ``Rejected`` when fonte, source id or text is blank (the contract the ingest enforces)."""
    item_ref = side.source_id or "?"
    if not side.fonte:
        return Rejected("missing_fonte", item_ref)
    if not side.source_id:
        return Rejected("missing_source_id", item_ref)
    if not ids.is_safe_source_id(side.source_id):
        return Rejected("unsafe_source_id", side.source_id[:80])
    body = (text or "").strip()
    if not body:
        return Rejected("missing_text", side.source_id)
    site = side.fonte if side.fonte != FS_FONTE else None
    return Entry(
        fonte=side.fonte,
        source_id=side.source_id,
        legacy_doc_id=side.legacy_doc_id,
        ente=FONTE_ENTE.get(side.fonte, side.fonte),
        tipo=side.doc_type or side.section or site or DEFAULT_TIPO,
        section=side.section,
        group_label=side.group,
        numero=side.code or (str(side.number) if side.number is not None else None),
        number=side.number,
        dept=side.dept,
        anno=_year_of(side, body),
        data=side.published,
        oggetto=side.title,
        text_raw=body,
        text_source=text_source,
        source_url=side.pdf_url,
        pdf_bytes=side.pdf_bytes if side.pdf_bytes is not None else pdf_bytes,
        pdf_pages=pdf_pages,
        pdf_created=pdf_created,
        warnings=_warnings(side, body, text_source),
    )
