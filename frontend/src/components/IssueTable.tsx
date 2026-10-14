import { useEffect, useState } from "react";
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Filter,
  Search,
} from "lucide-react";
import type { Finding, Pillar, Severity } from "../types";
import { labels, pillars, severities } from "../lib";
import { Empty, PillarLabel, SeverityBadge, VerifiedBadge } from "./Common";

export default function IssueTable({
  findings,
  onSelect,
  initialPillar = "",
  initialSeverity = "",
  compact = false,
}: {
  findings: Finding[];
  onSelect: (issue: Finding) => void;
  initialPillar?: Pillar | "";
  initialSeverity?: Severity | "";
  compact?: boolean;
}) {
  const [pillar, setPillar] = useState<Pillar | "">(initialPillar),
    [severity, setSeverity] = useState<Severity | "">(initialSeverity),
    [verification, setVerification] = useState(""),
    [search, setSearch] = useState(""),
    [page, setPage] = useState(0);
  useEffect(() => {
    setPillar(initialPillar);
    setSeverity(initialSeverity);
  }, [initialPillar, initialSeverity]);
  useEffect(() => setPage(0), [pillar, severity, verification, search]);
  const filtered = findings.filter(
    (f) =>
      (!pillar || f.pillar === pillar) &&
      (!severity || f.severity === severity) &&
      (!verification || f.status === verification) &&
      `${f.title} ${f.location.url} ${f.location.selector ?? ""} ${f.location.header ?? ""}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const pageSize = compact ? 5 : 10,
    rows = compact
      ? filtered.slice(0, 5)
      : filtered.slice(page * pageSize, (page + 1) * pageSize);
  const clear = () => {
    setPillar("");
    setSeverity("");
    setVerification("");
    setSearch("");
  };
  return (
    <div className="issue-table-wrap">
      {!compact && (
        <div className="filter-bar">
          <div className="search-control">
            <Search size={15} />
            <input
              aria-label="Search findings"
              placeholder="Search issues or locations…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="filter-controls">
            <Filter size={14} />
            <select
              aria-label="Filter by pillar"
              value={pillar}
              onChange={(e) => setPillar(e.target.value as Pillar | "")}
            >
              <option value="">All pillars</option>
              {pillars.map((p) => (
                <option key={p} value={p}>
                  {labels[p]}
                </option>
              ))}
            </select>
            <select
              aria-label="Filter by severity"
              value={severity}
              onChange={(e) => setSeverity(e.target.value as Severity | "")}
            >
              <option value="">All severities</option>
              {severities.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <select
              aria-label="Filter by verification"
              value={verification}
              onChange={(e) => setVerification(e.target.value)}
            >
              <option value="">Any status</option>
              <option>Verified</option>
              <option>Possible</option>
            </select>
          </div>
        </div>
      )}
      <div className="table-scroll">
        <table className="issues-table">
          <thead>
            <tr>
              <th>Issue</th>
              <th>Pillar</th>
              <th>Severity</th>
              <th>Verification</th>
              <th>
                <span className="sr-only">Details</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.id}>
                <td>
                  <button className="issue-title" onClick={() => onSelect(f)}>
                    {f.title}
                  </button>
                  <span className="issue-url">
                    {f.location.header
                      ? `Header: ${f.location.header}`
                      : f.location.selector || f.location.url}
                  </span>
                </td>
                <td>
                  <PillarLabel pillar={f.pillar} />
                </td>
                <td>
                  <SeverityBadge severity={f.severity} />
                </td>
                <td>
                  <VerifiedBadge status={f.status} />
                </td>
                <td>
                  <button
                    className="table-arrow"
                    aria-label={`View ${f.title}`}
                    onClick={() => onSelect(f)}
                  >
                    <ArrowRight size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && (
        <Empty
          title={
            findings.length ? "No matching findings" : "No issues observed"
          }
          description={
            findings.length
              ? "Try broadening your filters."
              : "No findings were detected by the completed checks. Review coverage before treating this as a pass."
          }
        >
          {findings.length > 0 && (
            <button className="btn btn-secondary" onClick={clear}>
              Clear filters
            </button>
          )}
        </Empty>
      )}
      {!compact && (
        <div className="table-pagination">
          <span>
            Showing{" "}
            {filtered.length
              ? Math.min(page * pageSize + 1, filtered.length)
              : 0}
            –{Math.min((page + 1) * pageSize, filtered.length)} of{" "}
            {filtered.length} findings
          </span>
          <div>
            <button
              disabled={page === 0}
              className="icon-button"
              aria-label="Previous page"
              onClick={() => setPage((p) => p - 1)}
            >
              <ChevronLeft size={16} />
            </button>
            <span>
              {page + 1} / {Math.max(1, Math.ceil(filtered.length / pageSize))}
            </span>
            <button
              disabled={(page + 1) * pageSize >= filtered.length}
              className="icon-button"
              aria-label="Next page"
              onClick={() => setPage((p) => p + 1)}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
