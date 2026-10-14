from app.ai.client import LocalAI, OPEN_MODELS
from app.ai.tasks import GeneratedTests, TestCase as GeneratedCase, Triage, TriageItem, generate_cases, triage
from app.core.models import Form, InputField, Pillar, Severity


class FakeAI:
    def __init__(self, result):
        self.result = result
    async def perform(self, *args, **kwargs):
        return self.result


def form():
    return Form(id="f1",page_id="p1",selector="#form",action="http://lab.test:3000/",method="POST",
                fields=[InputField(id="email",selector="#email",type="email",required=True)])


async def test_ai_cannot_invent_selectors_or_unknown_fields():
    malicious = GeneratedTests(tests=[GeneratedCase(name="bad",form_id="f1",kind="special",inputs={"unknown":"x"})])
    cases, source = await generate_cases(FakeAI(malicious), form(), 4)
    assert "fallback" in source.lower()
    assert all(set(case.inputs) <= {"email"} for case in cases)


async def test_executable_payload_rejected():
    generated = GeneratedTests(tests=[GeneratedCase(name="bad",form_id="f1",kind="special",inputs={"email":"<script>alert(1)</script>"})])
    _, source = await generate_cases(FakeAI(generated), form(), 4)
    assert "fallback" in source.lower()


async def test_no_closed_model_fallback(settings):
    settings.text_model = "closed-cloud-model"
    settings.ai_enabled = True
    events = []
    ai = LocalAI(settings, on_task_update=events.append)
    result = await ai.perform("test","test",{},GeneratedTests)
    assert result is None
    assert "manifest" in ai.tasks[0]["detail"]
    assert [event["status"] for event in events] == ["running", "skipped"]
    assert all(license == "Apache-2.0" for license in OPEN_MODELS.values())


async def test_ai_alone_cannot_suppress_verified_finding(make_finding):
    finding=make_finding(status="Verified")
    result=Triage(items=[TriageItem(id=finding.id,severity=Severity.INFO,explanation="Simple explanation",suggested_fix="Concrete fix",likely_false_positive=True,reason="Guess")])
    assert await triage(FakeAI(result),[finding]) == []
    assert finding.status == "Verified"


async def test_suppression_requires_independent_contradiction(make_finding):
    finding=make_finding(contradicted=True)
    result=Triage(items=[TriageItem(id=finding.id,severity=Severity.LOW,explanation="Transient observation",suggested_fix="Confirm response configuration",likely_false_positive=True,reason="Re-test contradicted it")])
    suppressed=await triage(FakeAI(result),[finding])
    assert suppressed == [finding] and finding.suppressed_reason


async def test_schema_constrained_slots_map_only_to_observed_fields():
    class ScopedAI:
        async def perform(self, name, instruction, data, schema):
            return schema.model_validate({"tests":[
                {"name":"Empty required email","kind":"empty","inputs":{"field_1":""},"expected":"reject"},
                {"name":"Invalid email","kind":"invalid","inputs":{"field_1":"not-email"},"expected":"reject"},
                {"name":"Long input","kind":"boundary","inputs":{"field_1":"x"*128},"expected":"observe"},
                {"name":"Special input","kind":"special","inputs":{"field_1":"UWT_<>"},"expected":"observe"}
            ]})
    cases, source = await generate_cases(ScopedAI(), form(), 4)
    assert source == "Ollama-generated" and len(cases) == 4
    assert all(case.form_id == "f1" and set(case.inputs) == {"email"} for case in cases)
    assert all(case.provenance == "Ollama" for case in cases)


async def test_adaptive_diagnostic_plan_uses_only_known_applicable_pages():
    from app.ai.tasks import DiagnosticPlan, DiagnosticRecommendation, plan_diagnostics
    from app.core.models import PageInfo, Form, InputField

    pages = [
        PageInfo(id="p-login", url="http://lab.test:3000/login", title="Login", text="Sign in", depth=0,
                 forms=[Form(id="f-login", page_id="p-login", selector="#login", action="http://lab.test:3000/login",
                             method="POST", fields=[InputField(id="email", selector="#email", type="email")])],
                 links=[{"url":"http://lab.test:3000/help", "text":"Help"}],
                 screenshots={"desktop":"p-login-desktop.png"}),
        PageInfo(id="p-help", url="http://lab.test:3000/help", title="Help", text="Support", depth=1, links=[]),
    ]
    response = DiagnosticPlan(recommendations=[
        DiagnosticRecommendation(page_id="p-login", test_type="form_validation", priority="high", rationale="Observed a form."),
        DiagnosticRecommendation(page_id="p-login", test_type="visual_review", priority="normal", rationale="Screenshot exists."),
        DiagnosticRecommendation(page_id="p-help", test_type="form_validation", priority="high", rationale="Invalid: no form here."),
        DiagnosticRecommendation(page_id="unknown", test_type="link_health", priority="high", rationale="Invalid page ID."),
    ])
    class FakeAI:
        tasks = []
        async def perform(self, *args, **kwargs):
            return response
    plan = await plan_diagnostics(FakeAI(), pages)
    assert [(x["page_id"], x["test_type"]) for x in plan] == [
        ("p-login", "form_validation"), ("p-login", "visual_review")]
    assert all(x["source"] == "Ollama" and x["execution_status"] == "planned" for x in plan)
    assert plan[0]["execution_step"] == "ai_tests"
    assert plan[1]["execution_step"] == "vision"


async def test_adaptive_diagnostic_plan_empty_when_no_observations():
    from app.ai.tasks import plan_diagnostics
    class NeverAI:
        async def perform(self, *args, **kwargs):
            raise AssertionError("No inference should be attempted with no pages")
    assert await plan_diagnostics(NeverAI(), []) == []


async def test_diagnostic_plan_is_limited_to_selected_pillars():
    from app.ai.tasks import DiagnosticPlan, DiagnosticRecommendation, plan_diagnostics
    from app.core.models import PageInfo

    page = PageInfo(id="p1", url="http://lab.test:3000/", title="Home", text="Welcome", depth=0)
    class CapturingAI:
        tasks = []
        def __init__(self):
            self.data = None
        async def perform(self, name, instruction, data, schema):
            self.data = data
            return DiagnosticPlan(recommendations=[
                DiagnosticRecommendation(page_id="p1", test_type="security_review", priority="high", rationale="Review response defenses."),
                DiagnosticRecommendation(page_id="p1", test_type="performance_review", priority="normal", rationale="Measure performance."),
            ])

    ai = CapturingAI()
    plan = await plan_diagnostics(ai, [page], [Pillar.SECURITY])
    assert ai.data["supported_test_types"] == ["security_review"]
    assert [item["test_type"] for item in plan] == ["security_review"]
    assert plan[0]["execution_step"] == "custom_security"
