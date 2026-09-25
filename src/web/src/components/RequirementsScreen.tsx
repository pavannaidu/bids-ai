import { useState } from "react";
import { C, F, ghostBtn } from "../theme";
import { IconTrash } from "./icons";
import type { Bid, RequirementItem, ResponsibilityMatrix, ReviewStatus, RiskLevel } from "../types";
import type { RequirementPatch } from "../api";

interface Props {
  bid: Bid;
  matrix: ResponsibilityMatrix | null;
  loading: boolean;
  scope: string; // reviewer-queue team filter ("all" or a team)
  onUpdate: (requirementId: string, fields: RequirementPatch) => Promise<void> | void;
  onAdd: () => void;
  onDelete: (requirementId: string) => void;
  onReextract: () => void;
  materialOpen: boolean;
  onToggleMaterial: () => void;
}

type Filter = "all" | "pending" | "high" | "approved";

const RISK_DOT: Record<string, string> = { high: C.alert, medium: C.review, low: C.rule, "": C.rule };

function riskPill(risk: RiskLevel | ""): React.CSSProperties {
  const map: Record<string, { bg: string; fg: string; bd: string }> = {
    high: { bg: C.alertSoft, fg: C.alert, bd: C.alertLine },
    medium: { bg: C.reviewSoft, fg: C.reviewDeep, bd: C.review },
    low: { bg: C.wash, fg: C.inkSoft, bd: C.rule },
    "": { bg: C.wash, fg: C.inkFaint, bd: C.rule },
  };
  const c = map[risk] ?? map[""];
  return {
    fontFamily: F.mono, fontSize: 10, fontWeight: 700, textTransform: "uppercase",
    background: c.bg, color: c.fg, border: `1px solid ${c.bd}`, borderRadius: 999,
    padding: "2px 8px", justifySelf: "start", whiteSpace: "nowrap",
  };
}

function statusPill(status: ReviewStatus): { label: string; style: React.CSSProperties } {
  const approved = status === "approved";
  const label = status === "needs_changes" ? "Needs changes" : status.charAt(0).toUpperCase() + status.slice(1).replace("_", " ");
  return {
    label,
    style: {
      fontFamily: F.mono, fontSize: 10, fontWeight: 700, textTransform: "uppercase",
      background: approved ? C.accentSoft : C.wash, color: approved ? C.accentDeep : C.inkFaint,
      borderRadius: 999, padding: "2px 8px", justifySelf: "start", whiteSpace: "nowrap",
    },
  };
}

const GRID = "34px 178px minmax(200px,1fr) 130px 84px 106px";

const helpStyle: React.CSSProperties = { fontSize: 10.5, color: C.inkFaint, lineHeight: 1.45, marginTop: 5 };

