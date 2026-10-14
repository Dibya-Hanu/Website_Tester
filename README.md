# AI Universal Website Tester v3

> **This revision's improvement focus:** strict competition allowlisting, page-readiness metadata,
> AI-selected diagnostic prioritization, report transparency, and a separate Docker scan-worker
> process with persisted cancellation. The existing `backend/` + `frontend/` project structure is
> retained. For native development start with `python scripts/setup_dev.py` and
> `python scripts/run_demo.py`; see `BUILD_STATUS.md` and the `docs/` directory.


**One URL. Four pillars. One evidence-based report.**

An MIT-licensed, local-first, black-box website tester. React + TypeScript + Tailwind
on the frontend; FastAPI with a persistent SQLite queue and replayable SSE progress
on the backend. Real scanners produce the measurements; local Ollama models classify
pages, propose and generate safe tests, triage findings, review screenshots, and write
plain-language explanations and fixes.

No repository access, stack-specific configuration, credentials, paid API, proprietary
AI service, external analytics, or cloud-model fallback is required.

> **Only test targets you own or are explicitly authorized to test.** By default,
> every scan **REFUSES** an origin not on the deployment allowlist, before any target
> request or DNS resolution is initiated. For competition mode, keep
> `UWT_REQUIRE_ALLOWLIST_ALL_SCANS=true` and add only organizer-approved exact origins.
> Setting it to `false` is an explicit administrator opt-in for passive/read-only checks
> on non-allowlisted public targets; security and load testing still require allowlisting.
> This is not a comprehensive penetration test or WCAG certification.

## Quick start — Docker Compose

Prerequisites: Docker Engine / Docker Desktop and Compose v2, an internet connection
for the first image/model downloads, and approximately 15–20 GB of free disk space.
For both models, use **16 GB RAM minimum, 24 GB recommended**, and preferably 4+ CPU
cores. Allocate sufficient RAM to the Docker VM as well. CPU vision inference can be
slow. The Ollama runtime image copies only upstream CPU libraries, excluding optional
proprietary NVIDIA accelerator directories. No proprietary accelerator runtime is needed.

```bash
cd ai-universal-website-tester
cp .env.example .env
# Includes disposable, local OWASP Juice Shop and DVWA:
docker compose --profile labs up --build -d
# First startup automatically downloads the approved open-source local models.
docker compose logs -f model-init
```

Open **http://localhost:8080**. Enter only a website URL, leave all pillars selected,
and click **Start test**. For the bundled labs, enter:

```text
http://juice-shop:3000/
http://dvwa:80/
```

These are container-network URLs resolved by the backend, not by your browser. The
labs' optional browser-facing addresses are http://localhost:3000 and
http://localhost:4280, respectively. The tester's **default allowlist contains the
container origins**, not every public Juice Shop/DVWA instance or every localhost port.

Once submitted, the API enqueues the job and the dedicated worker runs the crawl, AI
planning/tasks, scanners, verification, scoring and report generation. The report now
shows the AI-selected diagnostic plan and whether recommendations were executed,
observed, partially completed or not confirmed. Follow the live progress screen; open
an issue's evidence drawer, filter findings, or export HTML/PDF/JSON. Past reports
persist in the `app-data` volume.

Without bundled labs, run `docker compose up --build -d` and add your organizer-approved
origins before starting security/load checks. Check **System & tool status** in the UI
or `/api/tools` for actual availability.

### Explicit authorization

Edit `.env` as the deployment administrator; visitors cannot change the allowlist:

```dotenv
UWT_ALLOWLIST=http://juice-shop:3000,http://dvwa:80,https://staging.your-approved-site.example
```

Authorization matches **scheme + exact hostname + effective port**. It is not substring,
suffix, product-name, wildcard, or subdomain matching. Paths do not narrow an origin-wide
approval. HTTP and HTTPS are different approvals. Private addresses require an explicit
safe local origin; metadata/link-local/reserved infrastructure addresses remain blocked.
Do not add a host simply because someone pasted its URL. The browser and UI are not the
security boundary: the API and worker also enforce the allowlist.

A refused scan receives a visible `blocked` status and **N/A**, not 100. To run the bundled
labs, keep `UWT_REQUIRE_ALLOWLIST_ALL_SCANS=true` and ensure `.env` allows
`http://juice-shop:3000,http://dvwa:80` (the Compose defaults).
Do not expose the application, ZAP, Ollama, or intentionally vulnerable labs publicly.
The Compose web/lab ports bind to loopback; ZAP and Ollama have no published ports.
For remote collaboration, put an authenticated, TLS-protected reverse proxy in front
of the application. Authentication/multi-tenant isolation is not built into this v1.

