# Validation record

## Latest modification pass (October 2026)

The project was modified to enforce exact-origin allowlisting for every scan by default,
add page-aware AI diagnostic planning and adaptive DOM-readiness metadata, improve report
transparency, and separate the Docker scan worker from the HTTP API process. Native
scripts retain the inline worker default.

Validation performed in the modification environment:

- `python -m compileall -q backend/app backend/tests`: passed.
- Backend suite excluding the two mitmproxy-dependent integration files:
  **149 passed, 5 skipped**. The excluded `test_form_network.py` and
  `test_guard_integration.py` require the `mitmdump` executable, which is not installed
  in this environment; those tests were not counted as passing.
- All frontend `.ts` / `.tsx` source files parsed without TypeScript syntax errors.
  A full `npm run build` / type-check could not be run because installing the npm
  dependencies timed out and left an incomplete local `node_modules` directory.
- `docker-compose.yml` parsed successfully as YAML. Docker Compose could not be started
  here because the Docker CLI/daemon is unavailable.
- Real Ollama inference and full browser/scanner integration were not exercised in this
  modification environment. Run the project setup and validate with the actual approved
  practice app before relying on the live demo.

These results are a fresh run of the modified source. They supersede earlier test counts
for the specific test subset above, but do not imply that excluded proxy tests, the
frontend production build, Docker startup or real-model inference succeeded.

---

This record describes executed tests, not a promise of complete universal coverage.

## Automated backend tests

**73 passed** on Python 3.13 / Debian 13. Run:

```bash
.venv/bin/pytest -q backend/tests
```

The captured output is in `docs/backend-tests.log`. One upstream Starlette/AnyIO
deprecation warning is non-fatal. Tests include:

- Exact-origin authorization; suffix/userinfo/port bypass rejection; metadata,
  link-local, private-DNS and ambiguous address restrictions.
- Administrator hard limits, and rejection of source/stack/model/limit overrides in
  the URL-only submission schema.
- SQLite atomic claims, queue backpressure, persisted events, recovery and cancellation.
- API validation, report readiness, SSE replay and evidence path protection.
- HTML escaping, null/unassessed scoring, partial coverage, deterministic deduplication,
  provenance retention, sensitive-value redaction and SPA exposure false-positive checks.
- AI known-page/field-slot gates, inert values, fallback provenance, independent
  contradiction requirements and inability to suppress a Verified fact.
- A **real HTTP fixture + mitmproxy**: approved GET works; POST, action URL and
  cross-origin metadata redirect are blocked. The redirect test also verifies correct
  HTTP body framing rather than merely testing a mocked refusal.
- A **real Chromium fixture** whose input event tries to call a GET endpoint: four
  validation categories execute with **zero GET/POST callbacks reaching the server**.
- A security-only, nonallowlisted pipeline request launches no guard/scanner/target HTTP.
- Proposed AI flows replay only known pages, with `submitted:false` on every observation.

## Browser UI validation

`npm run build` succeeds: TypeScript checking plus the Vite production build. The
frontend sources have been formatted with pinned open-source Prettier.

```bash
.venv/bin/python scripts/check_ui.py --job <a-completed-real-job-id>
```

The script checks the actual running app, not screenshots of a static mock:

1. URL-only entry and four initially selected pillars; explicit unauthorized warning.
2. Pillar + severity filters return the expected rows.
3. Finding drawer exposes location/evidence/fix, with Escape-to-close.
4. Durable past-report history renders.
5. 390px mobile viewport has no page-level horizontal overflow.
6. HTML download includes self-contained screenshot data URIs.
7. PDF download has a valid PDF signature.
8. JSON download identifies the actual measured report.

The captured output is `docs/screenshots/ui-validation.json`; screenshots are in the
same directory. The last completed audit reported **zero uncaught JavaScript errors**
and **zero axe-core WCAG 2/2.1 A/AA violations** across home desktop, report desktop,
issue drawer, history desktop and home mobile. This narrow automated result is not a
manual accessibility certification.

The UI validation found and fixed faint text contrast and a mobile overflow caused by
an absolutely positioned screen-reader table header. The final table scroll container
contains that positioning without removing accessible header text.

## Real end-to-end run

The shipped Juice Shop exports are genuinely measured. The exact final run data is in
`samples/execution-manifest.json`, including every stage and AI task. It was submitted
through **POST `/api/jobs` with only a URL**, after which the backend automatically ran
the complete selected pipeline. Earlier development runs remain only in local history,
not as invented dashboard fixtures.

Environment:

- OWASP Juice Shop **20.2.0**, served as an explicitly approved local fixture.
- Native Linux, approximately **2 GB RAM / 2 CPU cores**; no Docker daemon available.
- Actual Playwright Chromium, axe-core, Pa11y, Lighthouse, bounded Locust, Nuclei 3.4.10,
  ZAP **2.16.1**, and Ollama **0.9.2**.
- Official Apache-2.0 **Qwen2.5-0.5B Q2_K** text weights, with a 2048-token context,
  chosen solely for this small environment. Deployment defaults use Qwen 1.5B / vision 7B.
- No vision model installed: its tasks are explicitly skipped, never fabricated.

Local inference was actually exercised for classification, proposed known-page flows,
scoped form-case generation/execution, security triage and final synthesis. Not every
small-model output is usable; missing categories use separately labeled deterministic
cases. Scanner timings are specific to this machine and the mandatory safety proxy.

## Not validated here

- **Docker Compose build/start and the CPU-only Ollama runtime image were not executed**
  because Docker is unavailable. The recipes, dependencies, paths and service configuration
  are provided; native component integration was exercised.
- Default **Qwen 1.5B / Qwen2.5-VL 7B** inference was not exercised in this 2 GB sandbox.
  There is no claim of a successful visual-review sample.
- Public HTTPS DNS-pinning/TLS-SNI integration was not exercised against an external
  organizer-approved site. Policy and redirect tests cover local fixtures and mocks.
- DVWA's optional container/database setup was not run here.
- Authenticated server-side login, checkout, account mutations and destructive security
  probes are deliberately not tested, by design.
- No sustained/stress load test was performed; only the configured light, bounded GET run.

These limitations must remain visible when evaluating the sample. Reproduce on an
appropriately resourced approved deployment with the README commands.

A derived-coverage reporting fix now counts accepted partial AI output as partial,
not skipped. Five regression cases cover that aggregation. The sample coverage was
rebuilt from its unchanged recorded task ledger with `scripts/recompute_sample.py`;
no finding, measurement, case, or verification result was invented or changed.
