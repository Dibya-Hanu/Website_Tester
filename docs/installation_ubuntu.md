# Installation: Ubuntu / Linux / macOS

Needs Python 3.11–3.13 and (optional but recommended) Node.js 18+. No root needed, nothing installed system-wide.

```bash
git clone <your-repo-url> ai-universal-website-tester && cd ai-universal-website-tester   # or unzip the archive
python3 scripts/setup_dev.py            # creates .venv, installs deps + Chromium, tools/ npm packages, builds the frontend
source .venv/bin/activate
python scripts/verify_installation.py   # honest list of what is installed / missing
```

Python-only (no Lighthouse/axe/Pa11y/dashboard): `python3 scripts/setup_dev.py --skip-node`.
On a fresh Ubuntu you may need the Chromium system libraries once: `python -m playwright install-deps chromium` (uses sudo; skip if you cannot).

## Run the one-command demo (offline, bundled practice app)
```bash
python scripts/run_demo.py                 # scans http://127.0.0.1:8765/ and writes reports/sample/ (HTML, JSON, CSV, PDF)
python scripts/run_demo.py --keep-running  # then open http://127.0.0.1:8080
```

## Run the pieces yourself
```bash
python scripts/practice_ctl.py start                    # practice app on 127.0.0.1:8765
export UWT_ALLOWLIST=http://127.0.0.1:8765 UWT_DATA_DIR=./data UWT_AI_ENABLED=false
cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8080
# dashboard: http://127.0.0.1:8080  | frontend dev server: cd frontend && npm run dev
python scripts/practice_ctl.py stop
```

## Tests
```bash
cd backend && python -m pytest -q                 # everything (slow integration test ~1 min)
python -m pytest -q -m "not slow"                 # skip the full-pipeline test
```

## Optional components (each is reported as "skipped" when absent, never as a pass)
* **Nuclei**: `python scripts/install_nuclei.py bin/nuclei` then `export UWT_NUCLEI_BIN=$PWD/bin/nuclei`.
* **Local AI (Ollama)**: install Ollama, `ollama pull qwen2.5:1.5b`, then `export UWT_OLLAMA_URL=http://127.0.0.1:11434 UWT_AI_ENABLED=true`. Vision review needs `ollama pull qwen2.5vl:7b` (about 6 GB; check the model licence).
* **OWASP ZAP**: run the ZAP daemon and set `UWT_ZAP_URL` and `UWT_ZAP_API_KEY`.
* **Juice Shop / DVWA** (separately authorised): `docker run -p 3000:3000 bkimminich/juice-shop`, then `UWT_ALLOWLIST=http://127.0.0.1:3000`, and submit that URL.
