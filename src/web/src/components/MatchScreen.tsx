import { useEffect, useState } from "react";
import { repriceLine, searchCatalog } from "../api";
import { C, F, ghostBtn } from "../theme";
import { fmtPrice } from "../hooks";
import MultiSelectPopover from "./MultiSelectPopover";
import RematchMenu from "./RematchMenu";
import type { CandidateMatch, MatchMode, MatchSensitivity, PricedLineItem } from "../types";

interface Props {
  bidId: string;
  lines: PricedLineItem[];
  matching: boolean;
  acceptingAll: boolean;
  manufacturers: string[];
  matchManufacturers: string[];
  onMatchManufacturers: (next: string[]) => void;
  matchThreshold: number;
  matchSensitivity: MatchSensitivity;
  onReview: (lineId: string, itemCode: string, price: number, action: "accepted" | "overridden") => void;
  onManualMatch: (lineId: string, itemCode: string) => Promise<void>;
  onNoMatch: (lineId: string) => Promise<void>;
  onRematch: (mode: MatchMode) => void;
  onAcceptAll: () => void;
  acceptAllTotal: number;
  exceptionsCount: number;
}

const GRID = "34px minmax(240px,1fr) 230px 116px 84px 100px";
const SENS_LABEL: Record<MatchSensitivity, string> = { conservative: "Conservative", balanced: "Balanced", permissive: "Permissive" };

function guardExplanation(top: CandidateMatch | undefined, threshold: number, sensitivity: MatchSensitivity): string {
  const pct = (n: number) => `${Math.round(n * 100)}%`;
  const need = `${SENS_LABEL[sensitivity]} requires ${pct(threshold)}`;
  switch (top?.guard_reason) {
    case "below_confidence_threshold": return `Top semantic score ${pct(top.semantic_score ?? 0)}; ${need}.`;
    case "confidence_unavailable": return "Catalog candidates were found, but semantic confidence could not be verified — needs a reviewer decision.";
    case "uom_mismatch": return "Top candidate has a unit-of-measure or size/gauge mismatch — needs a reviewer decision.";
    case "hard_incompatibility": return "Top candidate looks like a different product family — needs a reviewer decision.";
    case "low_specificity": return "The requested description is too generic to match confidently — needs a reviewer decision.";
    case "not_catalog_source": return "No catalog match — only a general-knowledge suggestion is available.";
    default: return `No confident catalog match — ${need}.`;
  }
}

type RowFilter = "all" | "decision" | "accepted";

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

// Score cell. Leads with the SEMANTIC score (pure-ANN cosine similarity — the
// calibrated "how close" number the guard actually gates on) plus a tick at the
// sensitivity threshold, so a weak candidate visibly stops short. Hybrid RRF is a
// ranking signal that saturates near 100% for the top hit regardless of true
// similarity, so it's NOT shown as the quality bar — only as a small secondary
// "rel N%" label. When semantic_score is unavailable (the ANN confidence pass
// failed) we fall back to the RRF bar, clearly labeled as a ranking score so a
// saturated bar isn't misread as match quality.
function ScoreCell({ c, threshold }: { c: CandidateMatch; threshold: number }) {
  const relPct = Math.round((c.retrieval_score ?? c.score) * 100);
  if (c.semantic_score == null) {
    return (
      <>
        <span style={{ display: "block", fontSize: 9.5, letterSpacing: ".04em", textTransform: "uppercase", color: C.inkSoft, marginBottom: 3 }}>Relevance (ranking)</span>
        <span style={{ position: "relative", display: "block", width: 118, height: 18, background: C.wash, borderRadius: 4, overflow: "hidden" }}>
          <span style={{ position: "absolute", inset: 0, width: `${relPct}%`, background: C.accentLine }} />
          <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "flex-end", paddingRight: 5, fontFamily: F.mono, fontSize: 10.5, fontWeight: 700, color: C.ink }}>{relPct}%</span>
        </span>
        <span style={{ display: "block", fontSize: 9, color: C.inkFaint, marginTop: 2, textAlign: "right" }}>semantic score unavailable</span>
      </>
    );
  }
  const semPct = Math.round(c.semantic_score * 100);
  const thrPct = Math.round(threshold * 100);
  const clears = semPct >= thrPct;
  const fill = clears ? C.accent : C.review;
  return (
    <>
      <span style={{ display: "flex", alignItems: "baseline", justifyContent: "flex-end", gap: 6, marginBottom: 3 }}>
        <span style={{ fontSize: 9.5, letterSpacing: ".04em", textTransform: "uppercase", color: clears ? C.inkSoft : C.reviewDeep, fontWeight: 700 }}>Match {semPct}%</span>
        <span style={{ fontSize: 9, color: C.inkFaint }}>rel {relPct}%</span>
      </span>
      <span style={{ position: "relative", display: "block", width: 118, height: 18, background: C.wash, borderRadius: 4, overflow: "hidden" }}>
        <span style={{ position: "absolute", inset: 0, width: `${semPct}%`, background: fill }} />
        {/* threshold tick */}
        <span title={`Balanced threshold ${thrPct}%`} style={{ position: "absolute", top: 0, bottom: 0, left: `${thrPct}%`, width: 2, background: C.ink, opacity: 0.55 }} />
        <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "flex-end", paddingRight: 5, fontFamily: F.mono, fontSize: 10.5, fontWeight: 700, color: C.ink }}>{semPct}%</span>
      </span>
      <span style={{ display: "block", fontSize: 9, color: C.inkFaint, marginTop: 2, textAlign: "right" }}>threshold {thrPct}%</span>
    </>
  );
}

