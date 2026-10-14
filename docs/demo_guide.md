# Five-minute demo

Prepare (once, before presenting): `python scripts/setup_dev.py`, then `python scripts/run_demo.py --keep-running` (Windows: same command). Dashboard: http://127.0.0.1:8080. No internet needed.

| Time | Action | What to say |
|---|---|---|
| 0:00 | Open the dashboard | "One input: a URL. No source code, no stack config." |
| 0:30 | Paste `http://127.0.0.1:8765/`, tick authorization, Start | "Security/load run only on allow-listed origins; anything else gets read-only checks." |
| 1:00 | Progress page | Real phases: crawl, forms, headers/cookies, Nuclei, timing, Lighthouse, load, axe, Pa11y. Show Cancel exists. |
| 2:00 | Report: scores + coverage | "Missing tools are shown as skipped, never as 100." |
| 2:45 | Open a finding (`/.env` exposed, or image alt) | Evidence, location, fix, Verified vs Possible, sources merged from several tools. |
| 3:30 | Crawl map + AI section | If Ollama is running: AI page classification, generated form tests, plain-English fixes, flagged as AI. If not: show the explicit "unavailable, deterministic fallback" status. |
| 4:15 | Export menu: PDF / HTML / JSON / CSV | Open the self-contained HTML. |
| 4:45 | Limits | Black-box snapshot, not a pentest; ZAP/AI optional; no authenticated or state-changing flows. |

Expected findings are listed in `practice_app/expected_findings.json`. A pre-generated run is in `reports/sample/`.
