import { C, F, ghostBtn } from "../theme";
import { fmtMoney } from "../hooks";
import type { Bid, PricedLineItem } from "../types";
import type { StepId } from "./StepRail";

interface Props {
  bid: Bid;
  reqApproved: number;
  reqTotal: number;
  submitting: boolean;
  downloadLinks: { pdf: string; excel: string } | null;
  onGenerate: () => void;
  // Navigate to the step (and optionally focus a line) behind a blocker.
  onFix: (step: StepId, lineId?: string) => void;
}

interface Blocker { line: PricedLineItem; reasons: string[]; }

function blockingLines(bid: Bid): Blocker[] {
  const out: Blocker[] = [];
  for (const line of bid.line_items) {
    const resolution = line.resolution ?? (line.selected_item_code ? "catalog_match" : "pending");
    const reasons: string[] = [];
    if (resolution !== "no_match") {
      if (!line.selected_item_code) reasons.push("no product selected");
      if (line.proposed_price == null || line.proposed_price < 0) reasons.push("no valid price");
      if (line.review_action === "pending") reasons.push("not yet reviewed");
    }
    if (reasons.length) out.push({ line, reasons });
  }
  return out;
}

const PROPOSAL_GRID = "34px 84px minmax(180px,1.3fr) 46px 46px 66px minmax(150px,1fr)";

