import { useRef, useState } from "react";
import { C, F, ghostBtn } from "../theme";
import type { Customer, SampleDocument, SourceDocument } from "../types";

export interface UploadState {
  customerId: string;
  dueDate: string;
  bidName: string;
  files: File[];
  sample: SampleDocument | null;
}

interface Props {
  customers: Customer[];
  sampleDocuments: SampleDocument[];
  state: UploadState;
  onState: (next: UploadState) => void;
  onCreateCustomer: (name: string) => Promise<Customer>;
  busy: boolean;
  // Non-null once the bid exists server-side (just uploaded, or reopened from
  // history). Its documents then live in the Volume rather than in `state.files`,
  // so the pane lists `savedDocuments` and routes adds/removes through the API.
  bidId: string | null;
  savedDocuments: SourceDocument[];
  onAddDocuments: (files: File[]) => void;
  onRemoveDocument: (docId: string) => void;
  // No-op until the bid exists; afterwards each detail edit is PATCHed.
  onCommitDetails: (fields: { bid_name?: string; due_date?: string; customer_id?: string }) => void;
  // The server rejects a customer change once extraction has run.
  customerLocked: boolean;
}

const card: React.CSSProperties = {
  background: "#fff", border: `1px solid ${C.rule}`, borderRadius: 10, padding: "14px 16px",
};
const cardTitle: React.CSSProperties = { fontFamily: F.serif, fontSize: 16, marginBottom: 12 };
const fieldLabel: React.CSSProperties = { fontSize: 11.5, fontWeight: 600, color: C.inkSoft };
const inputStyle: React.CSSProperties = {
  padding: "7px 9px", border: `1px solid ${C.rule}`, borderRadius: 6, fontSize: 12.5,
  background: "#fff", color: C.ink, fontFamily: "inherit",
};

