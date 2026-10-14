import { useCallback, useEffect, useState } from "react";
import type { Pillar, Severity } from "./types";

export const pillars: Pillar[] = [
  "functionality",
  "security",
  "performance",
  "accessibility",
];
export const labels: Record<Pillar, string> = {
  functionality: "Functionality",
  security: "Security",
  performance: "Performance",
  accessibility: "UX & Accessibility",
};
export const severities: Severity[] = [
  "Critical",
  "High",
  "Medium",
  "Low",
  "Info",
];
export const severityColors: Record<Severity, string> = {
  Critical: "#a34453",
  High: "#d66d62",
  Medium: "#d6a955",
  Low: "#83a6b7",
  Info: "#c5cecb",
};
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const error = await response.json();
      message =
        typeof error.detail === "string"
          ? error.detail
          : Array.isArray(error.detail)
            ? error.detail.map((x: { msg: string }) => x.msg).join("; ")
            : message;
    } catch {
      /* Keep status if no JSON. */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
export function useApi<T>(path: string) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((x) => x + 1), []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api<T>(path)
      .then((value) => {
        if (active) setData(value);
      })
      .catch((err: Error) => {
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [path, revision]);
  return { data, error, loading, reload };
}
export function date(value: string, full = false) {
  return new Date(value).toLocaleString(
    undefined,
    full
      ? {
          month: "short",
          day: "numeric",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        }
      : { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" },
  );
}
export function hostname(url: string) {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}
export function canonicalOrigin(url: string) {
  try {
    const u = new URL(url);
    return `${u.protocol}//${u.hostname.toLowerCase()}:${u.port || (u.protocol === "https:" ? "443" : "80")}`;
  } catch {
    return "";
  }
}
export function healthLabel(score: number | null) {
  return score === null
    ? "Not assessed"
    : score >= 80
      ? "Looking good"
      : score >= 50
        ? "Needs attention"
        : "At risk";
}
export function number(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
export function elapsed(seconds: number) {
  return seconds < 60
    ? `${Math.round(seconds)}s`
    : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}
