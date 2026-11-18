import { useState } from "react";
import { C, F, shadow } from "../theme";
import { useDismiss } from "../hooks";
import type { MatchMode } from "../types";

interface Props {
  disabled?: boolean;
  onRematch: (mode: MatchMode) => void;
}

// "Re-run matching ▾" popover: re-match unresolved only (keeps picks) vs
// re-match all (destructive, discards picks).
export default function RematchMenu({ disabled, onRematch }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss<HTMLSpanElement>(open, () => setOpen(false));

  const pick = (mode: MatchMode) => { setOpen(false); onRematch(mode); };

  return (
    <span ref={ref} style={{ position: "relative", display: "inline-flex", flex: "none" }}>
      <button
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        style={{
          background: "#fff", border: `1px solid ${C.rule}`, color: C.inkSoft, borderRadius: 6,
          padding: "6px 11px", fontSize: 12, cursor: disabled ? "default" : "pointer",
          display: "inline-flex", alignItems: "center", gap: 6, whiteSpace: "nowrap", opacity: disabled ? 0.6 : 1,
        }}
      >Re-run matching <span style={{ fontSize: 8, color: C.inkFaint }}>▾</span></button>
      {open && (
        <span style={{ position: "absolute", top: 34, right: 0, zIndex: 40, width: 290, background: "#fff", border: `1px solid ${C.rule}`, borderRadius: 8, boxShadow: shadow.popover, padding: 5, display: "flex", flexDirection: "column" }}>
          <button onClick={() => pick("unmatched")} style={{ textAlign: "left", background: "none", border: "none", borderRadius: 6, padding: "9px 10px", cursor: "pointer", color: C.ink, fontFamily: F.sans }}>
            <span style={{ display: "block", fontSize: 12.5, fontWeight: 600 }}>Re-match unresolved only</span>
            <span style={{ display: "block", fontSize: 11.5, color: C.inkFaint, marginTop: 2, lineHeight: 1.4 }}>Keeps your accepted / no-catalog-match picks.</span>
          </button>
          <button onClick={() => pick("all")} style={{ textAlign: "left", background: "none", border: "none", borderRadius: 6, padding: "9px 10px", cursor: "pointer", color: C.alert, fontFamily: F.sans }}>
            <span style={{ display: "block", fontSize: 12.5, fontWeight: 600 }}>Re-match all (discard my picks)</span>
            <span style={{ display: "block", fontSize: 11.5, color: C.inkFaint, marginTop: 2, lineHeight: 1.4 }}>Clears every candidate and selection, re-matches from scratch.</span>
          </button>
        </span>
      )}
    </span>
  );
}
