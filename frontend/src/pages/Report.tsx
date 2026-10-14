import { useCallback, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Activity,
  AlertCircle,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronDown,
  Clock3,
  Download,
  FileJson2,
  FileSpreadsheet,
  FileText,
  Globe2,
  Layers,
  Loader2,
  MapPin,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import type { Finding, Job, Pillar, Report, Severity } from "../types";
import {
  api,
  date,
  elapsed,
  hostname,
  number,
  pillars,
  severities,
  severityColors,
  useApi,
} from "../lib";
import { Empty, ErrorPanel, Loading } from "../components/Common";
import ScoreCard, { ScoreRing } from "../components/ScoreCard";
import IssueDrawer from "../components/IssueDrawer";
import IssueTable from "../components/IssueTable";

type Tab = "overview" | "issues" | "coverage" | "map";
export default function ReportPage() {
  const { id = "" } = useParams(),
    navigate = useNavigate(),
    { data: report, error, loading, reload } = useApi<Report>(`/reports/${id}`);
  const [tab, setTab] = useState<Tab>("overview"),
    [issue, setIssue] = useState<Finding | null>(null),
    [filterPillar, setFilterPillar] = useState<Pillar | "">(""),
    [filterSeverity, setFilterSeverity] = useState<Severity | "">(""),
    [retesting, setRetesting] = useState(false),
    [retestError, setRetestError] = useState("");
  const close = useCallback(() => setIssue(null), []);
  const filter = (pillar: Pillar | "" = "", severity: Severity | "" = "") => {
    setFilterPillar(pillar);
    setFilterSeverity(severity);
    setTab("issues");
  };
  if (loading) return <Loading message="Opening your evidence-based report…" />;
  if (error || !report)
    return <ErrorPanel message={error || "Report not found."} retry={reload} />;
  const retest = async () => {
    setRetesting(true);
    setRetestError("");
    try {
      const job = await api<Job>("/jobs", {
        method: "POST",
        body: JSON.stringify({
          url: report.url,
          pillars: report.selected_pillars,
        }),
      });
      navigate(`/tests/${job.id}`);
    } catch (err) {
      setRetestError((err as Error).message);
    } finally {
      setRetesting(false);
    }
  };
  const verified = report.findings.filter(
    (f) => f.status === "Verified",
  ).length;
  const skipped = report.steps.filter(
    (s) =>
      ["skipped", "failed", "blocked", "partial"].includes(s.status) &&
      (!s.pillar || report.selected_pillars.includes(s.pillar)),
  ).length;
  return (
    <div className="page report-page">
      <div className="report-heading">
        <div>
          <div className="section-kicker">
            THE RESULTS ARE IN{" "}
            {report.sample && (
              <span className="sample-label">REAL SAMPLE RUN</span>
            )}
          </div>
          <h1>Website health report</h1>
          <div className="report-target">
            <span className="target-favicon">
              <Globe2 size={15} />
            </span>
            <strong>{hostname(report.url)}</strong>
            <span className="target-url">{report.url}</span>
          </div>
        </div>
        <div className="report-actions">
          <button
            className="btn btn-secondary"
            disabled={retesting}
            onClick={retest}
          >
            {retesting ? (
              <Loader2 className="animate-spin" size={14} />
            ) : (
              <RotateCcw size={14} />
            )}{" "}
            Run again
          </button>
          <details className="export-menu">
            <summary className="btn btn-primary">
              <Download size={15} /> Export report <ChevronDown size={13} />
            </summary>
            <div>
              {(["pdf", "html", "json", "csv", "xlsx"] as const).map((format) => (
                <a
                  key={format}
                  href={`/api/reports/${id}/export/${format}`}
                  download
                >
                  {format === "json" ? (
                    <FileJson2 size={15} />
                  ) : format === "csv" || format === "xlsx" ? (
                    <FileSpreadsheet size={15} />
                  ) : (
                    <FileText size={15} />
                  )}{" "}
                  {format === "xlsx" ? "Excel (XLSX)" : format.toUpperCase()} report <ArrowUpRight size={12} />
                </a>
              ))}
            </div>
          </details>
        </div>
      </div>
      {retestError && (
        <p className="form-error" role="alert">
          {retestError}
        </p>
      )}
      <div className="report-metadata">
        <span>
          <Clock3 size={13} />
          {date(report.finished_at, true)}
        </span>
        <span>
          <Layers size={13} />
          {report.pages.length} pages mapped
        </span>
        <span>
          <Activity size={13} />
          {elapsed(report.duration_seconds)} test duration
        </span>
        <span
          className={report.partial ? "metadata-partial" : "metadata-complete"}
        >
          <i />
          {report.partial ? "Partial coverage" : "Checks completed"}
        </span>
      </div>
      {report.partial && (
        <div className="coverage-notice">
          <AlertCircle size={17} />
          <div>
            <strong>
              This is a partial report, not a clean bill of health.
            </strong>
            <span>
              {skipped} checks have limited or unavailable coverage. Scores
              reflect only what was assessed.
            </span>
          </div>
          <button onClick={() => setTab("coverage")}>
            Review coverage <ArrowRight size={13} />
          </button>
        </div>
      )}
      <div className="score-cards">
        {pillars.map((p) => (
          <ScoreCard
            key={p}
            pillar={p}
            value={report.scores[p]}
            onClick={() => filter(p)}
          />
        ))}
      </div>
      <nav className="report-tabs" aria-label="Report sections">
        {(
          [
            { id: "overview", label: "Overview" },
            {
              id: "issues",
              label: "All findings",
              count: report.findings.length,
            },
            { id: "coverage", label: "Coverage & AI" },
            { id: "map", label: "Site map & tests" },
          ] as { id: Tab; label: string; count?: number }[]
        ).map((t) => (
          <button
            key={t.id}
            className={tab === t.id ? "active" : ""}
            onClick={() => setTab(t.id)}
            aria-current={tab === t.id ? "page" : undefined}
          >
            {t.label}
            {t.count !== undefined && <span>{t.count}</span>}
          </button>
        ))}
        <span className="tabs-verified">
          <ShieldCheck size={13} />
          {verified} findings verified
        </span>
      </nav>
      {tab === "overview" && (
        <Overview
          report={report}
          onSelect={setIssue}
          onFilter={filter}
          onAll={() => filter()}
        />
      )}{" "}
      {tab === "issues" && (
        <section className="panel findings-panel">
          <div className="panel-heading">
            <div>
              <h2>
                All findings{" "}
                <span className="heading-count">{report.findings.length}</span>
              </h2>
              <p>Evidence first. Fixes next.</p>
            </div>
            <span className="small-muted">
              Select an issue to inspect the details
            </span>
          </div>
          <IssueTable
            findings={report.findings}
            onSelect={setIssue}
            initialPillar={filterPillar}
            initialSeverity={filterSeverity}
          />
        </section>
      )}
      {tab === "coverage" && <Coverage report={report} />}{" "}
      {tab === "map" && <SiteMap report={report} />}
      <footer className="report-footer">
        <span>
          <ShieldCheck size={12} /> Open-source checks. Local intelligence.
          Transparent limitations.
        </span>
        <span>Report {report.id.slice(0, 8)}</span>
      </footer>
      {issue && <IssueDrawer issue={issue} reportId={id} close={close} />}
    </div>
  );
}

function Overview({
  report,
  onSelect,
  onFilter,
  onAll,
}: {
  report: Report;
  onSelect: (issue: Finding) => void;
  onFilter: (pillar?: Pillar | "", severity?: Severity | "") => void;
  onAll: () => void;
}) {
  const lighthouse = report.metrics.lighthouse || {},
    timer = report.metrics.http_timing || {};
  const metrics = [
    {
      label: "Largest contentful paint",
      value: number(lighthouse.lcp_ms),
      format: (v: number) => `${(v / 1000).toFixed(2)}s`,
      hint: "Lighthouse lab · LCP",
    },
    {
      label: "Layout stability",
      value: number(lighthouse.cls),
      format: (v: number) => v.toFixed(3),
      hint: "Cumulative layout shift · CLS",
    },
    {
      label: "Main-thread blocking",
      value: number(lighthouse.tbt_ms),
      format: (v: number) => `${Math.round(v)}ms`,
      hint: "Lab responsiveness · TBT",
    },
    {
      label: "HTTP response",
      value: number(timer.average_ms),
      format: (v: number) => `${Math.round(v)}ms`,
      hint: "Mean of bounded GET requests",
    },
  ];
  return (
    <>
      <div className="overview-grid">
        <section className="panel summary-panel">
          <div className="overall-score-block">
            <ScoreRing score={report.overall_score} />
            <div>
              <span className="section-kicker">OBSERVED WEBSITE HEALTH</span>
              <h2>
                {report.overall_score === null
                  ? "More coverage needed"
                  : report.overall_score >= 80
                    ? "A solid foundation."
                    : report.overall_score >= 50
                      ? "Good potential. Room to improve."
                      : "Some important work ahead."}
              </h2>
              <p>
                {report.coverage}% overall check coverage <span>·</span>{" "}
                {report.partial ? "Partial assessment" : "Completed assessment"}
              </p>
            </div>
          </div>
          <div className="summary-body">
            <div className="summary-label">
              <Sparkles size={14} />
              {report.ai_tasks.some(
                (t) =>
                  t.name === "Final report synthesis" &&
                  t.status === "completed",
              )
                ? "LOCAL AI SUMMARY"
                : "MEASURED RESULTS SUMMARY"}
            </div>
            <p>{report.summary}</p>
            {report.priorities.length > 0 && (
              <ul
                className="summary-next-steps"
                aria-label="Suggested next steps"
              >
                {report.priorities.slice(0, 3).map((fix, index) => (
                  <li key={index}>{fix}</li>
                ))}
              </ul>
            )}
          </div>
        </section>
        <section className="panel severity-panel">
          <div className="panel-heading">
            <h2>Findings by severity</h2>
            <span className="small-muted">{report.findings.length} total</span>
          </div>
          <SeverityChart
            findings={report.findings}
            onSelect={(severity) => onFilter("", severity)}
          />
        </section>
      </div>
      <section className="panel metrics-panel">
        <div className="metrics-panel-title">
          <GaugeIcon />
          <div>
            <h3>The performance snapshot</h3>
            <p>Laboratory measurements, not real-user percentiles.</p>
          </div>
        </div>
        <div className="metric-values">
          {metrics.map((m) => (
            <div key={m.label}>
              <span>{m.label}</span>
              <strong>{m.value === null ? "—" : m.format(m.value)}</strong>
              <small>{m.value === null ? "Not measured" : m.hint}</small>
            </div>
          ))}
        </div>
      </section>
      <section className="panel priority-panel">
        <div className="panel-heading">
          <div>
            <h2>A good place to start</h2>
            <p>Your highest-priority findings, with a concrete next step.</p>
          </div>
          <button className="text-link" onClick={onAll}>
            View all findings <ArrowRight size={14} />
          </button>
        </div>
        <IssueTable findings={report.findings} compact onSelect={onSelect} />
      </section>
    </>
  );
}
function GaugeIcon() {
  return (
    <div className="metric-heading-icon">
      <Activity size={19} />
    </div>
  );
}
function SeverityChart({
  findings,
  onSelect,
}: {
  findings: Finding[];
  onSelect: (severity: Severity) => void;
}) {
  const counts = Object.fromEntries(
    severities.map((s) => [s, findings.filter((f) => f.severity === s).length]),
  ) as Record<Severity, number>;
  const radius = 40,
    circ = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="severity-chart">
      <div className="severity-donut">
        <svg
          viewBox="0 0 100 100"
          role="img"
          aria-label={`${findings.length} issues by severity`}
        >
          <circle
            cx="50"
            cy="50"
            r={radius}
            stroke="#eef1ef"
            fill="none"
            strokeWidth="11"
          />
          {severities.map((s) => {
            const value = (counts[s] / Math.max(1, findings.length)) * circ;
            const element = (
              <circle
                key={s}
                cx="50"
                cy="50"
                r={radius}
                fill="none"
                stroke={severityColors[s]}
                strokeWidth="11"
                strokeDasharray={`${Math.max(0, value - 1.5)} ${circ}`}
                strokeDashoffset={-offset}
                transform="rotate(-90 50 50)"
              >
                <title>
                  {s}: {counts[s]}
                </title>
              </circle>
            );
            offset += value;
            return element;
          })}
        </svg>
        <div>
          <strong>{findings.length}</strong>
          <span>FINDINGS</span>
        </div>
      </div>
      <div className="severity-legend">
        {severities.map((s) => (
          <button key={s} onClick={() => onSelect(s)}>
            <span style={{ backgroundColor: severityColors[s] }} />
            <span>{s}</span>
            <strong>{counts[s]}</strong>
          </button>
        ))}
      </div>
    </div>
  );
}