export default function RequirementsScreen({ bid, matrix, loading, scope, onUpdate, onAdd, onDelete, onReextract, materialOpen, onToggleMaterial }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [noteDraft, setNoteDraft] = useState<Record<string, string>>({});

  const reqs = bid.requirements;
  const verdict = bid.review_verdict;

  // Apply reviewer-queue scope (team) then the filter chip.
  const scoped = scope === "all" ? reqs : reqs.filter((r) => r.owning_teams.includes(scope));
  const filtered = scoped.filter((r) => {
    if (filter === "pending") return r.review_status === "pending" || r.review_status === "in_review";
    if (filter === "high") return r.risk_level === "high";
    if (filter === "approved") return r.review_status === "approved";
    return true;
  });

  const approvedCount = reqs.filter((r) => r.review_status === "approved").length;
  const highN = reqs.filter((r) => r.risk_level === "high").length;
  const medN = reqs.filter((r) => r.risk_level === "medium").length;
  const lowN = reqs.filter((r) => r.risk_level === "low").length;
  const selCount = Object.values(selected).filter(Boolean).length;
  const allSelected = filtered.length > 0 && filtered.every((r) => selected[r.requirement_id]);

  const approveSelected = async () => {
    const ids = filtered.filter((r) => selected[r.requirement_id]).map((r) => r.requirement_id);
    for (const id of ids) await onUpdate(id, { review_status: "approved" });
    setSelected({});
  };

  // Whether a term label exists in the current matrix (so we can flag unmatched ones).
  const matrixHas = (label: string) => !!matrix?.terms.some((t) => t.term_label === label);

  // Reclassify to a different matrix term: re-derive owning team(s) + risk from
  // that term's BRD definition and send all three in one PATCH.
  const reclassify = async (r: RequirementItem, termLabel: string) => {
    if (!termLabel || termLabel === r.term_label) return;
    const term = matrix?.terms.find((t) => t.term_label === termLabel);
    if (!term) return;
    await onUpdate(r.requirement_id, {
      term_label: term.term_label,
      owning_teams: term.owning_teams,
      risk_level: term.default_risk,
    });
  };

  const approve = async (r: RequirementItem) => {
    const note = noteDraft[r.requirement_id];
    await onUpdate(r.requirement_id, { review_status: "approved", ...(note != null ? { note } : {}) });
    setExpanded(null);
  };

  const filterChip = (id: Filter, label: string) => {
    const on = filter === id;
    return (
      <button key={id} onClick={() => setFilter(id)} style={{
        ...ghostBtn, padding: "4px 10px",
        background: on ? C.accentDeep : "#fff", color: on ? "#fff" : C.inkSoft,
        border: `1px solid ${on ? C.accentDeep : C.rule}`,
      }}>{label}</button>
    );
  };

  const scopeNote = scope === "all"
    ? `${reqs.length} clauses · routed by the BRD responsibility matrix`
    : `${scoped.length} clauses routed to ${scope} — your queue`;

  return (
    <div style={{ overflowX: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", minWidth: 0 }}>
          <span style={{ fontFamily: F.serif, fontSize: 16, whiteSpace: "nowrap", flex: "none" }}>Requirements &amp; routing</span>
          {verdict?.material && (
            <button onClick={onToggleMaterial} style={{
              fontFamily: F.mono, fontSize: 10, fontWeight: 700, letterSpacing: ".04em", textTransform: "uppercase",
              whiteSpace: "nowrap", flex: "none", color: C.reviewDeep, background: C.reviewSoft,
              border: `1px solid ${C.review}`, borderRadius: 999, padding: "3px 9px", cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 6,
            }}>Material · needs review <span>{materialOpen ? "▴" : "▾"}</span></button>
          )}
          <span style={{ flex: "1 1 100%", fontSize: 11.5, color: C.inkFaint }}>{scopeNote}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: "auto" }}>
          <button style={{ ...ghostBtn, marginRight: 4 }} disabled={loading} onClick={onReextract} title="Re-run requirement extraction">{loading ? "Re-extracting…" : "Re-extract"}</button>
          <button style={{ ...ghostBtn, marginRight: 4 }} onClick={onAdd} title="Add a clause the extractor missed">+ Add clause</button>
          {filterChip("all", "All")}
          {filterChip("pending", "Pending")}
          {filterChip("high", "High risk")}
          {filterChip("approved", "Approved")}
        </div>
      </div>

      {materialOpen && verdict?.material && (
        <div style={{ background: C.reviewSoft, border: `1px solid ${C.review}`, borderRadius: 10, padding: "11px 13px", marginBottom: 10 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: C.reviewDeep }}>Material — needs review</span>
            {verdict.review_teams.length > 0 && (
              <span style={{ marginLeft: "auto", fontSize: 12, fontWeight: 600, color: C.reviewDeep }}>Route to: {verdict.review_teams.join(", ")}</span>
            )}
          </div>
          <div style={{ fontSize: 12, color: C.reviewDeep, marginTop: 3 }}>{verdict.summary}</div>
          {verdict.trigger_terms.length > 0 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 9 }}>
              {verdict.trigger_terms.map((t) => {
                const target = reqs.find((r) => r.term_label === t);
                return (
                  <button key={t} onClick={() => target && setExpanded(target.requirement_id)} style={{
                    background: C.review, color: "#fff", border: "none", borderRadius: 999,
                    padding: "4px 11px", fontSize: 11.5, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
                  }}>{t}</button>
                );
              })}
            </div>
          )}
          <div style={{ fontSize: 11, color: C.inkFaint, fontStyle: "italic", marginTop: 9, lineHeight: 1.45 }}>
            Triage routing per the BRD review process (trigger-clause presence) — a routing signal, distinct from the automated per-clause risk levels below.
          </div>
        </div>
      )}

      {/* Progress toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", minWidth: 900, padding: "9px 12px", background: "#fff", border: `1px solid ${C.rule}`, borderRadius: "10px 10px 0 0", borderBottom: "none" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 190 }}>
          <span style={{ fontFamily: F.mono, fontSize: 11, fontWeight: 700, color: C.ink }}>{approvedCount} / {reqs.length}</span>
          <span style={{ fontSize: 11.5, color: C.inkSoft }}>approved</span>
        </div>
        <div style={{ flex: 1, height: 6, background: C.wash, borderRadius: 999, overflow: "hidden", maxWidth: 320 }}>
          <div style={{ width: `${reqs.length ? (approvedCount / reqs.length) * 100 : 0}%`, height: "100%", background: C.accent }} />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 11.5, color: C.inkSoft }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: C.alert }} />{highN} high</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: C.review }} />{medN} medium</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: C.rule }} />{lowN} low</span>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ fontSize: 11.5, color: C.inkFaint }}>{selCount} selected</span>
          <button onClick={approveSelected} disabled={!selCount} style={{
            background: C.accent, color: "#fff", border: "none", borderRadius: 6, padding: "5px 11px",
            fontSize: 11.5, fontWeight: 600, cursor: selCount ? "pointer" : "default", opacity: selCount ? 1 : 0.5,
          }}>Approve selected</button>
        </div>
      </div>

      {/* Header row */}
      <div style={{ display: "grid", gridTemplateColumns: GRID, minWidth: 900, padding: "7px 12px", background: C.wash, border: `1px solid ${C.rule}`, fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint }}>
        <span><input type="checkbox" checked={allSelected} onChange={(e) => {
          const next = { ...selected };
          filtered.forEach((r) => { next[r.requirement_id] = e.target.checked; });
          setSelected(next);
        }} style={{ margin: 0, accentColor: C.accent }} /></span>
        <span>Term</span><span>Clause</span><span>Team</span><span>Risk</span><span>Status</span>
      </div>

      {loading && !reqs.length ? (
        <div style={{ padding: 20, background: "#fff", border: `1px solid ${C.rule}`, borderTop: "none", color: C.inkFaint, fontSize: 12.5 }}>Extracting requirements & routing…</div>
      ) : filtered.map((r) => {
        const open = expanded === r.requirement_id;
        const sp = statusPill(r.review_status);
        return (
          <div key={r.requirement_id} style={{ minWidth: 900 }}>
            <div
              onClick={() => setExpanded(open ? null : r.requirement_id)}
              style={{
                display: "grid", gridTemplateColumns: GRID, alignItems: "center", padding: "8px 12px",
                background: "#fff", border: `1px solid ${C.rule}`, borderTop: "none", cursor: "pointer",
              }}
            >
              <span><input type="checkbox" checked={!!selected[r.requirement_id]} onClick={(e) => e.stopPropagation()} onChange={(e) => setSelected((s) => ({ ...s, [r.requirement_id]: e.target.checked }))} style={{ margin: 0, accentColor: C.accent }} /></span>
              <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, paddingRight: 10 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: RISK_DOT[r.risk_level] ?? C.rule, flex: "none" }} />
                <span style={{ fontSize: 12.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.term_label}</span>
              </span>
              <span style={{ fontSize: 12.5, color: C.inkSoft, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", paddingRight: 12, visibility: open ? "hidden" : "visible" }}>{r.raw_text}</span>
              <span style={{ fontSize: 11.5, color: C.inkSoft, paddingRight: 8, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.owning_teams.join(", ") || "—"}</span>
              <span style={riskPill(r.risk_level)}>{r.risk_level || "—"}</span>
              <span style={sp.style}>{sp.label}</span>
            </div>
            {open && (
              <div style={{ padding: "2px 12px 14px 46px", background: "#fff", border: `1px solid ${C.rule}`, borderTop: "none", display: "grid", gridTemplateColumns: "minmax(280px,1fr) 300px", gap: 18, minWidth: 900 }}>
                <div>
                  {/* Reclassify the term. Picking a different matrix term re-derives
                      the owning team(s) + risk from that term's BRD definition, so the
                      Team and Risk columns update in one PATCH. */}
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint, marginBottom: 4 }}>Term</div>
                    <select
                      value={matrixHas(r.term_label) ? r.term_label : ""}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => reclassify(r, e.target.value)}
                      disabled={!matrix}
                      style={{ width: "100%", maxWidth: 320, padding: "6px 8px", border: `1px solid ${C.rule}`, borderRadius: 5, fontSize: 12.5, fontWeight: 600, background: "#fff", color: C.ink, cursor: matrix ? "pointer" : "default" }}
                    >
                      {!matrixHas(r.term_label) && <option value="">{r.term_label} (unmatched — pick a term)</option>}
                      {(matrix?.terms ?? []).map((t) => (
                        <option key={t.term_label} value={t.term_label}>{t.term_label}</option>
                      ))}
                    </select>
                    <div style={helpStyle}>Changing the term re-derives the owning team(s) and risk from the BRD matrix.</div>
                  </div>
                  <div style={{ fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint, marginBottom: 4 }}>Clause</div>
                  <textarea
                    defaultValue={r.raw_text}
                    placeholder="Paste or type the clause text…"
                    onClick={(e) => e.stopPropagation()}
                    onBlur={(e) => { if (e.target.value !== r.raw_text) onUpdate(r.requirement_id, { raw_text: e.target.value }); }}
                    rows={3}
                    style={{ width: "100%", maxWidth: "74ch", margin: "0 0 8px", padding: "7px 9px", fontFamily: F.sans, fontSize: 12.5, lineHeight: 1.55, color: C.ink, border: `1px solid ${C.rule}`, borderRadius: 5, background: "#fff", resize: "vertical" }}
                  />
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    {r.source === "ai_classified" && (
                      <span style={{ fontFamily: F.mono, fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", background: C.accentSoft, color: C.accentDeep, borderRadius: 4, padding: "2px 6px" }}>AI classified</span>
                    )}
                    <span style={{ fontSize: 11, color: C.inkFaint }}>
                      {r.source_page != null ? `Page ${r.source_page}` : "Page —"}
                      {r.confidence != null && ` · confidence ${Math.round(r.confidence * 100)}%`}
                    </span>
                  </div>
                  {r.risk_rationale && <p style={{ margin: "8px 0 0", fontSize: 11.5, color: C.inkFaint, lineHeight: 1.5 }}>{r.risk_rationale}</p>}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div>
                    <div style={{ fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint, marginBottom: 4 }}>Review note</div>
                    <input
                      type="text"
                      placeholder="Add a review note…"
                      defaultValue={r.note}
                      onChange={(e) => setNoteDraft((d) => ({ ...d, [r.requirement_id]: e.target.value }))}
                      onBlur={(e) => { if (e.target.value !== r.note) onUpdate(r.requirement_id, { note: e.target.value }); }}
                      style={{ width: "100%", padding: "6px 8px", border: `1px solid ${C.rule}`, borderRadius: 5, fontSize: 12, background: "#fff", color: C.ink }}
                    />
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button onClick={() => approve(r)} style={{ background: C.accent, color: "#fff", border: "none", borderRadius: 6, padding: "6px 12px", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>Approve</button>
                    <button onClick={() => onUpdate(r.requirement_id, { review_status: "needs_changes" })} style={{ background: "#fff", border: `1px solid ${C.rule}`, color: C.reviewDeep, borderRadius: 6, padding: "6px 12px", fontSize: 12, cursor: "pointer" }}>Needs changes</button>
                    <button onClick={() => onUpdate(r.requirement_id, { review_status: "rejected" })} style={{ background: "#fff", border: `1px solid ${C.alertLine}`, color: C.alert, borderRadius: 6, padding: "6px 12px", fontSize: 12, cursor: "pointer" }}>Reject</button>
                    <button onClick={() => onDelete(r.requirement_id)} title="Delete this clause" style={{ marginLeft: "auto", background: "none", border: "1px solid transparent", borderRadius: 6, color: C.inkFaint, padding: "6px 8px", fontSize: 12, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 5 }}><IconTrash /> Delete</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
