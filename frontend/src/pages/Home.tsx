import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  Clock3,
  Cpu,
  FileBarChart2,
  Globe2,
  Link2,
  Loader2,
  LockKeyhole,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import type { Job, Pillar, Policy, Tools } from "../types";
import { api, canonicalOrigin, date, hostname, labels, pillars, useApi } from "../lib";
import { PillarIcon } from "../components/Common";

const descriptions: Record<Pillar, string> = {
  functionality: "Links, forms and navigation",
  security: "Headers, cookies and safe exposure checks",
  performance: "Load speed and response behavior",
  accessibility: "Accessible controls and visual review",
};

const pillarDetails: Record<Pillar, string[]> = {
  functionality: ["Link health", "Form constraints", "Navigation"],
  security: ["Security headers", "Cookie attributes", "Configured safe checks"],
  performance: ["Page timing", "Lighthouse", "Bounded load checks"],
  accessibility: ["axe-core rules", "Pa11y checks", "Visual observations"],
};

const pillarTone: Record<Pillar, string> = {
  functionality: "functional",
  security: "security",
  performance: "performance",
  accessibility: "accessibility",
};

function jobStatusLabel(job: Job) {
  if (job.status === "completed" && job.partial) return "Partial report";
  return job.status;
}

export default function Home() {
  const navigate = useNavigate();
  const { data: policy, loading: policyLoading } = useApi<Policy>("/policy");
  const { data: history, loading: historyLoading, reload: reloadHistory } = useApi<{ jobs: Job[] }>("/jobs?limit=8");
  const { data: tools, error: toolsError, loading: toolsLoading, reload: reloadTools } = useApi<Tools>("/tools");
  const [url, setUrl] = useState("");
  const [selected, setSelected] = useState<Pillar[]>([...pillars]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const origin = canonicalOrigin(url.trim());
  const authorized = !!origin && !!policy?.origins.includes(origin);
  const strictAllowlist = policy?.require_allowlist_all_scans !== false;
  const canSubmit = !!url.trim() && selected.length > 0 && !busy && !policyLoading && !(strictAllowlist && !authorized);
  const jobs = history?.jobs || [];
  const completedCount = jobs.filter((job) => job.status === "completed").length;
  const runningCount = jobs.filter((job) => ["running", "queued"].includes(job.status)).length;
  const reportedFindings = jobs.reduce((sum, job) => sum + (job.issue_count ?? 0), 0);
  const availableCount = tools?.tools.filter((tool) => tool.available).length ?? 0;
  const recentJobs = jobs.slice(0, 5);
  const toolHealthPercent = tools?.tools.length ? Math.round((availableCount / tools.tools.length) * 100) : 0;
  const sampleOrigin = useMemo(() => policy?.origins.find((item) => item.includes("8765"))
    || policy?.origins.find((item) => item.includes("127.0.0.1:3000"))
    || policy?.origins.find((item) => item.includes("juice-shop"))
    || (policy?.origins && policy.origins.length > 0 ? policy.origins[0] : "") || "", [policy?.origins]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (selected.length === 0) {
      setError("Select at least one testing pillar before starting the scan.");
      return;
    }
    if (strictAllowlist && !authorized) {
      setError("This deployment accepts only exact origins approved by the organizer or administrator.");
      return;
    }
    setBusy(true);
    try {
      const job = await api<Job>("/jobs", {
        method: "POST",
        body: JSON.stringify({ url: url.trim(), pillars: selected }),
      });
      navigate(`/tests/${job.id}`);
    } catch (err) {
      setError((err as Error).message || "The scan could not be created. Check the target and backend status.");
    } finally {
      setBusy(false);
    }
  };

  const togglePillar = (pillar: Pillar) => {
    setSelected((current) => current.includes(pillar)
      ? current.filter((item) => item !== pillar)
      : [...current, pillar]);
    setError("");
  };

  return (
    <div className="page dashboard-home">
      <section className="dashboard-page-heading">
        <div>
          <div className="dashboard-breadcrumb-kicker"><span className="dashboard-status-dot" /> DIAGNOSTIC CONTROL ROOM</div>
          <h1>Scan workspace</h1>
          <p>Configure a target, choose the testing disciplines, and launch an evidence-led diagnosis.</p>
        </div>
        <div className="dashboard-heading-actions">
          <div className={`runtime-summary-chip ${tools?.ollama_reachable ? "is-online" : "is-unknown"}`}>
            <span className="runtime-summary-icon"><Cpu size={17} /></span>
            <span><strong>{tools?.ollama_reachable ? "Local AI reachable" : toolsLoading ? "Checking local AI" : "AI not confirmed"}</strong><small>{tools?.ollama_reachable ? "Ollama health check passed" : toolsError ? "Runtime status unavailable" : "Confirm model availability before demo"}</small></span>
          </div>
          <Link className="dashboard-secondary-action" to="/models">Manage models <ArrowUpRight size={14} /></Link>
        </div>
      </section>

      <section className="workspace-metrics" aria-label="Workspace summary">
        <article className="workspace-metric-card">
          <span className="metric-card-icon icon-violet"><FileBarChart2 size={17} /></span>
          <div><small>SCANS IN RECENT HISTORY</small><strong>{historyLoading ? "—" : jobs.length}</strong><span>Latest {jobs.length ? `${jobs.length} stored jobs` : "No jobs yet"}</span></div>
        </article>
        <article className="workspace-metric-card">
          <span className="metric-card-icon icon-green"><CheckCircle2 size={17} /></span>
          <div><small>COMPLETED SCANS</small><strong>{historyLoading ? "—" : completedCount}</strong><span>{runningCount} queued or running</span></div>
        </article>
        <article className="workspace-metric-card">
          <span className="metric-card-icon icon-amber"><Activity size={17} /></span>
          <div><small>FINDINGS REPORTED</small><strong>{historyLoading ? "—" : reportedFindings}</strong><span>Across jobs in this history view</span></div>
        </article>
        <article className="workspace-metric-card">
          <span className="metric-card-icon icon-cyan"><Wrench size={17} /></span>
          <div><small>TOOL READINESS</small><strong>{toolsLoading ? "—" : tools ? `${availableCount}/${tools.tools.length}` : "—"}</strong><span>{tools ? `${toolHealthPercent}% of listed tools available` : "Waiting for backend status"}</span></div>
        </article>
      </section>

      <section className="scan-composer-card" aria-labelledby="scan-composer-title">
        <div className="scan-composer-heading">
          <div className="scan-composer-title-block">
            <span className="step-marker">01</span>
            <div><div className="dashboard-overline">NEW DIAGNOSTIC</div><h2 id="scan-composer-title">Start with a website URL</h2><p>Black-box testing: no source code or framework-specific setup required.</p></div>
          </div>
          <span className={`authorization-chip ${url && strictAllowlist && !authorized ? "is-blocked" : ""}`}><LockKeyhole size={13} /> {url && strictAllowlist && !authorized ? "Origin not approved" : "Target policy enforced"}</span>
        </div>

        <form onSubmit={submit}>
          <div className="scan-url-row">
            <div className="scan-url-input-wrap">
              <span className="scan-url-symbol"><Link2 size={19} /></span>
              <label className="scan-url-copy" htmlFor="website-url"><small>WEBSITE URL</small><input id="website-url" type="url" autoComplete="url" placeholder="https://approved-lab.example" required value={url} onChange={(event) => { setUrl(event.target.value); setError(""); }} /></label>
              {url && <button type="button" className="clear-url-button" onClick={() => { setUrl(""); setError(""); document.getElementById("website-url")?.focus(); }} aria-label="Clear target URL"><X size={15} /></button>}
            </div>
            <button type="submit" disabled={!canSubmit} className="scan-submit-button">
              {busy ? <Loader2 className="animate-spin" size={17} /> : <ScanLine size={18} />}
              <span>{busy ? "Preparing scan…" : "Start diagnosis"}<small>{busy ? "Creating a controlled job" : "Observe · Adapt · Verify"}</small></span>
              {!busy && <ArrowRight size={17} />}
            </button>
          </div>
          <div className="scan-url-support-row">
            <span><ShieldCheck size={13} /> {url && strictAllowlist && !authorized ? "Exact origin must be approved before a scan can start." : "Authorized targets only. Destructive form submissions are not performed."}</span>
            {sampleOrigin && <button type="button" className="text-button" onClick={() => { setUrl(`${sampleOrigin.replace(/\/$/, "")}/`); setError(""); document.getElementById("website-url")?.focus(); }}>Use approved lab <ArrowUpRight size={12} /></button>}
          </div>

          <div className="scan-scope-heading">
            <div><div className="dashboard-overline">02 / DIAGNOSTIC SCOPE</div><h3>Choose testing disciplines</h3><p>Run all four for the most complete report, or narrow the scope.</p></div>
            <div className="scope-selection-tools"><span className="scope-count"><strong>{selected.length}</strong> of 4 selected</span><button type="button" className="text-button" onClick={() => { setSelected([...pillars]); setError(""); }}>Select all</button><button type="button" className="text-button" onClick={() => { setSelected([]); setError(""); }}>Clear</button></div>
          </div>

          <div className="dashboard-pillar-grid">
            {pillars.map((pillar, index) => {
              const checked = selected.includes(pillar);
              return (
                <label key={pillar} className={`dashboard-pillar-card pillar-tone-${pillarTone[pillar]} ${checked ? "is-selected" : ""}`}>
                  <input type="checkbox" checked={checked} onChange={() => togglePillar(pillar)} aria-label={`Include ${labels[pillar]}`} />
                  <span className="pillar-card-topline"><span className="pillar-card-number">0{index + 1}</span><span className="pillar-card-check" aria-hidden="true">{checked && <Check size={13} />}</span></span>
                  <span className="pillar-card-icon"><PillarIcon pillar={pillar} size={20} /></span>
                  <strong>{labels[pillar]}</strong>
                  <span className="pillar-card-description">{descriptions[pillar]}</span>
                  <span className="pillar-card-tags">{pillarDetails[pillar].map((detail) => <i key={detail}>{detail}</i>)}</span>
                  <span className="pillar-card-footer"><span className="pillar-card-status-dot" />{checked ? "Included in scan" : "Not selected"}</span>
                </label>
              );
            })}
          </div>

          <div className={`scan-policy-banner ${url && strictAllowlist && !authorized ? "is-warning" : ""}`}>
            <span className="scan-policy-icon"><ShieldCheck size={17} /></span>
            <div><strong>{url && strictAllowlist && !authorized ? "Target approval required" : policyLoading ? "Loading target policy…" : "Safe, bounded execution"}</strong><p>{url && strictAllowlist && !authorized ? "The backend will reject an origin that is not on the approved list. No scan should be launched until it is authorized." : `Load testing, when permitted, is bounded to ${policy?.max_users ?? 4} users for ${policy?.load_seconds ?? 10} seconds. Unavailable checks must remain visible in the report.`}</p></div>
            <span className="policy-lock-label"><LockKeyhole size={12} /> POLICY</span>
          </div>
          {error && <div role="alert" className="form-error dashboard-form-error">{error}</div>}
        </form>
      </section>

      <section className="diagnostic-workflow-strip" aria-label="Diagnostic workflow">
        <div className="workflow-strip-heading"><span className="dashboard-overline">HOW A SCAN RUNS</span><span>Automated workflow</span></div>
        <div className="workflow-strip-steps">
          <div className="workflow-step"><span className="workflow-step-symbol"><Globe2 size={17} /></span><span className="workflow-step-content"><strong>Observe</strong><small>Map pages and controls</small></span></div>
          <span className="workflow-step-connector" />
          <div className="workflow-step"><span className="workflow-step-symbol violet"><Sparkles size={17} /></span><span className="workflow-step-content"><strong>Adapt</strong><small>AI proposes relevant checks</small></span></div>
          <span className="workflow-step-connector" />
          <div className="workflow-step"><span className="workflow-step-symbol amber"><Zap size={17} /></span><span className="workflow-step-content"><strong>Execute</strong><small>Specialist tools measure behavior</small></span></div>
          <span className="workflow-step-connector" />
          <div className="workflow-step"><span className="workflow-step-symbol green"><ShieldCheck size={17} /></span><span className="workflow-step-content"><strong>Verify</strong><small>Evidence anchors findings</small></span></div>
        </div>
      </section>

      <section className="dashboard-bottom-grid">
        <article className="dashboard-content-card tool-readiness-card">
          <div className="dashboard-card-heading"><div><span className="dashboard-overline">RUNTIME</span><h2>Tool readiness</h2><p>Availability is not proof that a scan completed.</p></div><button type="button" className="round-icon-button" onClick={() => { reloadTools(); }} aria-label="Refresh tool readiness" title="Refresh tool readiness"><RefreshCw size={15} /></button></div>
          {toolsLoading && !tools ? <div className="dashboard-empty-inline"><Loader2 size={17} className="animate-spin" /> Checking local integrations…</div> : toolsError || !tools ? <div className="dashboard-inline-error"><span><Activity size={17} /></span><div><strong>Runtime status unavailable</strong><p>{toolsError || "The backend did not return tool status."}</p><button type="button" className="text-button" onClick={reloadTools}>Try again <ArrowRight size={12} /></button></div></div> : (
            <>
              <div className="tool-readiness-summary"><span className="readiness-track"><i style={{ width: `${toolHealthPercent}%` }} /></span><strong>{availableCount} / {tools.tools.length}</strong></div>
              <div className="readiness-list">
                {tools.tools.slice(0, 6).map((tool) => <div className="readiness-row" key={tool.name}><span className={`readiness-indicator ${tool.available ? "available" : "unavailable"}`} /><div><strong>{tool.name}</strong><small>{tool.detail}</small></div><span className={`readiness-status ${tool.available ? "ready" : "missing"}`}>{tool.available ? "Ready" : "Unavailable"}</span></div>)}
              </div>
              {tools.tools.length > 6 && <p className="readiness-more">Showing 6 of {tools.tools.length} listed integrations.</p>}
            </>
          )}
          <div className="dashboard-card-footer"><span><Cpu size={13} /> Local-first model execution</span><Link to="/models">Model settings <ArrowRight size={13} /></Link></div>
        </article>

        <article className="dashboard-content-card recent-scans-card">
          <div className="dashboard-card-heading"><div><span className="dashboard-overline">SCAN ARCHIVE</span><h2>Recent diagnostics</h2><p>Reopen reports or return to an active scan.</p></div><Link className="dashboard-link-action" to="/history">View history <ArrowRight size={14} /></Link></div>
          {historyLoading && !history ? <div className="dashboard-empty-inline"><Loader2 size={17} className="animate-spin" /> Loading recent scans…</div> : recentJobs.length ? <div className="recent-scan-list">{recentJobs.map((job) => {
            const isCompleted = job.status === "completed";
            const destination = isCompleted ? `/reports/${job.id}` : `/tests/${job.id}`;
            return <Link className="recent-scan-row" key={job.id} to={destination}>
              <span className="recent-scan-site-icon"><Globe2 size={16} /></span>
              <span className="recent-scan-main"><strong>{hostname(job.url)}</strong><small>{date(job.created_at)} · {job.issue_count ?? 0} findings {job.sample ? "· Sample run" : ""}</small></span>
              <span className={`recent-scan-status status-${job.status}`}>{jobStatusLabel(job)}</span>
              <span className="recent-scan-score"><strong>{job.overall_score ?? "—"}</strong><small>{job.overall_score != null ? "/100" : "score"}</small></span>
              <ArrowUpRight size={15} className="recent-scan-arrow" />
            </Link>;
          })}</div> : <div className="dashboard-empty-state"><span className="dashboard-empty-icon"><Clock3 size={21} /></span><strong>No scans yet</strong><p>Start with an approved practice target. Completed reports will appear here.</p>{sampleOrigin && <button type="button" className="dashboard-link-action" onClick={() => { setUrl(`${sampleOrigin.replace(/\/$/, "")}/`); document.getElementById("website-url")?.focus(); }}>Fill approved lab URL <ArrowRight size={13} /></button>}</div>}
          <div className="dashboard-card-footer"><span><Activity size={13} /> {historyLoading ? "Refreshing scan history" : `${jobs.length} job(s) in recent history`}</span><button type="button" className="text-button" onClick={reloadHistory}>Refresh <RefreshCw size={12} /></button></div>
        </article>
      </section>

      <footer className="dashboard-footer"><span><ShieldCheck size={13} /> AUTHORIZED TARGETS ONLY</span><span><Cpu size={13} /> LOCAL AI / OPEN-SOURCE STACK</span><span><CheckCircle2 size={13} /> EVIDENCE BEFORE CLAIMS</span><span>NOT A SECURITY CERTIFICATION</span></footer>
    </div>
  );
}
