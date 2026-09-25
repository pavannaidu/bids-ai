// Inline SVG icons matching the design handoff (18px default, 1.6 stroke,
// currentColor). Sizes are overridable per use.
type P = { size?: number };

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 20 20",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
});

export const IconWorkbench = ({ size = 18 }: P) => (
  <svg {...base(size)}>
    <path d="M3 15.5 7.5 11l2.5 2.5L16.5 7" />
    <path d="M12.5 7h4v4" />
  </svg>
);

export const IconAllBids = ({ size = 18 }: P) => (
  <svg {...base(size)}>
    <rect x="3" y="4" width="14" height="4" rx="1" />
    <rect x="3" y="12" width="14" height="4" rx="1" />
  </svg>
);

export const IconMatrix = ({ size = 18 }: P) => (
  <svg {...base(size)}>
    <rect x="3" y="3" width="14" height="14" rx="1.5" />
    <path d="M3 8.5h14M3 13h14M8.5 3v14" />
  </svg>
);

export const IconPlus = ({ size = 16 }: P) => (
  <svg {...base(size)} strokeWidth={1.9}>
    <path d="M10 4v12M4 10h12" />
  </svg>
);

export const IconDoc = ({ size = 18 }: P) => (
  <svg {...base(size)} strokeWidth={1.6} strokeLinecap="round">
    <path d="M12 2.5H5.5A1.5 1.5 0 0 0 4 4v12a1.5 1.5 0 0 0 1.5 1.5h9A1.5 1.5 0 0 0 16 16V6.5z" />
    <path d="M12 2.5V6.5H16" />
  </svg>
);

export const IconTrash = ({ size = 15 }: P) => (
  <svg {...base(size)}>
    <path d="M4 6h12M8 6V4.5A1 1 0 0 1 9 3.5h2a1 1 0 0 1 1 1V6M6.5 6l.6 9a1 1 0 0 0 1 1h3.8a1 1 0 0 0 1-1l.6-9M9 9v5M11 9v5" />
  </svg>
);

export const IconInfo = ({ size = 14 }: P) => (
  <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden>
    <circle cx="10" cy="10" r="7.2" />
    <path d="M10 9v4.5" strokeLinecap="round" />
    <circle cx="10" cy="6.6" r=".9" fill="currentColor" stroke="none" />
  </svg>
);
