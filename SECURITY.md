# Security and responsible testing

## Operation

This is a local, single-workspace tester for owner/organizer-approved staging targets
and disposable labs. Docker separates the HTTP API from the scanner worker, but this
is not a multi-tenant hosted vulnerability scanning service: user authentication and
tenant ownership checks are not built in. Do not publish it or the lab applications on
the internet without authentication, network isolation and a deployment-specific
security review. Default Compose ports bind to loopback; scanner APIs are internal.

Never weaken the origin allowlist, SSRF/DNS checks, mandatory outbound guard, mutation
blocking, Nuclei template scope, ZAP passive-only mode, or user/time/rate limits to
make a scan "pass". A failed safety configuration must fail closed. Do not add an
origin you do not have permission to test.

Read-only HTTP GET is a conservative practical boundary, not a formal guarantee
that an incorrectly designed target cannot mutate state on GET. Chromium executes
untrusted target JavaScript in an isolated context, with outbound request constraints.
The container runs non-root and drops capabilities; Chromium uses `--no-sandbox` for
container compatibility. The Docker worker runs separately from the API and has container resource/network
boundaries, but it still processes one shared queue and is not a per-job sandbox. For
hostile, multi-tenant use, add per-scan disposable sandboxes/VMs with stronger network
isolation and resource quotas.

## Evidence

Reports can contain screenshots, URLs, publicly exposed identifiers and staging data.
Keep `/app/data` and exported reports private. Cookie values, token values, environment
secrets and authorization headers must never be included in retained scanner evidence.
Do not attach credentials or full sensitive response bodies to a public issue.

## AI boundary

Model input from websites is untrusted. All output is schema-validated and narrowed
to observed page IDs/field slots. The model has no shell, browser, HTTP, source-code,
allowlist or configuration control. It cannot verify an exploit, upgrade verification
status, or suppress a verified fact. Model guesses and visual findings remain labeled.

## Contributions / disclosure

Report an application vulnerability privately to the maintainer of your deployed
fork, using that repository's private security reporting channel. This generated
project does not invent a maintainer email or repository URL. Include a minimal
non-destructive reproduction, affected commit/version and scope; omit real secrets.

New scanner adapters must demonstrate unauthorized refusal, safe proxy configuration,
subprocess timeout/cancellation, evidence redaction and accurate skipped/partial status
in tests before adoption. Never execute arbitrary AI-generated code or unreviewed
attack template packs.

## Security review of the tester itself (this revision)
Checked with automated regression tests (`backend/tests/test_tester_security.py`, `test_additional_coverage.py`, existing policy tests):
URL scheme/private-IP/metadata/IPv6 rejection at submission; DNS answers re-validated on every resolve (rebinding); redirects to other origins refused; path traversal on evidence and job-id routes blocked; hostile finding text escaped in the HTML report (Jinja2 autoescape); no permissive CORS (cross-origin requests get no CORS headers); `nosniff` and `no-store` headers; unknown/oversized request fields rejected; spreadsheet/CSV formula injection neutralised; model output schema-validated, never executed; models are only called at the deployment-configured Ollama URL (never a user-supplied URL).
**Not verified / remaining risk:** no authentication exists (the app is designed for local/trusted use; do not expose it to untrusted networks without a reverse proxy and auth); no external penetration test was done; sqlmap is not used; Windows behaviour untested; DoS limits (queue, pages, timeouts) exist but were not load-tested. This is not a claim that the application is completely secure.


## Competition target policy

Keep `UWT_REQUIRE_ALLOWLIST_ALL_SCANS=true` for hackathon runs. The API rejects a non-allowlisted origin before DNS resolution or queueing, and the worker repeats the check before initializing scanner networking. Setting this flag to `false` is an administrator-only opt-in for passive checks on public targets; it does not permit off-allowlist security or concurrent-load testing. Never disable this control to scan a target that you do not own or have permission to test.