function Coverage({ report }: { report: Report }) {
  return (
    <div className="coverage-grid">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Every check, accounted for</h2>
            <p>Skipped or refused checks are never counted as passing.</p>
          </div>
          <span className="coverage-value">{report.coverage}%</span>
        </div>
        <div className="coverage-step-list">
          {report.steps.map((step) => (
            <div key={step.id}>
              <span className={`step-dot status-${step.status}`}>
                {step.status === "completed" ? (
                  <Check size={13} />
                ) : step.status === "running" ? (
                  <Loader2 size={13} />
                ) : (
                  <span />
                )}
              </span>
              <div>
                <strong>{step.title}</strong>
                <p>{step.detail}</p>
                {Object.keys(step.metrics).length > 0 && (
                  <details>
                    <summary>Measured details</summary>
                    <pre>{JSON.stringify(step.metrics, null, 2)}</pre>
                  </details>
                )}
              </div>
              <span className={`status-badge status-${step.status}`}>
                {step.status}
              </span>
            </div>
          ))}
        </div>
      </section>
      <div className="coverage-right">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>
                <Sparkles size={16} /> Meaningful AI work
              </h2>
              <p>Schema-validated decisions. Local inference only.</p>
            </div>
          </div>
          <div className="ai-task-list">
            {report.ai_tasks.map((task, i) => (
              <div key={i}>
                <div>
                  <strong>{task.name}</strong>
                  <span className={`status-badge status-${task.status}`}>
                    {task.status}
                  </span>
                </div>
                <code>{task.model}</code>
                <p>{task.detail}</p>
              </div>
            ))}
          </div>
        </section>
        <section className="panel diagnostic-plan-panel">
          <div className="panel-heading">
            <div>
              <h2><Workflow size={16} /> AI-selected diagnostic plan</h2>
              <p>Recommendations use observed page IDs and map only to built-in safe checks.</p>
            </div>
            <span className="heading-count">{report.diagnostic_plan?.length ?? 0}</span>
          </div>
          {report.diagnostic_plan?.length ? (
            <div className="diagnostic-plan-list">
              {report.diagnostic_plan.map((item, i) => (
                <div key={`${item.page_id}-${item.test_type}-${i}`}>
                  <div className="diagnostic-plan-title">
                    <strong>{item.test_type.replaceAll("_", " ")}</strong>
                    <span className={`status-badge ${item.execution_status.startsWith("executed") || item.execution_status === "observed" ? "status-completed" : item.execution_status.includes("partial") ? "status-partial" : ["failed", "skipped", "blocked"].includes(item.execution_status) ? `status-${item.execution_status}` : "status-pending"}`}>
                      {item.execution_status.replaceAll("_", " ")}
                    </span>
                  </div>
                  <span className="diagnostic-plan-page">{item.page_title || item.page_url}</span>
                  <p>{item.rationale}</p>
                  <small>Priority: {item.priority} · Source: {item.source} · Runner: {item.execution_step}</small>
                </div>
              ))}
            </div>
          ) : (
            <div className="diagnostic-plan-empty">
              <strong>No AI-generated diagnostic plan was recorded.</strong>
              <p>The baseline checks may still have run. Check AI task status above to see whether Ollama was unavailable or returned no valid recommendations.</p>
            </div>
          )}
        </section>
        <section className="panel scope-panel">
          <h3>
            <ShieldCheck size={17} /> Scope & safety
          </h3>
          <ul>
            {report.limitations.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
          <div className="scope-status">
            <LockIcon />
            {report.authorized
              ? "Exact origin approved for the scan."
              : "Origin not allowlisted. Security and load checks were refused; consult the coverage details for this deployment's passive-check policy."}
          </div>
        </section>
        <section className="panel version-panel">
          <h3>Tool provenance</h3>
          {Object.entries(report.tool_versions).map(([name, value]) => (
            <div key={name}>
              <span>{name}</span>
              <code>{value}</code>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
function LockIcon() {
  return <ShieldCheck size={14} />;
}
function SiteMap({ report }: { report: Report }) {
  return (
    <div className="map-grid">
      <section className="panel sitemap-panel">
        <div className="panel-heading">
          <div>
            <h2>
              <Workflow size={18} /> Crawl map
            </h2>
            <p>Same-origin pages, bounded depth. No destructive navigation.</p>
          </div>
          <span className="heading-count">{report.pages.length}</span>
        </div>
        {report.pages.length ? (
          <div className="sitemap-list">
            {report.pages.map((page) => (
              <div key={page.id}>
                <div className="map-node">
                  <Globe2 size={16} />
                </div>
                <div>
                  <strong>{page.title || hostname(page.url)}</strong>
                  <code>{page.url}</code>
                  <div className="page-map-meta">
                    <span>Depth {page.depth}</span>
                    <span>
                      {page.status_code
                        ? `HTTP ${page.status_code}`
                        : "No response"}
                    </span>
                    <span>{page.forms.length} forms</span>
                    {page.readiness && <span title={page.readiness.note || page.readiness.strategy}>{page.readiness.stable ? `DOM stable · ${page.readiness.wait_ms ?? 0}ms` : "DOM stability uncertain"}</span>}
                  </div>
                </div>
                <span className="classification">
                  {page.classification === "other"
                    ? "Unclassified"
                    : page.classification}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <Empty
            title="No pages mapped"
            description="The browser could not map this target. See coverage details."
          />
        )}
        {report.flows.length > 0 && (
          <div className="flow-list">
            <h3>AI-discovered user flows</h3>
            {report.flows.map((flow, i) => (
              <div key={i}>
                <strong>{flow.name}</strong>
                <p>{flow.rationale}</p>
                <p className="flow-coverage">
                  {flow.coverage ||
                    "Proposed known-page navigation only; no login or transaction submitted."}
                </p>
                {flow.observations && (
                  <p className="flow-coverage">
                    {flow.status === "navigation_observed"
                      ? "Navigation observed"
                      : "Limited navigation coverage"}{" "}
                    · {flow.observations.length} page observations · No
                    submissions
                  </p>
                )}
                <div>
                  {flow.page_ids.map((pid, index) => (
                    <span key={`${pid}-${index}`}>
                      <MapPin size={11} />
                      {report.pages.find((p) => p.id === pid)?.classification ||
                        pid}
                      {index < flow.page_ids.length - 1 && (
                        <ArrowRight size={12} />
                      )}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="panel test-case-panel">
        <div className="panel-heading">
          <div>
            <h2>Generated validation tests</h2>
            <p>Filled and inspected. No mutation submissions.</p>
          </div>
          <span className="heading-count">{report.test_cases.length}</span>
        </div>
        {report.test_cases.length ? (
          <div className="test-case-list">
            {report.test_cases.map((test, index) => (
              <details key={index}>
                <summary>
                  <span
                    className={`test-case-dot ${test.status === "executed" ? "executed" : ""}`}
                  />
                  <span>
                    {test.name}
                    <small>
                      {test.kind} · {test.source}
                    </small>
                  </span>
                  <span className="status-badge">{test.status}</span>
                </summary>
                <div className="test-case-detail">
                  <code>{test.url}</code>
                  <p>
                    Expected: {test.expected} · Submitted:{" "}
                    {test.submitted ? "Yes" : "No (safety policy)"}
                  </p>
                  {test.observations.map((obs, i) => (
                    <div key={i}>
                      <code>{obs.selector}</code>
                      <p>
                        Native validity: {obs.valid ? "valid" : "invalid"}
                        {obs.message ? ` · ${obs.message}` : ""}
                      </p>
                    </div>
                  ))}
                  {test.screenshot && (
                    <img
                      loading="lazy"
                      src={`/api/jobs/${report.id}/evidence/${test.screenshot}`}
                      alt={`Validation case: ${test.name}`}
                    />
                  )}
                </div>
              </details>
            ))}
          </div>
        ) : (
          <Empty
            title="No form cases executed"
            description="No suitable form was observed, the pillar was not selected, or the browser was unavailable."
          />
        )}
      </section>
    </div>
  );
}
