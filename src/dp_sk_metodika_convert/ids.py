"""``source_id`` safety check of the convert class (P81b-05, live fix P81b-34).

The identity of a document is derived ONCE, by the grab class (slug of the PDF URL path, ``dp_sk_metodika_grab.ids``). The convert class never recomputes it:
it trusts the ``source_id`` that the grab wrote into the sidecar and only checks that the value is one safe path component (an id that could escape the
item directory or break a file name is refused). There is deliberately no URL-to-id rule in this module: two rule sets drifted apart in 0.1.0.
"""
from __future__ import annotations

import re

MAX_LENGTH = 200
_SAFE = re.compile(r"^[A-Za-z0-9_.À-ɏ-]+$")


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