export default function GenerateScreen({ bid, reqApproved, reqTotal, submitting, downloadLinks, onGenerate, onFix }: Props) {
  // Show EVERY requested line so the proposal mirrors the solicitation 1:1 (no
  // gaps in the line numbering). No-catalog-product lines render as an explicit
  // "No bid" row rather than being dropped. The total still sums priced lines only.
  const rows = bid.line_items;
  const total = bid.line_items.reduce((sum, l) => sum + (l.proposed_price ?? 0) * (l.qty || 0), 0);
  const reviewedCount = bid.line_items.filter((l) => l.review_action !== "pending").length;
  const blocking = blockingLines(bid);
  const submitted = bid.status === "submitted";

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-start" }}>
      <div style={{ flex: "1 1 460px", minWidth: 0, background: "#fff", border: `1px solid ${C.rule}`, borderRadius: 10, overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "10px 14px", borderBottom: `1px solid ${C.rule}`, background: C.wash }}>
          <span style={{ fontFamily: F.mono, fontSize: 9.5, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint }}>Generated proposal</span>
          <span style={{ fontSize: 11, color: C.inkFaint }}>{submitted ? "Generated · pricing from the selected strategy" : "Preview — generate to finalize"}</span>
          <span style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
            {downloadLinks && <a href={downloadLinks.excel} style={{ ...ghostBtn, textDecoration: "none", whiteSpace: "nowrap" }}>Download XLSX</a>}
            {downloadLinks && <a href={downloadLinks.pdf} style={{ ...ghostBtn, textDecoration: "none", whiteSpace: "nowrap" }}>Download PDF</a>}
            <button onClick={onGenerate} disabled={submitting || blocking.length > 0} style={{ background: C.accent, color: "#fff", border: "none", borderRadius: 6, padding: "5px 11px", fontSize: 11.5, fontWeight: 600, cursor: submitting || blocking.length ? "default" : "pointer", opacity: submitting || blocking.length ? 0.55 : 1, whiteSpace: "nowrap" }}>
              {submitting ? "Generating…" : submitted ? "Regenerate" : "Generate"}
            </button>
          </span>
        </div>
        <div style={{ padding: "22px 26px", fontFamily: F.serif, overflowX: "auto" }}>
          <div style={{ fontSize: 17 }}>Price proposal — {bid.bid_name || bid.file_name}</div>
          <div style={{ fontSize: 11.5, color: C.inkFaint, marginTop: 3, fontFamily: F.sans }}>
            {bid.customer_name}{bid.solicitation_ref && ` · Solicitation ${bid.solicitation_ref}`} · Submitted by Bids AI{bid.due_date && ` · Due ${bid.due_date}`}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: PROPOSAL_GRID, gap: 10, padding: "7px 0", marginTop: 16, borderTop: `1px solid ${C.ink}`, borderBottom: `1px solid ${C.rule}`, fontFamily: F.mono, fontSize: 9, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint }}>
            <span>Line</span><span>Item</span><span>Product</span><span style={{ textAlign: "right" }}>Qty</span><span>UOM</span><span style={{ textAlign: "right" }}>Price</span><span>Requested product</span>
          </div>
          {rows.map((l) => {
            const cand = l.candidates.find((c) => c.item_code === l.selected_item_code);
            const noBid = (l.resolution ?? "") === "no_match" || !l.selected_item_code;
            return (
              <div key={l.line_id} style={{ display: "grid", gridTemplateColumns: PROPOSAL_GRID, gap: 10, padding: "7px 0", borderBottom: `1px solid ${C.wash}`, alignItems: "baseline" }}>
                <span style={{ fontFamily: F.mono, fontSize: 11, color: C.inkFaint }}>{l.line_number}</span>
                <span style={{ fontFamily: F.mono, fontSize: 10.5, color: noBid ? C.inkFaint : C.accentDeep }}>{noBid ? "—" : l.selected_item_code}</span>
                <span style={{ fontSize: 11.5, lineHeight: 1.4, fontFamily: F.sans, color: noBid ? C.inkFaint : C.ink, fontStyle: noBid ? "italic" : "normal" }}>{noBid ? "No bid — no catalog product" : (cand?.description_long ?? "")}</span>
                <span style={{ fontFamily: F.mono, fontSize: 11, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{l.qty}</span>
                <span style={{ fontFamily: F.mono, fontSize: 11, color: C.inkSoft }}>{l.uom}</span>
                <span style={{ fontFamily: F.mono, fontSize: 11, textAlign: "right", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{noBid ? "—" : (l.proposed_price != null ? fmtMoney(l.proposed_price) : "—")}</span>
                <span style={{ fontSize: 11, lineHeight: 1.4, color: C.inkFaint, fontFamily: F.sans }}>{l.raw_description}</span>
              </div>
            );
          })}
          <div style={{ display: "flex", alignItems: "baseline", gap: 14, padding: "10px 0 0", borderTop: `1px solid ${C.ink}`, marginTop: 2 }}>
            <span style={{ fontSize: 12, fontFamily: F.sans, color: C.inkSoft }}>Total bid value</span>
            <span style={{ marginLeft: "auto", fontFamily: F.mono, fontSize: 15, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{fmtMoney(total)}</span>
          </div>
        </div>
      </div>

      <div style={{ flex: "1 1 220px", minWidth: 200, maxWidth: 280, display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ background: "#fff", border: `1px solid ${C.rule}`, borderRadius: 10, padding: "12px 14px" }}>
          <div style={{ fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint, marginBottom: 9 }}>Summary</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            <SummaryRow label="Lines priced" value={`${reviewedCount} / ${bid.line_items.length}`} />
            <SummaryRow label="Requirements approved" value={`${reqApproved} / ${reqTotal}`} />
            <SummaryRow label="Total bid value" value={fmtMoney(total)} />
          </div>
        </div>
        <div style={{ background: "#fff", border: `1px solid ${C.rule}`, borderRadius: 10, padding: "12px 14px" }}>
          <div style={{ fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint, marginBottom: 9 }}>Before you submit</div>
          {blocking.length === 0 ? (
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0" }}>
              <span style={{ width: 16, height: 16, borderRadius: "50%", background: C.accentSoft, color: C.accentDeep, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 10, flex: "none" }}>✓</span>
              <span style={{ fontSize: 12 }}>All lines resolved — ready to generate.</span>
            </div>
          ) : blocking.map((b) => (
            <div key={b.line.line_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0" }}>
              <span style={{ width: 16, height: 16, borderRadius: "50%", background: C.reviewSoft, color: C.reviewDeep, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 10, flex: "none" }}>!</span>
              <span style={{ fontSize: 12, minWidth: 0 }}>Line {b.line.line_number}: {b.reasons.join(", ")}</span>
              <button onClick={() => onFix("match", b.line.line_id)} style={{ ...ghostBtn, marginLeft: "auto", padding: "3px 8px", fontSize: 11, flex: "none" }}>Fix →</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <span style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
      <span style={{ fontSize: 12, color: C.inkSoft }}>{label}</span>
      <span style={{ marginLeft: "auto", fontFamily: F.mono, fontSize: 12.5, fontWeight: 700 }}>{value}</span>
    </span>
  );
}