function CandidateRow({ c, selected, onSelect, disabled, threshold }: { c: CandidateMatch; selected: boolean; onSelect: () => void; disabled: boolean; threshold: number }) {
  const isHistory = c.source === "purchase_history";
  return (
    <div
      onClick={onSelect}
      style={{
        display: "flex", alignItems: "flex-start", gap: 10, padding: "9px 10px", borderRadius: 6, cursor: "pointer",
        border: `1px solid ${selected ? C.review : "transparent"}`, background: selected ? C.reviewSoft : "transparent",
        marginBottom: 4, opacity: disabled ? 0.6 : 1,
      }}
    >
      <span style={{ width: 14, height: 14, borderRadius: "50%", border: `2px solid ${selected ? C.review : C.inkFaint}`, background: selected ? C.review : "transparent", flex: "none", marginTop: 2, boxShadow: selected ? `inset 0 0 0 2px #fff` : "none" }} />
      <span style={{ minWidth: 0, flex: 1 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
          <span style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".03em", background: isHistory ? C.wash : C.accentSoft, color: isHistory ? C.inkSoft : C.accentDeep, borderRadius: 4, padding: "2px 6px", fontFamily: F.mono }}>{c.source.replace("_", " ")}</span>
          <span style={{ fontFamily: F.mono, fontSize: 11.5, fontWeight: 700, color: C.accentDeep }}>{c.item_code}</span>
          {c.manufacturer_name && <span style={{ fontSize: 11, color: C.inkFaint }}>{c.manufacturer_name}</span>}
        </span>
        <span style={{ display: "block", fontSize: 12, marginTop: 2 }}>{c.description_long}</span>
        {c.history_snippet && <span style={{ display: "block", fontSize: 11, color: C.inkSoft, marginTop: 2 }}>{c.history_snippet}</span>}
        {c.review_flag && <span style={{ display: "block", fontSize: 11, color: C.alert, marginTop: 2 }}>⚠ {c.review_flag}</span>}
      </span>
      <span style={{ marginLeft: "auto", textAlign: "right", flex: "none", width: 118 }}>
        <ScoreCell c={c} threshold={threshold} />
      </span>
    </div>
  );
}

