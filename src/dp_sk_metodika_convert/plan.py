"""The plan of one item: what the ingest step loads (plan schema v1, ``plan.schema.json``).

Order of operations per document: sidecar of the grab -> PDF present, a real PDF, not too large -> text layer -> local OCR when the layer is not a document
(``text_source = ocr``) -> entry (metadata wins) . A document that cannot become text is NOT written with an empty ``text_raw``: it goes to ``skipped`` with
a reason (``no_pdf``, ``not_a_pdf``, ``too_large``, ``ocr_empty``, ``ocr_unavailable``, ``ocr_failed``, ``bad_sidecar``, ``convert_failed`` or a reject
reason of ``entry``) - the corpus never holds a ghost. The plan is a pure function of the files: keys sorted, no clock, so two runs give the same bytes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dp_sk_metodika_convert import ids, pdftext, sidecar
from dp_sk_metodika_convert import ocr as ocr_mod
from dp_sk_metodika_convert.entry import Entry, Rejected, build_entry

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PLAN_VERSION = 1
MAX_PDF_BYTES = 40 * 1024 * 1024  # the grab refuses larger files too (maxPdfBytes)
FS_FONTE = "financnasprava"
COVERAGE_NAME = "_coverage.json"
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(item_id: str) -> str:
    """Directory / file name of an item id (identical to the grab class): unsafe runs become ``_``."""
    return _UNSAFE_NAME.sub("_", item_id.replace(" ", "-"))


@dataclass
class Selection:
    """Which documents of an item are converted (the ``only`` and ``maxDocs`` settings)."""

    only: list[dict[str, str]] | None = None
    max_docs: int | None = None

    def wants_stem(self, source_id: str) -> bool:
        return self.only is None or any(entry["docId"] == source_id for entry in self.only)

    def wants_section(self, source_id: str, section: str | None) -> bool:
        """True unless an ``only`` entry names this document with another section/site."""
        if self.only is None:
            return True
        for entry in self.only:
            if entry["docId"] != source_id:
                continue
            wanted = entry.get("section") or entry.get("site")
            if wanted is None or wanted == section:
                return True
        return False

    @property
    def filtered(self) -> bool:
        return self.only is not None or self.max_docs is not None


@dataclass
class Plan:
    """One plan file."""

    item_id: str
    fonte: str
    documents: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    listed: int = 0
    note: str | None = None
    warnings: list[str] = field(default_factory=list)
    ocr_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        skipped = sorted({(row["item_ref"], row["reason"]): row for row in self.skipped}.values(), key=lambda row: (row["item_ref"], row["reason"]))
        return {
            "planVersion": PLAN_VERSION,
            "itemId": self.item_id,
            "fonte": self.fonte,
            "documents": self.documents,
            "skipped": skipped,
            "coverage": {
                "fonte": self.fonte,
                "item_id": self.item_id,
                "listed": max(self.listed, len(self.documents) + len(skipped)),
                "taken": len(self.documents),
                "skipped": len(skipped),
                "note": self.note,
            },
            "warnings": self.warnings,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _skip(plan: Plan, source_id: str, reason: str) -> None:
    plan.skipped.append({"fonte": plan.fonte, "item_ref": source_id, "reason": reason})


def _read_text(pdf: Path, ocr: Callable[[Path], str]) -> tuple[str, str]:
    """``(text, text_source)``; raises ``OcrEmpty`` / ``OcrUnavailable`` / ``OcrFailed`` when the scan cannot be read."""
    text = pdftext.clean_text("\n\n".join(pdftext.extract_pages(pdf)))
    if not ocr_mod.needs_ocr(text):
        return text, "pdf"
    pages = ocr(pdf).split(ocr_mod.FORM_FEED)
    return pdftext.clean_text("\n\n".join(pdftext.strip_page_number_lines(page) for page in pages)), "ocr"


def _convert_document(plan: Plan, source_id: str, meta_path: Path, ocr: Callable[[Path], str]) -> None:  # noqa: C901, PLR0911 - one flat decision list
    try:
        side = sidecar.read_sidecar(meta_path)
    except sidecar.SidecarError:
        _skip(plan, source_id, "bad_sidecar")
        return
    if side.source_id != source_id or not ids.is_safe_source_id(source_id):
        _skip(plan, source_id, "bad_sidecar")  # the file name is the identity on disk; a sidecar that says otherwise is not trusted
        return
    pdf = meta_path.with_name(f"{source_id}.pdf")
    if not pdf.is_file():
        _skip(plan, source_id, "no_pdf")
        return
    size = pdf.stat().st_size
    if size > MAX_PDF_BYTES:
        _skip(plan, source_id, "too_large")
        return
    try:
        facts = pdftext.pdf_facts(pdf)
        text, text_source = _read_text(pdf, ocr)
    except pdftext.PdfUnreadable:
        _skip(plan, source_id, "not_a_pdf")
        return
    except ocr_mod.OcrEmpty:
        _skip(plan, source_id, "ocr_empty")
        return
    except ocr_mod.OcrUnavailable:
        _skip(plan, source_id, "ocr_unavailable")
        plan.warnings.append(f"{source_id}: tesseract or its language data is missing, the scan was not read")
        return
    except ocr_mod.OcrFailed:
        _skip(plan, source_id, "ocr_failed")
        return
    except Exception as error:  # noqa: BLE001 - one broken PDF must not stop the others; the reason is declared
        _skip(plan, source_id, "convert_failed")
        plan.warnings.append(f"{source_id}: {type(error).__name__}")
        return
    result = build_entry(side, text, text_source, pdf_pages=facts.pages, pdf_created=facts.created, pdf_bytes=size)
    if isinstance(result, Rejected):
        _skip(plan, source_id, result.reason)
        return
    _take(plan, result)


def _take(plan: Plan, entry: Entry) -> None:
    plan.documents.append(entry.to_document())
    plan.ocr_count += 1 if entry.text_source == "ocr" else 0
    plan.warnings.extend(f"{entry.source_id}: {warning}" for warning in entry.warnings)


def _grab_coverage(source: Path, plan: Plan, selection: Selection) -> None:
    path = source / COVERAGE_NAME
    if not path.is_file():
        return
    try:
        coverage = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        plan.warnings.append(f"{COVERAGE_NAME} of the grab is unreadable")
        return
    if not isinstance(coverage, dict):
        return
    listed = coverage.get("listed")
    if isinstance(listed, int) and not isinstance(listed, bool) and listed > 0:
        plan.listed = max(plan.listed, listed)
    notes = coverage.get("warnings")
    if isinstance(notes, list):
        joined = ";".join(str(note) for note in notes if str(note).strip())
        plan.note = joined or None
    carried = coverage.get("skipped")
    if isinstance(carried, list) and not selection.filtered:
        for row in carried:
            if isinstance(row, dict) and row.get("item_ref") and row.get("reason"):
                _skip(plan, str(row["item_ref"]), str(row["reason"]))


def build_item_plan(
    source: Path, item_id: str, fonte: str, selection: Selection, ocr: Callable[[Path], str] = ocr_mod.ocr_pdf
) -> Plan:
    """The plan of the item whose grab output is the directory ``source``."""
    plan = Plan(item_id=item_id, fonte=fonte)
    entries = [(source_id, path) for source_id, path in sidecar.list_sidecars(source) if selection.wants_stem(source_id)]
    if selection.max_docs is not None:
        entries = entries[: selection.max_docs]
    plan.listed = len(entries)
    for source_id, meta_path in entries:
        if selection.only is not None:
            try:
                section = sidecar.read_sidecar(meta_path).section
            except sidecar.SidecarError:
                section = None
            if not selection.wants_section(source_id, section) and section is not None:
                plan.listed -= 1
                continue
        _convert_document(plan, source_id, meta_path, ocr)
    _grab_coverage(source, plan, selection)
    return plan
