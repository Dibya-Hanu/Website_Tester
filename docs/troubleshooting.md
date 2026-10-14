# Troubleshooting
* **`Executable doesn't exist` from Playwright** – `python -m playwright install chromium`. If your Playwright version differs from an already-installed browser build, install the matching one.
* **Lighthouse/axe/Pa11y "skipped"** – run `npm ci` in `tools/` (Node 18+). Check with `python scripts/verify_installation.py`.
* **ZAP "unavailable"** – expected unless you run a ZAP daemon; it is reported as skipped, never as a pass.
* **AI tasks "skipped"** – Ollama not reachable or model not pulled; the scan continues with deterministic fallbacks.
* **Target refused / "not on allowlist"** – set `UWT_ALLOWLIST` to the exact origin (scheme+host+port), e.g. `http://127.0.0.1:8765`. Private/loopback targets are blocked unless allow-listed.
* **Port in use** – `run_demo.py --app-port 8081 --practice-port 8766`.
* **Orphan `mitmdump` after a crash** – it is the outbound safety proxy; stop it (`pkill mitmdump` on Linux, Task Manager on Windows). The next scan starts its own.
* **CSV looks odd in Excel** – the file is UTF-8 with BOM; use Data > From Text/CSV if needed. Cells starting with `'=` were neutralised on purpose.
