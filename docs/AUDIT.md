# Audit of the uploaded project (baseline)

**Archive:** `AI-Universal-Website-Tester.zip` (left unchanged). **Stack:** FastAPI + SQLite job queue, React/Vite/Tailwind frontend, Playwright, mitmproxy egress guard, axe-core, Pa11y, Lighthouse, Nuclei (3 curated GET-only templates), ZAP (passive, optional), Locust, Ollama (Qwen) AI layer, Jinja2/ReportLab exports.

**Baseline tests:** 73 passed, 0 failed, 0 skipped (backend, Linux, Python 3.12, Playwright pinned to 1.56 to match the sandbox Chromium).

| Area | Status at upload |
|---|---|
| URL-only input, exact-origin allowlist, SSRF/DNS pinning, redirect checks | Implemented, tested |
| Crawl, links, console/network errors, safe client-side form cases | Implemented |
| Security headers/cookies/exposed files/inert reflection, Nuclei, ZAP | Implemented (ZAP/Nuclei need external binaries) |
| Lighthouse, HTTP timing (landing page only), capped Locust | Implemented; per-page and resource-size metrics **missing** |
| axe, Pa11y, vision review | Implemented (vision needs a local model) |
| Deduplication, scoring, honest partial coverage | Implemented |
| HTML / PDF / JSON export | Implemented; **CSV missing** |
| Bundled non-Docker practice app | **Missing** (Juice Shop/DVWA via Docker only) |
| Windows support/docs | **Missing**; POSIX-only process killing (`os.killpg`, `SIGKILL`) |
| BUILD_STATUS, prototypes, k6 | **Missing** |
| UI | Home, progress (cancel), report (scores, findings, evidence, crawl map, AI sections), history, system/tool status panel. No separate editable Settings page (limits are deployment-owned by design). |

**Unavailable in the audit sandbox:** Docker, Ollama, ZAP, Juice Shop, DVWA. Claims about those in the uploaded docs (e.g. the Juice Shop sample) rest on the uploaded project's own records and were not re-run.
