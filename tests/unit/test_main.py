"""convert: the ``execute`` action end to end on fixture PDFs (item directories, plan files, settings, skipped reasons) and the Proc-protocol loop."""
from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import main
from dp_sk_metodika_convert import ocr, pdftext, plan
from dp_sk_metodika_convert.convert import CONFIG_ERROR, SYSTEM_ERROR, ConvertError, run_convert

FS_ITEM: dict[str, Any] = {"key": "fs:metodicke-pokyny|v1", "meta": {"kind": "fs", "itemId": "fs:metodicke-pokyny", "version": "1", "section": "metodicke-pokyny"}}
NBS_ITEM: dict[str, Any] = {"key": "pdf:nbs-metodicke:all|v1", "meta": {"kind": "pdf", "itemId": "pdf:nbs-metodicke:all", "version": "1", "site": "nbs-metodicke"}}
FS_DIR = "fs_metodicke-pokyny"
NBS_DIR = "pdf_nbs-metodicke_all"


def sidecar_json(source_id: str, **fields: Any) -> str:
    base: dict[str, Any] = {"fonte": "financnasprava", "source_id": source_id, "section": "metodicke-pokyny", "pdf_file": f"{source_id}.pdf"}
    base.update(fields)
    return json.dumps(base, ensure_ascii=False)


def put(directory: Path, source_id: str, pdf: Path | bytes | None, **fields: Any) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{source_id}.meta.json").write_text(sidecar_json(source_id, **fields), encoding="utf-8")
    if isinstance(pdf, Path):
        shutil.copy(pdf, directory / f"{source_id}.pdf")
    elif pdf is not None:
        (directory / f"{source_id}.pdf").write_bytes(pdf)


@pytest.fixture
def raw(tmp_path: Path, fixtures: Path) -> Path:
    base = tmp_path / "raw"
    fs = base / FS_DIR
    put(fs, "a_mp_10", fixtures / "mfsr-poucenie.pdf", code="10/DZPaU/2026/MP", doc_type="MP", year=2026, published="2026-06-01", title="Metodický pokyn 10")
    put(fs, "b_zapis", fixtures / "fs-zapis-2014.pdf", section="zavery-komisii", year=2014, published="2014-05-09", title="Zápis zo zasadnutia Komisie")
    put(fs, "c_scan", fixtures / "scan-sk.pdf", year=2020, title="Skenovaný pokyn")
    put(fs, "d_html", b"<html><body>Not found</body></html>", title="Stránka namiesto PDF")
    return base


def fake_ocr(_path: Path) -> str:
    return "Prečítaný text skenu. " * 20


def params(raw: Path, tmp_path: Path, items: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"items": items, "dirIn": str(raw), "dirOut": str(tmp_path / "plan"), **extra}


