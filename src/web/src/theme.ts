// Central design tokens for the Reviewer Workbench UI. These mirror the CSS
// custom properties in the existing app's index.css (:root) 1:1 — the redesign
// deliberately keeps the app's existing green/Georgia palette. Kept here as a
// single JS source of truth so components reference tokens, not scattered
// literals (per the design handoff).
export const C = {
  paper: "#f5f7f6",
  paperRaise: "#ffffff",
  ink: "#14211e",
  inkSoft: "#4b5c57",
  inkFaint: "#7e8c87",
  inkDisabled: "#a8b3af",
  accent: "#2f6f62",
  accentDeep: "#1f4d43",
  accentSoft: "#dceae6",
  accentLine: "#bcd6cf",
  review: "#c97c2e",
  reviewDeep: "#8a5620",
  reviewSoft: "#f7e6d2",
  alert: "#b5533c",
  alertSoft: "#f5e1dc",
  alertLine: "#e3c2b8",
  rule: "#d8dfdc",
  wash: "#eef2f0",
} as const;

export const F = {
  serif: 'Georgia, "Iowan Old Style", "Palatino Linotype", serif',
  sans: '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
  mono: 'ui-monospace, "SF Mono", Menlo, monospace',
} as const;

export const shadow = {
  popover: "0 8px 22px rgba(20,33,30,.16)",
  userMenu: "0 10px 26px rgba(20,33,30,.22)",
  tooltip: "0 6px 18px rgba(20,33,30,.14)",
  paper: "0 1px 3px rgba(20,33,30,.08)",
} as const;

// Common button styles reused across screens.
export const primaryBtn: React.CSSProperties = {
  background: C.accent,
  color: "#fff",
  border: "none",
  borderRadius: 6,
  padding: "7px 14px",
  fontSize: 12.5,
  fontWeight: 600,
  cursor: "pointer",
};

export const ghostBtn: React.CSSProperties = {
  background: "#fff",
  border: `1px solid ${C.rule}`,
  color: C.inkSoft,
  borderRadius: 6,
  padding: "5px 11px",
  fontSize: 11.5,
  cursor: "pointer",
};

export const eyebrow: React.CSSProperties = {
  fontFamily: F.mono,
  fontSize: 9.5,
  letterSpacing: ".05em",
  textTransform: "uppercase",
  color: C.inkFaint,
};
