import { ArrowUpRight } from "lucide-react";
import type { Pillar, PillarScore } from "../types";
import { healthLabel, labels } from "../lib";
import { PillarIcon } from "./Common";

export function ScoreRing({
  score,
  size = 112,
}: {
  score: number | null;
  size?: number;
}) {
  const circumference = 2 * Math.PI * 43;
  return (
    <div
      className={`score-ring ${score === null ? "unassessed" : ""}`}
      style={{ width: size, height: size }}
    >
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle
          cx="50"
          cy="50"
          r="43"
          fill="none"
          stroke="currentColor"
          strokeOpacity=".12"
          strokeWidth="5"
        />
        <circle
          cx="50"
          cy="50"
          r="43"
          fill="none"
          stroke="currentColor"
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={`${((score ?? 0) / 100) * circumference} ${circumference}`}
          transform="rotate(-90 50 50)"
        />
      </svg>
      <div>
        <strong>{score ?? "—"}</strong>
        <span>{score === null ? "NOT ASSESSED" : "OUT OF 100"}</span>
      </div>
    </div>
  );
}
export default function ScoreCard({
  pillar,
  value,
  onClick,
}: {
  pillar: Pillar;
  value: PillarScore;
  onClick: () => void;
}) {
  return (
    <button className={`score-card score-card-${pillar}`} onClick={onClick}>
      <div className="score-card-top">
        <span className="pillar-icon">
          <PillarIcon pillar={pillar} />
        </span>
        <ArrowUpRight size={15} className="muted" />
      </div>
      <h3>{labels[pillar]}</h3>
      <div className="score-card-value">
        <strong>{value.score ?? "—"}</strong>
        <span>/ 100</span>
      </div>
      <div className="score-card-meta">
        <span
          className={
            value.score !== null && value.score >= 80
              ? "score-good"
              : value.score === null
                ? ""
                : "score-attention"
          }
        >
          <i />
          {healthLabel(value.score)}
        </span>
        <span>
          {value.issues} {value.issues === 1 ? "issue" : "issues"}
        </span>
      </div>
      <div className="coverage-track">
        <span style={{ width: `${value.coverage}%` }} />
      </div>
      <span className="score-card-coverage">
        {value.coverage}% check coverage · {value.status.replace("_", " ")}
      </span>
    </button>
  );
}
