# TEST_REPORT (revision 2)

Environment: Linux sandbox, Python 3.12, Playwright 1.56 + Chromium, Node 18+, Nuclei 3.4.10. **Not available:** Ollama (no models), OWASP ZAP, Docker, Juice Shop, DVWA, Windows.

## Automated results (real)
`cd backend && python -m pytest -q` → **146 passed, 0 failed, 0 skipped** (111 s). Log: `docs/final-test-run-v2.log`.
Breakdown: 119 from the previous revision (73 originally uploaded) + 6 XLSX + 15 Model Hub + 6 tester-security.
`python scripts/check_ui_models.py` (real Chromium against the real backend) → **16/16 UI checks passed**: AI Models nav, honest Ollama status, Rank, paid filter disables unsupported buttons, Select, Test Model failing honestly (HTTP 503) while Ollama is down, Details, XLSX download opens with 8 sheets, PDF/HTML/JSON/CSV downloads still work, History/Reports/New-test pages still load, no unexpected console errors (the expected 503 from Test Model is filtered and documented in the script).
Screenshots: `screenshots/actual/models-page*.png`, `report-with-xlsx-export.png`.

## Mocked vs real
Model tests use `httpx.MockTransport` to **mock Ollama** (validate the sample-task checking and failure handling). **No real model was ever run in this build**, so real model integration is **unverified/blocked**.

## Defects found and fixed
| Issue | Root cause | Fix | Test |
|---|---|---|---|
| Default text model never ran; AI steps always "skipped" | `OPEN_MODELS` entry `qwen2.5:1.5b` was inside a `#` comment on the previous line | Entries on separate lines; allow-list now also derived from the model catalogue | `test_default_models_are_allowed_regression` |
| Cancel/timeout crashes on Windows | `os.killpg`, `SIGKILL` | Cross-platform process helper (previous revision) | process tests |
| No Excel export, no model hub | missing | Added | `test_xlsx_export.py`, `test_model_hub.py` |

## NOT done / not verified from your requirements (honest list)
* **P0 page readiness / SPA / loading-spinner screenshots / unbounded `networkidle`:** not investigated or changed in this revision.
* **Per-test execution duration for functional tests:** not recorded by the pipeline (the XLSX shows "Not recorded"); form cases are client-side validity checks only, not full user-flow tests (search, direct-route refresh, responsive navigation were not added).
* **Vision AI diagnosis:** the vision model name was already allowed; the real cause of earlier vision failures could not be diagnosed without a running model. Model-health self-test exists in the Model Hub only.
* **Juice Shop / DVWA end-to-end scans:** not run (Docker unavailable). Only the bundled practice app was scanned (previous revision).
* **Hosted/paid model calls and secure API-key storage:** not implemented (listed in catalogue as unsupported). No external AI is contacted.
* **Hardware-profile detection, benchmark scores, measured latency:** not implemented; shown as Not benchmarked / Unknown.
* **Catalogue facts (licences, sizes, memory, context, pricing):** not re-verified (see `MODEL_LICENSES.md`).
* **Scoring/deduplication, SSE progress, job states (Partial etc.), SQLite transactions:** reviewed only through existing tests; no new changes or tests this revision.
* **Visual regression:** no pixel diff; existing pages were only checked to still load. New UI uses existing CSS classes (inline spacing in one new page).
* **Windows/macOS:** untested. **Authentication:** none exists.
* **Clean-room ZIP install** was done as an extraction + test run (see BUILD_STATUS.md), not a full from-scratch setup on a second machine.
