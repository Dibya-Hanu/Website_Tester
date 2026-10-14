export type Pillar =
  | "functionality"
  | "security"
  | "performance"
  | "accessibility";
export type Severity = "Critical" | "High" | "Medium" | "Low" | "Info";
export type StepStatus =
  | "pending"
  | "running"
  | "completed"
  | "partial"
  | "skipped"
  | "blocked"
  | "failed";
export interface Evidence {
  kind: string;
  detail: string;
  file: string | null;
}
export interface Finding {
  id: string;
  title: string;
  pillar: Pillar;
  severity: Severity;
  status: "Verified" | "Possible";
  category: string;
  location: { url: string; selector: string | null; header: string | null };
  evidence: Evidence[];
  explanation: string;
  suggested_fix: string;
  sources: string[];
  verification_note: string;
  ai_assisted: boolean;
}
export interface Step {
  id: string;
  title: string;
  pillar: Pillar | null;
  status: StepStatus;
  detail: string;
  metrics: Record<string, unknown>;
  started_at: string | null;
  finished_at: string | null;
}
export interface PillarScore {
  score: number | null;
  status: string;
  coverage: number;
  completed_checks: number;
  total_checks: number;
  issues: number;
}
export interface PageInfo {
  id: string;
  url: string;
  title: string;
  depth: number;
  classification: string;
  status_code: number | null;
  screenshots: Record<string, string>;
  forms: { id: string; fields: unknown[] }[];
  links: { url: string; text: string }[];
  readiness?: { strategy?: string; stable?: boolean; wait_ms?: number; note?: string };
}
export interface DiagnosticRecommendation {
  page_id: string;
  page_url: string;
  page_title: string;
  test_type: "form_validation" | "navigation_flow" | "link_health" | "visual_review" | "accessibility_review" | "security_review" | "performance_review";
  priority: "high" | "normal" | "low";
  rationale: string;
  source: string;
  execution_step: string;
  execution_status: string;
  execution_detail?: string;
}
export interface PillarActivity {
  selected: boolean;
  status: string;
  completed_steps: number;
  total_steps: number;
  finished_steps: number;
  running_steps: number;
  unavailable_steps: number;
  partial_steps: number;
  pipeline_coverage_percent: number;
}
export interface VerificationSummary {
  phase: string;
  verified: number;
  possible: number;
  unresolved: number;
  total: number;
  suppressed?: number;
  details?: Record<string, unknown>;
}
export interface DiagnosticPlanEvent {
  status: string;
  detail: string;
  model: string;
  inference_confirmed: boolean;
  recommendations: DiagnosticRecommendation[];
  accepted_count: number;
  page_count: number;
  selected_pillars: Pillar[];
}
export interface SiteMapEvent {
  phase?: string;
  status: string;
  pages_mapped: number;
  forms_mapped: number;
  links_mapped: number;
  flows_proposed?: number;
}
export interface TestCase {
  name: string;
  form_id: string;
  kind: string;
  source: string;
  url: string;
  status: string;
  expected: string;
  submitted: boolean;
  screenshot?: string;
  observations: {
    field_id: string;
    selector: string;
    valid: boolean;
    message: string;
  }[];
}
export interface AITask {
  name: string;
  model: string;
  status: string;
  detail: string;
  started_at?: string;
  finished_at?: string;
}
export interface Report {
  id: string;
  url: string;
  created_at: string;
  finished_at: string;
  duration_seconds: number;
  selected_pillars: Pillar[];
  authorized: boolean;
  overall_score: number | null;
  coverage: number;
  partial: boolean;
  sample: boolean;
  summary: string;
  priorities: string[];
  scores: Record<Pillar, PillarScore>;
  findings: Finding[];
  suppressed_findings: Finding[];
  steps: Step[];
  pages: PageInfo[];
  diagnostic_plan: DiagnosticRecommendation[];
  flows: {
    name: string;
    page_ids: string[];
    rationale: string;
    status?: string;
    coverage?: string;
    observations?: {
      page_id: string;
      url: string;
      http_status?: number | null;
      result: string;
      submitted: boolean;
    }[];
  }[];
  test_cases: TestCase[];
  ai_tasks: AITask[];
  metrics: Record<string, Record<string, unknown>>;
  limitations: string[];
  tool_versions: Record<string, string>;
}
export interface Job {
  id: string;
  url: string;
  pillars: Pillar[];
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: { steps?: Step[]; percent?: number };
  error: string | null;
  overall_score?: number | null;
  issue_count?: number;
  coverage?: number;
  partial?: boolean;
  sample?: boolean;
}
export interface Policy {
  origins: string[];
  max_users: number;
  load_seconds: number;
  max_pages: number;
  require_allowlist_all_scans?: boolean;
  warning: string;
}
export interface Tools {
  ready: boolean;
  ollama_reachable?: boolean;
  tools: {
    name: string;
    available: boolean;
    detail: string;
    license: string;
  }[];
}

export interface LiveFinding {
  id: string;
  title: string;
  pillar: Pillar;
  severity: Severity;
  status: "Verified" | "Possible";
  category: string;
  url: string;
  selector?: string | null;
  sources: string[];
  explanation: string;
  suggested_fix?: string;
  timestamp?: string;
}

export interface LiveCrawlerPage {
  id: string;
  url: string;
  title: string;
  depth: number;
  forms: number;
  links: number;
  status_code?: number | null;
  readiness?: Record<string, unknown>;
  classification?: string;
}

export interface BrowserFrameEvent {
  type: "browser_frame";
  image: string;
  action: string;
  url: string;
  timestamp?: string;
}

