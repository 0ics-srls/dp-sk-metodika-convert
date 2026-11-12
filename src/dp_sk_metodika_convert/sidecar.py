"""The sidecar of one grabbed document: ``<item dir>/<source_id>.meta.json`` written by the grab class (shared contract of the three Python classes).

Unknown values are JSON null in the file; this reader is defensive and also treats a blank string, ``0`` and a malformed date as unknown.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

SUFFIX = ".meta.json"


class SidecarError(Exception):
    """The sidecar is not valid JSON or not a JSON object."""


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip() if isinstance(value, str | int | float) else ""
    return text or None


def _number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    return value if isinstance(value, int) and value > 0 else None


def _iso_date(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat() if len(text) >= 10 else None  # noqa: PLR2004 - yyyy-mm-dd
    except ValueError:
        return None


@dataclass(frozen=True)
class Sidecar:
    """The metadata of one document as the grab recorded it."""

    fonte: str | None = None
    source_id: str | None = None
    legacy_doc_id: str | None = None
    section: str | None = None
    group: str | None = None
    title: str | None = None
    pdf_url: str | None = None
    listing_url: str | None = None
    code: str | None = None
    number: int | None = None
    dept: str | None = None
    year: int | None = None
    doc_type: str | None = None
    category: str | None = None
    published: str | None = None
    pdf_file: str | None = None
    pdf_bytes: int | None = None
    fetched: str | None = None
    version: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Sidecar:
        """Build from the decoded JSON object; unknown keys are ignored."""
        return cls(
            fonte=_text(raw.get("fonte")),
            source_id=_text(raw.get("source_id")),
            legacy_doc_id=_text(raw.get("legacy_doc_id")),
            section=_text(raw.get("section")),
            group=_text(raw.get("group")),
            title=_text(raw.get("title")),
            pdf_url=_text(raw.get("pdf_url")),
            listing_url=_text(raw.get("listing_url")),
            code=_text(raw.get("code")),
            number=_number(raw.get("number")),
            dept=_text(raw.get("dept")),
            year=_number(raw.get("year")),
            doc_type=_text(raw.get("doc_type")),
            category=_text(raw.get("category")),
            published=_iso_date(raw.get("published")),
            pdf_file=_text(raw.get("pdf_file")),
            pdf_bytes=_number(raw.get("pdf_bytes")),
            fetched=_text(raw.get("fetched")),
            version=_text(raw.get("version")),
        )


def read_sidecar(path: Path) -> Sidecar:
    """Read one ``*.meta.json``; raises ``SidecarError`` when it is unreadable, not JSON or not an object."""
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        msg = f"cannot read {path.name}: {error}"
        raise SidecarError(msg) from error
    if not isinstance(decoded, dict):
        msg = f"{path.name} is not a JSON object"
        raise SidecarError(msg)
    return Sidecar.from_dict(decoded)


def list_sidecars(directory: Path) -> list[tuple[str, Path]]:
    """The ``(source_id taken from the file name, path)`` of every sidecar in the directory, ascending by source_id."""
    found = [(path.name.removesuffix(SUFFIX), path) for path in directory.glob(f"*{SUFFIX}") if path.is_file()]
    return sorted(found)
