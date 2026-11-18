import { useState } from "react";
import { C, F, ghostBtn } from "../theme";
import type { BidSummary } from "../types";

interface Props {
  bids: BidSummary[];
  loading: boolean;
  onOpen: (bidId: string) => void;
}

type Filter = "all" | "extracting" | "matching" | "submitted" | "due-week";

const GRID = "minmax(240px,1fr) 210px 110px 80px 110px 140px";

// Map the bid status to a stage pill + a rough review-progress fraction (the
// summary payload doesn't carry per-line review counts, so progress is derived
// from the workflow stage — enough for an at-a-glance list).
// Label each backend status with the wizard STEP a bid resumes at, so the Stage
// column speaks the same vocabulary as the step rail (Upload · Requirements ·
// Line Items · Match · Generate). The status enum doesn't map 1:1 to steps —
// `uploaded` means extraction is done (Line Items), and `pending_review` means it
// has been matched and is awaiting decisions (Match). pct is a coarse status-based
// estimate aligned to the step (the summary payload carries no per-line count).
function stage(status: BidSummary["status"]): { label: string; bg: string; fg: string; pct: number } {
  switch (status) {
    case "submitted": return { label: "Generate", bg: C.accentSoft, fg: C.accentDeep, pct: 100 };
    case "pending_review": return { label: "Match", bg: C.reviewSoft, fg: C.reviewDeep, pct: 80 };
    case "matching": return { label: "Match", bg: C.wash, fg: C.inkSoft, pct: 65 };
    case "uploaded": return { label: "Line Items", bg: C.wash, fg: C.inkSoft, pct: 40 };
    default: return { label: "Upload", bg: C.wash, fg: C.inkFaint, pct: 10 };
  }
}

function daysUntil(due: string): number | null {
  if (!due) return null;
  const d = new Date(due);
  if (isNaN(d.getTime())) return null;
  return Math.ceil((d.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
}

export default function AllBidsScreen({ bids, loading, onOpen }: Props) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const matches = bids.filter((b) => {
    const hay = `${b.bid_name} ${b.bid_id} ${b.file_name} ${b.customer_name}`.toLowerCase();
    if (q && !hay.includes(q.toLowerCase())) return false;
    if (filter === "extracting") return b.status === "parsing" || b.status === "uploaded";
    if (filter === "matching") return b.status === "matching" || b.status === "pending_review";
    if (filter === "submitted") return b.status === "submitted";
    if (filter === "due-week") { const d = daysUntil(b.due_date); return d != null && d <= 7; }
    return true;
  });

  const chip = (id: Filter, label: string) => {
    const on = filter === id;
    return <button key={id} onClick={() => setFilter(id)} style={{ ...ghostBtn, background: on ? C.accentDeep : "#fff", color: on ? "#fff" : C.inkSoft, border: `1px solid ${on ? C.accentDeep : C.rule}` }}>{label}</button>;
  };

  return (
    <div style={{ overflowX: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search bid name, ID, file, customer…" style={{ flex: 1, maxWidth: 340, padding: "6px 9px", border: `1px solid ${C.rule}`, borderRadius: 6, fontSize: 12, background: "#fff" }} />
        <div style={{ display: "flex", gap: 6 }}>
          {chip("all", "All")}
          {chip("extracting", "Extracting")}
          {chip("matching", "Matching")}
          {chip("submitted", "Submitted")}
          {chip("due-week", "Due this week")}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: GRID, minWidth: 940, padding: "7px 12px", background: C.wash, border: `1px solid ${C.rule}`, borderRadius: "10px 10px 0 0", fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint }}>
        <span>Bid</span><span>Customer</span><span>Stage</span><span>Lines</span><span>Due</span><span>Review progress</span>
      </div>

      {loading ? (
        <div style={{ padding: 20, background: "#fff", border: `1px solid ${C.rule}`, borderTop: "none", color: C.inkFaint, fontSize: 12.5 }}>Loading bids…</div>
      ) : matches.length === 0 ? (
        <div style={{ padding: 20, background: "#fff", border: `1px solid ${C.rule}`, borderTop: "none", color: C.inkFaint, fontSize: 12.5 }}>No bids match.</div>
      ) : matches.map((b) => {
        const s = stage(b.status);
        const dLeft = daysUntil(b.due_date);
        const dueSoon = dLeft != null && dLeft <= 7;
        return (
          <div key={b.bid_id} onClick={() => onOpen(b.bid_id)} style={{ display: "grid", gridTemplateColumns: GRID, minWidth: 940, alignItems: "center", padding: "9px 12px", background: "#fff", border: `1px solid ${C.rule}`, borderTop: "none", cursor: "pointer" }}>
            <span style={{ minWidth: 0, paddingRight: 14 }}>
              <span style={{ display: "block", fontSize: 12.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{b.bid_name || b.file_name}</span>
              <span style={{ display: "block", fontFamily: F.mono, fontSize: 10.5, color: C.inkFaint, marginTop: 2 }}>{b.bid_id}</span>
            </span>
            <span style={{ fontSize: 11.5, color: C.inkSoft, paddingRight: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{b.customer_name}</span>
            <span style={{ fontFamily: F.mono, fontSize: 10, fontWeight: 700, textTransform: "uppercase", background: s.bg, color: s.fg, borderRadius: 999, padding: "2px 8px", justifySelf: "start", whiteSpace: "nowrap" }}>{s.label}</span>
            <span style={{ fontFamily: F.mono, fontSize: 12, fontVariantNumeric: "tabular-nums" }}>{b.line_item_count}</span>
            <span style={{ fontFamily: F.mono, fontSize: 12, color: dueSoon ? C.alert : C.inkSoft, fontWeight: dueSoon ? 700 : 400 }}>{b.due_date || "—"}</span>
            <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{ flex: 1, height: 6, background: C.wash, borderRadius: 999, overflow: "hidden" }}>
                <span style={{ display: "block", width: `${s.pct}%`, height: "100%", background: s.pct === 100 ? C.accent : C.accentLine }} />
              </span>
              <span style={{ fontFamily: F.mono, fontSize: 10.5, color: C.inkFaint }}>{s.pct}%</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
