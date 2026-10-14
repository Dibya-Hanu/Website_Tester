# Production Readiness and Implementation Notes

This repository is a local-first, single-workspace hackathon application. The improvements in this revision make the testing flow more adaptive and improve process separation, but **do not make this a safe, multi-tenant public scanning SaaS by themselves**.

## Implemented in this revision

- **Strict competition target policy:** `UWT_REQUIRE_ALLOWLIST_ALL_SCANS=true` is the default. The API refuses a URL not on the exact-origin allowlist before DNS lookup or job creation. The pipeline repeats this check before resolving DNS so manually inserted queued jobs also fail closed. Private, reserved and metadata addresses remain blocked under the existing policy.
- **Adaptive diagnostic planning:** after Playwright observes pages, the local AI can recommend a bounded set of existing check types for observed page IDs, limited to the selected pillars. Recommendations must refer to known pages and match available evidence, such as a form, internal links or screenshots. Supported security recommendations can prioritize bounded header/cookie inspection; performance recommendations can prioritize an observed URL for Lighthouse.
- **Constrained plan execution:** the AI does not generate executable code, unrestricted selectors, arbitrary destinations or shell/network commands. Accepted recommendations only prioritize built-in adapters already controlled by the pipeline. Baseline checks continue even if AI planning fails.
- **Execution transparency:** reports include the AI-selected plan, its rationale, priority, source, mapped scanner, and an execution status/detail. A recommendation is not represented as a confirmed issue merely because the AI suggested it.
- **Adaptive browser readiness:** page navigation uses a bounded load-state wait and DOM-stability sampling rather than relying only on a fixed post-load sleep. Per-page readiness metadata is stored and shown in the report. This is a heuristic; no browser wait can guarantee every application has finished all asynchronous work.
- **Separate Docker worker:** Docker Compose runs FastAPI and the scan worker in separate containers using the same durable data volume. The external worker observes persisted cancellation changes. Native development continues to use the simpler inline worker by default.
- **UI education:** the homepage explains the observe → adapt → verify approach, while the report includes the AI-selected plan and page-readiness information.

## Required before public or multi-user production

These are intentionally called out rather than hidden behind a “production-ready” claim:

1. **Authentication and ownership authorization.** Add a real identity model and enforce owner/tenant authorization on every job, event, report, evidence and cancellation endpoint. A random job ID is not access control. The current UI/API is single-workspace and does not implement tenant isolation.
2. **Per-scan isolation.** The dedicated worker container is a process boundary, not a disposable sandbox per scan. For untrusted multi-user targets, execute each scan in a short-lived container/VM with strict CPU, memory, process, filesystem and outbound-network policies.
3. **Durable production queue/database.** SQLite WAL is appropriate for this single-worker setup. Before running multiple API replicas or workers, move to a shared database/queue with robust claim/lease semantics, idempotency, back-pressure and tested recovery. Do not simply scale worker replicas: ZAP sessions and current artifact handling are shared state.
4. **Network-egress review.** Keep exact-origin allowlisting enabled for the hackathon. Audit DNS rebinding, all redirect hops, IPv4/IPv6 handling, alternate protocols and every scanner’s proxy configuration in the production deployment. Confirm scanners cannot bypass the enforced proxy.
5. **Secrets, reports and privacy.** Add artifact access controls, retention/deletion policies, encryption where appropriate, secret redaction tests and privacy notice/consent. Screenshots and public pages may still contain sensitive information.
6. **Abuse protection and operations.** Add distributed rate/concurrency quotas, scan time budgets, worker heartbeats, alerting, structured audit logs, backups and recovery drills. Test cancellation while each scanner subprocess is running.
7. **License and model review.** Pin and review the exact model artifacts and versions plus every scanner/library license and redistribution condition. Check the combined container image and model weights, not just package names.
8. **Evaluation.** Maintain a benchmark of known seeded defects across more than one approved application. Track precision, recall, reproducibility, pillar coverage, latency and actual-model success/fallback rate over repeated runs.

## Validation checklist for the team

- [ ] An unapproved exact origin receives HTTP 403 before DNS resolution or queue creation.
- [ ] A queued/manual job for an unapproved origin is refused in the pipeline before DNS or scanner startup.
- [ ] Only organizer-approved exact origins appear in the allowlist during the competition.
- [ ] A real local Ollama run produces a schema-valid diagnostic plan; task status and latency are recorded.
- [ ] Accepted recommendations refer only to observed pages and applicable evidence.
- [ ] At least one recommended functional check is executed by Playwright and its observed result appears in the report.
- [ ] AI unavailable/invalid output triggers explicit failed/partial task reporting and does not falsely imply that an AI task ran.
- [ ] Browser readiness works on delayed hydration, a normal multi-page site and a long-lived-connection SPA without unbounded waits.
- [ ] Cancel a live scan through the API and confirm the worker stops browser/scanner processes and releases the proxy.
- [ ] Repeated runs against the benchmark record true positives, false positives, false negatives and scan failures.
- [ ] Do not expose this deployment publicly until authentication, ownership checks and isolation requirements above are addressed.

## Configuration

- `UWT_REQUIRE_ALLOWLIST_ALL_SCANS=true`: recommended for hackathons and labs; every scan must be on the approved exact-origin allowlist.
- `UWT_REQUIRE_ALLOWLIST_ALL_SCANS=false`: administrator opt-in for deployments that intentionally permit limited passive checks on public targets. Security and concurrent-load tests still refuse non-allowlisted origins. This is not permission to test unauthorized sites.
- `UWT_WORKER_MODE=inline`: default for native development and the one-command practice demo.
- `UWT_WORKER_MODE=external`: used by Docker Compose; the API and one separate worker share the SQLite/artifact volume. Keep one worker for this revision.
