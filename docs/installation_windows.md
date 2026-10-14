# Installation: Windows (PowerShell)

> **Honesty note:** the Windows-specific code paths (process-tree termination with `taskkill`, `Scripts\` executable lookup) were written and reviewed, but this project was **built and tested on Linux**. Windows commands below are **untested**; please report problems.

Prerequisites: Python 3.11–3.13 from python.org (tick "Add python.exe to PATH"), and Node.js 18+ LTS (optional but needed for Lighthouse/axe/Pa11y/dashboard). No admin rights needed.

```powershell
cd ai-universal-website-tester
py -3 scripts\setup_dev.py                 # creates .venv, installs deps + Chromium, tools npm packages, builds frontend
.\.venv\Scripts\Activate.ps1               # if blocked: Set-ExecutionPolicy -Scope Process Bypass
python scripts\verify_installation.py
```
Python only: `py -3 scripts\setup_dev.py --skip-node`.

## One-command demo
```powershell
python scripts\run_demo.py                 # writes reports\sample\ (HTML, JSON, CSV, PDF)
python scripts\run_demo.py --keep-running  # dashboard at http://127.0.0.1:8080 (Ctrl+C to stop)
```

## Run pieces separately
```powershell
python scripts\practice_ctl.py start
$env:UWT_ALLOWLIST = "http://127.0.0.1:8765"; $env:UWT_DATA_DIR = "$PWD\data"; $env:UWT_AI_ENABLED = "false"
cd backend; uvicorn app.main:app --host 127.0.0.1 --port 8080
# second window: cd frontend; npm run dev
python scripts\practice_ctl.py stop
```

## Tests
```powershell
cd backend; python -m pytest -q
python -m pytest -q -m "not slow"
```

## Optional
* Nuclei: `python scripts\install_nuclei.py bin\nuclei.exe` (the installer currently targets Linux release assets; on Windows download the official `nuclei` Windows build, verify its checksum, and set `$env:UWT_NUCLEI_BIN`).
* Ollama for Windows: install from ollama.com, `ollama pull qwen2.5:1.5b`, then `$env:UWT_OLLAMA_URL="http://127.0.0.1:11434"; $env:UWT_AI_ENABLED="true"`.
* Do not use `uvicorn --reload` with scans: Windows reload mode uses an event loop that cannot start Playwright subprocesses.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `running scripts is disabled` | `Set-ExecutionPolicy -Scope Process Bypass` |
| `python` not found | use `py -3` or reinstall Python with PATH ticked |
| Port 8080/8765 busy | `--app-port` / `--practice-port` on run_demo.py; `netstat -ano \| findstr :8080` |
| Chromium missing | `python -m playwright install chromium` |
| Windows Firewall prompt | allow private networks; everything binds to 127.0.0.1 only |
