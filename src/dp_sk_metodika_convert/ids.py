"""``source_id``: the identity of a document inside its ``fonte`` (P81b-05). One rule, kept as an identical copy in the grab and the convert class.

The id is the slug of the PDF URL path below the host, not the file stem: the legacy stem rule gave 645 ids for 715 MF SR PDFs, so 70 documents
overwrote one another. Rules, in this order:

1. host, query and fragment are dropped, the path is percent-decoded and the extension removed;
2. financnasprava.sk keeps only what follows ``Zverejnovanie_dok/``; another leading ``_img/`` segment is dropped; a trailing ``/stiahnut`` (NBS
   ``/dokument/<uuid>/stiahnut``) is dropped; ``files/archiv/...``, ``extdoc/<n>`` and ``fileadmin/...`` stay as they are;
3. segments are joined with ``_`` and every character outside ``[A-Za-z0-9_.-]`` and the Latin-1/Extended letters becomes ``_`` (runs collapse);
4. more than 200 characters: the first 191 characters, ``_`` and 8 hex characters of the sha256 of the full slug.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import unquote, urlparse

MAX_LENGTH = 200
_HASH_LENGTH = 8
_SAFE = re.compile(r"^[A-Za-z0-9_.À-ɏ-]+$")
_UNSAFE_RUN = re.compile(r"[^A-Za-z0-9_.À-ɏ-]+")
_EXTENSION = re.compile(r"\.(?:pdf|PDF)$")
_DROP_BEFORE = "Zverejnovanie_dok"


class InvalidSourceId(ValueError):  # noqa: N818 - public error name of the class
    """A source id that could escape a directory or break a file name."""


def is_safe_source_id(value: str) -> bool:
    """True for a name that is one safe path component: allowed characters only, not ``.``/``..``, at most 200 characters."""
    return 0 < len(value) <= MAX_LENGTH and value not in {".", ".."} and _SAFE.fullmatch(value) is not None


def check_source_id(value: str) -> str:
    """Return the id unchanged, or raise ``InvalidSourceId`` (separators, ``..``, absolute paths, odd characters, too long)."""
    if not is_safe_source_id(value):
        msg = f"unsafe source_id: {value[:80]!r}"
        raise InvalidSourceId(msg)
    return value


def source_id_from_url(url: str) -> str:
    """The source id of a PDF URL (see the module doc for the rule)."""
    path = unicodedata.normalize("NFC", unquote(urlparse(url).path))
    segments = [segment for segment in path.split("/") if segment]
    if _DROP_BEFORE in segments:
        segments = segments[segments.index(_DROP_BEFORE) + 1 :]
    elif segments and segments[0] == "_img":
        segments = segments[1:]
    if len(segments) > 1 and segments[-1] == "stiahnut":
        segments = segments[:-1]
    if segments:
        segments[-1] = _EXTENSION.sub("", segments[-1])
    slug = _UNSAFE_RUN.sub("_", "_".join(segments)).strip("_")
    if not slug or slug in {".", ".."}:
        msg = f"no source_id can be derived from {url[:80]!r}"
        raise InvalidSourceId(msg)
    if len(slug) > MAX_LENGTH:
        digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
        slug = f"{slug[: MAX_LENGTH - _HASH_LENGTH - 1]}_{digest}"
    return slug
