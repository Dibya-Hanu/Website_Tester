import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  Clock3,
  Globe2,
  Plus,
  RefreshCw,
  Search,
} from "lucide-react";
import type { Job } from "../types";
import { date, hostname, useApi } from "../lib";
import { Empty, ErrorPanel, Loading } from "../components/Common";

export default function History({
  reportsOnly = false,
}: {
  reportsOnly?: boolean;
}) {
  const { data, error, loading, reload } = useApi<{ jobs: Job[] }>(
      "/jobs?limit=100",
    ),
    [query, setQuery] = useState(""),
    [status, setStatus] = useState("");
  const jobs = (data?.jobs || []).filter(
    (job) =>
      (!reportsOnly || job.status === "completed") &&
      (!status || job.status === status) &&
      job.url.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="page history-page">
      <div className="history-heading">
        <div>
          <div className="section-kicker">YOUR TESTING WORKSPACE</div>
          <h1>{reportsOnly ? "Your reports" : "Test history"}</h1>
          <p>
            {reportsOnly
              ? "One place for every insight, every issue, and every next step."
              : "A clear record of what ran, what finished, and what needs another look."}
          </p>
        </div>
        <Link to="/" className="btn btn-primary">
          <Plus size={15} /> New test
        </Link>
      </div>
      <section className="panel history-panel">
        <div className="history-toolbar">
          <div className="search-control">
            <Search size={16} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search past reports"
              placeholder="Search by website…"
            />
          </div>
          <div>
            {!reportsOnly && (
              <select
                aria-label="Filter test status"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="">All statuses</option>
                {["completed", "running", "queued", "failed", "cancelled"].map(
                  (s) => (
                    <option key={s}>{s}</option>
                  ),
                )}
              </select>
            )}
            <button
              className="icon-button"
              onClick={reload}
              aria-label="Refresh history"
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
        {loading ? (
          <Loading />
        ) : error ? (
          <ErrorPanel message={error} retry={reload} />
        ) : jobs.length ? (
          <div className="table-scroll">
            <table className="history-table">
              <thead>
                <tr>
                  <th>Website</th>
                  <th>Tested</th>
                  <th>Status</th>
                  <th>Overall score</th>
                  <th>Findings</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td>
                      <Link
                        to={
                          job.status === "completed"
                            ? `/reports/${job.id}`
                            : `/tests/${job.id}`
                        }
                        className="history-site"
                      >
                        <span className="site-avatar">
                          <Globe2 size={18} />
                        </span>
                        <span>
                          <strong>{hostname(job.url)}</strong>
                          <small>
                            {job.url}
                            {job.sample ? " · Real sample run" : ""}
                          </small>
                        </span>
                      </Link>
                    </td>
                    <td>{date(job.created_at)}</td>
                    <td>
                      <span className={`status-badge status-${job.status}`}>
                        {job.status === "completed" && job.partial
                          ? "Partial report"
                          : job.status}
                      </span>
                    </td>
                    <td>
                      <span className="history-score">
                        {job.overall_score ?? "—"}
                      </span>
                      {job.overall_score !== undefined &&
                        job.overall_score !== null && <small> / 100</small>}
                    </td>
                    <td>{job.issue_count ?? "—"}</td>
                    <td>
                      <Link
                        aria-label={`Open test of ${job.url}`}
                        className="table-arrow"
                        to={
                          job.status === "completed"
                            ? `/reports/${job.id}`
                            : `/tests/${job.id}`
                        }
                      >
                        <ArrowUpRight size={16} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title={
              query || status
                ? "No tests match those filters"
                : "A fresh start for better websites"
            }
            description="Submit a website URL and your evidence-based report will appear here."
          >
            <Link to="/" className="btn btn-primary">
              Start your first test <ArrowRight size={15} />
            </Link>
          </Empty>
        )}
        <div className="history-footer">
          <span>
            <Clock3 size={12} /> Persistent reports stored locally
          </span>
          <span>
            {jobs.length} {reportsOnly ? "reports" : "tests"}
          </span>
        </div>
      </section>
    </div>
  );
}