### Smaller machines / text-only mode

```dotenv
UWT_TEXT_MODEL=qwen2.5:0.5b
UWT_PULL_VISION=false
UWT_AI_CONTEXT=2048
UWT_AI_KEEP_ALIVE=0
```

Recreate the affected services with `docker compose --profile labs up --build -d`.
This mode is deliberately **partial**: visual review is skipped, and smaller models
can return lower-quality or invalid output. Fallback cases are labeled per case and
are never represented as AI-generated. Measured scanners still run. To disable local
AI altogether, set `UWT_AI_ENABLED=false`; this is also reported as partial.

## What runs

| Stage | Implementation | Important boundary |
|---|---|---|
| Crawl & map | Playwright, same-origin BFS, DOM forms, observed GET endpoints, desktop/mobile screenshots | Default 8 pages / depth 2; no arbitrary action-button crawler |
| Page classes & flows | Local Qwen text inference in bounded batches | Known page IDs only; proposed flows are not completed transactions |
| Adaptive diagnostic plan | Local AI selects among built-in tests for the selected pillars; priorities are tied to observed page IDs | No generated code/commands/selectors; unsupported recommendations are dropped and baseline checks still run |
| Generated cases | Ollama structured JSON with grammar-constrained field slots | Empty, invalid, boundary and inert special-character cases; observed fields only |
| Functionality | Playwright validation and navigation-only flow replay, internal HTTP links, console errors, HTTP errors, broken images | No account guesses, purchases, registrations, uploads or mutation submissions |
| Custom security | Headers/cookies on the root plus up to two AI-prioritized observed pages, signature-checked `.git/HEAD`/`.env`, robots metadata, inert reflection and punctuation-only SQL signals | Allowlist required; pages selected from crawl observations only; no JavaScript payload execution, UNION/stacked SQL, time delays or extraction |
| ZAP | API-driven **passive baseline**, seeded by safe crawl pages and observed GET endpoints | Safe mode; verified upstream guard; active scan and autonomous/AJAX/form spiders disabled |
| Nuclei | Three committed GET-only templates | No downloaded template pack, OAST, fuzzing, code or headless templates |
| Performance | Lighthouse mobile lab, three HTTP timings, Locust read-only concurrency | LCP/CLS/FCP/TBT; field percentiles and INP are not invented |
| Accessibility | axe-core WCAG 2/2.1 and Pa11y/HTML_CodeSniffer WCAG2AA | Objective rule errors vs possible/manual-review warnings |
| Visual UX | Qwen2.5-VL desktop/mobile screenshot review | Always Possible; no invented contrast ratio or verified visual judgment |
| Verification & synthesis | Independent GET/browser re-tests, deterministic root-cause deduplication, AI triage and fixes | AI cannot execute tools or upgrade verification; suppressed originals remain in JSON |

### Non-destructive design

- Every tool's outbound target traffic passes through a per-job **mitmproxy safety
  guard**. The target DNS result is pinned; cross-origin requests and redirects,
  state-changing methods, action-like URLs, credential query keys, WebSockets,
  excessive requests, and oversized responses are blocked.
- Browser contexts block service workers/downloads and additionally route-guard all
  requests. Even an on-input POST from target JavaScript is refused.
- Forms are filled and native validity is inspected. After initial loading, form-case
  network callbacks are blocked entirely, even GET; forms are never submitted as POST.
  Flow replay means safe navigation among observed URLs, not authenticated checkout.
  Server-side validation, successful login, lockout behavior, and transaction outcomes
  cannot be established safely from an arbitrary URL alone.
- The reflection marker is an inert `<uwt-probe>` tag. Unescaped reflection remains
  **Possible** HTML/XSS exposure, never Verified executable XSS. A reproduced database
  error from a quote remains **Possible**, not a demonstrated SQL injection exploit.
- Locust defaults to **4 users / 10 seconds** and has hard caps of **20 users / 30
  seconds**, request timeouts, a global rate cap (default 15 req/s, maximum 20), and
  early stop on backoff, repeated slow responses, or >20% failures after 8 requests.
- `.env` values, cookie values, JWTs and authentication headers are not retained.
  Screenshots may still contain sensitive public/staging content: keep the data local.

