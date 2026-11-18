import { useMemo, useState } from "react";
import { deleteMatrixTerm, upsertMatrixTerm } from "../api";
import { C, F, ghostBtn } from "../theme";
import MultiSelectPopover from "./MultiSelectPopover";
import type { MatrixTerm, ResponsibilityMatrix, RiskLevel } from "../types";

interface Props {
  matrix: ResponsibilityMatrix | null;
  onMatrixChange: (matrix: ResponsibilityMatrix) => void;
}

const GRID = "200px minmax(260px,1fr) 200px 90px 78px";
const RISK_COLOR: Record<RiskLevel, string> = { high: C.alert, medium: C.reviewDeep, low: C.inkSoft };

// Editable BRD responsibility matrix. The original 8 boolean team columns (which
// clipped horizontally) are replaced by a single multi-select chip-list popover
// per term. Every edit upserts the term and returns the full merged matrix.
export default function MatrixScreen({ matrix, onMatrixChange }: Props) {
  const [savingLabel, setSavingLabel] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    const terms = matrix?.terms ?? [];
    const filtered = q ? terms.filter((t) => `${t.term_label} ${t.description}`.toLowerCase().includes(q.toLowerCase())) : terms;
    return [...filtered].sort((a, b) => a.term_label.localeCompare(b.term_label));
  }, [matrix, q]);

  if (!matrix) {
    return <div style={{ padding: 20, color: C.inkFaint, fontSize: 12.5 }}>Loading responsibility matrix…</div>;
  }

  const runWrite = async (label: string, fn: () => Promise<ResponsibilityMatrix>) => {
    setSavingLabel(label);
    setError(null);
    try { onMatrixChange(await fn()); }
    catch (e) { setError(String(e)); }
    finally { setSavingLabel(null); }
  };

  const save = (term: MatrixTerm, changes: Partial<MatrixTerm>) => {
    const next = { ...term, ...changes };
    return runWrite(term.term_label, () => upsertMatrixTerm({
      term_label: next.term_label, owning_teams: next.owning_teams,
      default_risk: next.default_risk, description: next.description, is_trigger: next.is_trigger,
    }));
  };

  const addTerm = () => {
    const label = window.prompt("New term name:");
    if (!label?.trim()) return;
    runWrite(label, () => upsertMatrixTerm({ term_label: label.trim(), owning_teams: [], default_risk: "medium", description: "", is_trigger: false }));
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
        <span style={{ fontSize: 11.5, color: C.inkFaint }}>{matrix.terms.length} terms · {matrix.teams.length} owning teams · edits change how future bids route</span>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter terms…" style={{ marginLeft: "auto", width: 220, padding: "6px 9px", border: `1px solid ${C.rule}`, borderRadius: 6, fontSize: 12, background: "#fff" }} />
        <button style={ghostBtn} onClick={addTerm}>+ Add term</button>
      </div>

      {error && <div style={{ background: C.alertSoft, border: `1px solid ${C.alertLine}`, color: C.alert, borderRadius: 8, padding: "8px 12px", marginBottom: 10, fontSize: 12 }}>{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: GRID, minWidth: 900, padding: "7px 12px", background: C.wash, border: `1px solid ${C.rule}`, borderRadius: "10px 10px 0 0", fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint }}>
        <span>Term</span><span>Description (used by the classifier)</span><span>Owning team(s)</span><span>Default risk</span><span style={{ textAlign: "center" }}>Material trigger</span>
      </div>

      {rows.map((t) => {
        const saving = savingLabel === t.term_label;
        return (
          <div key={t.term_label} style={{ display: "grid", gridTemplateColumns: GRID, minWidth: 900, alignItems: "center", padding: "8px 12px", background: "#fff", border: `1px solid ${C.rule}`, borderTop: "none", opacity: saving ? 0.6 : 1 }}>
            <span style={{ fontSize: 12.5, fontWeight: 600, paddingRight: 12 }}>{t.term_label}</span>
            <input
              defaultValue={t.description}
              onBlur={(e) => { if (e.target.value !== t.description) save(t, { description: e.target.value }); }}
              style={{ fontSize: 11.5, color: C.inkSoft, lineHeight: 1.45, padding: "5px 7px", border: "1px solid transparent", borderRadius: 5, background: "transparent", marginRight: 14, fontFamily: F.sans }}
            />
            <span style={{ paddingRight: 10 }}>
              <MultiSelectPopover
                label={t.owning_teams.length ? `${t.owning_teams.length} team(s)` : "— none —"}
                options={matrix.teams}
                selected={t.owning_teams}
                onChange={(next) => save(t, { owning_teams: next })}
                align="left"
                renderChips
              />
            </span>
            <span style={{ paddingRight: 10 }}>
              <select
                value={t.default_risk}
                onChange={(e) => save(t, { default_risk: e.target.value as RiskLevel })}
                style={{ width: "100%", padding: "5px 7px", border: `1px solid ${C.rule}`, borderRadius: 5, fontSize: 12, background: "#fff", color: RISK_COLOR[t.default_risk], fontWeight: 600, cursor: "pointer", fontFamily: F.sans }}
              >
                <option value="high">high</option>
                <option value="medium">medium</option>
                <option value="low">low</option>
              </select>
            </span>
            <span style={{ display: "flex", justifyContent: "center" }}>
              <input type="checkbox" checked={t.is_trigger} onChange={(e) => save(t, { is_trigger: e.target.checked })} title="Material trigger" style={{ margin: 0, width: 15, height: 15, accentColor: C.accent, cursor: "pointer" }} />
            </span>
          </div>
        );
      })}
    </div>
  );
}
