# dp-sk-metodika-convert

Convert class of the `sk-metodika` package (open-lex-it, phase 81b). Reads the grab output of the Slovak guidance sources (`<dirIn>/<safe itemId>/<source_id>.pdf` + `<source_id>.meta.json`, plus
`_coverage.json`) and writes one `<dirOut>/<safe itemId>.plan.json` per item (`plan.schema.json`, `planVersion` 1). Data only: files in, files out, no database, no network.

- Protocol 1.1 stdin class: actions `execute` and `terminate` (`manifest.json`). Params `items`, `dirIn`, `dirOut`; settings `maxDocs`, `only` (`{section|site, docId}`, docId = source_id), `dryRun`; every other Source key may arrive as JSON null and is ignored.
- Text: pypdfium2 text layer (NFC, no-break spaces and soft hyphens normalised, page-number lines at page edges dropped); below 200 characters local tesseract `slk` at 200 dpi (`text_source` = `ocr`). Spike numbers: `tasks/81b-dp-sk-metodika/spike-p81b-07.md` in the umbrella repo.
- Metadata wins: `numero`, `anno`, `data`, `oggetto` come from the grab sidecar; the text may only fill an empty year and never overwrites. A text that names another number or year is a plan warning (`<source_id>: ...`).
- Skipped reasons: `not_a_pdf` (magic bytes `%PDF-`, also an unparsable file), `no_pdf`, `too_large` (> 40 MB), `ocr_empty`, `ocr_unavailable`, `ocr_failed`, `bad_sidecar`, `convert_failed`, and the entry rejects `missing_fonte`, `missing_source_id`, `unsafe_source_id`, `missing_text`. Reasons the grab recorded in `_coverage.json` are carried over.
- The plan is deterministic (sorted keys, no clock): two runs give the same bytes.

## Develop

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest -m "not integration" tests
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy .
```

Tests marked `ocr` need the `tesseract` binary with `slk` data: skipped on a host without it, mandatory in the test image (`REQUIRE_TESSERACT=1`).

## Test image

`docker build -f Dockerfile.test .` installs `tesseract-ocr tesseract-ocr-slk` (apt) and runs the whole unit suite including the `ocr` tests, offline (`docker run --network none` passes).
Measured 2026-11-12: image 547 MB, build 0.6 min with a warm base image (`--no-cache`, apt + pip downloads included), 127 tests passed, 1 skipped (the schema sync test needs the sibling ingest repo).
