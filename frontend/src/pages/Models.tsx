import { Fragment, useState } from "react";
import { CheckCircle2, FlaskConical, Info, RefreshCw } from "lucide-react";
import { api, useApi } from "../lib";
import { Empty, ErrorPanel, Loading } from "../components/Common";

type Kind = "text" | "vision" | "coding";
interface ModelRow {
  id: string;
  display_name: string;
  provider: string;
  categories: string[];
  purpose: string;
  classification: string;
  deployment: string;
  cost_type: string;
  api_key_required: boolean;
  license: { name: string; url: string | null; reviewed: boolean; commercial_use: string };
  memory_requirements: string;
  context_length: string;
  approx_size: string;
  limitations: string[];
  setup: string[];
  repository_url: string | null;
  supported_in_app: boolean;
  status: string;
  last_test: { ok: boolean; detail: string; seconds: number | null; tested_at: string } | null;
}
interface Catalog {
  note: string;
  ollama: { reachable: boolean; detail: string };
  selection: Record<string, { model_id: string; verified_working: boolean }>;
  models: ModelRow[];
}
interface Rec {
  id: string;
  score: number;
  method: string;
  not_measured: string[];
}
const kindCategory: Record<Kind, string> = { text: "general-reasoning", vision: "vision", coding: "coding" };

