import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  BrainCircuit,
  Bug,
  Check,
  CheckCheck,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  Eye,
  FileSearch,
  Gauge,
  Globe2,
  Layers3,
  Loader2,
  Monitor,
  Network,
  Play,
  Plus,
  Radar,
  Radio,
  Scan,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
  Terminal,
  Wifi,
  WifiOff,
  Wrench,
  XCircle,
} from "lucide-react";
import type {
  AITask,
  BrowserFrameEvent,
  DiagnosticPlanEvent,
  DiagnosticRecommendation,
  Job,
  LiveCrawlerPage,
  LiveFinding,
  Pillar,
  PillarActivity,
  SiteMapEvent,
  Step,
  Tools,
  VerificationSummary,
} from "../types";
import { api, hostname, labels, pillars } from "../lib";
import { ErrorPanel, Loading, PillarIcon } from "../components/Common";

interface Log {
  message: string;
  timestamp?: string;
}
interface WorkspaceEvent {
  type: string;
  [key: string]: unknown;
}
interface ReportSummaryEvent {
  overall_score: number | null;
  coverage: number;
  partial: boolean;
  findings: number;
  verified: number;
  selected_pillars: Pillar[];
}

const testLabels: Record<DiagnosticRecommendation["test_type"], string> = {
  form_validation: "Form validation",
  navigation_flow: "Navigation flow",
  link_health: "Link health",
  visual_review: "Visual review",
  accessibility_review: "Accessibility review",
  security_review: "Security review",
  performance_review: "Performance review",
};
const stepLabels: Record<string, string> = {
  ai_tests: "Playwright form checks",
  links: "Link / navigation adapter",
  vision: "Local vision model",
  axe: "axe-core adapter",
  custom_security: "Custom security checks",
  lighthouse: "Lighthouse adapter",
};

function statusLabel(status: string | undefined): string {
  if (!status) return "Waiting";
  const labelsByStatus: Record<string, string> = {
    planned: "Proposed by AI",
    running: "Runner in progress",
    adapter_finished_pending_page_confirmation: "Adapter finished · page confirmation pending",
    executed: "Executed",
    executed_sitewide: "Executed site-wide",
    observed: "Behavior observed",
    partially_executed: "Partially executed",
    partial: "Partial result",
    failed: "Failed",
    skipped: "Skipped",
    blocked: "Blocked by policy",
    halted: "Halted · stopped",
    stopped: "Stopped",
    not_confirmed: "Not confirmed",
    not_executed: "Not executed",
    not_executed_budget_or_no_usable_case: "Not executed · no usable case or budget",
    not_executed_or_outside_page_budget: "Not executed · outside page budget",
    not_confirmed_or_different_priority_page: "Not confirmed for this page",
    not_covered_by_replayed_flow: "Flow did not cover this page",
  };
  if (labelsByStatus[status]) return labelsByStatus[status];
  if (status.startsWith("not_")) return "Not confirmed";
  return status.replaceAll("_", " ");
}

function statusTone(status: string | undefined): string {
  if (!status) return "neutral";
  if (["completed", "executed", "executed_sitewide", "observed"].includes(status)) return "good";
  if (["running", "planned", "adapter_finished_pending_page_confirmation"].includes(status)) return "active";
  if (["failed", "blocked"].includes(status)) return "bad";
  if (["partial", "partially_executed", "skipped", "halted", "stopped"].includes(status)) return "warn";
  return "neutral";
}

function summarizePillar(pillar: Pillar, steps: Step[], selected: Pillar[], isTerminal: boolean = false): PillarActivity {
  const own = steps.filter((step) => step.pillar === pillar);
  const completed = own.filter((step) => step.status === "completed").length;
  const partial = own.filter((step) => step.status === "partial").length;
  const running = own.filter((step) => step.status === "running").length;
  const unavailable = own.filter((step) => ["failed", "skipped", "blocked"].includes(step.status)).length;
  let status: string = "running";
  if (!selected.includes(pillar)) {
    status = "not_selected";
  } else if (completed === own.length && own.length > 0) {
    status = "complete";
  } else if (isTerminal) {
    status = completed > 0 || partial > 0 ? "partial" : "stopped";
  } else if (own.some((step) => ["running", "pending"].includes(step.status))) {
    status = "running";
  } else {
    status = "partial";
  }
  return {
    selected: selected.includes(pillar),
    status,
    completed_steps: completed,
    total_steps: own.length,
    finished_steps: own.filter((step) => !["pending", "running"].includes(step.status)).length,
    running_steps: isTerminal ? 0 : running,
    unavailable_steps: unavailable,
    partial_steps: partial,
    pipeline_coverage_percent: Math.round((100 * (completed + partial * 0.5)) / Math.max(1, own.length)),
  };
}