Read-only GETs can still have side effects on a badly designed target. No universal
black-box tool can prove otherwise. Use owner-approved staging or disposable labs;
never interpret the safety limits as permission to test an unrelated production site.

## Models, libraries and licenses

The default models are **Qwen2.5-1.5B-Instruct** (`qwen2.5:1.5b`) and
**Qwen2.5-VL-7B-Instruct** (`qwen2.5vl:7b`), both Apache-2.0 licensed. These exact
variants were chosen intentionally; not every size in a family has the same license.
The model manifest also permits the official lower-memory
`qwen2.5:0.5b-instruct-q2_K` quantization, reviewed Apache-2.0 Qwen text sizes and
`mistral:7b`.
Unreviewed model tags are refused; there is no closed/cloud-model fallback.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for primary tool licenses and model
source links. Dependencies are pinned in requirements/package lock files. MIT applies
to this application's code, not as a replacement for the dependencies' own licenses.

## Reports & scoring

Every issue contains a title, pillar, severity, exact URL/element/header, evidence,
plain explanation, concrete suggested fix, provenance, and **Verified / Possible**
status. HTML is escaped and self-contained, including local screenshot data URIs.
PDF uses ReportLab; JSON contains the sitemap, flows, generated cases, AI tasks,
measurements, scanner coverage, suppressed originals, and limitations.

Scores are transparent heuristics, **not** an industry certification:

- Start at 100 for an assessed pillar; severity penalties are Critical 24, High 12,
  Medium 6, Low 2, Info 0. Possible signals use half weight.
- Group matching root causes and cap repeated-instance amplification at 1.6×, avoiding
  double punishment for tool duplicates. Performance is also capped by the measured
  Lighthouse score when available.
- Unassessed, refused, or unselected pillars have a null score. Overall averages only
  assessed selected pillars. Missing checks reduce **coverage**, not an invented metric.
- Completed check = 1 coverage unit; partial = 0.5; failed/skipped/blocked = 0.
  A 100 observed score with partial coverage is **not** a comprehensive pass. The UI
  displays the partial warning and every missing/limited check.

## Repository structure

```text
backend/
  app/
    main.py                 FastAPI app + static frontend
    core/                   models, settings, exact-origin policy, redaction,
                            SQLite persistence, subprocess and guard lifecycle
    ai/                     Ollama client + scoped classification/tests/triage/vision
    scanners/               browser, custom HTTP, ZAP, Nuclei, accessibility, performance
    pipeline/               durable worker, orchestration, verification, scoring
    api/                    REST/SSE, evidence, HTML/PDF/JSON exports
  tests/                    policy, queue, API, AI gates, scoring, exports, real guard
frontend/src/
  components/               issue table, evidence drawer, scores, dialogs
  pages/                    home, progress, report, history
  App.tsx                   responsive workspace and routes
tools/
  proxy/addon.py            DNS-pinned, same-origin, read-only egress guard
  runner.mjs                Lighthouse + Pa11y Chromium bridge
  locustfile.py             hard-capped load + circuit breaker
  nuclei/*.yaml             reviewed read-only templates
scripts/                    automatic model bootstrap, pinned Nuclei install,
                            smoke check, real sample generation/import
samples/                    measured Juice Shop report + execution manifest/evidence
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the system diagram, trust boundaries and design.

## Native development

Docker is the supported full-stack path. Native development is optional and requires
Python 3.12+, Node 20.20+ / 22+, Chromium system libraries, local Ollama and ZAP.
No target-specific source access is involved.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements-dev.txt
playwright install --with-deps chromium
# Browser deps on unsupported Linux distributions may need their distro package names.
(cd tools && PUPPETEER_SKIP_DOWNLOAD=true npm ci)
python scripts/install_nuclei.py "$PWD/.venv/bin/nuclei"
(cd frontend && npm ci)
```

Configure native locations in `.env` (`UWT_OLLAMA_URL`, `UWT_ZAP_URL`,
`UWT_PROXY_ADVERTISED_HOST=127.0.0.1`) and approved exact local lab origins. Start
Ollama/ZAP (disable ZAP telemetry with `-config callhome.tel.enabled=false`), then bootstrap the reviewed local models:

```bash
PYTHONPATH=backend python scripts/bootstrap_models.py
PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1
# In a second terminal:
cd frontend && npm run dev
```

