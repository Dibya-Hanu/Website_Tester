# Change Log — AI Diagnostic and Reliability Revision

This revision strengthens the existing architecture instead of replacing the stack.

## Backend

- Added bounded, page-aware AI diagnostic recommendations for supported functional, navigation/link, visual and accessibility checks.
- Validated model recommendations against observed page IDs, selected pillars and available page evidence before using them to prioritize existing adapters.
- Added bounded AI prioritization across functional, security, performance and accessibility checks. Security header/cookie inspection can cover up to two additional AI-prioritized observed pages, and Lighthouse can measure an observed same-origin page selected by the plan.
- Added bounded DOM-stability readiness checks and per-page readiness metadata.
- Enforced strict allowlist refusal before DNS resolution in the pipeline as well as at API submission.
- Added a separate external Docker worker mode, persisted cancellation observation and a worker entry point; native development remains inline by default.
- Added regression tests for diagnostic-plan scope, browser readiness, pre-DNS refusal and external-worker cancellation.

## Frontend

- Added a homepage explanation of the observe → adapt → verify loop.
- Added an AI-selected diagnostic-plan panel in the report with priority, rationale, source, mapped runner and execution status.
- Exposed page-readiness metadata in the sitemap and clarified AI availability/fallback language.

## Operations and documentation

- Docker Compose now has separate `app` and `worker` services while retaining one worker by default.
- Updated architecture, security and run instructions.
- Added `PRODUCTION_READINESS.md` with implemented scope, remaining production blockers and a team validation checklist.

## Not claimed

- Real Ollama inference was not run as part of this code-edit environment.
- The full Docker stack was not started here; Docker was unavailable.
- User authentication, tenant ownership, per-scan disposable sandboxing, horizontal worker scaling and a PostgreSQL/Redis production queue are not implemented by this revision.
