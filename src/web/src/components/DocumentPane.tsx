import { useCallback, useEffect, useState } from "react";
import { C, F } from "../theme";
import { IconDoc } from "./icons";
import type { SourceDocument } from "../types";

interface Props {
  bidId: string;
  documents: SourceDocument[];
  open: boolean;
  onToggle: () => void;
  // A provenance click focuses a specific doc + opens the pane (nonce lets a
  // repeat click on the same doc re-focus).
  focus?: { docId: string; nonce: number } | null;
}

const docUrl = (bidId: string, docId: string) => `/api/bids/${bidId}/documents/original/${docId}`;

// Expanded pane width is user-resizable (drag the left edge) and persisted.
const WIDTH_KEY = "bids-wb:doc-width";
const MIN_WIDTH = 320;
const MAX_WIDTH = 1100;
const DEFAULT_WIDTH = 400;

function clampWidth(w: number): number {
  // Never let the pane swallow the whole viewport — cap at ~72vw.
  const vwCap = Math.round(window.innerWidth * 0.72);
  return Math.max(MIN_WIDTH, Math.min(w, Math.min(MAX_WIDTH, vwCap)));
}

// Right-edge source-document pane: a 38px collapsed rail that expands to a 400px
// side-by-side reader with one tab per document. Deliberately a plain reader —
// no click-to-source highlighting. Real PDFs render inline; Office files get an
// open link (they can't preview inline).
export default function DocumentPane({ bidId, documents, open, onToggle, focus }: Props) {
  const firstPdf = documents.find((d) => d.file_format === "pdf");
  const [activeId, setActiveId] = useState<string>((firstPdf ?? documents[0])?.doc_id ?? "");

  const [width, setWidth] = useState<number>(() => {
    const saved = Number(localStorage.getItem(WIDTH_KEY));
    return saved ? clampWidth(saved) : DEFAULT_WIDTH;
  });
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (focus?.docId && documents.some((d) => d.doc_id === focus.docId)) {
      setActiveId(focus.docId);
    }
  }, [focus, documents]);

  // Drag the left edge to resize. Width grows as the pointer moves left, so it's
  // (viewport right edge − pointer X). Persisted on release.
  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setDragging(true);
    const onMove = (ev: MouseEvent) => setWidth(clampWidth(window.innerWidth - ev.clientX));
    const onUp = () => {
      setDragging(false);
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      setWidth((w) => { localStorage.setItem(WIDTH_KEY, String(w)); return w; });
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, []);

  if (documents.length === 0) return null;

  if (!open) {
    return (
      <button
        onClick={onToggle}
        title="Show source document"
        style={{
          width: 38, flex: "none", border: "none", borderLeft: `1px solid ${C.rule}`,
          background: "#fff", cursor: "pointer", display: "flex", flexDirection: "column",
          alignItems: "center", gap: 10, padding: "12px 0", color: C.inkSoft,
        }}
      >
        <IconDoc />
        <span style={{ writingMode: "vertical-rl", fontFamily: F.mono, fontSize: 10, letterSpacing: ".1em", textTransform: "uppercase" }}>Document</span>
      </button>
    );
  }

  const active = documents.find((d) => d.doc_id === activeId) ?? documents[0];
  const isPdf = active.file_format === "pdf";
  const activeIdx = documents.findIndex((d) => d.doc_id === active.doc_id);

  return (
    <div style={{ width, flex: "none", borderLeft: `1px solid ${C.rule}`, background: "#fff", display: "flex", flexDirection: "column", minHeight: 0, position: "relative" }}>
      {/* Left-edge resize handle. A 6px hit target with a hairline; the whole pane
          tints while dragging. */}
      <div
        onMouseDown={onDragStart}
        title="Drag to resize"
        style={{
          position: "absolute", top: 0, bottom: 0, left: -3, width: 6, cursor: "col-resize", zIndex: 5,
          borderLeft: dragging ? `2px solid ${C.accent}` : "2px solid transparent",
        }}
        onMouseEnter={(e) => { if (!dragging) (e.currentTarget.style.borderLeft = `2px solid ${C.accentLine}`); }}
        onMouseLeave={(e) => { if (!dragging) (e.currentTarget.style.borderLeft = "2px solid transparent"); }}
      />
      {/* While dragging, an overlay swallows iframe pointer events so the drag
          doesn't get "stuck" when the cursor passes over the PDF. */}
      {dragging && <div style={{ position: "absolute", inset: 0, zIndex: 4, cursor: "col-resize" }} />}
      {documents.length > 1 && (
        <div style={{ flex: "none", display: "flex", alignItems: "stretch", borderBottom: `1px solid ${C.rule}`, background: C.wash, overflowX: "auto" }}>
          {documents.map((d) => {
            const on = d.doc_id === active.doc_id;
            return (
              <button
                key={d.doc_id}
                onClick={() => setActiveId(d.doc_id)}
                title={d.file_name}
                style={{
                  display: "flex", alignItems: "center", gap: 6, maxWidth: 170, padding: "8px 10px",
                  background: on ? "#fff" : "transparent", border: "none",
                  boxShadow: on ? `inset 0 2px 0 ${C.accent}` : "none",
                  color: on ? C.ink : C.inkSoft, cursor: "pointer",
                }}
              >
                <span style={{ fontFamily: F.mono, fontSize: 8.5, fontWeight: 700, background: C.wash, color: C.inkSoft, borderRadius: 3, padding: "1px 4px", flex: "none" }}>{d.file_format || "doc"}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 11 }}>{d.file_name}</span>
              </button>
            );
          })}
        </div>
      )}
      <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 8, padding: "7px 12px", borderBottom: `1px solid ${C.rule}` }}>
        <span style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: C.inkSoft }}>{active.file_name}</span>
        <button onClick={onToggle} title="Collapse" style={{ marginLeft: "auto", background: "none", border: "none", color: C.inkFaint, fontSize: 14, cursor: "pointer", padding: "0 2px" }}>✕</button>
      </div>
      <div style={{ flex: 1, overflow: "auto", background: C.paper, minHeight: 0 }}>
        {isPdf ? (
          <iframe
            src={`${docUrl(bidId, active.doc_id)}?inline=true`}
            title={`Source — ${active.file_name}`}
            style={{ width: "100%", height: "100%", border: "none", background: "#fff" }}
          />
        ) : (
          <div style={{ padding: 18 }}>
            <div style={{ background: "#fff", border: `1px solid ${C.rule}`, borderRadius: 6, padding: "16px 18px", fontSize: 11.5, color: C.inkSoft, lineHeight: 1.5 }}>
              {active.file_name} — {active.file_format.toUpperCase()} files can't preview inline.
              <div style={{ marginTop: 10 }}>
                <a href={docUrl(bidId, active.doc_id)} target="_blank" rel="noreferrer" style={{ fontSize: 11.5, color: C.accentDeep, fontWeight: 600 }}>Open document →</a>
              </div>
            </div>
          </div>
        )}
      </div>
      <div style={{ flex: "none", padding: "8px 12px", borderTop: `1px solid ${C.rule}`, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 11, color: C.inkFaint }}>Document {activeIdx + 1} of {documents.length} in this bid</span>
        <a href={docUrl(bidId, active.doc_id)} target="_blank" rel="noreferrer" style={{ marginLeft: "auto", fontSize: 11, color: C.accentDeep }}>Open full document</a>
      </div>
    </div>
  );
}
