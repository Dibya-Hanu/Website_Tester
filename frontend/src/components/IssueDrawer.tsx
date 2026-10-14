import { useCallback, useState } from "react";
import { Check, Copy, FileText, MapPin, Sparkles, Wrench } from "lucide-react";
import type { Finding } from "../types";
import { Modal, PillarLabel, SeverityBadge, VerifiedBadge } from "./Common";

export default function IssueDrawer({
  issue,
  reportId,
  close,
}: {
  issue: Finding;
  reportId: string;
  close: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(issue.suggested_fix);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [issue.suggested_fix]);
  return (
    <Modal title="Finding details" close={close} drawer>
      <div className="drawer-content">
        <div className="drawer-badges">
          <SeverityBadge severity={issue.severity} />
          <VerifiedBadge status={issue.status} />
        </div>
        <h2>{issue.title}</h2>
        <PillarLabel pillar={issue.pillar} />
        <section className="location-box">
          <h4>
            <MapPin size={14} /> Exact location
          </h4>
          <code>{issue.location.url}</code>
          {issue.location.selector && (
            <>
              <span>Element</span>
              <code>{issue.location.selector}</code>
            </>
          )}
          {issue.location.header && (
            <>
              <span>Response header</span>
              <code>{issue.location.header}</code>
            </>
          )}
        </section>
        <section>
          <h4>What this means</h4>
          <p>{issue.explanation}</p>
        </section>
        <section className="fix-box">
          <div className="flex justify-between items-center">
            <h4>
              <Wrench size={15} /> Suggested fix
            </h4>
            <button
              className="icon-button"
              onClick={copy}
              aria-label="Copy suggested fix"
            >
              {copied ? <Check size={16} /> : <Copy size={15} />}
            </button>
          </div>
          <p>{issue.suggested_fix}</p>
        </section>
        <section>
          <h4>
            <Check size={15} /> Verification
          </h4>
          <p>{issue.verification_note}</p>
        </section>
        <section>
          <h4>
            <FileText size={15} /> Supporting evidence
          </h4>
          {issue.evidence.map((e, index) => (
            <div key={index} className="evidence-item">
              {e.file ? (
                <figure>
                  <img
                    src={`/api/jobs/${reportId}/evidence/${encodeURIComponent(e.file)}`}
                    alt={e.detail || "Screenshot evidence"}
                    loading="lazy"
                  />
                  <figcaption>{e.detail}</figcaption>
                </figure>
              ) : (
                <pre>{e.detail}</pre>
              )}
            </div>
          ))}
        </section>
        <section>
          <h4>Provenance</h4>
          <div className="source-chips">
            {issue.sources.map((source) => (
              <span key={source}>{source}</span>
            ))}
          </div>
          {issue.ai_assisted && (
            <p className="ai-note">
              <Sparkles size={13} /> Explanation assisted by a local open-source
              model.
            </p>
          )}
          <p className="issue-id">Finding ID: {issue.id}</p>
        </section>
      </div>
    </Modal>
  );
}
