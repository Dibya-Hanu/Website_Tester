# Stability & Live Diagnostic Update — 13 October 2026

This update retains the existing FastAPI/SQLite + React/TypeScript architecture. It focuses on honest live status, edge-case handling, and scanner output integrity rather than introducing a new framework.

## User-visible improvements

- The homepage uses the distinct midnight / violet / cyan **Diagnostic Lab** visual direction rather than the earlier green-and-cream layout.
- The Progress page contains an event-driven **AI Diagnostic Activity** panel. It consumes the persisted SSE event stream and shows the selected local model, whether actual inference was confirmed, accepted recommendations, each recommendation's mapped adapter and execution state, AI task events, site-map observations, verification counts, per-pillar workflow coverage, and unavailable tools. These are backend events, not timer-generated mock data.
- Evidence KPI shows verified, possible, and unresolved counts separately; pipeline coverage is labelled workflow coverage rather than a website quality score.
- The dark visual system includes responsive overrides for the workspace at mobile widths.

## Stability and pillar improvements

### Functional
- A crawl that maps zero pages is marked failed or skipped, never successful by default.
- Browser response observers ignore malformed/internal response URLs safely, and a page-close error no longer tears down the entire crawl.
- Empty link inventories and absent forms remain explicit skipped/not-assessed outcomes. Link health distinguishes discovered links from the subset checked under its request budget, uses a redirect-safe same-origin fetch, and reports request failures/blocked requests.

### Security
- Nuclei clears any stale result file before execution. A zero exit code without a fresh output file is a failure, unreadable output is a failure, and malformed or unsupported output rows produce partial status rather than a silent pass. Metrics report parsed, ignored and malformed rows.
- Local Ollama catalogue and `/api/tools` handling reject malformed JSON shapes as unavailable instead of raising an attribute error. HTTP error bodies that are valid JSON but not objects no longer leave AI tasks stuck in `running`.
- Security triage is marked complete as not-applicable when there were no security findings to triage; the report keeps a real triage run distinct from a scan with no findings. Existing target authorization and read-only policy remain in force.

### Performance
- Per-resource request metrics exclude global duplicate resources that were not fetched a second time.
- Locust output with zero measured requests is failed, not an apparent performance pass. Malformed summary output is surfaced as failed.
- Lighthouse and response-time outputs remain lab measurements; field Core Web Vitals are not fabricated.

### UX / Accessibility
- axe-core with no discovered pages is explicitly skipped, with zero pages audited in metrics.
- A page-aware accessibility recommendation can be marked executed when Pa11y performed the page-level audit even if axe-core was unavailable; execution details say which adapter actually ran. A page audit failure is not labelled executed. Vision findings remain hypotheses requiring review.

### AI orchestration & reporting
- A structurally valid but empty adaptive plan is reported as partial, not as a useful completed plan. Baseline checks still continue.
- The Progress page treats a recommendation as executed only when the pipeline can support that status; a proposal is not displayed as a finding.

## Validation run in this environment

- Python compilation: `python -m compileall -q backend/app backend/tests` — passed.
- Backend suite excluding proxy-integration modules unavailable in this environment: `pytest -q --ignore=tests/test_form_network.py --ignore=tests/test_guard_integration.py --disable-warnings --maxfail=1` from `backend/` — **161 passed, 5 skipped**. The two excluded test modules depend on mitmproxy/proxy integration that could not be exercised here.
- Frontend source syntax: TypeScript's `transpileModule` parsed all 13 `.ts` / `.tsx` source files with no syntax diagnostics. CSS delimiter balance check passed.
- Full `npm run build` was **not verified** in this run: frontend dependency installation timed out and the offline npm cache lacked a required package. Syntax parsing is not a substitute for a TypeScript type-check or Vite production build.
- Live browser run with actual Ollama inference plus ZAP, Nuclei, Lighthouse, Locust, axe-core and Pa11y was not performed here. Those integrations must be checked on the demo machine.

## Remaining known limits

- Functional form testing is intentionally non-submitting; server-side login, checkout and account-mutation journeys are not claimed as tested.
- AI adaptive planning currently prioritizes supported adapters; it is not yet a free-running observe → re-plan → execute follow-up loop.
- Public production still requires authentication and report ownership checks, per-scan disposable sandboxing / stronger egress isolation, data-retention controls, and multi-worker queue design.

## Suggested verification on the demo machine

1. Install exactly the lockfile dependencies with `cd frontend && npm ci && npm run build`.
2. Start the approved practice app, Ollama text model and required scanner tools.
3. Run a URL scan and watch the Progress page. Confirm the model task reports real inference, recommendations transition from proposed to executed/partial/failed/skipped, and the final report's counts match its findings.
4. Check each pillar with its tool deliberately unavailable and confirm coverage is partial/skipped/failed, never silently passed.
5. Repeat with an unapproved origin; in competition mode it must be refused before DNS/target requests.
