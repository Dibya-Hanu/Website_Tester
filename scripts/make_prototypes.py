#!/usr/bin/env python3
"""Render the CONCEPTUAL prototype screens to screenshots/prototypes/*.png (HTML sources are kept beside them).

These are design mockups with illustrative placeholder numbers. They are NOT screenshots of the running app
(those are in screenshots/actual/) and contain no scan results.
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parents[1] / "screenshots" / "prototypes"
CSS = """*{box-sizing:border-box}body{margin:0;font:15px/1.5 Inter,system-ui,Segoe UI,sans-serif;background:#f4f7f6;color:#14232c}
.ban{background:#fff4d6;border-bottom:1px solid #e4c870;color:#7a5a05;font-size:12px;font-weight:700;letter-spacing:.06em;padding:7px 24px;text-transform:uppercase}
.top{display:flex;justify-content:space-between;align-items:center;padding:16px 32px;background:#fff;border-bottom:1px solid #dfe7e5}.logo{font-weight:800;color:#137565}
nav span{margin-left:22px;color:#5b6c75;font-size:14px}nav .on{color:#137565;font-weight:700}main{max-width:1100px;margin:0 auto;padding:28px 32px}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.02em}h2{font-size:18px;margin:0 0 10px}.muted{color:#5b6c75}.card{background:#fff;border:1px solid #dfe7e5;border-radius:12px;padding:20px;margin-bottom:16px}
.btn{display:inline-block;background:#137565;color:#fff;padding:11px 20px;border-radius:8px;font-weight:700}.in{border:1.5px solid #b9c7c4;border-radius:8px;padding:12px 14px;background:#fff;color:#14232c;font-size:16px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.score{font-size:40px;font-weight:800;color:#137565}.bar{height:7px;background:#e6eeec;border-radius:5px}.bar i{display:block;height:7px;border-radius:5px;background:#2b9a85}
.b{display:inline-block;padding:2px 9px;border-radius:5px;font-size:11px;font-weight:800;text-transform:uppercase}.Critical,.High{background:#fde6e6;color:#a8323c}.Medium{background:#fff0d4;color:#8a5f10}.Low{background:#e6effc;color:#365f98}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:11px 10px;border-bottom:1px solid #e6edeb}th{font-size:12px;text-transform:uppercase;color:#5b6c75;letter-spacing:.04em}
pre{background:#f1f5f4;border-radius:8px;padding:12px;font:12.5px/1.5 ui-monospace,Consolas,monospace;margin:8px 0}.fix{background:#eaf6f1;border-left:4px solid #2b9a85;padding:12px 16px;border-radius:6px}
.ai{background:#efeafc;border-left:4px solid #7a5bd0;padding:12px 16px;border-radius:6px;margin-top:12px}.chip{display:inline-block;border:1px solid #b9d6cf;background:#eaf6f1;color:#0f5f52;border-radius:20px;padding:5px 13px;margin:0 6px 6px 0;font-size:13px;font-weight:600}
.step{display:flex;gap:12px;align-items:center;padding:9px 0;border-bottom:1px solid #edf2f1}.dot{width:20px;height:20px;border-radius:50%;flex:none}.ok{background:#2b9a85}.run{background:#e0a42b}.pend{background:#cfd9d7}.skip{background:#9aa8ad}"""


def page(title: str, body: str, active: str) -> str:
    nav = "".join(f'<span class="{"on" if n == active else ""}">{n}</span>' for n in ["Test", "Reports", "History", "System status"])
    return (f"<!doctype html><html lang='en'><meta charset='utf-8'><title>{title}</title><style>{CSS}</style><body>"
            "<div class='ban'>Prototype design &mdash; conceptual mockup with illustrative placeholder data. Not a screenshot of the running application.</div>"
            f"<div class='top'><div class='logo'>&#9679; AI Universal Website Tester</div><nav>{nav}</nav></div><main>{body}</main></body></html>")


def score_card(name, val, cov):
    return f"<div class='card'><div class='muted'>{name}</div><div class='score'>{val}</div><div class='bar'><i style='width:{val}%'></i></div><div class='muted' style='font-size:12px;margin-top:6px'>{cov}% coverage</div></div>"


SCREENS = {}
SCREENS["01-home"] = ("Test", """<h1>Test any website with one URL</h1><p class='muted'>No source code or configuration needed. Security and load checks only run on approved targets.</p>
<div class='card'><h2>Start a website test</h2><div class='in' style='margin-bottom:14px'>http://127.0.0.1:8765/</div>
<div style='margin-bottom:12px'><span class='chip'>&#10003; Functionality</span><span class='chip'>&#10003; Security</span><span class='chip'>&#10003; Performance</span><span class='chip'>&#10003; UX &amp; Accessibility</span></div>
<p class='muted' style='font-size:13px'>&#9744; I confirm I own this site or am explicitly authorized to test it. Unapproved origins receive read-only checks only.</p><span class='btn'>Start test</span></div>
<div class='card'><h2>Recent tests</h2><table><tr><th>Target</th><th>Status</th><th>Score</th></tr><tr><td>practice-shop (example row)</td><td>Completed</td><td>&mdash;</td></tr></table></div>""")
SCREENS["02-scan-progress"] = ("Test", "<h1>Testing 127.0.0.1:8765</h1><p class='muted'>Live phase list; every row reflects a real backend step.</p><div class='card'><div class='bar' style='margin-bottom:14px'><i style='width:58%'></i></div>"
    + "".join(f"<div class='step'><div class='dot {c}'></div><div><b>{t}</b><div class='muted' style='font-size:13px'>{d}</div></div></div>" for t, d, c in [
        ("Authorization &amp; network safety", "Exact origin approved", "ok"), ("Crawl &amp; map the website", "7 pages mapped", "ok"),
        ("Forms &amp; links", "Safe client-side validation only", "ok"), ("Security checks", "Headers, cookies, exposed files", "ok"),
        ("Lighthouse performance audit", "Running...", "run"), ("Accessibility audit", "Waiting", "pend"), ("AI report synthesis", "Skipped if no local model", "pend")])
    + "<span class='btn' style='background:#a8323c;margin-top:14px'>Cancel test</span></div>")
SCREENS["03-website-map"] = ("Reports", """<h1>Website map</h1><p class='muted'>Same-origin pages and the links between them.</p><div class='card'>
<svg viewBox='0 0 1000 380' width='100%'><g stroke='#9fb5b0' stroke-width='2' fill='none'><path d='M500 60 L190 190'/><path d='M500 60 L400 190'/><path d='M500 60 L610 190'/><path d='M500 60 L810 190'/><path d='M190 190 L120 310'/><path d='M810 190 L880 310'/><path d='M400 190 L400 310'/></g>
<g font-size='14' font-weight='700' text-anchor='middle'><g><rect x='430' y='30' width='140' height='54' rx='10' fill='#137565'/><text x='500' y='62' fill='#fff'>/ (Home)</text></g>
<g fill='#fff' stroke='#2b9a85' stroke-width='2'><rect x='120' y='164' width='140' height='54' rx='10'/><rect x='330' y='164' width='140' height='54' rx='10'/><rect x='540' y='164' width='140' height='54' rx='10'/><rect x='740' y='164' width='140' height='54' rx='10'/></g>
<g fill='#14232c'><text x='190' y='196'>/about</text><text x='400' y='196'>/products</text><text x='610' y='196'>/contact</text><text x='810' y='196'>/search</text></g>
<g><rect x='50' y='284' width='140' height='54' rx='10' fill='#fde6e6' stroke='#a8323c' stroke-width='2'/><text x='120' y='316' fill='#a8323c'>/missing (404)</text><rect x='330' y='284' width='140' height='54' rx='10' fill='#fff0d4' stroke='#c98c1a' stroke-width='2'/><text x='400' y='316' fill='#8a5f10'>/assets/big.js</text><rect x='810' y='284' width='140' height='54' rx='10' fill='#fff' stroke='#2b9a85' stroke-width='2'/><text x='880' y='316'>/slow</text></g></g></svg>
<span class='chip'>Green = reachable</span><span class='chip' style='background:#fde6e6;border-color:#e8b4b8;color:#a8323c'>Red = broken</span><span class='chip' style='background:#fff0d4;border-color:#e4c870;color:#8a5f10'>Amber = heavy</span></div>""")
SCREENS["04-results-dashboard"] = ("Reports", "<h1>Results</h1><p class='muted'>Missing measurements are never scored as 100.</p><div class='card' style='display:flex;gap:32px;align-items:center'><div><div class='muted'>Overall</div><div class='score' style='font-size:64px'>66</div></div><div class='muted'>Partial coverage &mdash; ZAP and local AI were unavailable and are listed as skipped. This is not a clean bill of health.</div></div><div class='grid4'>"
    + score_card("Functionality", 83, 83) + score_card("Security", 51, 50) + score_card("Performance", 62, 100) + score_card("UX &amp; Accessibility", 28, 67)
    + "</div><div class='card'><h2>Findings by severity</h2>" + "".join(f"<div style='display:flex;gap:12px;align-items:center;margin:8px 0'><span class='b {s}' style='width:70px;text-align:center'>{s}</span><div class='bar' style='flex:1'><i style='width:{w}%'></i></div><b>{n}</b></div>" for s, w, n in [("High", 30, 7), ("Medium", 70, 16), ("Low", 40, 9)]) + "</div>")
SCREENS["05-findings-table"] = ("Reports", "<h1>Findings</h1><div class='card'><div style='display:flex;gap:10px;margin-bottom:14px'><div class='in' style='flex:1;font-size:14px'>Search findings&hellip;</div><div class='in' style='font-size:14px'>Severity &#9662;</div><div class='in' style='font-size:14px'>Pillar &#9662;</div><div class='in' style='font-size:14px'>Verification &#9662;</div><span class='btn' style='font-size:14px'>Export CSV</span></div>"
    "<table><tr><th>Severity</th><th>Finding</th><th>Pillar</th><th>Where</th><th>Status</th></tr>"
    + "".join(f"<tr><td><span class='b {s}'>{s}</span></td><td>{t}</td><td>{p}</td><td><code>{w}</code></td><td>{v}</td></tr>" for s, t, p, w, v in [
        ("High", "Sensitive environment file is publicly exposed", "Security", "/.env", "Verified"), ("High", "Images must have alternative text", "Accessibility", "/", "Verified"),
        ("Medium", "Content Security Policy is missing", "Security", "/", "Verified"), ("Medium", "Resource returns HTTP 404", "Functionality", "/missing-page", "Verified"),
        ("Medium", "Slow page response", "Performance", "/slow", "Verified"), ("Low", "Email field is not type=email", "Functionality", "/contact", "Possible")]) + "</table></div>")
SCREENS["06-finding-detail"] = ("Reports", """<div class='card'><span class='b High'>High</span> <span class='b' style='background:#e0f3ec;color:#0f5f52'>Verified</span> <span class='muted'>Security &middot; Custom HTTP checks + Nuclei</span>
<h1 style='margin-top:10px'>Sensitive environment file is publicly exposed</h1><p class='muted'>Location: <code>http://127.0.0.1:8765/.env</code></p>
<h2>Evidence</h2><pre>GET /.env  -> HTTP 200 text/plain
Environment-style keys detected (4); sensitive key names: DEMO_SECRET_KEY, DEMO_API_TOKEN. All values withheld.</pre>
<h2>Why it matters</h2><p>Deployment files can hold passwords and API keys that let attackers reach other systems.</p>
<div class='fix'><b>Suggested fix</b><br>Remove the file from the web root, block dotfiles at the web server, and rotate any secret that may have been exposed.</div>
<div class='ai'><b>AI-generated explanation</b> (only shown when a local model ran; labelled separately from scanner facts)<br>Plain-English summary and priority advice appear here.</div></div>""")
SCREENS["07-html-report-preview"] = ("Reports", "<div class='muted' style='font-size:12px;letter-spacing:.1em;font-weight:700'>AI UNIVERSAL WEBSITE TESTER / PARTIAL COVERAGE</div><h1>Website test report</h1><p class='muted'><code>http://127.0.0.1:8765/</code> &middot; 7 pages</p><div class='grid4'>"
    + score_card("Functionality", 83, 83) + score_card("Security", 51, 50) + score_card("Performance", 62, 100) + score_card("UX &amp; Accessibility", 28, 67)
    + "</div><div class='card' style='border-left:4px solid #c89536;background:#fff7e7'><b>Partial report &mdash; not a clean bill of health.</b> Unavailable tools and refused checks are listed below; unassessed pillars have no score.</div><div class='card'><h2>Executive summary</h2><p>Self-contained HTML that works offline, with filters, evidence, screenshots, suggested fixes and a full execution log.</p></div>")
SCREENS["08-accessibility-annotations"] = ("Reports", """<h1>Accessibility annotations</h1><p class='muted'>Numbered boxes mark the elements reported by axe-core and Pa11y.</p><div style='display:grid;grid-template-columns:1.2fr 1fr;gap:20px'>
<div class='card' style='position:relative;height:420px'><div style='font-weight:800;font-size:22px;margin-bottom:8px'>About us</div><div style='position:absolute;left:30px;top:70px;width:300px;height:30px;border:3px solid #a8323c;border-radius:4px'><b style='position:absolute;left:-14px;top:-14px;background:#a8323c;color:#fff;width:24px;height:24px;border-radius:50%;text-align:center'>1</b>Our story (h4 after h1)</div>
<div style='position:absolute;left:30px;top:130px;width:420px;height:56px;border:3px solid #a8323c;border-radius:4px;color:#bbb'><b style='position:absolute;left:-14px;top:-14px;background:#a8323c;color:#fff;width:24px;height:24px;border-radius:50%;text-align:center'>2</b>Light-grey text on white (contrast)</div>
<div style='position:absolute;left:30px;top:220px;width:120px;height:60px;border:3px solid #c98c1a;border-radius:4px;background:#e8efee'><b style='position:absolute;left:-14px;top:-14px;background:#c98c1a;color:#fff;width:24px;height:24px;border-radius:50%;text-align:center'>3</b></div></div>
<div class='card'><h2>Issues on this page</h2><p><b>1</b> Heading levels should only increase by one</p><p><b>2</b> Elements must meet minimum color contrast thresholds</p><p><b>3</b> Image has no alternative text</p><p class='muted' style='font-size:13px'>Machine-detected (axe-core / Pa11y). AI visual suggestions would be listed separately.</p></div></div>""")


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page_ = await browser.new_page(viewport={"width": 1280, "height": 820})
        for name, (active, body) in SCREENS.items():
            html = page(name, body, active)
            (OUT / f"{name}.html").write_text(html, encoding="utf-8")
            await page_.set_content(html)
            await page_.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            print("wrote", name)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