function MatchRow(props: {
  bidId: string; line: PricedLineItem; expanded: boolean; onToggle: () => void;
  manufacturers: string[]; defaultManufacturers: string[]; matchThreshold: number; matchSensitivity: MatchSensitivity;
  onReview: Props["onReview"]; onManualMatch: Props["onManualMatch"]; onNoMatch: Props["onNoMatch"];
}) {
  const { bidId, line, expanded, onToggle } = props;
  const [price, setPrice] = useState<number>(line.proposed_price ?? 0);
  const [pricing, setPricing] = useState(false);
  useEffect(() => { setPrice(line.proposed_price ?? 0); }, [line.proposed_price]);

  const selected = line.selected_item_code;
  const resolution = line.resolution ?? (selected ? "catalog_match" : "pending");
  const isNoMatch = resolution === "no_match";
  const guarded = !isNoMatch && !selected && line.review_action === "pending";
  const accepted = line.review_action !== "pending" && !isNoMatch;
  const top = line.candidates[0];
  const realCandidates = line.candidates.filter((c) => c.item_code);
  const selCand = line.candidates.find((c) => c.item_code === selected);
  // Collapsed bar mirrors the expanded ScoreCell: prefer the SEMANTIC score
  // (calibrated, guard-gated) of the relevant candidate — the selected one if any,
  // else the top — and only fall back to hybrid RRF when semantic is unavailable.
  // The RRF value saturates near 100% for the top hit regardless of quality, so we
  // never lead with it. `confIsSemantic` drives the color: green when it clears the
  // threshold, amber when below (a genuine weak match reads low, not a false 100%).
  const confCand = selCand ?? top;
  const confIsSemantic = confCand?.semantic_score != null;
  const confPct = confCand
    ? Math.round((confIsSemantic ? confCand.semantic_score! : (confCand.retrieval_score ?? confCand.score)) * 100)
    : 0;
  const confBelow = confIsSemantic && confPct < Math.round(props.matchThreshold * 100);

  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchMfr, setSearchMfr] = useState<string[]>(props.defaultManufacturers);
  const [results, setResults] = useState<CandidateMatch[]>([]);
  const [searching, setSearching] = useState(false);
  const dq = useDebounced(query, 300);
  const mfrKey = searchMfr.join("|");
  useEffect(() => {
    if (!searchOpen || dq.trim().length < 2) { setResults([]); return; }
    let cancelled = false;
    setSearching(true);
    searchCatalog(bidId, line.line_id, dq, searchMfr).then((r) => { if (!cancelled) setResults(r); }).finally(() => { if (!cancelled) setSearching(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dq, searchOpen, mfrKey]);

  const selectCandidate = async (code: string, wasTop: boolean) => {
    if (code === selected) { props.onReview(line.line_id, code, price, wasTop ? "accepted" : "overridden"); return; }
    setPricing(true);
    try {
      const { proposed_price } = await repriceLine(bidId, line.line_id, code);
      const next = proposed_price ?? price;
      setPrice(next);
      props.onReview(line.line_id, code, next, wasTop ? "accepted" : "overridden");
    } finally { setPricing(false); }
  };

  // State pill.
  let statePill: React.ReactNode = null;
  if (isNoMatch) statePill = <span style={pill(C.wash, C.inkFaint)}>No match</span>;
  else if (accepted) statePill = <span style={pill(C.accentSoft, C.accentDeep)}>Accepted</span>;
  else if (guarded) statePill = <span style={pill(C.reviewSoft, C.reviewDeep, C.review)}>Decide</span>;
  else statePill = <span style={pill(C.wash, C.inkFaint)}>Pending</span>;

  return (
    <div style={{ minWidth: 1000, borderLeft: guarded ? `3px solid ${C.review}` : "3px solid transparent" }}>
      <div onClick={onToggle} style={{ display: "grid", gridTemplateColumns: GRID, alignItems: "center", padding: "8px 12px", background: "#fff", border: `1px solid ${C.rule}`, borderTop: "none", cursor: "pointer" }}>
        <span style={{ fontFamily: F.mono, fontSize: 11, color: C.inkFaint }}>{line.line_number}</span>
        <span style={{ minWidth: 0, paddingRight: 14 }}>
          <span style={{ display: "block", fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{line.raw_description}</span>
          <span style={{ display: "block", fontSize: 11, color: C.inkFaint, marginTop: 2 }}>Qty {line.qty} {line.uom}</span>
        </span>
        <span style={{ minWidth: 0, paddingRight: 12 }}>
          {selected ? (
            <>
              <span style={{ display: "block", fontFamily: F.mono, fontSize: 11.5, fontWeight: 700, color: C.accentDeep }}>{selected}</span>
              <span style={{ display: "block", fontSize: 11, color: C.inkSoft, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{selCand?.description_long ?? ""}</span>
            </>
          ) : (
            <span style={{ fontSize: 11.5, color: C.inkFaint }}>{isNoMatch ? "— no catalog product —" : "— needs selection —"}</span>
          )}
        </span>
        <span>
          <span style={{ position: "relative", display: "block", width: 100, height: 16, background: C.wash, borderRadius: 4, overflow: "hidden" }}>
            <span style={{ position: "absolute", inset: 0, width: `${confPct}%`, background: confBelow ? C.review : C.accentLine }} />
            <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "flex-end", paddingRight: 5, fontFamily: F.mono, fontSize: 10, fontWeight: 700, color: C.ink }}>{confPct}%</span>
          </span>
        </span>
        <span style={{ fontFamily: F.mono, fontSize: 12, fontVariantNumeric: "tabular-nums" }}>{fmtPrice(line.proposed_price)}</span>
        {statePill}
      </div>

      {expanded && (
        <div style={{ padding: "4px 12px 14px 46px", background: "#fff", border: `1px solid ${C.rule}`, borderTop: "none", minWidth: 1000 }}>
          {guarded && (
            <div style={{ padding: "8px 10px", borderRadius: 6, background: C.reviewSoft, border: `1px solid ${C.review}`, marginBottom: 10 }}>
              <strong style={{ fontSize: 12, color: C.reviewDeep }}>No confident catalog match — reviewer decision required.</strong>
              <div style={{ fontSize: 11.5, color: C.reviewDeep, marginTop: 2 }}>{guardExplanation(top, props.matchThreshold, props.matchSensitivity)}</div>
            </div>
          )}

          {realCandidates.length === 0 && (
            <div style={{ padding: "9px 10px", borderRadius: 6, background: C.paper, border: `1px dashed ${C.rule}`, marginBottom: 4 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ fontFamily: F.mono, fontSize: 11.5, fontWeight: 700, color: C.inkFaint }}>—</span>
                <span style={{ fontSize: 12, color: C.inkSoft }}>No catalog candidate cleared the threshold.</span>
              </span>
              <span style={{ display: "block", fontSize: 11, color: C.inkFaint, marginTop: 3 }}>Search the catalog, pick from purchase history, or mark this line no catalog match.</span>
            </div>
          )}

          {realCandidates.map((c, idx) => (
            <CandidateRow key={c.item_code} c={c} selected={selected === c.item_code} disabled={pricing} onSelect={() => selectCandidate(c.item_code, idx === 0)} threshold={props.matchThreshold} />
          ))}

          {searchOpen ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "10px 0" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search the item catalog…" style={{ flex: 1, minWidth: 200, padding: "6px 9px", border: `1px solid ${C.rule}`, borderRadius: 6, fontSize: 12 }} />
                <MultiSelectPopover label={searchMfr.length ? `${searchMfr.length} mfr` : "All manufacturers"} options={props.manufacturers} selected={searchMfr} onChange={setSearchMfr} resetLabel="All manufacturers" />
                <button style={ghostBtn} onClick={() => { setSearchOpen(false); setQuery(""); setResults([]); }}>Cancel</button>
              </div>
              {searching && <div style={{ fontSize: 11.5, color: C.inkFaint }}>Searching…</div>}
              {!searching && results.map((hit) => (
                <div key={hit.item_code} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", border: `1px solid ${C.rule}`, borderRadius: 6 }}>
                  <span style={{ minWidth: 0, flex: 1 }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                      <span style={{ fontFamily: F.mono, fontSize: 11.5, fontWeight: 700, color: C.accentDeep }}>{hit.item_code}</span>
                      {hit.manufacturer_name && <span style={{ fontSize: 11, color: C.inkFaint }}>{hit.manufacturer_name}</span>}
                    </span>
                    <span style={{ display: "block", fontSize: 12, marginTop: 2 }}>{hit.description_long}</span>
                  </span>
                  <button style={{ ...ghostBtn, background: C.accent, color: "#fff", border: "none" }} onClick={async () => { await props.onManualMatch(line.line_id, hit.item_code); setSearchOpen(false); setQuery(""); setResults([]); }}>Select</button>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
              <button style={ghostBtn} onClick={() => setSearchOpen(true)}>Search catalog →</button>
              <button style={{ ...ghostBtn, opacity: isNoMatch ? 0.5 : 1 }} disabled={isNoMatch} onClick={() => props.onNoMatch(line.line_id)}>No catalog match</button>
              {!isNoMatch && selected && (
                <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: C.inkSoft }}>
                  Proposed price
                  <input
                    type="number" step="0.01" value={price}
                    onChange={(e) => setPrice(parseFloat(e.target.value) || 0)}
                    onBlur={() => selected && props.onReview(line.line_id, selected, price, "overridden")}
                    style={{ width: 78, padding: "4px 6px", border: `1px solid ${C.rule}`, borderRadius: 5, fontFamily: F.mono, fontSize: 12 }}
                  />
                </span>
              )}
              <span style={{ fontSize: 11, color: C.inkFaint }}>{pricing ? "Updating price…" : line.pricing_basis}</span>
              {!isNoMatch && selected && (
                <button style={{ marginLeft: "auto", background: C.accent, color: "#fff", border: "none", borderRadius: 6, padding: "6px 13px", fontSize: 12, fontWeight: 600, cursor: "pointer" }} onClick={() => selectCandidate(selected, selected === top?.item_code)}>Accept &amp; next</button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function pill(bg: string, fg: string, bd?: string): React.CSSProperties {
  return { fontFamily: F.mono, fontSize: 10, fontWeight: 700, textTransform: "uppercase", background: bg, color: fg, border: bd ? `1px solid ${bd}` : "none", borderRadius: 999, padding: "2px 8px", justifySelf: "start", whiteSpace: "nowrap" };
}

export default function MatchScreen(props: Props) {
  const { lines, matching, acceptingAll, manufacturers, matchManufacturers, onMatchManufacturers } = props;
  const [filter, setFilter] = useState<RowFilter>("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  const needsDecision = (l: PricedLineItem) => l.review_action === "pending" && (l.resolution ?? (l.selected_item_code ? "catalog_match" : "pending")) !== "no_match" && !l.selected_item_code;
  const isAccepted = (l: PricedLineItem) => l.review_action !== "pending" && (l.resolution ?? "") !== "no_match";
  const matchedCount = lines.filter((l) => l.selected_item_code).length;
  const decisionCount = lines.filter(needsDecision).length;
  const acceptedCount = lines.filter(isAccepted).length;

  const filtered = lines.filter((l) => filter === "decision" ? needsDecision(l) : filter === "accepted" ? isAccepted(l) : true);
  const mfrLabel = matchManufacturers.length === 0 ? "All manufacturers" : matchManufacturers.length === 1 ? matchManufacturers[0] : `${matchManufacturers.length} manufacturers`;

  const chip = (id: RowFilter, label: string) => {
    const on = filter === id;
    return <button key={id} onClick={() => setFilter(id)} style={{ ...ghostBtn, flex: "none", whiteSpace: "nowrap", background: on ? C.accentDeep : "#fff", color: on ? "#fff" : C.inkSoft, border: `1px solid ${on ? C.accentDeep : C.rule}` }}>{label}</button>;
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
        <span style={{ fontFamily: F.serif, fontSize: 16 }}>Match &amp; price</span>
        <span style={{ fontSize: 11.5, color: C.inkFaint }}>{matchedCount} of {lines.length} lines matched · {decisionCount} need a decision</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", minWidth: 0, marginLeft: "auto" }}>
          {chip("all", `All ${lines.length}`)}
          {chip("decision", `Needs decision · ${decisionCount}`)}
          {chip("accepted", `Accepted · ${acceptedCount}`)}
          <span style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 4, paddingLeft: 10, borderLeft: `1px solid ${C.rule}`, flex: "none" }}>
            <label style={{ fontSize: 11.5, color: C.inkSoft, whiteSpace: "nowrap" }}>Restrict to manufacturer</label>
            <MultiSelectPopover label={mfrLabel} options={manufacturers} selected={matchManufacturers} onChange={onMatchManufacturers} resetLabel="All manufacturers" />
          </span>
          <RematchMenu disabled={matching || acceptingAll} onRematch={props.onRematch} />
          {props.acceptAllTotal > 0 && (
            <button style={{ ...ghostBtn, flex: "none", whiteSpace: "nowrap" }} disabled={acceptingAll} onClick={props.onAcceptAll}>
              {acceptingAll ? "Accepting…" : props.exceptionsCount > 0 ? `Accept matches & clear remaining (${props.acceptAllTotal}) →` : `Accept eligible matches (${props.acceptAllTotal}) →`}
            </button>
          )}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: GRID, minWidth: 1000, padding: "7px 12px", background: C.wash, border: `1px solid ${C.rule}`, borderRadius: "10px 10px 0 0", fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint }}>
        <span>#</span><span>Requested line</span><span>Selected match</span><span>Confidence</span><span>Price</span><span>State</span>
      </div>

      {filtered.map((line) => (
        <MatchRow
          key={line.line_id}
          bidId={props.bidId}
          line={line}
          expanded={expanded === line.line_id}
          onToggle={() => setExpanded(expanded === line.line_id ? null : line.line_id)}
          manufacturers={manufacturers}
          defaultManufacturers={matchManufacturers}
          matchThreshold={props.matchThreshold}
          matchSensitivity={props.matchSensitivity}
          onReview={props.onReview}
          onManualMatch={props.onManualMatch}
          onNoMatch={props.onNoMatch}
        />
      ))}
    </div>
  );
}
