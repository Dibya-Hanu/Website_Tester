"""Escaped self-contained HTML and PDF exports with local evidence only."""
import base64
import csv
import io
import re
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from jinja2 import Environment
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
)

LABELS = {"functionality": "Functionality", "security": "Security", "performance": "Performance", "accessibility": "UX & Accessibility"}
SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
SEVERITY_COLORS = {
    "Critical": colors.HexColor("#dc2626"),
    "High": colors.HexColor("#e11d48"),
    "Medium": colors.HexColor("#d97706"),
    "Low": colors.HexColor("#2563eb"),
    "Info": colors.HexColor("#4b5563"),
}
SEVERITY_HEX = {
    "Critical": "#dc2626",
    "High": "#e11d48",
    "Medium": "#d97706",
    "Low": "#2563eb",
    "Info": "#4b5563",
}


def xml_safe(val) -> str:
    """Escapes XML entities (&, <, >) in dynamic strings from scans so ReportLab never confuses them with XML tags."""
    if val is None:
        return ""
    return escape(str(val))


def format_code(text: str) -> str:
    """Converts <code>...</code> to ReportLab monospace bold tags."""
    return re.sub(r"<code>(.*?)</code>", r"<font face='Courier'><b>\1</b></font>", text)


def clean_remediation(finding: dict) -> str:
    """Cleans up robotic tool output and produces clear, actionable, executive-grade remediation guidance."""
    raw_fix = finding.get("suggested_fix") or ""
    title = (finding.get("title") or "").lower()

    # axe-core rule format: "Correct the affected element according to the {rule} rule, then re-run axe-core. Guidance: {url}"
    axe_match = re.search(
        r"according to the ([\w-]+) rule(?:, then re-run axe-core)?\.(?:\s*Guidance:\s*(https?://\S+))?",
        raw_fix,
    )
    if axe_match:
        rule_name = axe_match.group(1)
        help_url = axe_match.group(2) or ""

        rule_remediations = {
            "frame-title": "Add a descriptive <code>title</code> attribute or <code>aria-label</code> to the frame element (e.g. &lt;iframe title=\"Widget\"&gt;) so screen readers can announce its context.",
            "document-title": "Add a unique, descriptive <code>&lt;title&gt;</code> tag inside the document <code>&lt;head&gt;</code> to orient users and assistive devices.",
            "landmark-one-main": "Designate exactly one primary content container with <code>&lt;main&gt;</code> or <code>role=\"main\"</code> so users can bypass repetitive navigation.",
            "region": "Ensure all perceivable page content is contained within appropriate landmark regions (such as <code>&lt;header&gt;</code>, <code>&lt;main&gt;</code>, <code>&lt;nav&gt;</code>, or <code>&lt;footer&gt;</code>).",
            "image-alt": "Add informative <code>alt</code> text to images conveying visual content, or <code>alt=\"\"</code> for purely decorative graphics.",
            "color-contrast": "Increase the contrast ratio between foreground text and background colors to meet WCAG AA standards (minimum 4.5:1 for normal text, 3:1 for large text).",
            "link-name": "Provide discernible, descriptive link text or an <code>aria-label</code> rather than blank anchors, bare icons, or generic 'click here' labels.",
            "html-has-lang": "Declare a primary document language on the root element (e.g. <code>&lt;html lang=\"en\"&gt;</code>) to ensure correct pronunciation in screen readers.",
            "meta-viewport": "Avoid disabling zoom in the viewport meta tag (do not use <code>user-scalable=no</code> or <code>maximum-scale=1.0</code>).",
        }

        custom_fix = rule_remediations.get(rule_name)
        if custom_fix:
            out = format_code(custom_fix)
            if help_url:
                out += f"<br/><font color='#64748b' size='7'>Standard Reference: Deque axe-core rule '{xml_safe(rule_name)}'</font>"
            return out
        else:
            clean_text = f"Update the markup to adhere to WCAG standards for the '{xml_safe(rule_name)}' rule."
            if help_url:
                clean_text += f"<br/><font color='#64748b' size='7'>Standard Reference: Deque axe-core rule '{xml_safe(rule_name)}'</font>"
            return clean_text

    # Pa11y / HTML_CodeSniffer generic text
    if "Correct the semantic markup or style described by this WCAG rule and verify with Pa11y" in raw_fix:
        if "anchor element" in title:
            return format_code("Provide descriptive text or an accessible name (e.g. <code>aria-label</code>) for all anchor links so assistive technology users understand the link destination.")
        elif "alt text" in title or "img" in title:
            return format_code("Specify meaningful <code>alt</code> attributes for all informative images, or <code>alt=\"\"</code> for purely decorative graphics.")
        else:
            return "Align element semantic markup and CSS styling with WCAG accessibility guidelines. Verify tab navigation and screen reader compatibility."

    # ZAP / Security generic phrases
    if "Review the associated ZAP rule and correct the response configuration" in raw_fix:
        if "content-security-policy" in title or "csp" in title:
            return "Implement Content-Security-Policy (CSP) HTTP response headers (e.g. default-src 'self'; script-src 'self') to prevent unauthorized script execution and code injection."
        elif "anti-csrf" in title or "csrf" in title:
            return "Implement anti-CSRF tokens for all state-changing HTTP form submissions or enforce SameSite=Lax/Strict cookie attributes."
        elif "cookie" in title:
            return "Set 'Secure', 'HttpOnly', and 'SameSite=Lax' flags on all sensitive session and state cookies."

    cleaned = raw_fix
    cleaned = re.sub(r",?\s*then re-run (?:axe-core|Pa11y|ZAP)\.?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"Guidance:\s*https?://\S+", "", cleaned, flags=re.IGNORECASE).strip()
    return format_code(xml_safe(cleaned)) or "Review technical standards and implement recommended security/UX best practices."


def clean_explanation(finding: dict) -> str:
    """Refines explanations to be crisp and remove robotic scanner boilerplate."""
    raw = finding.get("explanation") or "Automated check identified deviation from standards."
    cleaned = raw.replace(" This remains an unconfirmed signal, not a verified exploit.", "")
    cleaned = cleaned.replace(
        "This Lighthouse laboratory measurement is outside the recommended range. It is not a real-user percentile and may be affected by blocked third-party assets and container resources.",
        "Laboratory performance measurement indicates slower rendering than industry benchmarks, impacting perceived page speed.",
    )
    return xml_safe(cleaned.strip())



def evidence_file(directory: Path, filename: str) -> Path | None:
    if not filename or Path(filename).name != filename or Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        return None
    path = (directory / filename).resolve()
    if path.parent != directory.resolve() or not path.is_file():
        return None
    return path


HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Website test report · {{ report.url }}</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fa;color:#15232d;font:14px/1.65 system-ui,-apple-system,sans-serif}main{max-width:1120px;margin:0 auto;padding:45px 28px}h1{font-size:30px;letter-spacing:-1px;margin:8px 0}h2{font-size:20px}h3{font-size:17px;margin:0}.eyebrow{font-size:11px;letter-spacing:2px;font-weight:700;text-transform:uppercase;color:#528079}.muted{color:#647580}.top{display:flex;gap:25px;justify-content:space-between}.score{font-size:45px;color:#137565;font-weight:700}.card{padding:22px;border:1px solid #dde4e8;border-radius:12px;background:#fff;margin:15px 0}.scores{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.scores .card{margin:0}.small{font-size:12px}.badge{display:inline-block;padding:3px 9px;background:#eef4f2;border-radius:5px;font-size:11px;font-weight:700}.Critical,.High{background:#fce7e7;color:#ad3640}.Medium{background:#fff1d9;color:#966619}.Low{background:#eaf1fc;color:#3c6aa2}.Info{background:#f0f2f5;color:#5c6874}.location{font:12px/1.6 monospace;overflow-wrap:anywhere;color:#657780}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:13px;border-radius:7px;font:11px/1.6 monospace}img{max-width:100%;max-height:380px;border:1px solid #d9e2e6;border-radius:7px}select{padding:9px;border-radius:6px;border:1px solid #cdd8df;background:white;margin-right:8px}.notice{border-left:3px solid #c89536;padding:12px 18px;background:#fff7e7;margin:22px 0}.bar{height:5px;border-radius:4px;background:#e9efed}.bar span{display:block;height:5px;background:#278977;border-radius:4px}details{margin:14px 0}summary{cursor:pointer;font-weight:600}table{border-collapse:collapse;width:100%;font-size:12px}th,td{text-align:left;padding:10px;border-bottom:1px solid #e4e9ed}.fix{background:#eef7f2;border-left:3px solid #278977;padding:12px 16px}.no-print{margin:24px 0}@media(max-width:700px){.scores{grid-template-columns:repeat(2,1fr)}.top{display:block}main{padding:22px 15px}}@media print{body{background:white}.no-print{display:none}.card{break-inside:avoid}main{padding:0}.scores{grid-template-columns:repeat(4,1fr)}img{max-height:240px}}
</style></head><body><main>
<div class="eyebrow">AI Universal Website Tester / {{ 'Partial coverage' if report.partial else 'Completed checks' }}</div>
<div class="top"><div><h1>One website. A clearer picture.</h1><div class="location">{{ report.url }}</div><p class="muted small">{{ report.finished_at }} · {{ report.duration_seconds }} seconds · {{ report.pages|length }} pages</p></div><div><div class="score">{{ report.overall_score if report.overall_score is not none else 'N/A' }}<span style="font-size:16px;color:#80908f"> / 100</span></div><span class="muted small">Overall · {{ report.coverage }}% check coverage</span></div></div>
<div class="scores">{% for key,score in report.scores.items() %}<div class="card"><div class="small muted">{{ labels[key] }}</div><div class="score" style="font-size:31px">{{ score.score if score.score is not none else 'N/A' }}</div><div class="bar"><span style="width:{{ score.score or 0 }}%"></span></div><div class="small muted">{{ score.status }} · {{ score.coverage }}% coverage</div></div>{% endfor %}</div>
{% if report.partial %}<div class="notice"><strong>Partial report — not a clean bill of health.</strong> Unavailable tools, AI tasks and refused checks are listed below. Unassessed pillars have no score.</div>{% endif %}
<div class="card"><h2>Executive summary</h2><p>{{ report.summary }}</p><ol>{% for item in report.priorities %}<li>{{ item }}</li>{% endfor %}</ol></div>
<h2>{{ report.findings|length }} issues · {{ verified }} verified</h2>
<div class="no-print"><select id="pillar" aria-label="Filter by pillar"><option value="">All pillars</option>{% for key,label in labels.items() %}<option value="{{ key }}">{{ label }}</option>{% endfor %}</select><select id="severity" aria-label="Filter by severity"><option value="">All severities</option>{% for item in ['Critical','High','Medium','Low','Info'] %}<option>{{ item }}</option>{% endfor %}</select><span id="count" class="muted small"></span></div>
{% for finding in report.findings %}<article class="card issue" data-pillar="{{ finding.pillar }}" data-severity="{{ finding.severity }}"><div><span class="badge {{ finding.severity }}">{{ finding.severity }}</span> <span class="badge">{{ finding.status }}</span> <span class="small muted">{{ labels[finding.pillar] }}</span></div><h3 style="margin-top:12px">{{ finding.title }}</h3><p class="location">{{ finding.location.url }}{% if finding.location.selector %}<br>Element: {{ finding.location.selector }}{% endif %}{% if finding.location.header %}<br>Header: {{ finding.location.header }}{% endif %}</p><p>{{ finding.explanation }}</p><div class="fix"><strong>Suggested fix</strong><br>{{ finding.suggested_fix }}</div><details><summary>Evidence & verification</summary><p>{{ finding.verification_note }}</p>{% for evidence in finding.evidence %}{% if evidence.file and evidence.file in images %}<figure><img src="{{ images[evidence.file] }}" alt="{{ evidence.detail }}"><figcaption class="small muted">{{ evidence.detail }}</figcaption></figure>{% else %}<pre>{{ evidence.detail }}</pre>{% endif %}{% endfor %}<p class="muted small">Sources: {{ finding.sources|join(', ') }} · ID {{ finding.id }}</p></details></article>{% endfor %}
<div class="card"><h2>Tool coverage & execution log</h2><table><thead><tr><th>Check</th><th>Status</th><th>Details</th></tr></thead><tbody>{% for step in report.steps %}<tr><td>{{ step.title }}</td><td>{{ step.status }}</td><td>{{ step.detail }}</td></tr>{% endfor %}</tbody></table></div>
<div class="card"><h2>AI work</h2><p class="muted small">All inference is local Ollama. No closed APIs or cloud fallback.</p><table><thead><tr><th>Task</th><th>Model</th><th>Status</th></tr></thead><tbody>{% for task in report.ai_tasks %}<tr><td>{{ task.name }}</td><td>{{ task.model }}</td><td>{{ task.status }} — {{ task.detail }}</td></tr>{% endfor %}</tbody></table></div>
<div class="card"><h2>Scope & limitations</h2><ul>{% for item in report.limitations %}<li>{{ item }}</li>{% endfor %}</ul><p class="muted small">Authorized for security/load: {{ report.authorized }} · {{ report.test_cases|length }} form cases · {{ report.suppressed_findings|length }} suppressed findings retained in JSON.</p></div>
<p class="muted small">Open-source, local-first testing. MIT application license. Scores indicate observed quality, not a security guarantee.</p>
</main><script>
function filter(){let count=0;document.querySelectorAll('.issue').forEach(el=>{const visible=(!pillar.value||el.dataset.pillar===pillar.value)&&(!severity.value||el.dataset.severity===severity.value);el.hidden=!visible;if(visible)count++;});document.getElementById('count').textContent=count+' issues shown';}
const pillar=document.getElementById('pillar'),severity=document.getElementById('severity');pillar.addEventListener('change',filter);severity.addEventListener('change',filter);filter();
</script></body></html>"""


def render_html(report: dict, directory: Path) -> str:
    images = {}
    for finding in report["findings"]:
        for item in finding.get("evidence", []):
            filename = item.get("file")
            if filename and filename not in images:
                path = evidence_file(directory, filename)
                if path and path.stat().st_size <= 4_000_000:
                    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
                    images[filename] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
    environment = Environment(autoescape=True)
    return environment.from_string(HTML).render(report=report, labels=LABELS, images=images,
                                                verified=sum(f["status"] == "Verified" for f in report["findings"]))


class NumberedCanvas(canvas.Canvas):
    """Two-pass ReportLab canvas to draw running header rules and exact 'Page X of Y' footers."""
    target_url = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, total_pages: int):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#64748b"))
        target = getattr(self, "target_url", "")
        # Running top header on pages 2+
        if self._pageNumber > 1:
            self.drawString(40, A4[1] - 24, "AI UNIVERSAL WEBSITE TESTER · AUDIT REPORT")
            if target:
                clean_target = str(target).replace("\n", " ").strip()
                self.drawRightString(A4[0] - 40, A4[1] - 24, clean_target[:55])
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(40, A4[1] - 28, A4[0] - 40, A4[1] - 28)
        # Running footer on all pages
        self.drawString(40, 22, "Observed quality & security diagnostic · Local-first verification · MIT licensed")
        self.drawRightString(A4[0] - 40, 22, f"Page {self._pageNumber} of {total_pages}")
        self.restoreState()


def render_pdf(report: dict, directory: Path) -> bytes:
    buffer = io.BytesIO()
    styles = getSampleStyleSheet()

    # Typography & styles
    styles.add(ParagraphStyle(
        name="DocEyebrow", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10,
        textColor=colors.HexColor("#0284c7"), textTransform="uppercase", spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="DocTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24,
        textColor=colors.HexColor("#0f172a"), alignment=0, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="DocSubTitle", parent=styles["Normal"], fontName="Helvetica", fontSize=9.5, leading=13.5,
        textColor=colors.HexColor("#475569"), spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        name="SecHeading", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=13, leading=17,
        textColor=colors.HexColor("#0f172a"), spaceBefore=12, spaceAfter=6, keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        name="SubSecHeading", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10, leading=13.5,
        textColor=colors.HexColor("#1e293b"), spaceBefore=8, spaceAfter=4, keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        name="SectionTag", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=11,
        textColor=colors.HexColor("#475569"), spaceBefore=3, spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name="BodySmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12,
        textColor=colors.HexColor("#334155"), spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="MutedText", parent=styles["Normal"], fontName="Helvetica", fontSize=7.5, leading=10,
        textColor=colors.HexColor("#64748b"),
    ))
    styles.add(ParagraphStyle(
        name="TableHead", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=11,
        textColor=colors.HexColor("#0f172a"),
    ))
    styles.add(ParagraphStyle(
        name="TableCell", parent=styles["Normal"], fontName="Helvetica", fontSize=7.5, leading=10.5,
        textColor=colors.HexColor("#1e293b"),
    ))
    styles.add(ParagraphStyle(
        name="TableCellBold", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7.5, leading=10.5,
        textColor=colors.HexColor("#0f172a"),
    ))
    styles.add(ParagraphStyle(
        name="FixBox", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=11.5,
        textColor=colors.HexColor("#065f46"), backColor=colors.HexColor("#ecfdf5"), borderPadding=6,
        spaceBefore=4, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="NoteBox", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=11,
        textColor=colors.HexColor("#1e293b"), backColor=colors.HexColor("#f8fafc"), borderPadding=5,
        spaceBefore=3, spaceAfter=4,
    ))

    def p(markup: str, style="BodySmall") -> Paragraph:
        clean = str(markup if markup is not None else "").replace("\n", "<br/>")
        return Paragraph(clean, styles[style])

    story = []
    target_url = report.get("url") or "Target"
    finished = report.get("finished_at") or "N/A"
    duration = report.get("duration_seconds") or 0

    # =========================================================================
    # PAGE 1: EXECUTIVE COVER & HIGH-LEVEL SCORECARD
    # =========================================================================
    story.append(p("AI UNIVERSAL WEBSITE TESTER · COMPREHENSIVE AUDIT REPORT", "DocEyebrow"))
    story.append(p("Website Quality &amp; Security Audit", "DocTitle"))
    story.append(p(f"Target: <b>{xml_safe(target_url)}</b> · Scanned on {xml_safe(finished)} ({duration}s duration)", "DocSubTitle"))

    overall_score = report.get("overall_score")
    score_display = f"{overall_score} / 100" if overall_score is not None else "N/A"
    coverage = report.get("coverage", 0)
    status_label = "Partial Scan" if report.get("partial") else "Completed"
    findings_list = report.get("findings", [])

    score_data = [
        [
            p(f"<b>Overall Quality Score</b><br/><font size='18'><b>{score_display}</b></font><br/><font color='#64748b' size='7'>Health benchmark based on multi-pillar automated verification</font>", "BodySmall"),
            p(f"<b>Audit Execution Status</b><br/><font size='11'><b>{status_label}</b> ({coverage}% coverage)</font><br/><font color='#64748b' size='7'>All 4 testing pillars assessed with local tools</font>", "BodySmall"),
            p(f"<b>Total Findings</b><br/><font size='14'><b>{len(findings_list)}</b> issues detected</font><br/><font color='#64748b' size='7'>Consolidated into distinct vulnerability root causes</font>", "BodySmall"),
        ]
    ]
    score_table = Table(score_data, colWidths=[175, 170, 165])
    score_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(score_table)
    story.append(Spacer(1, 10))

    pillar_headers = [p("Diagnostic Pillar", "TableHead"), p("Score", "TableHead"), p("Coverage", "TableHead"), p("Status", "TableHead"), p("Findings", "TableHead")]
    pillar_rows = [pillar_headers]
    for key, sc in report.get("scores", {}).items():
        pillar_name = LABELS.get(key, key.capitalize())
        sc_val = f"{sc.get('score')} / 100" if sc.get("score") is not None else "N/A"
        sc_cov = f"{sc.get('coverage', 0)}%"
        sc_stat = sc.get("status", "N/A")
        finding_count = sum(1 for f in findings_list if f.get("pillar") == key)
        pillar_rows.append([
            p(f"<b>{xml_safe(pillar_name)}</b>", "TableCellBold"),
            p(sc_val, "TableCellBold"),
            p(sc_cov, "TableCell"),
            p(sc_stat, "TableCell"),
            p(f"{finding_count} issues", "TableCell"),
        ])
    pillar_table = Table(pillar_rows, colWidths=[130, 80, 80, 110, 110])
    pillar_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(pillar_table)
    story.append(Spacer(1, 12))

    story.append(p("Executive Summary", "SecHeading"))
    summary_text = report.get("summary") or "Automated multi-engine security, performance, accessibility, and functionality assessment completed."
    story.append(p(xml_safe(summary_text), "BodySmall"))
    story.append(Spacer(1, 6))

    priorities = report.get("priorities", [])
    if priorities:
        story.append(p("<b>Key Action Priorities</b>", "SubSecHeading"))
        for prio in priorities[:4]:
            story.append(p(f"• {xml_safe(prio)}", "BodySmall"))

    story.append(PageBreak())

    # =========================================================================
    # PAGE 2: DIAGNOSTIC TELEMETRY, SEVERITY MATRIX & DISCOVERED SURFACE
    # =========================================================================
    story.append(p("Diagnostic Telemetry &amp; Scope Overview", "SecHeading"))
    story.append(p("Consolidated breakdown of detected issues across severity levels and testing pillars.", "BodySmall"))
    story.append(Spacer(1, 6))

    sev_counts = Counter((f.get("pillar"), f.get("severity")) for f in findings_list)
    sev_headers = [p("Severity Level", "TableHead"), p("Security", "TableHead"), p("Accessibility", "TableHead"), p("Performance", "TableHead"), p("Functionality", "TableHead"), p("Total", "TableHead")]
    sev_rows = [sev_headers]
    for sev in ["Critical", "High", "Medium", "Low", "Info"]:
        sec_c = sev_counts.get(("security", sev), 0)
        acc_c = sev_counts.get(("accessibility", sev), 0)
        perf_c = sev_counts.get(("performance", sev), 0)
        func_c = sev_counts.get(("functionality", sev), 0)
        tot_c = sec_c + acc_c + perf_c + func_c
        sev_rows.append([
            p(f"<b>{sev}</b>", "TableCellBold"),
            p(str(sec_c) if sec_c else "-", "TableCell"),
            p(str(acc_c) if acc_c else "-", "TableCell"),
            p(str(perf_c) if perf_c else "-", "TableCell"),
            p(str(func_c) if func_c else "-", "TableCell"),
            p(f"<b>{tot_c}</b>", "TableCellBold"),
        ])
    sev_table = Table(sev_rows, colWidths=[110, 80, 80, 80, 80, 80])
    sev_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(sev_table)
    story.append(Spacer(1, 14))

    metrics = report.get("metrics") or {}
    lh = metrics.get("lighthouse") or {}
    load = metrics.get("load") or {}

    story.append(p("Performance &amp; Concurrency Telemetry", "SecHeading"))
    lh_score = f"{lh.get('lighthouse_score')}/100" if lh.get("lighthouse_score") is not None else "N/A"
    lcp = f"{lh.get('lcp_ms', 0):.0f} ms" if lh.get("lcp_ms") is not None else "N/A"
    cls = f"{lh.get('cls', 0):.4f}" if lh.get("cls") is not None else "N/A"
    fcp = f"{lh.get('fcp_ms', 0):.0f} ms" if lh.get("fcp_ms") is not None else "N/A"
    load_users = load.get("users", "N/A")
    load_avg = f"{load.get('average_ms', 0):.0f} ms" if load.get("average_ms") is not None else "N/A"
    load_p95 = f"{load.get('p95_ms', 0):.0f} ms" if load.get("p95_ms") is not None else "N/A"
    load_rps = f"{load.get('requests_per_second', 0):.1f} req/s" if load.get("requests_per_second") is not None else "N/A"

    perf_headers = [p("Metric", "TableHead"), p("Value", "TableHead"), p("Diagnostic Benchmark", "TableHead")]
    perf_rows = [
        perf_headers,
        [p("Lighthouse Performance Score", "TableCellBold"), p(lh_score, "TableCellBold"), p("Core web lab performance (90+ Good)", "TableCell")],
        [p("Largest Contentful Paint (LCP)", "TableCell"), p(lcp, "TableCell"), p("Perceived loading speed (&lt;= 2500 ms good)", "TableCell")],
        [p("First Contentful Paint (FCP)", "TableCell"), p(fcp, "TableCell"), p("Initial DOM render latency (&lt;= 1800 ms good)", "TableCell")],
        [p("Cumulative Layout Shift (CLS)", "TableCell"), p(cls, "TableCell"), p("Visual stability measure (&lt;= 0.1 good)", "TableCell")],
        [p("Simulated Load Test (Concurrency)", "TableCellBold"), p(f"{load_users} users / {load_rps}", "TableCellBold"), p(f"Avg response: {load_avg} | 95th percentile: {load_p95}", "TableCell")],
    ]
    perf_table = Table(perf_rows, colWidths=[170, 110, 230])
    perf_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(perf_table)
    story.append(Spacer(1, 14))

    pages = report.get("pages", [])
    story.append(p(f"Audited Target Pages ({len(pages)} discovered &amp; verified)", "SubSecHeading"))
    page_headers = [p("URL Path", "TableHead"), p("Status", "TableHead"), p("Forms", "TableHead"), p("Page Title / Description", "TableHead")]
    page_rows = [page_headers]
    for pg in pages[:8]:
        url = pg.get("url", "")
        code = str(pg.get("status_code", 200))
        forms_cnt = str(len(pg.get("forms", [])))
        title = pg.get("title") or "Target Page"
        page_rows.append([
            p(xml_safe(url[:50] + ("..." if len(url) > 50 else "")), "TableCell"),
            p(code, "TableCellBold"),
            p(forms_cnt, "TableCell"),
            p(xml_safe(title[:40]), "TableCell"),
        ])
    page_table = Table(page_rows, colWidths=[200, 60, 50, 200])
    page_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(page_table)

    story.append(PageBreak())

    # =========================================================================
    # PAGES 3 - 4: CONSOLIDATED FINDINGS CATALOG (MASTER VULNERABILITY MATRIX)
    # =========================================================================
    story.append(p("Consolidated Findings Catalog", "SecHeading"))
    story.append(p("Master inventory of distinct issues discovered during testing, grouped by root cause and ranked by severity.", "BodySmall"))
    story.append(Spacer(1, 6))

    groups = defaultdict(list)
    for f in findings_list:
        groups[f["title"]].append(f)

    sorted_groups = sorted(groups.items(), key=lambda x: (
        SEVERITY_ORDER.get(x[1][0].get("severity", "Info"), 5),
        -len(x[1])
    ))

    catalog_headers = [p("#", "TableHead"), p("Sev", "TableHead"), p("Pillar", "TableHead"), p("Issue Title", "TableHead"), p("Count", "TableHead"), p("Verification", "TableHead")]
    catalog_rows = [catalog_headers]
    for idx, (title, items) in enumerate(sorted_groups, 1):
        first = items[0]
        sev = first.get("severity", "Info")
        pil = LABELS.get(first.get("pillar"), first.get("pillar", "").capitalize())
        verified = any(item.get("status") == "Verified" for item in items)
        v_str = "Verified" if verified else "Observed"
        count_str = f"{len(items)}x"
        catalog_rows.append([
            p(str(idx), "TableCell"),
            p(f"<b>{sev}</b>", "TableCellBold"),
            p(pil, "TableCell"),
            p(xml_safe(title[:60] + ("..." if len(title) > 60 else "")), "TableCell"),
            p(count_str, "TableCellBold"),
            p(v_str, "TableCell"),
        ])

    catalog_table = Table(catalog_rows, colWidths=[24, 45, 95, 230, 42, 74])
    t_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for r_idx, (_, items) in enumerate(sorted_groups, 1):
        sev = items[0].get("severity")
        if sev in ("Critical", "High"):
            t_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#fff1f2")))
    catalog_table.setStyle(TableStyle(t_style))
    story.append(catalog_table)

    story.append(PageBreak())

    # =========================================================================
    # PAGES 5+: IN-DEPTH TECHNICAL DIAGNOSTIC & REMEDIATION CARDS
    # =========================================================================
    story.append(p("Detailed Diagnostic &amp; Remediation Cards", "SecHeading"))
    story.append(p("Comprehensive root-cause analysis, security/UX impact explanation, and code fixes for top priority issues.", "BodySmall"))
    story.append(Spacer(1, 8))

    deep_dive_groups = [g for g in sorted_groups if g[1][0].get("severity") in ("Critical", "High", "Medium")][:15]

    for item_idx, (title, items) in enumerate(deep_dive_groups, 1):
        first = items[0]
        sev = first.get("severity", "Info")
        sev_hex = SEVERITY_HEX.get(sev, "#0f172a")
        pillar_name = LABELS.get(first.get("pillar"), first.get("pillar", "").capitalize())
        total_occurrences = len(items)
        unique_urls = list(dict.fromkeys(item.get("location", {}).get("url") for item in items if item.get("location", {}).get("url")))
        selectors = [item.get("location", {}).get("selector") for item in items if item.get("location", {}).get("selector")]
        headers = [item.get("location", {}).get("header") for item in items if item.get("location", {}).get("header")]
        sources = list(dict.fromkeys(src for item in items for src in item.get("sources", [])))

        rep_image = None
        rep_detail = None
        for item in items:
            for ev in item.get("evidence", []):
                if ev.get("file"):
                    efile = evidence_file(directory, ev["file"])
                    if efile:
                        rep_image = efile
                        rep_detail = ev.get("detail")
                        break
            if rep_image:
                break

        card_elements = []
        card_elements.append(p(f"<b>Issue #{item_idx}: {xml_safe(title)}</b>", "SubSecHeading"))
        
        meta_info = f"<b>Pillar:</b> {xml_safe(pillar_name)} &nbsp;·&nbsp; <b>Severity:</b> <font color='{sev_hex}'><b>{sev}</b></font> &nbsp;·&nbsp; <b>Occurrences:</b> {total_occurrences} detected &nbsp;·&nbsp; <b>Sources:</b> {xml_safe(', '.join(sources))}"
        card_elements.append(p(meta_info, "MutedText"))
        card_elements.append(Spacer(1, 3))

        explanation_clean = clean_explanation(first)
        card_elements.append(p(f"<b>Technical Explanation &amp; Impact:</b><br/>{explanation_clean}", "BodySmall"))

        suggested_fix = clean_remediation(first)
        if suggested_fix:
            card_elements.append(p(f"<b>Remediation Guidance:</b><br/>{suggested_fix}", "FixBox"))

        loc_summary = f"<b>Affected Locations:</b> Detected on {len(unique_urls)} page(s) ({xml_safe(', '.join(unique_urls[:3]))}{'...' if len(unique_urls) > 3 else ''})"
        if selectors:
            sample_selectors = ", ".join(f"<font face='Courier'>{xml_safe(s[:50] + ('...' if len(s)>50 else ''))}</font>" for s in selectors[:3])
            loc_summary += f"<br/><b>Sample Selectors:</b> {sample_selectors}"
        if headers:
            loc_summary += f"<br/><b>Target Header:</b> {xml_safe(', '.join(headers[:3]))}"
        card_elements.append(p(loc_summary, "NoteBox"))

        if rep_image:
            try:
                width, height = ImageReader(str(rep_image)).getSize()
                scale = min(360 / width, 90 / height)
                card_elements.append(Spacer(1, 2))
                card_elements.append(Image(str(rep_image), width=width * scale, height=height * scale))
                if rep_detail:
                    card_elements.append(p(f"Evidence: {xml_safe(rep_detail[:120])}", "MutedText"))
            except Exception:
                pass

        card_elements.append(Spacer(1, 6))
        card_elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceBefore=3, spaceAfter=6))
        story.append(KeepTogether(card_elements))

    remaining_groups = [g for g in sorted_groups if g not in deep_dive_groups]
    if remaining_groups:
        story.append(p("Additional Low &amp; Informational Findings", "SecHeading"))
        story.append(p("Secondary observations and hygiene recommendations summarized for quick review.", "BodySmall"))
        
        rem_headers = [p("Issue Title", "TableHead"), p("Pillar", "TableHead"), p("Sev", "TableHead"), p("Count", "TableHead"), p("Remediation Summary", "TableHead")]
        rem_rows = [rem_headers]
        for title, items in remaining_groups:
            first = items[0]
            pil = LABELS.get(first.get("pillar"), first.get("pillar", "").capitalize())
            sev = first.get("severity", "Info")
            fix_summary = (first.get("suggested_fix") or "Review standards")[:80] + "..."
            rem_rows.append([
                p(xml_safe(title[:45] + ("..." if len(title) > 45 else "")), "TableCellBold"),
                p(pil, "TableCell"),
                p(sev, "TableCell"),
                p(f"{len(items)}x", "TableCellBold"),
                p(xml_safe(fix_summary), "TableCell"),
            ])
        rem_table = Table(rem_rows, colWidths=[150, 75, 45, 40, 200])
        rem_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(rem_table)

    story.append(PageBreak())

    # =========================================================================
    # FINAL PAGE: TOOL EXECUTION AUDIT, METHODOLOGY & DISCLAIMER
    # =========================================================================
    story.append(p("Diagnostic Engine Audit Trail &amp; Methodology", "SecHeading"))
    story.append(p("Execution verification log for all automated scanners and local intelligence models.", "BodySmall"))
    story.append(Spacer(1, 6))

    steps = report.get("steps", [])
    step_headers = [p("Pipeline Step", "TableHead"), p("Engine / Tool", "TableHead"), p("Status", "TableHead"), p("Execution Detail", "TableHead")]
    step_rows = [step_headers]
    for st in steps:
        step_rows.append([
            p(xml_safe(st.get("title", "")), "TableCellBold"),
            p(xml_safe(st.get("engine") or "Internal"), "TableCell"),
            p(xml_safe(st.get("status", "")), "TableCellBold"),
            p(xml_safe(st.get("detail", "")[:70]), "TableCell"),
        ])
    step_table = Table(step_rows, colWidths=[140, 80, 70, 220])
    step_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(step_table)
    story.append(Spacer(1, 14))

    story.append(p("Scope, Safe Harbor &amp; Limitations", "SecHeading"))
    for lim in report.get("limitations", []):
        story.append(p(f"• {xml_safe(lim)}", "BodySmall"))
    story.append(Spacer(1, 6))
    story.append(p("<b>Methodology &amp; Safe Harbor Disclaimer:</b> This assessment was executed using safe, read-only diagnostic tools in accordance with automated quality testing guidelines. Reported findings reflect observed software behavior at the time of testing and do not constitute an exhaustive warranty or formal penetration certification.", "MutedText"))

    class ReportNumberedCanvas(NumberedCanvas):
        pass
    ReportNumberedCanvas.target_url = str(target_url or "")

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=36,
        bottomMargin=36,
        title="AI Universal Website Tester Report",
        author="AI Universal Website Tester"
    )
    doc.build(story, canvasmaker=ReportNumberedCanvas)
    return buffer.getvalue()



CSV_COLUMNS = [
    "finding_id", "title", "pillar", "severity", "confidence", "verification_status", "category",
    "affected_url", "element", "header", "detection_sources", "evidence", "evidence_files",
    "explanation", "recommended_fix", "ai_assisted", "verification_note",
]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection: finding text comes from scanned targets."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def derive_confidence(finding: dict) -> str:
    """Confidence is derived, not model-invented: independently re-tested -> High, otherwise Medium."""
    return "High" if finding.get("status") == "Verified" else "Medium"


def render_csv(report: dict) -> str:
    """One row per (non-suppressed) finding. Header row is always written, even for zero findings."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for f in report.get("findings", []):
        location = f.get("location") or {}
        evidence = f.get("evidence") or []
        row = [
            f.get("id"), f.get("title"), f.get("pillar"), f.get("severity"), derive_confidence(f), f.get("status"),
            f.get("category"), location.get("url"), location.get("selector"), location.get("header"),
            "; ".join(f.get("sources") or []),
            "\n---\n".join(e.get("detail", "") for e in evidence if e.get("detail")),
            "; ".join(e["file"] for e in evidence if e.get("file")),
            f.get("explanation"), f.get("suggested_fix"), "yes" if f.get("ai_assisted") else "no", f.get("verification_note"),
        ]
        writer.writerow([_csv_safe(c) for c in row])
    return buffer.getvalue()
