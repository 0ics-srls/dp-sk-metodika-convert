"""source_id in the convert class: trusted from the grab sidecar, only checked for safety (P81b-05, live fix P81b-34).

The URL-to-id rule lives in the grab class alone (``dp_sk_metodika_grab.ids``); here nothing is recomputed.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from dp_sk_metodika_convert import ids, plan, sidecar
from dp_sk_metodika_convert.entry import Entry, build_entry

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["../../x", "/etc/passwd", "a/b", "a\\b", "..", ".", "", "C:\\x", "a b", "x\x00y", "a:b", "x" * 201])
def test_should_reject_traversal_separators_and_unsafe_names(bad: str) -> None:
    assert not ids.is_safe_source_id(bad)
    with pytest.raises(ids.InvalidSourceId):
        ids.check_source_id(bad)


@pytest.mark.unit
@pytest.mark.parametrize("good", ["extdoc_53262", "2014.05.09_Zapis", "Poučenie_č_1", "dokument_0a1b-2c", "files_archiv_35_Priloha_c_1"])
def test_should_accept_slugs(good: str) -> None:
    assert ids.is_safe_source_id(good)
    assert ids.check_source_id(good) == good


@pytest.mark.unit
def test_the_module_holds_no_url_to_id_rule() -> None:
    public = {name for name, _ in inspect.getmembers(ids, inspect.isfunction)}

    assert public == {"is_safe_source_id", "check_source_id"}
    assert "hashlib" not in vars(ids)
    assert "urlparse" not in vars(ids)


@pytest.mark.unit
def test_the_entry_keeps_the_sidecar_source_id_whatever_the_pdf_url_says(tmp_path: Path) -> None:
    # the URL path would slug to "files_archiv_35_Priloha_c_1"; the grab said otherwise and the convert class must not second-guess it
    meta = tmp_path / "grab_assigned_id.meta.json"
    meta.write_text(
        json.dumps(
            {
                "fonte": "mfsr-spravodajca",
                "source_id": "grab_assigned_id",
                "pdf_file": "grab_assigned_id.pdf",
                "pdf_url": "https://www.mfsr.sk/files/archiv/35/Priloha_c_1.pdf",
                "title": "Príloha",
            },
        ),
        encoding="utf-8",
    )
    side = sidecar.read_sidecar(meta)

    built: Any = build_entry(side, "Text prílohy " * 30, "pdf")

    assert isinstance(built, Entry)
    assert built.source_id == "grab_assigned_id"
    assert built.source_url == "https://www.mfsr.sk/files/archiv/35/Priloha_c_1.pdf"


@pytest.mark.unit
def test_a_sidecar_whose_source_id_differs_from_its_file_name_is_skipped_not_repaired(tmp_path: Path) -> None:
    directory = tmp_path / "raw" / "pdf_mfsr-spravodajca_2026"
    directory.mkdir(parents=True)
    (directory / "a.meta.json").write_text(
        json.dumps({"fonte": "mfsr-spravodajca", "source_id": "files_archiv_35_Priloha_c_1", "pdf_file": "a.pdf", "pdf_url": "https://www.mfsr.sk/files/archiv/35/Priloha_c_1.pdf"}),
        encoding="utf-8",
    )
    (directory / "a.pdf").write_bytes((FIXTURES / "mfsr-poucenie.pdf").read_bytes())
    result_plan = plan.Plan(item_id="pdf:mfsr-spravodajca:2026", fonte="mfsr-spravodajca")

    plan._convert_document(result_plan, "a", directory / "a.meta.json", lambda _p: "")

    assert [(row["item_ref"], row["reason"]) for row in result_plan.skipped] == [("a", "bad_sidecar")]
    assert result_plan.documents == []
