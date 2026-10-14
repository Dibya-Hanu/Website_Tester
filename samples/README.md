# Actual OWASP Juice Shop sample

This is a measured run, **not invented example findings**.

- Report ID: `96fd38650f704e048b1f75136ebb4a2a`
- Target: `http://127.0.0.1:3000/` — explicitly approved local OWASP Juice Shop 20.2.0.
- Finished: 2026-10-09T14:37:54.899965+00:00 (UTC).
- Duration: 356 seconds.
- Observed overall score: **55/100**; **82% check coverage**, partial.
- 150 deduplicated findings; 65 independently verified observations.
- 5 pages mapped; 2 navigation-only flows, no submissions.
- 10/12 native cases executed; **5 executed cases came from Ollama**.
  Deterministic fallback cases have distinct per-case provenance.

| Pillar | Score | Coverage | Status | Findings |
|---|---:|---:|---|---:|
| Functionality | 100 | 67% | partial | 0 |
| Security | 82 | 88% | partial | 11 |
| Performance | 38 | 83% | partial | 3 |
| Accessibility | 0 | 67% | partial | 136 |

## Files

- `juice-shop-report.html`: escaped, self-contained, including screenshot evidence.
- `juice-shop-report.pdf`: printable report.
- `juice-shop-report.json`: full measured findings, metrics, cases and AI task ledger.
- `execution-manifest.json`: exact scanner/model provenance and coverage.
- `evidence/`: portable genuine screenshots used by the JSON report.

## Honest limitations

Native 2 GB / 2-core validation used official Apache-2.0 Qwen2.5-0.5B Q2_K weights,
not the larger deployment defaults. Vision was unavailable and is marked skipped.
Some text tasks are partial; one form-generation request exceeded available memory.
Security triage applied to six known findings, but not every ID was reviewed by AI.
Lighthouse and bounded SPA-link coverage are partial. There is no cloud/closed-model
fallback. A reproduced SQL error from one inert quote remains **Possible**, not a
proven injection exploit. Timings are specific to this machine and safety proxy.

Derived stage coverage was rebuilt from the unchanged task ledger to correctly count
accepted partial AI output as partial instead of skipped. All original measurements,
findings, verification statuses and executed-case records were preserved.

See `../TESTING.md` for validation details and untested Docker/vision/public-HTTPS
areas. To reproduce, start the full stack from `../README.md`, then run:

```bash
python scripts/generate_sample.py --url http://juice-shop:3000/
```
