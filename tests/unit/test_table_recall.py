"""Spike P81b-07 as a regression floor: word recall of the pypdfium2 text against the text the legacy converter (pdfplumber, tables as markdown pipes) made of
the same PDF. The reference texts are recorded next to the PDFs (``*.legacy.txt``, pipes removed). Spike numbers: zapis 1.0000, prehlad 0.9982,
mfsr-poucenie 1.0000, nbs-stanovisko 1.0000, mfsr-mu-2026 (14 table pages) 0.9964. A library change that drops words fails here."""
from __future__ import annotations

import collections
import re
import unicodedata
from pathlib import Path

import pytest

from dp_sk_metodika_convert import pdftext
from dp_sk_metodika_convert.pdftext import SOFT_HYPHEN

FLOOR = 0.98
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def words(text: str) -> collections.Counter[str]:
    cleaned = unicodedata.normalize("NFC", text).replace(SOFT_HYPHEN, "").replace(" ", " ")
    return collections.Counter(word.lower() for word in _WORD.findall(cleaned))


def recall_and_precision(reference: str, produced: str) -> tuple[float, float]:
    expected, found = words(reference), words(produced)
    common = sum((expected & found).values())
    return common / sum(expected.values()), common / sum(found.values())


@pytest.mark.unit
@pytest.mark.parametrize("stem", ["fs-zapis-2014", "fs-prehlad-zdz", "mfsr-poucenie", "mfsr-mu-2026", "nbs-stanovisko"])
def test_pdfium_text_keeps_the_words_of_the_legacy_text(fixtures: Path, stem: str) -> None:
    reference = (fixtures / f"{stem}.legacy.txt").read_text(encoding="utf-8")

    recall, precision = recall_and_precision(reference, pdftext.extract_text(fixtures / f"{stem}.pdf"))

    assert recall >= FLOOR, f"{stem}: recall {recall:.4f}"
    assert precision >= FLOOR, f"{stem}: precision {precision:.4f}"


@pytest.mark.unit
def test_a_table_cell_word_stays_a_word(fixtures: Path) -> None:
    found = words(pdftext.extract_text(fixtures / "fs-prehlad-zdz.pdf"))

    assert found["slovenskej"] > 0
    assert found["zdanenia"] > 0
