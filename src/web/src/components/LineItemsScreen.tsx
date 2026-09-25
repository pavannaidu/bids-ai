import { useState } from "react";
import { C, F, ghostBtn } from "../theme";
import { IconInfo, IconTrash, IconDoc } from "./icons";
import MultiSelectPopover from "./MultiSelectPopover";
import type { Bid, PricedLineItem } from "../types";

interface Props {
  bid: Bid;
  loading: boolean;
  manufacturers: string[];
  matchManufacturers: string[];
  onMatchManufacturers: (next: string[]) => void;
  onUpdateLine: (lineId: string, fields: { raw_description: string; qty: number; uom: string; given_code: string | null }) => Promise<void>;
  onAddLine: () => void;
  onDeleteLine: (lineId: string) => void;
  onReextract: () => void;
  onOpenSource: (docId: string) => void;
}

const GRID = "62px minmax(240px,1fr) 80px 70px 110px 58px";

const cellInput: React.CSSProperties = {
  width: "100%", fontFamily: F.mono, fontSize: 12, color: C.inkSoft,
  padding: "5px 7px", border: "1px solid transparent", borderRadius: 5, background: "transparent",
};

// Editable line-item row. Borderless inputs reveal a border on hover/focus; the
// description gets the flexible track (never truncates). Saves on blur when a
// field changed.
function LineRow({ line, onSave, onDelete, onOpenSource }: {
  line: PricedLineItem;
  onSave: Props["onUpdateLine"];
  onDelete: (id: string) => void;
  onOpenSource: (docId: string) => void;
}) {
  const [desc, setDesc] = useState(line.raw_description);
  const [qty, setQty] = useState(String(line.qty));
  const [uom, setUom] = useState(line.uom);
  const [code, setCode] = useState(line.given_code ?? "");
  const [showProv, setShowProv] = useState(false);

  const commit = () => {
    const nextQty = Number(qty) || 0;
    const nextCode = code.trim() || null;
    if (desc === line.raw_description && nextQty === line.qty && uom === line.uom && nextCode === (line.given_code ?? null)) return;
    onSave(line.line_id, { raw_description: desc, qty: nextQty, uom, given_code: nextCode });
  };

  const method = (line.extraction_method ?? "ai_extract").replace("_", " ").toUpperCase();

  return (
    <div style={{ display: "grid", gridTemplateColumns: GRID, minWidth: 840, alignItems: "center", padding: "6px 12px", background: "#fff", border: `1px solid ${C.rule}`, borderTop: "none" }}>
      <span style={{ position: "relative", display: "flex", alignItems: "center", gap: 5 }}>
        <span style={{ fontFamily: F.mono, fontSize: 11, color: C.inkFaint }}>{line.line_number}</span>
        <span style={{ position: "relative", display: "inline-flex" }}>
          <button
            onMouseEnter={() => setShowProv(true)}
            onMouseLeave={() => setShowProv(false)}
            onClick={() => line.source_doc_id && onOpenSource(line.source_doc_id)}
            style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: C.inkDisabled, display: "inline-flex" }}
            title="Source"
          ><IconInfo /></button>
          {showProv && (
            <span style={{ position: "absolute", top: 20, left: -6, zIndex: 30, width: 250, background: "#fff", border: `1px solid ${C.rule}`, borderRadius: 8, boxShadow: "0 6px 18px rgba(20,33,30,.14)", padding: "9px 10px", display: "flex", gap: 8, alignItems: "flex-start" }}>
              <span style={{ flex: "none", marginTop: 1, color: C.inkFaint }}><IconDoc size={15} /></span>
              <span style={{ minWidth: 0 }}>
                <span style={{ display: "block", fontSize: 11.5, fontWeight: 600, color: C.accentDeep, lineHeight: 1.35, wordBreak: "break-word" }}>{line.source_filename ?? "Source document"}</span>
                <span style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 5 }}>
                  <span style={{ fontFamily: F.mono, fontSize: 11, color: C.inkSoft }}>{line.source_page != null ? `Page ${line.source_page}` : "Page —"}</span>
                  <span style={{ fontFamily: F.mono, fontSize: 9, fontWeight: 700, letterSpacing: ".04em", textTransform: "uppercase", background: C.wash, color: C.inkSoft, borderRadius: 4, padding: "2px 5px" }}>{method}</span>
                </span>
              </span>
            </span>
          )}
        </span>
      </span>
      <input value={desc} onChange={(e) => setDesc(e.target.value)} onBlur={commit} style={{ ...cellInput, fontFamily: F.sans, fontSize: 12.5, color: C.ink }} />
      <input value={qty} onChange={(e) => setQty(e.target.value)} onBlur={commit} style={{ ...cellInput, color: C.ink, fontVariantNumeric: "tabular-nums" }} />
      <input value={uom} onChange={(e) => setUom(e.target.value)} onBlur={commit} style={cellInput} />
      <input value={code} placeholder="—" onChange={(e) => setCode(e.target.value)} onBlur={commit} style={cellInput} />
      <span style={{ display: "flex", justifyContent: "flex-end" }}>
        <button onClick={() => onDelete(line.line_id)} title="Delete line" style={{ background: "none", border: "1px solid transparent", borderRadius: 5, color: C.inkFaint, cursor: "pointer", padding: "4px 6px", display: "inline-flex", alignItems: "center" }}><IconTrash /></button>
      </span>
    </div>
  );
}

export default function LineItemsScreen({ bid, loading, manufacturers, matchManufacturers, onMatchManufacturers, onUpdateLine, onAddLine, onDeleteLine, onReextract, onOpenSource }: Props) {
  const lines = bid.line_items;
  const mfrLabel = matchManufacturers.length === 0 ? "All manufacturers" : matchManufacturers.length === 1 ? matchManufacturers[0] : `${matchManufacturers.length} manufacturers`;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
        <span style={{ fontFamily: F.serif, fontSize: 16 }}>Extracted line items</span>
        <span style={{ fontSize: 11.5, color: C.inkFaint }}>{loading && !lines.length ? "extracting…" : `${lines.length} line item${lines.length === 1 ? "" : "s"}`}</span>
        <span style={{ display: "flex", alignItems: "center", gap: 7, marginLeft: "auto" }}>
          <label style={{ fontSize: 11.5, color: C.inkSoft, whiteSpace: "nowrap" }}>Restrict matches to manufacturer</label>
          <MultiSelectPopover label={mfrLabel} options={manufacturers} selected={matchManufacturers} onChange={onMatchManufacturers} resetLabel="All manufacturers" />
        </span>
        <button style={ghostBtn} disabled={loading} onClick={onReextract} title="Re-run line-item extraction">{loading ? "Re-extracting…" : "Re-extract"}</button>
        <button style={ghostBtn} onClick={onAddLine}>+ Add line</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: GRID, minWidth: 840, padding: "7px 12px", background: C.wash, border: `1px solid ${C.rule}`, borderRadius: "10px 10px 0 0", fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".05em", textTransform: "uppercase", color: C.inkFaint }}>
        <span>#</span><span>Description</span><span>Qty</span><span>UOM</span><span>Code given</span><span style={{ textAlign: "right" }}>Actions</span>
      </div>

      {loading && !lines.length ? (
        <div style={{ padding: 20, background: "#fff", border: `1px solid ${C.rule}`, borderTop: "none", color: C.inkFaint, fontSize: 12.5 }}>Extracting line items… (this is the longer step)</div>
      ) : lines.map((l) => (
        <LineRow key={l.line_id} line={l} onSave={onUpdateLine} onDelete={onDeleteLine} onOpenSource={onOpenSource} />
      ))}
    </div>
  );
}
