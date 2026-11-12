"""Entry rules: port of the legacy ``_to_entry`` with P81b-05/06/08 (NULL instead of invented values, ente with diacritics)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dp_sk_metodika_convert import sidecar
from dp_sk_metodika_convert.entry import Entry, Rejected, build_entry

TEXT = "Metodicky pokyn k obmedzeniu platieb v hotovosti. " * 10


def make_sidecar(**fields: Any) -> sidecar.Sidecar:
    base: dict[str, Any] = {"fonte": "financnasprava", "source_id": "doc_1"}
    base.update(fields)
    return sidecar.Sidecar.from_dict(base)


def entry_of(**fields: Any) -> Entry:
    result = build_entry(make_sidecar(**fields), TEXT, "pdf")
    assert isinstance(result, Entry), result
    return result


@pytest.mark.unit
def test_fs_metodicky_pokyn_golden() -> None:
    entry = entry_of(
        section="metodicke-pokyny",
        code="10/DZPaU/2026/MP",
        doc_type="MP",
        year=2026,
        published="2026-06-01",
        title="Metodický pokyn k uplatňovaniu zákona č. 394/2012 Z. z.",
        legacy_doc_id="10_DZPaU_2026_MP",
        pdf_url="https://www.financnasprava.sk//_img/x.pdf",
        listing_url="https://www.financnasprava.sk/listing",
    )

    assert entry.ente == "Finančná správa SR"
    assert entry.tipo == "MP"
    assert entry.numero == "10/DZPaU/2026/MP"
    assert entry.anno == 2026
    assert entry.data == "2026-06-01"
    assert entry.oggetto == "Metodický pokyn k uplatňovaniu zákona č. 394/2012 Z. z."
    assert entry.fonte == "financnasprava"
    assert entry.source_id == "doc_1"
    assert entry.legacy_doc_id == "10_DZPaU_2026_MP"
    assert entry.source_url == "https://www.financnasprava.sk//_img/x.pdf"
    assert entry.text_source == "pdf"
    assert entry.warnings == []


@pytest.mark.unit
def test_codeless_zapis_has_section_as_tipo_null_numero_and_year_from_the_metadata() -> None:
    entry = entry_of(section="zavery-komisii", year=2014, published="2014-05-09", title="Zápis zo zasadnutia Komisie", source_id="2014.05.09_Zapis")

    assert entry.tipo == "zavery-komisii"
    assert entry.numero is None
    assert entry.number is None
    assert entry.anno == 2014
    assert entry.data == "2014-05-09"


@pytest.mark.unit
def test_mfsr_code_and_group_year() -> None:
    entry = entry_of(
        fonte="mfsr-spravodajca",
        section="mfsr-spravodajca",
        group="2025",
        code="MF/013819/2025-74",
        number=74,
        year=None,
        title="Metodické usmernenie",
        source_id="files_archiv_2025_1_2_MU",
    )

    assert entry.ente == "Ministerstvo financií SR"
    assert entry.numero == "MF/013819/2025-74"
    assert entry.number == 74
    assert entry.anno == 2025
    assert entry.group_label == "2025"
    assert entry.tipo == "mfsr-spravodajca"


@pytest.mark.unit
def test_nbs_uuid_document() -> None:
    entry = entry_of(
        fonte="nbs-metodicke", section="nbs-metodicke", source_id="dokument_0a1b2c3d-1111-2222-3333-444455556666", title="Stanovisko NBS", year=None
    )

    assert entry.ente == "Národná banka Slovenska"
    assert entry.tipo == "nbs-metodicke"
    assert entry.numero is None
    assert entry.anno is None
    assert entry.data is None


@pytest.mark.unit
def test_uvo_number_and_published_date() -> None:
    entry = entry_of(
        fonte="uvo-metodicke",
        section="uvo-metodicke",
        group="vseobecne",
        code="7/2026",
        published="2026-10-02",
        year=2026,
        source_id="extdoc_53262",
        title="Usmernenie",
    )

    assert entry.ente == "Úrad pre verejné obstarávanie"
    assert entry.numero == "7/2026"
    assert entry.data == "2026-10-02"
    assert entry.anno == 2026
    assert entry.group_label == "vseobecne"


@pytest.mark.unit
def test_numero_falls_back_to_the_number_as_text_never_to_the_source_id() -> None:
    assert entry_of(number=12).numero == "12"
    assert entry_of().numero is None


@pytest.mark.unit
def test_tipo_chain() -> None:
    assert entry_of(doc_type="MU", section="x").tipo == "MU"
    assert entry_of(section="metodicke-usmernenia").tipo == "metodicke-usmernenia"
    assert entry_of(fonte="nbs-metodicke").tipo == "nbs-metodicke"
    assert entry_of().tipo == "dokument"


@pytest.mark.unit
@pytest.mark.parametrize("title", [None, "", "   ", "\n"])
def test_blank_title_gives_null_oggetto(title: str | None) -> None:
    assert entry_of(title=title).oggetto is None


@pytest.mark.unit
def test_unknown_fonte_is_its_own_ente() -> None:
    assert entry_of(fonte="iny-zdroj").ente == "iny-zdroj"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("fields", "text", "reason"),
    [
        ({"fonte": None}, TEXT, "missing_fonte"),
        ({"source_id": None}, TEXT, "missing_source_id"),
        ({}, "", "missing_text"),
        ({}, "   \n ", "missing_text"),
        ({"source_id": "../../x"}, TEXT, "unsafe_source_id"),
    ],
)
def test_rejected(fields: dict[str, Any], text: str, reason: str) -> None:
    result = build_entry(make_sidecar(**fields), text, "pdf")

    assert isinstance(result, Rejected)
    assert result.reason == reason


@pytest.mark.unit
def test_document_dict_has_the_contract_keys_and_sorted_stable_order() -> None:
    entry = build_entry(make_sidecar(section="zavery-komisii", year=2014, pdf_bytes=10), TEXT, "ocr", pdf_pages=3, pdf_created="2014-05-01")
    assert isinstance(entry, Entry)

    document = entry.to_document()

    assert list(document) == sorted(document)
    assert set(document) == {
        "fonte", "source_id", "legacy_doc_id", "ente", "tipo", "section", "group_label", "numero", "number", "dept", "anno", "data", "oggetto",
        "text_raw", "text_source", "source_url", "pdf_bytes", "pdf_pages", "pdf_created",
    }  # fmt: skip
    assert document["text_source"] == "ocr"
    assert document["pdf_pages"] == 3
    assert document["pdf_created"] == "2014-05-01"
    assert json.dumps(document, sort_keys=True) == json.dumps(document)


@pytest.mark.unit
def test_sidecar_reader_treats_null_blank_and_zero_as_unknown(tmp_path: Path) -> None:
    path = tmp_path / "doc_1.meta.json"
    path.write_text(json.dumps({"fonte": "nbs-metodicke", "source_id": "doc_1", "title": "  ", "year": 0, "number": 0, "published": "garbage", "code": ""}), encoding="utf-8")

    side = sidecar.read_sidecar(path)

    assert (side.title, side.year, side.number, side.published, side.code) == (None, None, None, None, None)


@pytest.mark.unit
def test_sidecar_reader_rejects_a_non_object_and_bad_json(tmp_path: Path) -> None:
    for content in ("[1]", "not json", ""):
        path = tmp_path / "x.meta.json"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(sidecar.SidecarError):
            sidecar.read_sidecar(path)


@pytest.mark.unit
def test_list_sidecars_is_sorted_by_source_id(tmp_path: Path) -> None:
    for name in ("b_2", "a_1", "c_3"):
        (tmp_path / f"{name}.meta.json").write_text("{}", encoding="utf-8")
    (tmp_path / "_coverage.json").write_text("{}", encoding="utf-8")
    (tmp_path / "other.json").write_text("{}", encoding="utf-8")

    assert [(source_id, path.name) for source_id, path in sidecar.list_sidecars(tmp_path)] == [
        ("a_1", "a_1.meta.json"),
        ("b_2", "b_2.meta.json"),
        ("c_3", "c_3.meta.json"),
    ]
