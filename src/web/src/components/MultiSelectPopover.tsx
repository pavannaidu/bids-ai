import { useState } from "react";
import { C, F, shadow } from "../theme";
import { useDismiss } from "../hooks";

interface Props {
  // Button label shown when nothing/one/many selected.
  label: string;
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
  // Text of the reset row at the top (e.g. "All manufacturers"). Omit to hide.
  resetLabel?: string;
  width?: number;
  align?: "left" | "right";
  // Render the current selection as brand-tint chips inside the button (used by
  // the Matrix owning-teams cell); otherwise just show `label` text.
  renderChips?: boolean;
}

// Shared multi-select dropdown: manufacturer filter (Line items / Match) and
// owning-teams editor (Matrix). Multi-select with an optional reset row. Closes
// on outside click / Escape.
export default function MultiSelectPopover({
  label, options, selected, onChange, disabled, resetLabel, width = 210, align = "right", renderChips,
}: Props) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss<HTMLSpanElement>(open, () => setOpen(false));

  const toggle = (name: string) => {
    onChange(selected.includes(name) ? selected.filter((s) => s !== name) : [...selected, name]);
  };

  return (
    <span ref={ref} style={{ position: "relative", display: "inline-flex", flex: "none" }}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 6, minWidth: 150, maxWidth: 260,
          background: "#fff", border: `1px solid ${C.rule}`, color: C.ink,
          borderRadius: 6, padding: "5px 9px", fontSize: 12, cursor: disabled ? "default" : "pointer",
          opacity: disabled ? 0.6 : 1,
        }}
      >
        {renderChips && selected.length ? (
          <span style={{ display: "flex", gap: 4, flexWrap: "wrap", minWidth: 0 }}>
            {selected.map((s) => (
              <span key={s} style={{
                fontSize: 10.5, fontWeight: 600, background: C.accentSoft, color: C.accentDeep,
                borderRadius: 999, padding: "2px 7px", whiteSpace: "nowrap",
              }}>{s}</span>
            ))}
          </span>
        ) : (
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
        )}
        <span style={{ marginLeft: "auto", fontSize: 8, color: C.inkFaint, flex: "none" }}>▼</span>
      </button>
      {open && (
        <span style={{
          position: "absolute", top: 34, [align]: 0, zIndex: 40, width,
          background: "#fff", border: `1px solid ${C.rule}`, borderRadius: 8,
          boxShadow: shadow.popover, padding: 5, display: "flex", flexDirection: "column",
          maxHeight: 280, overflow: "auto",
        }}>
          {resetLabel && (
            <button
              type="button"
              onClick={() => onChange([])}
              style={{
                textAlign: "left", background: "none", border: "none",
                borderBottom: `1px solid ${C.wash}`, borderRadius: 5, padding: "6px 8px",
                fontSize: 11.5, color: C.accentDeep, cursor: "pointer", marginBottom: 3,
              }}
            >{resetLabel}</button>
          )}
          {options.map((name) => (
            <label key={name} style={{
              display: "flex", alignItems: "center", gap: 8, padding: "6px 8px",
              borderRadius: 5, cursor: "pointer", fontSize: 12, fontFamily: F.sans,
            }}>
              <input
                type="checkbox"
                checked={selected.includes(name)}
                onChange={() => toggle(name)}
                style={{ margin: 0, accentColor: C.accent }}
              />
              {name}
            </label>
          ))}
        </span>
      )}
    </span>
  );
}