def load(tmp_path: Path, name: str = FS_DIR) -> dict[str, Any]:
    return json.loads((tmp_path / "plan" / f"{name}.plan.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.mark.unit
def test_one_plan_per_item_with_rows_skipped_and_coverage(raw: Path, tmp_path: Path) -> None:
    result = run_convert(params(raw, tmp_path, [FS_ITEM]), lambda *_: None, ocr_fn=fake_ocr)

    document = load(tmp_path)
    assert document["planVersion"] == 1
    assert document["itemId"] == "fs:metodicke-pokyny"
    assert document["fonte"] == "financnasprava"
    assert [row["source_id"] for row in document["documents"]] == ["a_mp_10", "b_zapis", "c_scan"]
    assert [row["text_source"] for row in document["documents"]] == ["pdf", "pdf", "ocr"]
    assert document["skipped"] == [{"fonte": "financnasprava", "item_ref": "d_html", "reason": "not_a_pdf"}]
    assert document["coverage"] == {"fonte": "financnasprava", "item_id": "fs:metodicke-pokyny", "listed": 4, "taken": 3, "skipped": 1, "note": None}
    first, second = document["documents"][0], document["documents"][1]
    assert (first["tipo"], first["numero"], first["anno"], first["data"], first["oggetto"]) == ("MP", "10/DZPaU/2026/MP", 2026, "2026-06-01", "Metodický pokyn 10")
    assert (second["tipo"], second["numero"], second["anno"]) == ("zavery-komisii", None, 2014)
    assert first["ente"] == "Finančná správa SR"
    assert first["pdf_pages"] == 5
    assert first["pdf_bytes"] == (raw / FS_DIR / "a_mp_10.pdf").stat().st_size
    assert len(first["text_raw"]) > 200
    assert result["metrics"] == {"documents": 3, "ocr": 1, "skipped": 1, "warnings": 0}
    assert result["converted"][0]["key"] == FS_ITEM["key"]
    assert result["converted"][0]["plan"] == str(tmp_path / "plan" / f"{FS_DIR}.plan.json")


@pytest.mark.unit
def test_every_plan_validates_against_the_schema(raw: Path, tmp_path: Path, fixtures: Path) -> None:
    schema = json.loads((fixtures.parent.parent / "plan.schema.json").read_text(encoding="utf-8"))
    run_convert(params(raw, tmp_path, [FS_ITEM]), lambda *_: None, ocr_fn=fake_ocr)

    Draft202012Validator(schema).validate(load(tmp_path))


@pytest.mark.unit
def test_plan_documents_have_the_contract_keys_in_sorted_order(raw: Path, tmp_path: Path) -> None:
    run_convert(params(raw, tmp_path, [FS_ITEM]), lambda *_: None, ocr_fn=fake_ocr)
    text = (tmp_path / "plan" / f"{FS_DIR}.plan.json").read_text(encoding="utf-8")
    document = json.loads(text)

    assert list(document) == sorted(document)
    assert set(document["documents"][0]) == {
        "fonte", "source_id", "legacy_doc_id", "ente", "tipo", "section", "group_label", "numero", "number", "dept", "anno", "data", "oggetto",
        "text_raw", "text_source", "source_url", "pdf_bytes", "pdf_pages", "pdf_created",
    }  # fmt: skip
    assert list(document["documents"][0]) == sorted(document["documents"][0])
    assert "\\u" not in text  # diacritics are written as characters


@pytest.mark.unit
def test_the_plan_is_byte_identical_when_run_twice(raw: Path, tmp_path: Path) -> None:
    run_convert(params(raw, tmp_path, [FS_ITEM]), lambda *_: None, ocr_fn=fake_ocr)
    first = (tmp_path / "plan" / f"{FS_DIR}.plan.json").read_bytes()
    (tmp_path / "plan" / f"{FS_DIR}.plan.json").unlink()

    run_convert(params(raw, tmp_path, [FS_ITEM]), lambda *_: None, ocr_fn=fake_ocr)

    assert (tmp_path / "plan" / f"{FS_DIR}.plan.json").read_bytes() == first


@pytest.mark.unit
def test_two_items_sharing_one_dir_do_not_overwrite_each_others_plan(raw: Path, tmp_path: Path, fixtures: Path) -> None:
    put(raw / NBS_DIR, "dokument_0a1b", fixtures / "nbs-stanovisko.pdf", fonte="nbs-metodicke", section="nbs-metodicke", title="Stanovisko NBS")

    run_convert(params(raw, tmp_path, [FS_ITEM, NBS_ITEM]), lambda *_: None, ocr_fn=fake_ocr)

    fs_plan, nbs_plan = load(tmp_path), load(tmp_path, NBS_DIR)
    assert [row["source_id"] for row in fs_plan["documents"]] == ["a_mp_10", "b_zapis", "c_scan"]
    assert [row["source_id"] for row in nbs_plan["documents"]] == ["dokument_0a1b"]
    assert nbs_plan["fonte"] == "nbs-metodicke"
    assert nbs_plan["documents"][0]["ente"] == "Národná banka Slovenska"


@pytest.mark.unit
def test_skipped_reasons(raw: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixtures: Path) -> None:
    fs = raw / FS_DIR
    put(fs, "e_no_pdf", None, title="Bez súboru")
    put(fs, "f_big", fixtures / "mfsr-poucenie.pdf")
    put(fs, "g_empty_scan", fixtures / "scan-sk.pdf")
    put(fs, "h_no_tesseract", fixtures / "scan-sk.pdf")
    (fs / "i_bad.meta.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(plan, "MAX_PDF_BYTES", (fs / "f_big.pdf").stat().st_size - 1)
    for name in ("a_mp_10", "b_zapis", "d_html"):
        (fs / f"{name}.meta.json").unlink()
        (fs / f"{name}.pdf").unlink()

    def selective(path: Path) -> str:
        if path.stem == "g_empty_scan":
            raise ocr.OcrEmpty("nothing")
        if path.stem == "h_no_tesseract":
            raise ocr.OcrUnavailable("tesseract")
        return fake_ocr(path)

    run_convert(params(raw, tmp_path, [FS_ITEM]), lambda *_: None, ocr_fn=selective)

    document = load(tmp_path)
    reasons = {row["item_ref"]: row["reason"] for row in document["skipped"]}
    assert reasons == {
        "e_no_pdf": "no_pdf",
        "f_big": "too_large",
        "g_empty_scan": "ocr_empty",
        "h_no_tesseract": "ocr_unavailable",
        "i_bad": "bad_sidecar",
    }
    assert [row["source_id"] for row in document["documents"]] == ["c_scan"]
    assert document["coverage"]["listed"] == 6
    assert document["coverage"]["skipped"] == 5


@pytest.mark.unit
def test_a_sidecar_whose_source_id_differs_from_its_file_name_is_skipped(raw: Path, tmp_path: Path) -> None:
    (raw / FS_DIR / "x_name.meta.json").write_text(sidecar_json("../../evil"), encoding="utf-8")
    shutil.copy(raw / FS_DIR / "a_mp_10.pdf", raw / FS_DIR / "x_name.pdf")

    run_convert(params(raw, tmp_path, [FS_ITEM]), lambda *_: None, ocr_fn=fake_ocr)

    document = load(tmp_path)
    assert "x_name" in {row["item_ref"] for row in document["skipped"]}
    assert all(row["source_id"] != "../../evil" for row in document["documents"])
    assert not (tmp_path / "evil.pdf").exists()


@pytest.mark.unit
def test_a_metadata_mismatch_is_a_plan_warning_and_the_source_value_stays(raw: Path, tmp_path: Path, fixtures: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    put(raw / FS_DIR, "j_conflict", fixtures / "mfsr-poucenie.pdf", code="10/DZPaU/2026/MP", number=10, year=2026)
    monkey_text = "Metodicky pokyn c. 99/2019 k niecomu. " + "Obsah pokynu. " * 40

    def pdf_text(_path: Path) -> list[str]:
        return [monkey_text]

    monkeypatch.setattr(pdftext, "extract_pages", pdf_text)
    result = run_convert(params(raw, tmp_path, [FS_ITEM], only=[{"section": "metodicke-pokyny", "docId": "j_conflict"}]), lambda *_: None, ocr_fn=fake_ocr)

    document = load(tmp_path)
    row = document["documents"][0]
    assert (row["numero"], row["number"], row["anno"]) == ("10/DZPaU/2026/MP", 10, 2026)
    assert len(document["warnings"]) == 2
    assert all(warning.startswith("j_conflict: ") for warning in document["warnings"])
    assert result["metrics"]["warnings"] == 2


@pytest.mark.unit
def test_grab_coverage_listed_skipped_and_warnings_are_carried(raw: Path, tmp_path: Path) -> None:
    coverage = {
        "fonte": "financnasprava",
        "itemId": "fs:metodicke-pokyny",
        "listed": 40,
        "taken": 4,
        "skipped": [{"item_ref": "https://www.financnasprava.sk/zly.pdf", "reason": "http_404"}],
        "warnings": ["zip_archives_only", "new_leaf:x"],
        "sample_filter": False,
    }
    (raw / FS_DIR / "_coverage.json").write_text(json.dumps(coverage), encoding="utf-8")

    run_convert(params(raw, tmp_path, [FS_ITEM]), lambda *_: None, ocr_fn=fake_ocr)

    document = load(tmp_path)
    assert document["coverage"]["listed"] == 40
    assert document["coverage"]["note"] == "zip_archives_only;new_leaf:x"
    assert {"fonte": "financnasprava", "item_ref": "https://www.financnasprava.sk/zly.pdf", "reason": "http_404"} in document["skipped"]
    assert document["coverage"]["skipped"] == len(document["skipped"]) == 2


@pytest.mark.unit
def test_max_docs_cuts_after_n_sidecars_in_ascending_source_id(raw: Path, tmp_path: Path) -> None:
    result = run_convert(params(raw, tmp_path, [FS_ITEM], maxDocs=2), lambda *_: None, ocr_fn=fake_ocr)

    document = load(tmp_path)
    assert [row["source_id"] for row in document["documents"]] == ["a_mp_10", "b_zapis"]
    assert document["skipped"] == []
    assert document["coverage"]["listed"] == 2
    assert result["metrics"]["documents"] == 2


@pytest.mark.unit
def test_only_selects_by_source_id_and_section(raw: Path, tmp_path: Path) -> None:
    run_convert(
        params(raw, tmp_path, [FS_ITEM], only=[{"section": "metodicke-pokyny", "docId": "c_scan"}, {"section": "metodicke-pokyny", "docId": "b_zapis"}]),
        lambda *_: None,
        ocr_fn=fake_ocr,
    )

    # b_zapis carries section zavery-komisii in its sidecar: the section in `only` does not match, so only c_scan is taken
    assert [row["source_id"] for row in load(tmp_path)["documents"]] == ["c_scan"]


@pytest.mark.unit
def test_only_with_a_site_key_for_pdf_items(raw: Path, tmp_path: Path, fixtures: Path) -> None:
    put(raw / NBS_DIR, "dokument_a", fixtures / "nbs-stanovisko.pdf", fonte="nbs-metodicke", section="nbs-metodicke")
    put(raw / NBS_DIR, "dokument_b", fixtures / "nbs-stanovisko.pdf", fonte="nbs-metodicke", section="nbs-metodicke")

    run_convert(params(raw, tmp_path, [NBS_ITEM], only=[{"site": "nbs-metodicke", "docId": "dokument_b"}]), lambda *_: None, ocr_fn=fake_ocr)

    assert [row["source_id"] for row in load(tmp_path, NBS_DIR)["documents"]] == ["dokument_b"]


@pytest.mark.unit
def test_null_settings_behave_as_absent(raw: Path, tmp_path: Path) -> None:
    nulls = {
        "sections": None, "sites": None, "annoFrom": None, "annoTo": None, "uvoRobotsAck": None, "only": None, "maxDocs": None, "baseUrl": None,
        "delaySeconds": None, "verifyTls": None, "refreshToken": None, "tokenBudget": None, "dryRun": None, "state": None,
    }  # fmt: skip

    result = run_convert(params(raw, tmp_path, [FS_ITEM], **nulls), lambda *_: None, ocr_fn=fake_ocr)

    assert result["metrics"]["documents"] == 3


@pytest.mark.unit
def test_dry_run_reads_and_counts_but_writes_no_plan_and_tolerates_a_missing_item_dir(raw: Path, tmp_path: Path) -> None:
    result = run_convert(params(raw, tmp_path, [FS_ITEM, NBS_ITEM], dryRun=True), lambda *_: None, ocr_fn=fake_ocr)

    assert not (tmp_path / "plan" / f"{FS_DIR}.plan.json").exists()
    assert result["metrics"]["documents"] == 3
    assert [entry["key"] for entry in result["converted"]] == [FS_ITEM["key"], NBS_ITEM["key"]]


@pytest.mark.unit
def test_bad_parameters_are_config_errors(raw: Path, tmp_path: Path) -> None:
    good = {"items": [FS_ITEM], "dirIn": str(raw), "dirOut": str(tmp_path)}
    for bad in (
        {**good, "items": []},
        {**good, "items": [{"key": "x", "meta": {"kind": "gazzetta", "itemId": "x"}}]},
        {**good, "items": [{"key": "x", "meta": {"kind": "fs", "itemId": ".."}}]},
        {**good, "items": [FS_ITEM, {"key": "other", "meta": {"kind": "fs", "itemId": "fs/metodicke-pokyny"}}]},
        {k: v for k, v in good.items() if k != "dirIn"},
        {k: v for k, v in good.items() if k != "dirOut"},
        {**good, "maxDocs": 0},
        {**good, "maxDocs": "many"},
        {**good, "only": "b_zapis"},
        {**good, "only": [{"section": "x"}]},
        {**good, "dryRun": "yes"},
    ):
        with pytest.raises(ConvertError) as caught:
            run_convert(bad, lambda *_: None, ocr_fn=fake_ocr)
        assert caught.value.code == CONFIG_ERROR, bad


@pytest.mark.unit
def test_a_missing_item_dir_fails_that_item_with_a_system_error_but_converts_the_others(raw: Path, tmp_path: Path) -> None:
    with pytest.raises(ConvertError) as caught:
        run_convert(params(raw, tmp_path, [NBS_ITEM, FS_ITEM]), lambda *_: None, ocr_fn=fake_ocr)

    assert caught.value.code == SYSTEM_ERROR
    assert NBS_ITEM["key"] in str(caught.value)
    assert (tmp_path / "plan" / f"{FS_DIR}.plan.json").exists()


@pytest.mark.unit
def test_progress_is_reported_per_item(raw: Path, tmp_path: Path, fixtures: Path) -> None:
    put(raw / NBS_DIR, "dokument_a", fixtures / "nbs-stanovisko.pdf", fonte="nbs-metodicke", section="nbs-metodicke")
    seen: list[tuple[int, str]] = []

    run_convert(params(raw, tmp_path, [FS_ITEM, NBS_ITEM]), lambda percent, message: seen.append((percent, message)), ocr_fn=fake_ocr)

    assert [percent for percent, _ in seen] == [50, 100]


@pytest.mark.unit
def test_the_protocol_loop_answers_execute_terminate_and_bad_requests(raw: Path, tmp_path: Path) -> None:
    request = {"_action": "execute", "_meta": {"executionId": "e1"}, **params(raw, tmp_path, [FS_ITEM], dryRun=True)}
    lines = json.dumps(request) + "\n" + "not json\n" + json.dumps({"_action": "frobnicate", "_meta": {"executionId": "e"}}) + "\n"
    out = io.StringIO()

    code = main.main(io.StringIO(lines + json.dumps({"_action": "terminate", "_meta": {"executionId": "e"}}) + "\n"), out)

    events = [json.loads(line) for line in out.getvalue().splitlines()]
    assert code == 1
    assert [e["type"] for e in events if e["type"] != "progress"] == ["result", "error", "error"]
    assert events[-1]["code"] == "config_error"


@pytest.mark.ocr
def test_a_scan_is_read_by_the_real_tesseract_and_marked_ocr(raw: Path, tmp_path: Path) -> None:
    result = run_convert(params(raw, tmp_path, [FS_ITEM]), lambda *_: None)

    rows = {row["source_id"]: row for row in load(tmp_path)["documents"]}
    assert rows["c_scan"]["text_source"] == "ocr"
    assert "dani" in rows["c_scan"]["text_raw"].lower()
    assert rows["a_mp_10"]["text_source"] == "pdf"
    assert result["metrics"]["ocr"] == 1
