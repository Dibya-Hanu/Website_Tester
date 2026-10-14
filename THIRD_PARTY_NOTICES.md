# Open-source dependencies and local model notices

The application source is MIT. This does not relicense external libraries, tools,
model weights, fixture applications or operating-system packages. Installed packages
retain their upstream license/copyright files. Dependency source/build inputs are in
this repository; unmodified upstream sources are linked below.

| Component | Pinned primary version / default | Upstream license | Source |
|---|---|---|---|
| React / React DOM | 18.3.1 | MIT | https://github.com/facebook/react |
| TypeScript | 5.8.3 | Apache-2.0 | https://github.com/microsoft/TypeScript |
| Tailwind CSS | 3.4.17 | MIT | https://github.com/tailwindlabs/tailwindcss |
| Vite / React plugin | 6.3.5 / 4.5.1 | MIT | https://github.com/vitejs/vite |
| React Router | 6.30.1 | MIT | https://github.com/remix-run/react-router |
| Lucide icons | 0.468.0 | ISC | https://github.com/lucide-icons/lucide |
| Inter fonts | @fontsource/inter 5.2.5 | SIL Open Font License 1.1 | https://github.com/rsms/inter |
| FastAPI | 0.115.12 | MIT | https://github.com/fastapi/fastapi |
| Uvicorn | 0.34.3 | BSD-3-Clause | https://github.com/encode/uvicorn |
| Pydantic | 2.11.7 | MIT | https://github.com/pydantic/pydantic |
| HTTPX | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx |
| Playwright | 1.52.0 | Apache-2.0 | https://github.com/microsoft/playwright |
| Chromium (Playwright build) | 136.0.7103.25 | BSD and bundled open-source notices | https://chromium.googlesource.com/chromium/src |
| mitmproxy | 12.1.2 | MIT | https://github.com/mitmproxy/mitmproxy |
| OWASP ZAP | Docker 2.17.0 | Apache-2.0 | https://github.com/zaproxy/zaproxy |
| Nuclei | 3.4.10 | MIT | https://github.com/projectdiscovery/nuclei |
| Lighthouse | 12.6.1 | Apache-2.0 | https://github.com/GoogleChrome/lighthouse |
| Locust | 2.37.14 | MIT | https://github.com/locustio/locust |
| axe-core | 4.10.3 | MPL-2.0 | https://github.com/dequelabs/axe-core |
| Pa11y | 8.0.0 | LGPL-3.0 | https://github.com/pa11y/pa11y |
| HTML_CodeSniffer (Pa11y runner) | locked by Pa11y | BSD-3-Clause | https://github.com/squizlabs/HTML_CodeSniffer |
| Puppeteer | 22.15.0 | Apache-2.0 | https://github.com/puppeteer/puppeteer |
| Ollama | 0.9.2 | MIT | https://github.com/ollama/ollama |
| Qwen2.5-1.5B-Instruct | qwen2.5:1.5b | Apache-2.0 | https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct |
| Qwen2.5-VL-7B-Instruct | qwen2.5vl:7b | Apache-2.0 | https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct |
| Qwen2.5-0.5B-Instruct (small-machine option) | qwen2.5:0.5b (and official Q2_K quantization) | Apache-2.0 | https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct |
| ReportLab | 4.4.1 | BSD | https://hg.reportlab.com/hg-public/reportlab (project: https://www.reportlab.com/opensource/) |
| Jinja2 | 3.1.6 | BSD-3-Clause | https://github.com/pallets/jinja |
| SQLite | system/Python standard library | Public domain | https://sqlite.org/src |
| OWASP Juice Shop (optional fixture) | v20.2.0 | MIT | https://github.com/juice-shop/juice-shop |
| DVWA (optional fixture) | ghcr.io/digininja/dvwa | GPL-3.0 | https://github.com/digininja/DVWA |
| MariaDB (optional DVWA fixture) | 11.4 | GPL-2.0 | https://github.com/MariaDB/server |

The exact sample versions/outcomes are in `samples/execution-manifest.json`; the
sample environment can differ from the default Docker pins. Nuclei templates and
scanner bridges in this repository are our own MIT code. Pa11y is invoked as an
unmodified independent process; its upstream LGPL license remains intact. axe-core
is injected unmodified into an ephemeral test browser and retains its MPL notice.

`Dockerfile.ollama-cpu` builds a CPU-only runtime from the pinned official release, copying only top-level CPU GGML libraries and omitting optional CUDA/accelerator directories.

Ollama pulls upstream model manifests/weights once and validates layer digests. It
performs all inference locally. The reviewed model tag manifest is in
`backend/app/ai/client.py`; unknown tags are refused rather than presumed open-source.
Do not assume other model sizes/variants share these licenses. No branded Chrome,
closed AI SDK, paid cloud scanner, proprietary model endpoint, OAST service, CDN
font dependency, or proprietary GPU runtime is required by the shipped CPU deployment.

Transitive package versions are fixed by `frontend/package-lock.json` and
`tools/package-lock.json`. Python primary versions are pinned; their transitive
constraints are resolved by pip and upstream open-source dependencies. The Docker
recipe preserves those installed dependency notices. Dependency updates should
include a license check and a rerun of the safety suite.


## Added in this revision
| Component | Use | License |
|---|---|---|
| openpyxl 3.1.5 | Excel (.xlsx) export | MIT |

Model licences and costs: see `MODEL_LICENSES.md` (reported, not re-verified).
