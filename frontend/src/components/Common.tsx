import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  Accessibility,
  AlertCircle,
  Check,
  CheckCheck,
  ChevronRight,
  CircleHelp,
  Code2,
  Gauge,
  Loader2,
  ShieldCheck,
  X,
} from "lucide-react";
import type { Pillar, Severity, Tools } from "../types";
import { labels, useApi } from "../lib";

export function PillarIcon({
  pillar,
  size = 18,
}: {
  pillar: Pillar;
  size?: number;
}) {
  const Icon = {
    functionality: Code2,
    security: ShieldCheck,
    performance: Gauge,
    accessibility: Accessibility,
  }[pillar];
  return <Icon size={size} strokeWidth={1.7} />;
}
export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`severity severity-${severity.toLowerCase()}`}>
      <span />
      {severity}
    </span>
  );
}
export function VerifiedBadge({ status }: { status: "Verified" | "Possible" }) {
  return (
    <span
      className={`verification ${status === "Verified" ? "is-verified" : ""}`}
    >
      {status === "Verified" ? (
        <CheckCheck size={13} />
      ) : (
        <CircleHelp size={12} />
      )}{" "}
      {status}
    </span>
  );
}
export function Loading({
  message = "Loading your workspace…",
}: {
  message?: string;
}) {
  return (
    <div className="state-panel">
      <Loader2 size={26} className="animate-spin" />
      <p>{message}</p>
    </div>
  );
}
export function ErrorPanel({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="state-panel error-panel">
      <AlertCircle size={30} />
      <h2>Something needs a second look</h2>
      <p>{message}</p>
      {retry && (
        <button className="btn btn-primary" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function Empty({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div className="state-panel empty-panel">
      <div className="empty-icon">
        <ShieldCheck size={27} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {children}
    </div>
  );
}

export function Modal({
  title,
  close,
  children,
  drawer = false,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
  drawer?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null,
      root = document.getElementById("app-root");
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (root) root.inert = true;
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
      if (event.key === "Tab") {
        const nodes = ref.current?.querySelectorAll<HTMLElement>(
          'button,a[href],input,select,textarea,[tabindex="0"]',
        );
        if (!nodes?.length) return;
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", keyboard);
    return () => {
      document.removeEventListener("keydown", keyboard);
      document.body.style.overflow = overflow;
      if (root) root.inert = false;
      previous?.focus();
    };
  }, [close]);
  return createPortal(
    <div
      className={`modal-backdrop ${drawer ? "drawer-backdrop" : ""}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={drawer ? "detail-drawer" : "modal-panel"}
      >
        <div className="modal-head">
          <span>{title}</span>
          <button
            className="icon-button"
            onClick={close}
            aria-label="Close dialog"
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
export function SystemStatus({ close }: { close: () => void }) {
  const { data, error, loading } = useApi<Tools>("/tools");
  return (
    <Modal title="Your local testing engine" close={close}>
      <div className="modal-content">
        <div className="section-kicker">OPEN SOURCE. NO CLOUD FALLBACK.</div>
        <h2>Real tools. Honest coverage.</h2>
        <p className="muted">
          Unavailable tools are clearly skipped in reports. Models and evidence
          stay on this deployment.
        </p>
        {loading ? (
          <Loading message="Checking scanner availability…" />
        ) : error ? (
          <ErrorPanel message={error} />
        ) : (
          <div className="tool-status-list">
            {data?.tools.map((tool) => (
              <div key={tool.name}>
                <div
                  className={`tool-status-icon ${tool.available ? "available" : ""}`}
                >
                  {tool.available ? (
                    <Check size={16} />
                  ) : (
                    <AlertCircle size={16} />
                  )}
                </div>
                <div>
                  <strong>{tool.name}</strong>
                  <span>
                    {tool.detail} · {tool.license}
                  </span>
                </div>
                <span
                  className={tool.available ? "text-forest" : "text-amber-700"}
                >
                  {tool.available ? "Ready" : "Unavailable"}
                </span>
              </div>
            ))}
          </div>
        )}
        <a className="text-link" href="/docs" target="_blank" rel="noreferrer">
          Explore the API documentation <ChevronRight size={14} />
        </a>
      </div>
    </Modal>
  );
}
export function PillarLabel({ pillar }: { pillar: Pillar }) {
  return (
    <span className="pillar-label">
      <PillarIcon pillar={pillar} size={14} />
      {labels[pillar]}
    </span>
  );
}
