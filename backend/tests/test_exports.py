from app.api.exports import evidence_file, render_html


def test_file_paths_are_basename_only(tmp_path):
    (tmp_path/"evidence.png").write_bytes(b"test")
    assert evidence_file(tmp_path,"evidence.png")
    assert evidence_file(tmp_path,"../evidence.png") is None
    assert evidence_file(tmp_path,"secret.txt") is None


def test_untrusted_report_text_escaped(tmp_path):
    report={"url":"<script>alert('url')</script>","partial":True,"overall_score":None,"coverage":0,
            "finished_at":"now","duration_seconds":0,"pages":[],"scores":{},"summary":"<script>alert('summary')</script>",
            "priorities":[],"findings":[],"steps":[],"ai_tasks":[],"limitations":[],"authorized":False,"test_cases":[],"suppressed_findings":[]}
    html=render_html(report,tmp_path)
    assert "<script>alert('url')" not in html
    assert "&lt;script&gt;" in html