// Upload screen: bid details + documents + sample solicitations. Fully
// controlled — App owns the staging state so the top-bar "Continue → extract"
// primary action can read it. Documents are staged client-side only until the
// bid exists; from then on they are server-side and this screen doubles as the
// document manager for a bid reopened from history.
export default function UploadScreen({
  customers, sampleDocuments, state, onState, onCreateCustomer, busy,
  bidId, savedDocuments, onAddDocuments, onRemoveDocument, onCommitDetails, customerLocked,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [addingAccount, setAddingAccount] = useState(false);
  const [newAccountName, setNewAccountName] = useState("");
  const [savingAccount, setSavingAccount] = useState(false);
  const [accountError, setAccountError] = useState<string | null>(null);

  const patch = (p: Partial<UploadState>) => onState({ ...state, ...p });

  const persisted = bidId !== null;

  const stageFiles = (files: File[]) => {
    if (!files.length) return;
    if (persisted) { onAddDocuments(files); return; }
    patch({ files: [...state.files, ...files], sample: null });
  };
  const removeFile = (i: number) => patch({ files: state.files.filter((_, idx) => idx !== i) });
  const stageSample = (doc: SampleDocument) =>
    patch({ files: [], sample: doc, customerId: doc.customer_id });

  const saveNewAccount = async () => {
    const name = newAccountName.trim();
    if (!name || savingAccount) return;
    setSavingAccount(true);
    setAccountError(null);
    try {
      const created = await onCreateCustomer(name);
      patch({ customerId: created.customer_id });
      if (!customerLocked) onCommitDetails({ customer_id: created.customer_id });
      setAddingAccount(false);
      setNewAccountName("");
    } catch (e) {
      setAccountError(String(e));
    } finally {
      setSavingAccount(false);
    }
  };

  const docCount = persisted ? savedDocuments.length : state.files.length + (state.sample ? 1 : 0);
  const docCountLabel = docCount === 0
    ? "none staged"
    : `${docCount} ${persisted ? (docCount === 1 ? "document" : "documents") : "staged"}`;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(320px,420px) minmax(320px,1fr)", gap: 18, alignItems: "start" }}>
      {/* Bid details */}
      <div style={card}>
        <div style={cardTitle}>Bid details</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 5, marginBottom: 12 }}>
          <label style={fieldLabel}>Bid name (optional)</label>
          <input
            style={inputStyle}
            value={state.bidName}
            placeholder="e.g. VA Medical Center — Q3 renewal"
            onChange={(e) => patch({ bidName: e.target.value })}
            onBlur={(e) => onCommitDetails({ bid_name: e.target.value })}
          />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 5, marginBottom: 12 }}>
          <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <label style={fieldLabel}>Bidding on behalf of</label>
            {!addingAccount && (
              <button type="button" style={{ ...ghostBtn, padding: "3px 8px", fontSize: 11 }} disabled={busy} onClick={() => setAddingAccount(true)}>+ New account</button>
            )}
          </span>
          {addingAccount ? (
            <div style={{ display: "flex", gap: 6 }}>
              <input
                autoFocus
                style={{ ...inputStyle, flex: 1 }}
                value={newAccountName}
                placeholder="New account name"
                disabled={savingAccount}
                onChange={(e) => setNewAccountName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveNewAccount();
                  else if (e.key === "Escape") { setAddingAccount(false); setNewAccountName(""); }
                }}
              />
              <button type="button" style={{ ...ghostBtn, background: C.accent, color: "#fff", border: "none" }} disabled={!newAccountName.trim() || savingAccount} onClick={saveNewAccount}>{savingAccount ? "…" : "Save"}</button>
              <button type="button" style={ghostBtn} disabled={savingAccount} onClick={() => { setAddingAccount(false); setNewAccountName(""); }}>Cancel</button>
            </div>
          ) : (
            <select
              style={{ ...inputStyle, cursor: customerLocked ? "default" : "pointer" }}
              value={state.customerId}
              disabled={customerLocked}
              title={customerLocked ? "The account can't change once extraction has run." : undefined}
              onChange={(e) => { patch({ customerId: e.target.value }); onCommitDetails({ customer_id: e.target.value }); }}
            >
              {customers.map((c) => <option key={c.customer_id} value={c.customer_id}>{c.customer_name}</option>)}
            </select>
          )}
          {accountError && <p style={{ color: C.alert, fontSize: 11, margin: "2px 0 0" }}>{accountError}</p>}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <label style={fieldLabel}>Submission deadline</label>
          <input
            type="date"
            style={{ ...inputStyle, fontFamily: F.mono }}
            value={state.dueDate}
            onChange={(e) => { patch({ dueDate: e.target.value }); onCommitDetails({ due_date: e.target.value }); }}
          />
        </div>
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: `1px dashed ${C.rule}`, fontSize: 11.5, color: C.inkFaint, lineHeight: 1.5 }}>
          Extraction starts when you continue. Requirements land first, line items follow — you can start reviewing clauses while items are still parsing.
        </div>
      </div>

      {/* Documents + samples */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={card}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <span style={{ fontFamily: F.serif, fontSize: 16 }}>Documents</span>
            <span style={{ fontSize: 11.5, color: C.inkFaint }}>{docCountLabel}</span>
            <button style={{ ...ghostBtn, marginLeft: "auto" }} disabled={busy} onClick={() => fileInputRef.current?.click()}>+ Add document</button>
            <input ref={fileInputRef} type="file" accept=".pdf,.xlsx,.xls,.docx" multiple hidden onChange={(e) => { stageFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
          </div>
          <div
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); stageFiles(Array.from(e.dataTransfer.files ?? [])); }}
            style={{ border: `1.5px dashed ${C.accentLine}`, borderRadius: 10, padding: 18, textAlign: "center", cursor: "pointer", background: C.paper }}
          >
            <div style={{ fontSize: 12.5, color: C.inkSoft }}>Drag &amp; drop bid documents here</div>
            <div style={{ fontSize: 11, color: C.inkFaint, marginTop: 3 }}>PDF, DOCX, XLSX · multiple files per bid</div>
          </div>
          {persisted
            ? savedDocuments.map((d) => (
                <div key={d.doc_id} style={docRow}>
                  <span style={extChip}>{(d.file_format || "doc").toUpperCase()}</span>
                  <a
                    href={`/api/bids/${bidId}/documents/original/${d.doc_id}`}
                    target="_blank"
                    rel="noreferrer"
                    title={d.file_name}
                    style={{ fontSize: 12, color: C.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  >{d.file_name}</a>
                  {/* The server requires a bid to keep at least one document. */}
                  <button
                    onClick={() => onRemoveDocument(d.doc_id)}
                    disabled={busy || savedDocuments.length <= 1}
                    title={savedDocuments.length <= 1 ? "A bid must keep at least one document." : "Remove document"}
                    style={{ ...removeBtn, marginLeft: "auto", opacity: savedDocuments.length <= 1 ? 0.35 : 1 }}
                  >✕</button>
                </div>
              ))
            : state.files.map((f, i) => (
                <div key={`${f.name}-${i}`} style={docRow}>
                  <span style={extChip}>{(f.name.split(".").pop() || "doc").toUpperCase()}</span>
                  <span style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span>
                  <span style={{ marginLeft: "auto", fontSize: 11, color: C.inkFaint, flex: "none" }}>{(f.size / 1024).toFixed(0)} KB</span>
                  <button onClick={() => removeFile(i)} style={removeBtn}>✕</button>
                </div>
              ))}
          {!persisted && state.sample && (
            <div style={{ ...docRow, borderColor: C.accent, background: C.accentSoft }}>
              <span style={extChip}>{state.sample.file_format.toUpperCase()}</span>
              <span style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{state.sample.title}</span>
              <span style={{ marginLeft: "auto", fontSize: 11, color: C.inkFaint, flex: "none" }}>{state.sample.line_count} lines</span>
              <button onClick={() => patch({ sample: null })} style={removeBtn}>✕</button>
            </div>
          )}
        </div>

        {/* Samples seed a brand-new bid, so the picker is only offered before one exists. */}
        <div style={{ ...card, display: persisted ? "none" : undefined }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <span style={{ fontFamily: F.serif, fontSize: 16 }}>Or load a sample solicitation</span>
            <span style={{ fontSize: 11.5, color: C.inkFaint }}>{sampleDocuments.length} government bid letters seeded in the Volume</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(230px,1fr))", gap: 9 }}>
            {sampleDocuments.map((s) => {
              const on = state.sample?.file_name === s.file_name;
              return (
                <button
                  key={s.file_name}
                  disabled={busy}
                  onClick={() => stageSample(s)}
                  style={{
                    textAlign: "left", background: on ? C.accentSoft : "#fff",
                    border: `1px solid ${on ? C.accent : C.rule}`, borderRadius: 8, padding: "10px 12px", cursor: "pointer",
                  }}
                >
                  <span style={{ display: "inline-block", ...extChip, marginBottom: 6 }}>{s.file_format.toUpperCase()}</span>
                  <span style={{ display: "block", fontSize: 12, fontWeight: 600, lineHeight: 1.35 }}>{s.title}</span>
                  <span style={{ display: "block", fontSize: 11, color: C.inkFaint, marginTop: 3 }}>{s.customer_name}</span>
                  <span style={{ display: "block", fontSize: 11, color: C.inkFaint, marginTop: 3 }}>{s.line_count} line items · due in {s.due_in_days} days</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

const docRow: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, marginTop: 8, padding: "7px 10px",
  border: `1px solid ${C.rule}`, borderRadius: 8, background: "#fff",
};
const extChip: React.CSSProperties = {
  fontFamily: F.mono, fontSize: 9.5, fontWeight: 700, textTransform: "uppercase",
  background: C.wash, color: C.inkSoft, borderRadius: 4, padding: "2px 5px", flex: "none",
};
const removeBtn: React.CSSProperties = {
  background: "none", border: "none", color: C.inkFaint, fontSize: 13, cursor: "pointer", padding: "0 3px", flex: "none",
};