The Vite development server proxies `/api` to FastAPI. Browser code uses relative
URLs, never localhost to reach a separate backend. To serve a production frontend
from FastAPI, run `npm run build` in `frontend` **before starting** the backend.
Native development defaults to one inline worker. Docker Compose uses a separate worker
container (`UWT_WORKER_MODE=external`) but still runs only one worker because ZAP sessions
are shared state and intentionally serial.

### Tests

```bash
.venv/bin/pytest -q backend/tests
(cd frontend && npm run build)
.venv/bin/python scripts/smoke.py http://localhost:8080
```

The suite uses only mocked transports or explicitly approved in-process local fixtures.
It covers origin bypasses, metadata/DNS restrictions, hard caps, source/limit override
rejection, persisted queue recovery, SSE replay, AI scope gates, evidence redaction,
verification limits, exports, and a real proxy enforcing mutation/redirect refusal.
The shipped `TESTING.md` records the actual validation performed for this deliverable.

## Actual Juice Shop sample

`samples/juice-shop-report.{html,pdf,json}` is a **real measured scan**, not fabricated
example findings. `samples/execution-manifest.json` records the exact target, date,
versions, scanner outcomes and AI tasks. The bundled sample is partial; consult that
manifest rather than assuming every scanner/model succeeded. Timing is specific to
the machine and safety proxy. The fixture was OWASP Juice Shop v20.2.0.

Regenerate through the same URL-only API:

```bash
# Host Python with httpx installed (already in requirements):
python scripts/generate_sample.py --url http://juice-shop:3000/
# Or entirely inside the app container, writing to its writable data volume:
docker compose exec app python scripts/generate_sample.py \
  --url http://juice-shop:3000/ --output /app/data/samples
```

To import the shipped measured example into a fresh local history (optional):

```bash
docker compose exec app python scripts/import_sample.py
# Native equivalent: PYTHONPATH=backend python scripts/import_sample.py
```

## Troubleshooting

- **Waiting on first startup:** inspect `docker compose logs model-init ollama`. Initial
  weights are several GB; subsequent starts reuse the model volume.
- **AI skipped/failed:** verify `/api/tools`, installed model tags, available RAM and
  inference timeout. Reduce page/form limits on small machines; skipped AI is visible.
- **Security/load blocked:** compare exact scheme, host and port with `/api/policy`.
  The public Juice Shop demo is not implicitly approved.
- **ZAP refused to scan:** its safe mode/upstream proxy could not be verified. Do not
  disable the guard; inspect app/ZAP logs and service DNS instead.
- **CDN-heavy site looks incomplete:** third-party resources are intentionally blocked.
  Rendering/UX and Lighthouse results include this caveat; do not treat resulting
  layout differences as confirmed production defects.
- **No forms/login coverage:** only observed, fillable controls are tested. Hidden menu
  links, authentication gates, captchas and unsupported widgets limit URL-only coverage.
- **Very long run:** CPU vision is expensive. The overall job timeout is 40 minutes by
  default; subprocess cancellation/timeout terminates their process groups safely.
- **Restart/cancel:** interrupted jobs are recovered once; repeated interruption fails
  clearly. Queued/running jobs can be cancelled from the progress screen.

## Contributing & responsible operation

Keep new scanner templates read-only, bounded, allowlist-gated, and covered by refusal
and network-policy tests. Never add active attacks, arbitrary generated code execution,
external model fallbacks, or stress-test defaults. Preserve provenance and coverage
when changing report schemas. See [SECURITY.md](SECURITY.md).

**License:** [MIT](LICENSE). Contributions welcome.

## Revision 2: AI Models hub, Excel export, fixes
* **AI Models** (sidebar): browse the model catalogue, filter by task/type, see licence/cost/deployment, rank with transparent weighted criteria, **Test Model** (small safe task against your local Ollama), **Select** (saved to `data/model_selection.json`). Unknown facts show "Unknown — verify before production". No hosted-API calls are implemented. See `MODEL_LICENSES.md`.
* **Export Excel (XLSX)** on the report page: 8 sheets built from the same report data as HTML/PDF/JSON/CSV; formula injection neutralised; empty categories say "Not Run".
* **Bug fixed:** the default text model `qwen2.5:1.5b` was silently blocked by a code comment inside `OPEN_MODELS`, so AI steps were always skipped. See `TEST_REPORT.md`.
* Tests: `cd backend && python -m pytest -q`; UI: `python scripts/check_ui_models.py` (after `python scripts/run_demo.py`).
