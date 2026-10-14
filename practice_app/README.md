# Practice Shop (bundled practice target)

Tiny deliberately-flawed website for demos and tests. Pure standard-library Python, **loopback only** (refuses other hosts), stores nothing, all "secrets" are fake, reflected text can never execute script.

Start/stop (Linux, macOS, Windows): `python scripts/practice_ctl.py start` / `status` / `stop`, or foreground: `python practice_app/practice_shop.py --port 8765`.
Verify: `curl http://127.0.0.1:8765/health` (PowerShell: `Invoke-RestMethod http://127.0.0.1:8765/health`).

Intentional flaws (ground truth in `expected_findings.json`): broken link `/missing-page`; broken image; JS console error on `/about`; email field typed as text; unlabeled inputs; missing alt; low contrast; heading skip; nameless button/link; no security headers; weak `session_id` cookie; fake `/.env` and `/.git/HEAD`; inert HTML reflection at `/search?q=`; 1.8 s `/slow`; ~1.5 MB `/assets/big.js`.

Optional separately authorised targets: OWASP Juice Shop (`docker run -p 3000:3000 bkimminich/juice-shop`) or DVWA; add the exact origin to `UWT_ALLOWLIST` first. Never point the allowlist at a site you are not authorised to test.
