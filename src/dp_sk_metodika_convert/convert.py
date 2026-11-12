"""The ``execute`` action: per item, the grab output (``<dirIn>/<safe itemId>/<source_id>.{pdf,meta.json}``) becomes ``<dirOut>/<safe itemId>.plan.json``
(plan schema v1). The Host shares one ``dir`` between the items of a Run, so every item has its own sub-directory in and its own file out. A failing item
does not stop the others: the run ends with one ``system_error`` listing the failed keys. Settings that arrive as JSON null are absent (P79-30)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dp_sk_metodika_convert import ocr as ocr_mod
from dp_sk_metodika_convert import plan as plan_mod
from dp_sk_metodika_convert.entry import FS_FONTE

if TYPE_CHECKING:
    from collections.abc import Callable

CONFIG_ERROR = "config_error"
SYSTEM_ERROR = "system_error"
KIND_FS, KIND_PDF = "fs", "pdf"
KINDS = (KIND_FS, KIND_PDF)
safe_name = plan_mod.safe_name


class ConvertError(Exception):
    """A run-level failure carrying one of the protocol error codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _validate_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise ConvertError(CONFIG_ERROR, "items must be a non-empty array")
    names: dict[str, str] = {}
    for entry in items:
        meta = entry.get("meta") if isinstance(entry, dict) else None
        if not isinstance(entry, dict) or not entry.get("key") or not isinstance(meta, dict):
            raise ConvertError(CONFIG_ERROR, f"item needs a key and a meta: {entry!r}")
        if meta.get("kind") not in KINDS or not isinstance(meta.get("itemId"), str) or not meta["itemId"]:
            raise ConvertError(CONFIG_ERROR, f"item {entry['key']}: meta.kind must be one of {list(KINDS)} and meta.itemId is required")
        name = safe_name(meta["itemId"])
        if name.strip(".") == "":
            raise ConvertError(CONFIG_ERROR, f"item {entry['key']}: itemId {meta['itemId']!r} is not usable as a directory name")
        if names.setdefault(name, meta["itemId"]) != meta["itemId"]:
            raise ConvertError(CONFIG_ERROR, f"itemIds {names[name]!r} and {meta['itemId']!r} map to the same directory {name!r}")
    return items


def _settings(params: dict[str, Any]) -> tuple[plan_mod.Selection, bool]:
    max_docs, only, dry_run = params.get("maxDocs"), params.get("only"), params.get("dryRun")
    if max_docs is not None and (isinstance(max_docs, bool) or not isinstance(max_docs, int) or max_docs < 1):
        raise ConvertError(CONFIG_ERROR, "maxDocs must be a positive integer")
    if dry_run is not None and not isinstance(dry_run, bool):
        raise ConvertError(CONFIG_ERROR, "dryRun must be a boolean")
    if only is not None:
        if not isinstance(only, list) or not all(isinstance(row, dict) and isinstance(row.get("docId"), str) and row["docId"] for row in only):
            raise ConvertError(CONFIG_ERROR, "only must be an array of objects with a docId (and section or site)")
        only = [{key: str(value) for key, value in row.items() if value is not None} for row in only]
    return plan_mod.Selection(only=only or None, max_docs=max_docs), bool(dry_run)


def _fonte(meta: dict[str, Any]) -> str:
    if meta["kind"] == KIND_FS:
        return FS_FONTE
    site = meta.get("site")
    if isinstance(site, str) and site:
        return site
    parts = str(meta["itemId"]).split(":")
    return parts[1] if len(parts) > 1 and parts[1] else parts[0]


@dataclass(frozen=True)
class _Run:
    """The settings of one execute call."""

    dir_in: Path
    dir_out: Path
    selection: plan_mod.Selection
    dry_run: bool
    ocr_fn: Callable[[Path], str]


def _convert_item(entry: dict[str, Any], run: _Run) -> plan_mod.Plan | None:
    """The plan of one item (written unless ``dry_run``); None for a dry run without grab output."""
    meta = entry["meta"]
    name = safe_name(meta["itemId"])
    source = run.dir_in / name
    if not source.is_dir():
        if run.dry_run:
            return None  # a dry grab downloads nothing: nothing to convert, the item still completes
        msg = f"no grab output for the item at {source}"
        raise ConvertError(SYSTEM_ERROR, msg)
    plan = plan_mod.build_item_plan(source, meta["itemId"], _fonte(meta), run.selection, run.ocr_fn)
    if not run.dry_run:
        run.dir_out.mkdir(parents=True, exist_ok=True)
        target = run.dir_out / f"{name}.plan.json"
        scratch = run.dir_out / f"{name}.plan.json.tmp"
        scratch.write_text(plan.to_json(), encoding="utf-8", newline="\n")
        scratch.replace(target)
    return plan


def run_convert(
    raw_params: dict[str, Any], on_progress: Callable[[int, str], None], ocr_fn: Callable[[Path], str] | None = None,
) -> dict[str, Any]:
    """Converts every item; if any failed raises ConvertError(system_error) naming the keys, after the others were written."""
    params = {name: value for name, value in raw_params.items() if value is not None}  # the Host resolves an undeclared Source config key to null
    items = _validate_items(params.get("items"))
    dir_in, dir_out = params.get("dirIn"), params.get("dirOut")
    if not isinstance(dir_in, str) or not dir_in or not isinstance(dir_out, str) or not dir_out:
        raise ConvertError(CONFIG_ERROR, "dirIn and dirOut are required")
    selection, dry_run = _settings(params)
    run = _Run(Path(dir_in), Path(dir_out), selection, dry_run, ocr_fn or ocr_mod.ocr_pdf)
    totals = {"documents": 0, "ocr": 0, "skipped": 0, "warnings": 0}
    converted: list[dict[str, Any]] = []
    failures: list[str] = []
    for position, entry in enumerate(items):
        try:
            plan = _convert_item(entry, run)
        except ConvertError as error:
            failures.append(f"{entry['key']} ({error})")
        else:
            if plan is not None:
                totals["documents"] += len(plan.documents)
                totals["ocr"] += plan.ocr_count
                totals["skipped"] += len(plan.to_dict()["skipped"])
                totals["warnings"] += len(plan.warnings)
            name = safe_name(entry["meta"]["itemId"])
            converted.append({"key": entry["key"], "plan": str(Path(dir_out) / f"{name}.plan.json"), "meta": entry["meta"]})
        on_progress(int((position + 1) * 100 / len(items)), f"{position + 1}/{len(items)} {entry['key']}")
    if failures:
        msg = f"{len(failures)} of {len(items)} items failed: {'; '.join(failures)}"
        raise ConvertError(SYSTEM_ERROR, msg)
    return {"dirOut": dir_out, "converted": converted, "metrics": totals}
