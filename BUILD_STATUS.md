# BUILD_STATUS: revision 2 summary (see TEST_REPORT.md for details and the full not-done list)
Revision 2 adds: AI Models hub (`backend/app/ai/{registry.py,model_catalog.json}`, `backend/app/api/models_routes.py`, `frontend/src/pages/Models.tsx`), Excel export (`backend/app/api/xlsx_export.py`, 8 sheets), a fix for the blocked default text model, tester-security regression tests, `MODEL_LICENSES.md`, `TEST_REPORT.md`, `.env.example`.
Verified here: **146 tests passed, 0 failed**; **16/16 real-browser UI checks passed**. **Not verified:** any real AI model (Ollama unavailable), Juice Shop/DVWA, ZAP, Windows, hosted models (not implemented), page-readiness/SPA fixes (not done). Previous revision details follow.

# BUILD_STATUS

Everything below was executed in a Linux sandbox (Python 3.12, Playwright 1.56 + Chromium 1194, Node 18+, Nuclei 3.4.10). **Nothing was run on Windows.** Docker, Ollama, OWASP ZAP, Juice Shop and DVWA were not available.

## Test results (real, from `docs/final-test-run.log`)
Command: `cd backend && python -m pytest -q` → **119 passed, 0 failed, 0 skipped** (128.7 s).
Baseline before changes: 73 passed (same environment). New: 46 tests (6 CSV, 32 additional unit, 7 practice-app integration incl. real Chromium crawl, 1 slow full-pipeline test that scans the practice app and asserts the expected findings). Frontend: no unit tests exist; `npm run build` (tsc + vite) succeeded.

## Real scan of the bundled practice app (`reports/sample/`)
`python scripts/run_demo.py` (log: `docs/demo-run.log`): overall **58/100, coverage 68%, partial**. 7 pages, 31 findings (High 9, Medium 16, Low 6; 27 Verified, 4 Possible). Scores: functionality 82 (partial), security 51 (partial), performance 88 (complete), accessibility 13 (partial). All 16 intentional flaws in `practice_app/expected_findings.json` appeared among the finding categories.
**Skipped/partial in that run:** ZAP (not installed), all Ollama AI steps (page classification, AI-written test cases, triage, vision review, synthesis) — fallbacks were used and labelled; form-case step partial. **No AI behaviour was verified in this build.**
Outputs: HTML, JSON, CSV, PDF + evidence screenshots.

## Added / changed
New: `practice_app/` (app, README, expected_findings.json); `scripts/{setup_dev,run_demo,practice_ctl,verify_installation,capture_screenshots,make_prototypes,_proc}.py`; `backend/tests/{test_csv_export,test_additional_coverage,test_practice_app}.py`; `docs/*`; `screenshots/prototypes/` (8 mockups + HTML sources, **conceptual, illustrative numbers**); `screenshots/actual/actual-*.png` (real dashboard screenshots; older Juice-Shop-era images from the uploaded project are in `juice-shop-upload/`); `reports/sample/`.
Modified: `backend/app/api/exports.py` (CSV), `routes.py` (csv route), `core/process.py` + `core/guard.py` (cross-platform process control), `scanners/performance.py` (per-page timing, resource sizes), `scanners/browser.py` (email-type check), `runner.py` (wires page URLs), `frontend/src/pages/Report.tsx` (CSV link), `backend/tests/conftest.py`, `pyproject.toml`, `README.md`.

## Gap status
| Gap | Status |
|---|---|
| 1 CSV export | Done, tested (API + unit), frontend link built |
| 2 Practice app | Done, tested, scanned end to end |
| 3 Windows docs | Written; **commands untested on Windows** |
| 4 BUILD_STATUS | This file |
| 5 Prototype images | 8 mockups rendered; 3 real screenshots captured |
| 6 k6 | **Not implemented.** Locust (existing) retained; k6 would need a separate binary, summary parser and authorisation gate — left out rather than claimed |
| 7 Extra tests | Done for the listed areas except: no browser-level frontend-to-backend test beyond the manual screenshot capture; cancellation tested at process level, not via the full job API |

## Known limitations
Cross-platform code unverified on Windows/macOS. Practice app flaws are synthetic; scores on real sites will differ. Nuclei uses only 3 curated templates. ZAP, Ollama/vision, Juice Shop, DVWA not exercised here. Scores indicate observed quality, not security guarantees. An orphaned `mitmdump` safety proxy can remain if the backend is hard-killed.

## Reproduce
Ubuntu/macOS: `python3 scripts/setup_dev.py && source .venv/bin/activate && python scripts/run_demo.py && (cd backend && python -m pytest -q)`
Windows: `py -3 scripts\setup_dev.py; .\.venv\Scripts\Activate.ps1; python scripts\run_demo.py; cd backend; python -m pytest -q`
