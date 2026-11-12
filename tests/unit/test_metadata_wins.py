"""D139 / P81b-06 / P81b-25: the metadata of the grab sidecar wins over the text (text layer or OCR). The text only fills an EMPTY field and a mismatch is a
plan warning, never an overwrite (lesson 80b F2)."""
from __future__ import annotations

from typing import Any

import pytest

from dp_sk_metodika_convert import sidecar
from dp_sk_metodika_convert.entry import Entry, build_entry

BODY = "Bratislava 14. 3. 2023\n" + "Obsah usmernenia k uplatnovaniu pravidiel. " * 10


def make(**fields: Any) -> sidecar.Sidecar:
    base: dict[str, Any] = {"fonte": "financnasprava", "source_id": "doc_1", "section": "metodicke-pokyny"}
    base.update(fields)
    return sidecar.Sidecar.from_dict(base)


def build(side: sidecar.Sidecar, text: str, source: str = "pdf") -> Entry:
    result = build_entry(side, text, source)
    assert isinstance(result, Entry), result
    return result


@pytest.mark.unit
@pytest.mark.parametrize("source", [pytest.param("pdf", id="text-layer"), pytest.param("ocr", id="scan")])
def test_text_with_another_number_and_year_never_changes_the_sidecar_values(source: str) -> None:
    text = "Metodicky pokyn c. 99/2019 k niecomu\n" + BODY
    entry = build(make(code="10/DZPaU/2026/MP", number=10, year=2026), text, source)

    assert entry.numero == "10/DZPaU/2026/MP"
    assert entry.number == 10
    assert entry.anno == 2026
    assert len(entry.warnings) == 2
    assert any("99" in w and "10" in w and source in w for w in entry.warnings)
    assert any("2019" in w and "2026" in w for w in entry.warnings)


@pytest.mark.unit
def test_number_from_the_leading_integer_of_the_code_is_compared_when_number_is_null() -> None:
    entry = build(make(code="10/DZPaU/2026/MP", year=2026), "Metodicky pokyn c. 99/2026 x\n" + BODY)

    assert entry.numero == "10/DZPaU/2026/MP"
    assert [w for w in entry.warnings if "99" in w]


@pytest.mark.unit
def test_agreeing_text_gives_no_warning() -> None:
    entry = build(make(code="10/DZPaU/2026/MP", number=10, year=2026), "Metodicky pokyn c. 10/2026 x\n" + BODY)

    assert entry.warnings == []


@pytest.mark.unit
def test_sidecar_without_year_takes_the_year_from_the_text_date_line() -> None:
    entry = build(make(year=None), BODY)

    assert entry.anno == 2023
    assert entry.warnings == []


@pytest.mark.unit
def test_sidecar_without_year_and_without_a_date_line_stays_null() -> None:
    assert build(make(year=None), "Obsah bez datumu. " * 20).anno is None


@pytest.mark.unit
def test_text_never_fills_numero_nor_oggetto_nor_data() -> None:
    entry = build(make(year=2020), "Metodicky pokyn c. 99/2019 k niecomu\n" + BODY)

    assert entry.numero is None
    assert entry.number is None
    assert entry.oggetto is None
    assert entry.data is None


@pytest.mark.unit
def test_a_sidecar_year_beats_the_group_year_and_the_published_year() -> None:
    entry = build(make(fonte="mfsr-spravodajca", group="2025", year=2024, published="2023-01-01"), BODY)

    assert entry.anno == 2024
    assert entry.warnings == []


@pytest.mark.unit
def test_year_order_without_sidecar_year_is_group_then_published_then_text() -> None:
    assert build(make(fonte="mfsr-spravodajca", group="2025", published="2023-01-01"), BODY).anno == 2025
    assert build(make(published="2022-05-01"), BODY).anno == 2022
    assert build(make(group="vseobecne"), BODY).anno == 2023