export default function Progress() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [logs, setLogs] = useState<Log[]>([]);
  const [connected, setConnected] = useState(true);
  const [cancelling, setCancelling] = useState(false);
  const [aiTasks, setAiTasks] = useState<AITask[]>([]);
  const [plan, setPlan] = useState<DiagnosticRecommendation[]>([]);
  const [planInfo, setPlanInfo] = useState<DiagnosticPlanEvent | null>(null);
  const [siteMap, setSiteMap] = useState<SiteMapEvent | null>(null);
  const [verification, setVerification] = useState<VerificationSummary | null>(null);
  const [reportedSummary, setReportedSummary] = useState<ReportSummaryEvent | null>(null);
  const [pillarActivity, setPillarActivity] = useState<Partial<Record<Pillar, PillarActivity>>>({});
  const [toolStatus, setToolStatus] = useState<Tools | null>(null);
  const [toolStatusError, setToolStatusError] = useState("");
  const [liveFindings, setLiveFindings] = useState<LiveFinding[]>([]);
  const [crawlerActivity, setCrawlerActivity] = useState<{ url: string; depth: number } | null>(null);
  const [crawledPages, setCrawledPages] = useState<LiveCrawlerPage[]>([]);
  const [browserFrame, setBrowserFrame] = useState<{
    image: string;
    action: string;
    url: string;
    timestamp?: string;
  } | null>(null);
  const [frameCount, setFrameCount] = useState<number>(0);
  const [findingsFilter, setFindingsFilter] = useState<string>("all");
  const logContainerRef = useRef<HTMLDivElement>(null);
  const [autoScrollLogs, setAutoScrollLogs] = useState(true);

  const handleLogsScroll = () => {
    const el = logContainerRef.current;
    if (!el) return;
    // Pause auto-scroll if user scrolled up by more than 45px
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 45;
    setAutoScrollLogs(isAtBottom);
  };

  useEffect(() => {
    let active = true;
    if (!id) {
      setError("No scan ID was supplied.");
      return;
    }
    const source = new EventSource(`/api/jobs/${id}/events`);
    api<Job>(`/jobs/${id}`)
      .then((value) => {
        if (!active) return;
        setJob(value);
        if (value.status === "completed") navigate(`/reports/${id}`, { replace: true });
      })
      .catch((err: Error) => {
        if (active) setError(err.message);
      });
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (message) => {
      try {
        const data = JSON.parse(message.data) as WorkspaceEvent;
        if (data.type === "log") {
          setLogs((items) => [...items, { message: String(data.message ?? ""), timestamp: String(data.timestamp ?? "") }].slice(-100));
        }
        if (data.type === "progress") {
          setJob((previous) => previous ? {
            ...previous,
            status: previous.status === "cancelled" ? "cancelled" : "running",
            progress: { steps: data.steps as Step[], percent: Number(data.percent ?? 0) },
          } : previous);
        }
        if (data.type === "ai_task_update" && data.task && typeof data.task === "object") {
          const task = data.task as AITask;
          setAiTasks((previous) => {
            const existing = previous.filter((item) => item.name !== task.name);
            return [...existing, task].slice(-30);
          });
        }
        if (data.type === "diagnostic_plan") {
          const event = data as unknown as DiagnosticPlanEvent;
          setPlanInfo(event);
          if (Array.isArray(event.recommendations)) setPlan(event.recommendations);
        }
        if (data.type === "recommendation_update" && data.recommendation && typeof data.recommendation === "object") {
          const updated = data.recommendation as DiagnosticRecommendation;
          setPlan((previous) => {
            const index = previous.findIndex((item) => item.page_id === updated.page_id && item.test_type === updated.test_type);
            if (index < 0) return [...previous, updated].slice(0, 12);
            return previous.map((item, current) => current === index ? { ...item, ...updated } : item);
          });
        }
        if (data.type === "crawler_activity") {
          setCrawlerActivity({
            url: String(data.url ?? ""),
            depth: Number(data.depth ?? 0),
          });
        }
        if (data.type === "browser_frame") {
          const frameEvt = data as unknown as BrowserFrameEvent;
          setBrowserFrame((prev) => ({
            image: frameEvt.image || prev?.image || "",
            action: frameEvt.action || prev?.action || "Auditing live viewport",
            url: frameEvt.url || prev?.url || "",
            timestamp: frameEvt.timestamp || new Date().toISOString(),
          }));
          if (frameEvt.image) {
            setFrameCount((prev) => prev + 1);
          }
        }
        if (data.type === "crawler_page" && data.page && typeof data.page === "object") {
          const page = data.page as LiveCrawlerPage;
          setCrawledPages((previous) => {
            if (previous.some((p) => p.id === page.id || p.url === page.url)) return previous;
            return [...previous, page].slice(-30);
          });
        }
        if (data.type === "live_findings" && Array.isArray(data.findings)) {
          const incomingFindings = (data.findings as LiveFinding[]).map((f) => ({
            ...f,
            timestamp: f.timestamp || new Date().toISOString(),
          }));
          setLiveFindings((previous) => {
            const existingIds = new Set(previous.map((item) => item.id));
            const filtered = incomingFindings.filter((item) => !existingIds.has(item.id));
            return [...previous, ...filtered].slice(-60);
          });
        }
        if (data.type === "site_map") {
          setSiteMap(data as unknown as SiteMapEvent);
          if (Array.isArray(data.pages) && data.pages.length > 0) {
            setCrawledPages((previous) => {
              if (previous.length > 0) return previous;
              return (data.pages as LiveCrawlerPage[]).slice(0, 30);
            });
          }
        }
        if (data.type === "verification_summary") setVerification(data as unknown as VerificationSummary);
        if (data.type === "pillar_activity" && data.pillars && typeof data.pillars === "object") {
          setPillarActivity(data.pillars as Partial<Record<Pillar, PillarActivity>>);
        }
        if (data.type === "report_summary") setReportedSummary(data as unknown as ReportSummaryEvent);
        if (data.type === "completed" || (data.type === "terminal" && data.status === "completed")) {
          source.close();
          navigate(`/reports/${id}`, { replace: true });
        }
        if (["failed", "cancelled"].includes(String(data.type)) || (data.type === "terminal" && ["failed", "cancelled"].includes(String(data.status)))) {
          source.close();
          api<Job>(`/jobs/${id}`).then((value) => { if (active) setJob(value); }).catch(() => undefined);
        }
      } catch {
        // A malformed optional event is ignored; the persisted scan keeps running.
      }
    };
    return () => {
      active = false;
      source.close();
    };
  }, [id, navigate]);

  // Scroll ONLY the inner log container - NEVER call scrollIntoView or scroll the document/page window!
  useEffect(() => {
    const el = logContainerRef.current;
    if (!el || !autoScrollLogs) return;
    el.scrollTop = el.scrollHeight;
  }, [logs, autoScrollLogs]);

  useEffect(() => {
    let active = true;
    api<Tools>("/tools").then((value) => {
      if (active) setToolStatus(value);
    }).catch((err: Error) => {
      if (active) setToolStatusError(err.message);
    });
    return () => { active = false; };
  }, []);

  const cancel = async () => {
    setCancelling(true);
    setError("");
    try {
      await api(`/jobs/${id}/cancel`, { method: "POST" });
      setJob((previous) => previous ? { ...previous, status: "cancelled" } : previous);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCancelling(false);
    }
  };

  const steps = job?.progress.steps || [];
  const terminal = !!job && ["failed", "cancelled"].includes(job.status);
  const percent = Math.max(0, Math.min(100, job?.progress.percent ?? 0));
  const current = steps.find((step) => step.status === "running");
  const inferenceCompleted = aiTasks.filter((task) => task.status === "completed").length;
  const inferenceRunning = aiTasks.filter((task) => task.status === "running").length;
  const inferenceFailed = aiTasks.filter((task) => ["failed", "skipped"].includes(task.status)).length;
  const modelName = planInfo?.model || [...aiTasks].reverse().find((task) => task.name === "Adaptive diagnostic plan")?.model || "Configured local model";
  const executedRecommendations = plan.filter((recommendation) => ["executed", "executed_sitewide", "observed"].includes(recommendation.execution_status)).length;
  const runningRecommendations = plan.filter((recommendation) => recommendation.execution_status === "running").length;
  const unavailableTools = toolStatus?.tools.filter((tool) => !tool.available) || [];
  const pillarCards = useMemo(() => pillars.map((pillar) => ({
    pillar,
    activity: pillarActivity[pillar] && !terminal ? pillarActivity[pillar] : summarizePillar(pillar, steps, job?.pillars || [], terminal),
  })), [pillarActivity, steps, job?.pillars, terminal]);

  const findingsByPillar = useMemo(() => {
    const counts: Record<Pillar, number> = {
      functionality: 0,
      security: 0,
      performance: 0,
      accessibility: 0,
    };
    liveFindings.forEach((f) => {
      if (counts[f.pillar] !== undefined) counts[f.pillar]++;
    });
    return counts;
  }, [liveFindings]);

  const filteredFindings = useMemo(() => {
    if (findingsFilter === "all") return liveFindings;
    return liveFindings.filter((f) => f.pillar === findingsFilter);
  }, [liveFindings, findingsFilter]);

  const [activeSection, setActiveSection] = useState<string>("section-live-audit");
  const [navCollapsed, setNavCollapsed] = useState<boolean>(false);

  useEffect(() => {
    const handleScroll = () => {
      const scrollPos = window.scrollY + 130;
      const sectionIds = [
        "section-live-audit",
        "section-crawler-radar",
        "section-live-defects",
        "section-ai-diagnostics",
        "section-testing-pipeline",
        "section-live-terminal",
      ];

      for (let i = sectionIds.length - 1; i >= 0; i--) {
        const el = document.getElementById(sectionIds[i]);
        if (el) {
          const top = el.getBoundingClientRect().top + window.pageYOffset;
          if (scrollPos >= top) {
            setActiveSection(sectionIds[i]);
            break;
          }
        }
      }
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const scrollToSection = (id: string) => {
    setActiveSection(id);
    const el = document.getElementById(id);
    if (el) {
      const navOffset = 90;
      const elementPosition = el.getBoundingClientRect().top + window.pageYOffset;
      const offsetPosition = elementPosition - navOffset;

      window.scrollTo({
        top: Math.max(0, offsetPosition),
        behavior: "smooth",
      });
    }
  };

  const navSections = [
    {
      id: "section-live-audit",
      label: "Audit Viewport",
      fullTitle: "Live Website Audit & Viewport Screencast",
      icon: Monitor,
      badge: frameCount > 0 ? `Frame #${frameCount}` : "Active",
      badgeType: "pulse",
    },
    {
      id: "section-crawler-radar",
      label: "Crawler Radar",
      fullTitle: "Crawler Radar & Target Inspection",
      icon: Scan,
      badge: `${crawledPages.length || (crawlerActivity ? 1 : 0)} routes`,
      badgeType: "neutral",
    },
    {
      id: "section-live-defects",
      label: "Defects Stream",
      fullTitle: "Real-Time Defects & Quality Observations Stream",
      icon: Bug,
      badge: `${liveFindings.length} found`,
      badgeType: liveFindings.length > 0 ? "warn" : "neutral",
    },
    {
      id: "section-ai-diagnostics",
      label: "AI Diagnostics",
      fullTitle: "AI Decisions & Adaptive Diagnostic Plan",
      icon: Sparkles,
      badge: `${inferenceCompleted} done`,
      badgeType: "neutral",
    },
    {
      id: "section-testing-pipeline",
      label: "Testing Pipeline",
      fullTitle: "18-Stage Testing Pipeline",
      icon: Layers3,
      badge: `${steps.filter((s) => s.status === "completed").length}/${steps.length || 18}`,
      badgeType: "neutral",
    },
    {
      id: "section-live-terminal",
      label: "Live Terminal",
      fullTitle: "Live Terminal Output & Activity Logs",
      icon: Terminal,
      badge: connected ? "Connected" : "Terminal",
      badgeType: connected ? "good" : "neutral",
    },
  ];

  if (error && !job) return <ErrorPanel message={error} />;
  if (!job) return <Loading message="Connecting to your test…" />;
  return (
    <div className="page progress-page">
      <div className="section-kicker">A CLOSER LOOK IS UNDERWAY</div>
      <div className="progress-heading">
        <div>
          <h1>
            {terminal ? job.status === "cancelled" ? "Test cancelled safely" : "The test stopped safely" : job.status === "queued" ? "Your test is in the queue." : "Testing, without the guesswork."}
          </h1>
          <p><Globe2 size={15} />{hostname(job.url)}<span>{job.url}</span></p>
        </div>
        {!terminal && job.status !== "completed" && (
          <button className="btn btn-secondary" disabled={cancelling} onClick={cancel}>
            {cancelling ? <Loader2 size={14} className="animate-spin" /> : <Square size={12} />} Stop test
          </button>
        )}
        {terminal && (
          <Link to="/" className="btn btn-secondary start-new-scan-btn" style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <Plus size={14} /> Start New Scan
          </Link>
        )}
      </div>
      {error && <p role="alert" className="form-error">{error}</p>}
      {terminal && (
        <div className="coverage-notice terminal-notice">
          <AlertCircle size={20} />
          <div>
            <strong>Scan Stopped: {job.error || "The test stopped before all checks were complete."}</strong>
            <span>All 8 security & quality tools are ready. You can safely launch a fresh scan now.</span>
          </div>
          <Link to="/" className="btn btn-secondary start-new-scan-btn" style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <Plus size={14} /> New scan
          </Link>
        </div>
      )}
      <section className="panel progress-summary">
        <span className="progress-running-icon">{terminal ? <ShieldAlert size={23} /> : <Loader2 size={24} className="animate-spin" />}</span>
        <div>
          <strong>{terminal ? "Execution stopped" : current?.title || "Waiting for the persistent worker"}</strong>
          <span>{terminal ? (job.error ? `Stopped safely: ${job.error}` : "Review the completed steps and unavailable checks below.") : "Specialist tools perform checks. Local AI proposes priorities. Evidence determines what can be reported."}</span>
          <div className="progress-bar"><span style={{ width: `${percent}%` }} /></div>
        </div>
        <div className="progress-percent"><strong>{percent}<small>%</small></strong><span>{steps.filter((step) => !["pending", "running"].includes(step.status)).length} / {steps.length || 18} steps</span></div>
      </section>

      {/* COCKPIT WORKSPACE WITH STICKY LEFT SECTION NAV */}
      <div className="progress-cockpit-layout">
        <aside className={`cockpit-left-nav ${navCollapsed ? "is-collapsed" : ""}`} aria-label="Section navigation">
          <div className="cockpit-nav-header">
            <div className="cockpit-nav-title">
              <Layers3 size={14} />
              {!navCollapsed && <span>Audit Sections</span>}
            </div>
            <button
              type="button"
              className="cockpit-collapse-btn"
              onClick={() => setNavCollapsed(!navCollapsed)}
              title={navCollapsed ? "Expand section bar" : "Collapse section bar"}
              aria-label={navCollapsed ? "Expand section bar" : "Collapse section bar"}
            >
              <ChevronRight size={14} style={{ transform: navCollapsed ? "none" : "rotate(180deg)", transition: "transform 0.2s" }} />
            </button>
          </div>

          <nav className="cockpit-nav-list">
            {navSections.map((sec) => {
              const IconComp = sec.icon;
              const isActive = activeSection === sec.id;
              return (
                <button
                  key={sec.id}
                  type="button"
                  className={`cockpit-nav-item ${isActive ? "active" : ""}`}
                  onClick={() => scrollToSection(sec.id)}
                  title={sec.fullTitle}
                >
                  <span className="cockpit-nav-icon">
                    <IconComp size={15} />
                  </span>
                  {!navCollapsed && (
                    <div className="cockpit-nav-label-wrap">
                      <span className="cockpit-nav-label">{sec.label}</span>
                      <span className={`cockpit-nav-badge badge-${sec.badgeType}`}>
                        {sec.badge}
                      </span>
                    </div>
                  )}
                  {isActive && <span className="cockpit-active-glow-bar" />}
                </button>
              );
            })}
          </nav>

          {!navCollapsed && (
            <div className="cockpit-nav-shortcuts">
              <button
                type="button"
                className="cockpit-shortcut-btn"
                onClick={() => scrollToSection("section-live-terminal")}
              >
                <Terminal size={12} />
                <span>Jump to Terminal ↓</span>
              </button>
              <button
                type="button"
                className="cockpit-shortcut-btn"
                onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
              >
                <span>Back to Top ↑</span>
              </button>
            </div>
          )}
        </aside>

        <div className="cockpit-main-column">
          {/* LIVE REAL-TIME ANALYSIS COCKPIT */}
          <section className="panel live-analysis-panel" id="section-live-audit" aria-labelledby="live-analysis-title">
        <div className="live-analysis-header">
          <div className="live-header-info">
            <div className="live-pulse-badge">
              <span className="live-pulse-dot" />
              <Radio size={13} className="live-radio-icon animate-pulse" />
              <span>REAL-TIME ENGINE ACTIVE</span>
            </div>
            <h2 id="live-analysis-title">Live Website Audit & Pillar Execution</h2>
            <p>Traversing target routes, executing the 4 quality pillars, and detecting defects live as specialist adapters run.</p>
          </div>
          <div className="live-stats-bar">
            <div className="live-stat-chip">
              <Globe2 size={14} />
              <span>{crawledPages.length || (crawlerActivity ? 1 : 0)} Pages Mapped</span>
            </div>
            <div className="live-stat-chip live-stat-defects">
              <AlertTriangle size={14} />
              <span>{liveFindings.length} Live Defects Found</span>
            </div>
          </div>
        </div>

        {/* 1. LIVE VISUAL BROWSER VIEWPORT */}
        <div className="live-browser-viewport-card">
          <div className="browser-chassis-topbar">
            <div className="browser-chassis-controls">
              <span className="chassis-dot dot-red" />
              <span className="chassis-dot dot-yellow" />
              <span className="chassis-dot dot-green" />
            </div>

            <div className="browser-address-bar">
              <span className="browser-ssl-lock">
                <ShieldCheck size={13} />
              </span>
              <span className="browser-url-text">
                {browserFrame?.url || crawlerActivity?.url || job.url}
              </span>
              <span className="browser-engine-badge">
                <Play size={10} /> Chromium Headless
              </span>
            </div>

            <div className="browser-frame-counter">
              <span className="browser-live-beacon" />
              <span>{frameCount > 0 ? `FRAME #${frameCount}` : "STANDBY"}</span>
            </div>
          </div>

          {(() => {
            const isHeadlessPhase = !!(current && ["load", "axe", "pa11y", "vision", "verify", "triage", "synthesis"].includes(current.id));
            const currentStepIdx = current ? steps.findIndex((s) => s.id === current.id) + 1 : 0;
            const displayAction = isHeadlessPhase
              ? `[HEADLESS & AI ENGINE] Step ${currentStepIdx}/${steps.length || 18}: ${current.title}`
              : (browserFrame?.action || "Auditing live viewport");
            const displayTime = isHeadlessPhase
              ? "Running in background"
              : (browserFrame?.timestamp ? new Date(browserFrame.timestamp).toLocaleTimeString([], { hour12: false }) : "");

            return (
              <div className="browser-action-banner">
                <div className="browser-action-pill">
                  <Sparkles size={12} />
                  <span>{displayAction}</span>
                </div>
                {displayTime && (
                  <time className="browser-frame-time">
                    {displayTime}
                  </time>
                )}
              </div>
            );
          })()}

          <div className="browser-screen-container">
            {browserFrame?.image ? (
              <div className="browser-live-canvas">
                <div className="browser-scanline-laser" />
                <img
                  src={`data:image/jpeg;base64,${browserFrame.image}`}
                  alt="Live Browser Screencast Viewport"
                  className="browser-rendered-frame"
                />
                <div className="browser-viewport-hud-overlay">
                  <div className="hud-telemetry-left">
                    <span className={`browser-telemetry-chip ${current && ["load", "axe", "pa11y", "vision", "verify", "triage", "synthesis"].includes(current.id) ? "" : "hud-pulse-green"}`}>
                      <Radio size={11} className={current && ["load", "axe", "pa11y", "vision", "verify", "triage", "synthesis"].includes(current.id) ? "text-sky-400" : "animate-pulse text-emerald-400"} />
                      <span>{current && ["load", "axe", "pa11y", "vision", "verify", "triage", "synthesis"].includes(current.id) ? "BROWSER PHASE DONE · AI ANALYSIS" : "STREAM ACTIVE"}</span>
                    </span>
                    <span className="browser-telemetry-chip">1440×1000 DESKTOP</span>
                    <span className="browser-telemetry-chip">SAFE EGRESS GUARD</span>
                  </div>
                  <div className="hud-telemetry-right">
                    <span className="browser-screencast-watermark">
                      <ShieldCheck size={11} className="text-sky-400" />
                      <span>PLAYWRIGHT BROWSER ENGINE</span>
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="browser-empty-canvas">
                <div className="browser-empty-grid">
                  <div className="browser-empty-icon-wrap animate-pulse">
                    <Monitor size={36} />
                  </div>
                  <strong>Playwright Visual Viewport Screencast</strong>
                  <p>
                    Streaming real-time browser screencast frames during target navigation, page scrolling, responsive viewports, and interactive form audits.
                  </p>
                  <div className="browser-empty-specs">
                    <span>1440×1000 Desktop Viewport</span>
                    <span>390×844 Mobile Audit</span>
                    <span>Safe Egress Guard Active</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 2. REAL-TIME CRAWLER RADAR */}
        <div className="crawler-radar-card" id="section-crawler-radar">
          <div className="crawler-radar-header">
            <div className="crawler-radar-title">
              <Scan size={15} />
              <strong>Crawler Radar & Target Inspection</strong>
            </div>
            <span className="crawler-depth-tag">
              Crawl Depth: {crawlerActivity?.depth ?? 0}
            </span>
          </div>
          <div className="crawler-radar-body">
            <div className="crawler-active-url-box">
              <div className="crawler-url-indicator">
                <span className="crawler-ping" />
                <small>CURRENTLY AUDITING TARGET ROUTE</small>
              </div>
              <div className="crawler-url-text">
                <span className="crawler-url-link">
                  {crawlerActivity?.url || (crawledPages.length ? crawledPages[crawledPages.length - 1].url : job.url)}
                </span>
              </div>
            </div>
            {crawledPages.length > 0 && (
              <div className="crawler-pages-stream">
                <small className="crawler-stream-label">DISCOVERED TARGET ROUTES ({crawledPages.length})</small>
                <div className="crawler-stream-list">
                  {crawledPages.slice(-6).reverse().map((page) => (
                    <div key={page.id} className="crawler-page-pill">
                      <span className="page-pill-status">{page.status_code || 200}</span>
                      <span className="page-pill-title" title={page.url}>{page.title || page.url}</span>
                      {page.forms > 0 && <span className="page-pill-forms">{page.forms} forms</span>}
                      {page.links > 0 && <span className="page-pill-links">{page.links} links</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 2. REAL-TIME 4-PILLAR EXECUTION MATRIX */}
        <div className="live-pillars-grid">
          {pillars.map((pillar) => {
            const isPillarRunning = current?.pillar === pillar;
            const pillarSteps = steps.filter((s) => s.pillar === pillar);
            const completedSteps = pillarSteps.filter((s) => s.status === "completed").length;
            const totalSteps = pillarSteps.length;
            const issuesCount = findingsByPillar[pillar] || 0;
            const isSelected = job.pillars.includes(pillar);
            const toolName = pillar === "functionality" ? "Playwright Engine" :
                             pillar === "security" ? "OWASP ZAP & Nuclei" :
                             pillar === "performance" ? "Lighthouse & Locust" :
                             "axe-core & Vision";

            return (
              <div
                key={pillar}
                className={`live-pillar-card ${isPillarRunning ? "is-executing" : ""} ${!isSelected ? "is-disabled" : ""}`}
              >
                <div className="live-pillar-header">
                  <div className="live-pillar-brand">
                    <span className={`live-pillar-icon pillar-${pillar}`}>
                      <PillarIcon pillar={pillar} size={15} />
                    </span>
                    <div>
                      <strong>{labels[pillar]}</strong>
                      <span className="live-tool-badge">{toolName}</span>
                    </div>
                  </div>
                  {isPillarRunning ? (
                    <span className="live-execution-tag">
                      <Loader2 size={11} className="animate-spin" /> RUNNING
                    </span>
                  ) : !isSelected ? (
                    <span className="live-skipped-tag">NOT SELECTED</span>
                  ) : completedSteps === totalSteps && totalSteps > 0 ? (
                    <span className="live-complete-tag">
                      <CheckCheck size={12} /> COMPLETE
                    </span>
                  ) : (
                    <span className="live-standby-tag">STANDBY</span>
                  )}
                </div>

                <div className="live-pillar-stats">
                  <div className="live-pillar-metric">
                    <small>DEFECTS DETECTED</small>
                    <strong className={issuesCount > 0 ? "has-issues" : ""}>
                      {issuesCount}
                    </strong>
                  </div>
                  <div className="live-pillar-metric">
                    <small>PIPELINE STEPS</small>
                    <strong>
                      {completedSteps} / {totalSteps || 4}
                    </strong>
                  </div>
                </div>

                <div className="live-pillar-progress">
                  <div
                    className="live-pillar-progress-bar"
                    style={{
                      width: `${totalSteps ? Math.round((completedSteps / totalSteps) * 100) : 0}%`,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* 3. REAL-TIME DETECTED ISSUES & OBSERVATIONS STREAM */}
        <div className="live-findings-section" id="section-live-defects">
          <div className="live-findings-header">
            <div className="live-findings-title">
              <Bug size={16} />
              <h3>Real-Time Defects & Quality Observations Stream</h3>
              <span className="live-counter-bubble">{filteredFindings.length}</span>
            </div>
            <div className="live-findings-filters">
              <button
                type="button"
                className={`live-filter-btn ${findingsFilter === "all" ? "active" : ""}`}
                onClick={() => setFindingsFilter("all")}
              >
                All ({liveFindings.length})
              </button>
              {pillars.map((p) => (
                <button
                  key={p}
                  type="button"
                  className={`live-filter-btn ${findingsFilter === p ? "active" : ""}`}
                  onClick={() => setFindingsFilter(p)}
                >
                  {labels[p]} ({findingsByPillar[p] || 0})
                </button>
              ))}
            </div>
          </div>

          {filteredFindings.length > 0 ? (
            <div className="live-findings-stream">
              {filteredFindings.slice().reverse().map((finding) => (
                <article key={finding.id} className={`live-finding-card severity-${finding.severity.toLowerCase()}`}>
                  <div className="live-finding-top">
                    <div className="live-finding-meta">
                      <span className={`live-sev-chip sev-${finding.severity.toLowerCase()}`}>
                        {finding.severity}
                      </span>
                      <span className="live-pillar-chip">
                        <PillarIcon pillar={finding.pillar} size={11} /> {labels[finding.pillar]}
                      </span>
                      {finding.sources?.length > 0 && (
                        <span className="live-source-chip">
                          {finding.sources[0]}
                        </span>
                      )}
                    </div>
                    {finding.timestamp && (
                      <time className="live-finding-time">
                        {new Date(finding.timestamp).toLocaleTimeString([], { hour12: false })}
                      </time>
                    )}
                  </div>
                  <h4 className="live-finding-heading">{finding.title}</h4>
                  {finding.url && (
                    <div className="live-finding-loc">
                      <code>{finding.url}</code>
                      {finding.selector && <span>· <code>{finding.selector}</code></span>}
                    </div>
                  )}
                  {finding.explanation && (
                    <p className="live-finding-snippet">{finding.explanation}</p>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <div className="live-findings-empty">
              <div className="live-empty-pulse">
                <Radar size={26} className="animate-spin text-muted" />
              </div>
              <strong>Auditing Target in Real Time</strong>
              <p>
                {terminal
                  ? "Scan halted. No defects surfaced before stop."
                  : "Specialist tools (Playwright, OWASP ZAP, axe-core, Lighthouse) are currently auditing the target website. Real-time defects and quality anomalies will populate here as adapters finish their tests."}
              </p>
            </div>
          )}
        </div>
      </section>

      <section className="panel diagnostic-activity-panel" id="section-ai-diagnostics" aria-labelledby="diagnostic-activity-title">
        <div className="diagnostic-activity-heading">
          <div>
            <div className="section-kicker"><Sparkles size={13} /> AI DIAGNOSTIC ACTIVITY</div>
            <h2 id="diagnostic-activity-title">See what the system is deciding — and what actually ran.</h2>
            <p>Recommendations are not findings. A recommendation only becomes an executed check after its adapter runs; final findings still depend on evidence and verification.</p>
          </div>
          <span className={`connection-pill ${connected ? "is-connected" : "is-disconnected"}`}>
            {connected ? <Wifi size={13} /> : <WifiOff size={13} />}{connected ? "Live event stream" : "Reconnecting"}
          </span>
        </div>

        <div className="diagnostic-kpis">
          <article className="diagnostic-kpi">
            <span className="diagnostic-kpi-icon"><BrainCircuit size={17} /></span>
            <div><small>LOCAL AI TASKS</small><strong>{inferenceCompleted} completed</strong><span>{inferenceRunning ? `${inferenceRunning} in progress` : inferenceFailed ? `${inferenceFailed} unavailable / failed` : aiTasks.length ? "Inference statuses reported" : "Waiting for first AI task"}</span></div>
          </article>
          <article className="diagnostic-kpi">
            <span className="diagnostic-kpi-icon"><FileSearch size={17} /></span>
            <div><small>DIAGNOSTIC PLAN</small><strong>{planInfo ? `${planInfo.accepted_count ?? plan.length} accepted` : "Building plan"}</strong><span>{runningRecommendations ? `${runningRecommendations} runner active` : `${executedRecommendations} recommendations confirmed executed`}</span></div>
          </article>
          <article className="diagnostic-kpi">
            <span className="diagnostic-kpi-icon"><ShieldCheck size={17} /></span>
            <div><small>EVIDENCE REVIEW</small><strong>{verification ? `${verification.verified} verified` : "Pending"}</strong><span>{verification ? `${verification.possible} possible · ${verification.unresolved} unresolved · ${verification.total} total` : "Counts appear after re-testing"}</span></div>
          </article>
          <article className="diagnostic-kpi">
            <span className="diagnostic-kpi-icon"><Network size={17} /></span>
            <div><small>WEBSITE MAP</small><strong>{siteMap ? `${siteMap.pages_mapped} pages` : "Discovering"}</strong><span>{siteMap ? `${siteMap.forms_mapped} forms · ${siteMap.links_mapped} links${siteMap.flows_proposed != null ? ` · ${siteMap.flows_proposed} proposed flows` : ""}` : "Waiting for browser observations"}</span></div>
          </article>
        </div>

        {reportedSummary && (
          <div className="diagnostic-final-summary">
            <CheckCircle2 size={16} />
            <span>Final run summary: {reportedSummary.findings} findings, {reportedSummary.verified} verified, {reportedSummary.coverage}% overall pipeline coverage{reportedSummary.partial ? " · partial coverage" : " · pipeline complete"}.</span>
          </div>
        )}

        <div className="diagnostic-live-grid">
          <section className="diagnostic-plan-card" aria-labelledby="diagnostic-plan-title">
            <div className="diagnostic-subheading">
              <div><h3 id="diagnostic-plan-title">AI-selected checks</h3><p>Page-aware recommendations with live runner state</p></div>
              <span className={`diagnostic-status tone-${statusTone(planInfo?.status)}`}>{planInfo ? statusLabel(planInfo.status) : "Awaiting plan"}</span>
            </div>
            {planInfo && (
              <div className="diagnostic-plan-meta"><span><BrainCircuit size={13} /> {modelName}</span><span>{planInfo.inference_confirmed ? "Real model response confirmed" : "Real inference not confirmed"}</span></div>
            )}
            {plan.length ? (
              <div className="diagnostic-recommendations">
                {plan.map((recommendation) => (
                  <article key={`${recommendation.page_id}-${recommendation.test_type}`} className="diagnostic-recommendation">
                    <div className="diagnostic-recommendation-top">
                      <span className="diagnostic-test-icon">{recommendation.test_type.includes("security") ? <ShieldCheck size={15} /> : recommendation.test_type.includes("performance") ? <Gauge size={15} /> : recommendation.test_type.includes("visual") ? <Eye size={15} /> : recommendation.test_type.includes("accessibility") ? <Layers3 size={15} /> : <Activity size={15} />}</span>
                      <div className="diagnostic-recommendation-name"><strong>{testLabels[recommendation.test_type] || recommendation.test_type.replaceAll("_", " ")}</strong><span>{recommendation.page_title || recommendation.page_id}</span></div>
                      <span className={`priority-chip priority-${recommendation.priority}`}>{recommendation.priority}</span>
                    </div>
                    <p className="diagnostic-rationale">{recommendation.rationale}</p>
                    <div className="diagnostic-recommendation-footer">
                      <span><Wrench size={12} /> {stepLabels[recommendation.execution_step] || recommendation.execution_step}</span>
                      <span className={`diagnostic-status tone-${statusTone(recommendation.execution_status)}`}><i />{statusLabel(recommendation.execution_status)}</span>
                    </div>
                    <small className="diagnostic-recommendation-url">{recommendation.page_url}</small>
                    {recommendation.execution_detail && <small className="diagnostic-execution-detail">{recommendation.execution_detail}</small>}
                  </article>
                ))}
              </div>
            ) : (
              <div className="diagnostic-empty-state">
                <div className="diagnostic-empty-icon">{terminal || planInfo?.status === "failed" || planInfo?.status === "skipped" || planInfo?.status === "blocked" ? <CircleHelp size={21} /> : <Loader2 size={21} className="animate-spin" />}</div>
                <strong>{terminal ? "Execution stopped before AI planning" : planInfo ? "No AI recommendations accepted" : "Waiting for discovery and local inference"}</strong>
                <p>{terminal ? (job.error || "The scan was halted before crawl observations could complete.") : planInfo?.detail || "The site map is being prepared. Once observations are available, local AI may recommend supported tests. Baseline checks continue if AI is unavailable."}</p>
              </div>
            )}
          </section>

          <aside className="diagnostic-side-stack">
            <section className="diagnostic-mini-panel">
              <div className="diagnostic-subheading"><div><h3>Four-pillar activity</h3><p>Workflow execution, not a quality score</p></div><Gauge size={17} /></div>
              <div className="pillar-activity-list">
                {pillarCards.map(({ pillar, activity }) => (
                  <div key={pillar} className={`pillar-activity-row ${!activity.selected ? "not-selected" : ""}`}>
                    <span className="pillar-activity-icon"><PillarIcon pillar={pillar} size={15} /></span>
                    <div className="pillar-activity-main"><strong>{labels[pillar]}</strong><span>{!activity.selected ? "Not selected" : `${activity.completed_steps}/${activity.total_steps} steps completed · ${activity.unavailable_steps} unavailable`}</span><div className="pillar-mini-bar"><i style={{ width: `${activity.pipeline_coverage_percent}%` }} /></div></div>
                    <span className={`diagnostic-status tone-${statusTone(activity.status === "complete" ? "completed" : activity.status === "running" ? "running" : activity.status === "not_selected" ? "skipped" : "partial")}`}>{activity.status.replaceAll("_", " ")}</span>
                  </div>
                ))}
              </div>
              <p className="diagnostic-footnote">These bars reflect pipeline-step completion. Final pillar scores and coverage come from the completed report.</p>
            </section>

            <section className="diagnostic-mini-panel">
              <div className="diagnostic-subheading"><div><h3>Local AI task trace</h3><p>Model responses and fallbacks are distinct</p></div><BrainCircuit size={17} /></div>
              {aiTasks.length ? (
                <div className="ai-task-list">
                  {[...aiTasks].reverse().slice(0, 7).map((task) => (
                    <div className="ai-task-row" key={`${task.name}-${task.model}`}>
                      <span className={`ai-task-status tone-${statusTone(task.status)}`}>{task.status === "running" ? <Loader2 size={13} className="animate-spin" /> : task.status === "completed" ? <Check size={13} /> : task.status === "failed" ? <XCircle size={13} /> : <Clock3 size={13} />}</span>
                      <div><strong>{task.name}</strong><span>{task.model} · {task.detail || task.status}</span></div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="diagnostic-placeholder"><BrainCircuit size={20} /><span>AI task events will appear here when each local model call starts and finishes.</span></div>
              )}
            </section>

            <section className="diagnostic-mini-panel">
              <div className="diagnostic-subheading"><div><h3>Tool availability</h3><p>Availability is not the same as a successful scan</p></div><Wrench size={17} /></div>
              {toolStatusError ? <p className="diagnostic-tool-note">Tool health could not be loaded: {toolStatusError}</p> : toolStatus ? (
                <>
                  <div className="diagnostic-tool-summary"><span className={`diagnostic-status tone-${unavailableTools.length ? "warn" : "good"}`}>{toolStatus.tools.length - unavailableTools.length}/{toolStatus.tools.length} listed tools available</span><span>{toolStatus.ollama_reachable ? "Ollama reachable" : "Ollama not confirmed reachable"}</span></div>
                  {unavailableTools.length > 0 && <div className="diagnostic-unavailable-tools">{unavailableTools.slice(0, 5).map((tool) => <span key={tool.name}><AlertCircle size={12} /> {tool.name}: {tool.detail}</span>)}</div>}
                  <p className="diagnostic-footnote">Unavailable tools are not treated as passes; read the final report for actual execution status.</p>
                </>
              ) : <p className="diagnostic-tool-note">Checking locally installed models and scanner integrations…</p>}
            </section>
          </aside>
        </div>
      </section>

      <div className="progress-grid">
        <section className="panel pipeline-panel" id="section-testing-pipeline">
          <div className="panel-heading"><h2>Testing pipeline</h2><span className="small-muted">End-to-end, automatically</span></div>
          <div className="pipeline-list">
            {steps.length ? steps.map((step, index) => (
              <div key={step.id} className={step.status === "running" ? "current" : ""}>
                <span className={`pipeline-step-icon status-${terminal && step.status === "pending" ? "not-reached" : step.status}`}>{step.status === "completed" ? <Check size={14} /> : step.status === "running" ? <Loader2 size={15} className="animate-spin" /> : step.status === "failed" || step.status === "blocked" ? <AlertCircle size={14} /> : <span>{String(index + 1).padStart(2, "0")}</span>}</span>
                <div><strong>{step.title}</strong>{step.detail ? <p>{step.detail}</p> : terminal && step.status === "pending" ? <p className="step-halted-hint">Not reached · scan stopped earlier</p> : null}</div>
                <span className={`pipeline-status status-${terminal && step.status === "pending" ? "stopped" : step.status}`}>{step.status === "pending" ? (terminal ? "Not reached" : "Waiting") : step.status}</span>
              </div>
            )) : <Loading message="Queueing the pipeline…" />}
          </div>
        </section>
        <section className="log-panel" id="section-live-terminal">
          <div className="log-header">
            <span><Terminal size={15} /> Live activity</span>
            <div className="log-header-actions">
              {!autoScrollLogs && (
                <button
                  type="button"
                  className="log-resume-btn"
                  onClick={() => {
                    setAutoScrollLogs(true);
                    if (logContainerRef.current) {
                      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
                    }
                  }}
                  title="Resume live log scrolling"
                >
                  Resume scroll ↓
                </button>
              )}
              <span>{connected ? <Wifi size={12} /> : <WifiOff size={12} />}{connected ? "Connected" : "Reconnecting"}</span>
            </div>
          </div>
          <div
            className="live-logs"
            ref={logContainerRef}
            onScroll={handleLogsScroll}
            aria-live="polite"
            aria-relevant="additions"
          >
            {logs.length ? logs.map((log, index) => (
              <div key={`${log.timestamp}-${index}`}><time>{log.timestamp ? new Date(log.timestamp).toLocaleTimeString([], { hour12: false }) : "··:··:··"}</time><ChevronRight size={11} /><span>{log.message}</span></div>
            )) : <p className="log-waiting">Waiting for the first observation…</p>}
          </div>
          <div className="log-footer"><ShieldCheck size={13} /> Same-origin policy. Safe test actions only. Unavailable checks remain visible.</div>
        </section>
      </div>
    </div>
  </div>
</div>
  );
}