export default function Models() {
  const { data, error, loading, reload } = useApi<Catalog>("/models");
  const [kind, setKind] = useState<Kind>("text");
  const [group, setGroup] = useState("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [recs, setRecs] = useState<Record<string, Rec>>({});
  const [open, setOpen] = useState<string | null>(null);

  async function run(key: string, work: () => Promise<string>) {
    if (busy) return;
    setBusy(key);
    setMessage(null);
    try {
      setMessage({ ok: true, text: await work() });
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(null);
      reload();
    }
  }
  const test = (m: ModelRow) =>
    run(`test-${m.id}`, async () => {
      const r = await api<{ ok: boolean; detail: string }>(`/models/${m.id}/test?kind=${kind}`, { method: "POST" });
      return `${m.display_name}: ${r.ok ? "test passed" : "test failed"}. ${r.detail}`;
    });
  const select = (m: ModelRow) =>
    run(`sel-${m.id}`, async () => {
      await api(`/models/selection`, { method: "PUT", body: JSON.stringify({ kind, model_id: m.id }) });
      return `${m.display_name} saved for ${kind} tasks. It is only confirmed working after Test Model passes.`;
    });
  const rank = () =>
    run("recommend", async () => {
      const r = await api<{ results: Rec[] }>(`/models/recommend`, {
        method: "POST",
        body: JSON.stringify({ task: kind, classification: group }),
      });
      setRecs(Object.fromEntries(r.results.map((x) => [x.id, x])));
      return "Ranking updated. Scores are an aid built from the criteria shown, not a quality benchmark.";
    });

  if (loading) return <Loading message="Loading model catalogue…" />;
  if (error || !data) return <ErrorPanel message={error ?? "Could not load models."} retry={reload} />;
  const rows = data.models
    .filter((m) => m.categories.includes(kindCategory[kind]))
    .filter((m) => group === "all" || (group === "open" && m.cost_type === "self-hosted") || (group === "paid" && m.cost_type === "paid-api") || (group === "local" && m.deployment === "local"))
    .sort((a, b) => (recs[b.id]?.score ?? 0) - (recs[a.id]?.score ?? 0));
  const chosen = data.selection[kind];
  return (
    <div className="page">
      <div className="page-heading">
        <h1>AI Models</h1>
        <p>
          Choose local models for page classification, adaptive test planning, form-case generation, visual review, security triage and report synthesis. Deterministic scanners still execute checks and verification; unavailable AI tasks are labelled rather than silently presented as model-driven work.
        </p>
      </div>
      <section className="panel" style={{ padding: 18, marginBottom: 16 }} aria-live="polite">
        <strong>{data.ollama.reachable ? "Local Ollama is reachable." : "Local Ollama is not reachable."}</strong>{" "}
        <span>{data.ollama.detail} {data.note}</span>
        {chosen && (
          <p style={{ margin: "8px 0 0" }}>
            Selected for {kind}: <strong>{chosen.model_id}</strong> {chosen.verified_working ? "(test passed)" : "(not yet tested)"}
          </p>
        )}
      </section>
      <section className="panel" style={{ padding: 18, marginBottom: 16, display: "flex", gap: 14, flexWrap: "wrap", alignItems: "end" }}>
        <label>
          <span className="field-label">1. Task</span>
          <select value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
            <option value="text">Reasoning and finding analysis</option>
            <option value="coding">Coding and fix suggestions</option>
            <option value="vision">Screenshot analysis</option>
          </select>
        </label>
        <label>
          <span className="field-label">2. Type</span>
          <select value={group} onChange={(e) => setGroup(e.target.value)}>
            <option value="all">All models</option>
            <option value="open">Open-source / open-weight (free to run)</option>
            <option value="local">Local</option>
            <option value="paid">Paid API</option>
          </select>
        </label>
        <button className="btn btn-secondary" disabled={busy !== null} onClick={rank}>
          <RefreshCw size={15} /> {busy === "recommend" ? "Ranking…" : "Rank models"}
        </button>
      </section>
      {message && (
        <div role="status" className="panel" style={{ padding: 14, marginBottom: 16, borderColor: message.ok ? "#2b9a85" : "#a8323c" }}>
          {message.text}
        </div>
      )}
      {rows.length === 0 ? (
        <Empty title="No models match" description="Change the task or type filter." />
      ) : (
        <div className="panel" style={{ overflowX: "auto" }}>
          <table className="history-table" style={{ width: "100%" }}>
            <thead>
              <tr>
                <th>Model</th><th>License</th><th>Cost / where</th><th>Memory</th><th>Status</th><th>Rank score</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <Fragment key={m.id}>
                  <tr>
                    <td>
                      <strong>{m.display_name}</strong>
                      <div>{m.provider}</div>
                      <button className="btn btn-secondary" aria-expanded={open === m.id} onClick={() => setOpen(open === m.id ? null : m.id)}>
                        <Info size={13} /> Details
                      </button>
                    </td>
                    <td>{m.license.name}<div>{m.classification}</div></td>
                    <td>{m.cost_type}, {m.deployment}{m.api_key_required ? ", needs API key" : ""}</td>
                    <td>{m.memory_requirements}</td>
                    <td>{m.status}{m.last_test && <div>{m.last_test.ok ? "Test passed" : "Test failed"}</div>}</td>
                    <td>{recs[m.id] ? recs[m.id].score : "Not ranked"}</td>
                    <td>
                      <button className="btn btn-secondary" disabled={busy !== null || !m.supported_in_app} onClick={() => test(m)} title={m.supported_in_app ? "Run a small safe sample task" : "Not supported by the built-in runner"}>
                        <FlaskConical size={14} /> {busy === `test-${m.id}` ? "Testing…" : "Test Model"}
                      </button>{" "}
                      <button className="btn btn-primary" disabled={busy !== null || !m.supported_in_app} onClick={() => select(m)}>
                        <CheckCircle2 size={14} /> {busy === `sel-${m.id}` ? "Saving…" : "Select"}
                      </button>
                    </td>
                  </tr>
                  {open === m.id && (
                    <tr>
                      <td colSpan={7}>
                        <p>{m.purpose}</p>
                        <p><strong>Commercial use:</strong> {m.license.commercial_use}. <strong>Size:</strong> {m.approx_size}. <strong>Context:</strong> {m.context_length}.</p>
                        <p><strong>Limitations:</strong> {m.limitations.join(" ")}</p>
                        <p><strong>Setup:</strong> {m.setup.join(" ")}</p>
                        {m.repository_url && <p><a href={m.repository_url} target="_blank" rel="noreferrer noopener">Official repository</a>{m.license.url && <> · <a href={m.license.url} target="_blank" rel="noreferrer noopener">Licence source</a></>}</p>}
                        {recs[m.id] && <p><strong>Ranking method:</strong> {recs[m.id].method} Not measured: {recs[m.id].not_measured.join("; ")}.</p>}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
