import { useEffect, useMemo, useState } from "react";
import {
  acceptAllLines, addLineItem, addRequirement, addDocuments, createCustomer, deleteDocument, deleteLineItem,
  deleteRequirement, extractLineItems, extractRequirements, fetchBids, fetchCurrentUser, fetchCustomers,
  fetchManufacturers, fetchResponsibilityMatrix, fetchSampleDocuments, fetchSettings,
  getBid, manualMatchLine, matchBid, noMatchLine, reviewLine, submitBid, updateBid,
  updateLineItem, updateRequirement, updateSettings, uploadBidFile, uploadSampleBid,
  type RequirementPatch,
} from "./api";
import { C, F } from "./theme";
import Sidebar, { type NavTab } from "./components/Sidebar";
import StepRail, { STEPS, stepIndex, type StepId } from "./components/StepRail";
import DocumentPane from "./components/DocumentPane";
import UploadScreen, { type UploadState } from "./components/UploadScreen";
import RequirementsScreen from "./components/RequirementsScreen";
import LineItemsScreen from "./components/LineItemsScreen";
import MatchScreen from "./components/MatchScreen";
import GenerateScreen from "./components/GenerateScreen";
import AllBidsScreen from "./components/AllBidsScreen";
import MatrixScreen from "./components/MatrixScreen";
import type {
  Bid, BidSummary, CurrentUser, Customer, ExtractionMethodSetting, MatchMode,
  MatchSensitivity, ResponsibilityMatrix, SampleDocument,
} from "./types";

type Screen = "wizard" | "all-bids" | "matrix";
const SIDEBAR_KEY = "bids-wb:sidebar-collapsed";
const DOC_KEY = "bids-wb:doc-open";

function isoPlusDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function resolveResumeStep(bid: Bid): StepId {
  if (bid.status === "submitted") return "generate";
  if (bid.line_items.some((l) => l.review_action !== "pending" || l.candidates.length)) return "match";
  if (bid.line_items.length) return "line-items";
  if (bid.requirements.length) return "requirements";
  return "upload";
}

export default function App() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [sampleDocuments, setSampleDocuments] = useState<SampleDocument[]>([]);
  const [matrix, setMatrix] = useState<ResponsibilityMatrix | null>(null);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [bid, setBid] = useState<Bid | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [matching, setMatching] = useState(false);
  const [requirementsLoading, setRequirementsLoading] = useState(false);
  const [lineItemsLoading, setLineItemsLoading] = useState(false);
  const [acceptingAll, setAcceptingAll] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [downloadLinks, setDownloadLinks] = useState<{ pdf: string; excel: string } | null>(null);

  const [screen, setScreen] = useState<Screen>("wizard");
  const [viewStep, setViewStep] = useState<StepId>("upload");
  const [maxStep, setMaxStep] = useState<StepId>("upload");
  const [historyBids, setHistoryBids] = useState<BidSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(SIDEBAR_KEY) === "1");
  const [docOpen, setDocOpen] = useState(() => localStorage.getItem(DOC_KEY) === "1");
  const [docFocus, setDocFocus] = useState<{ docId: string; nonce: number } | null>(null);

  const [extractionMethod, setExtractionMethod] = useState<ExtractionMethodSetting>("ai_extract");
  const [matchSensitivity, setMatchSensitivity] = useState<MatchSensitivity>("balanced");
  const [matchThreshold, setMatchThreshold] = useState(0.7);

  const [manufacturers, setManufacturers] = useState<string[]>([]);
  const [matchManufacturers, setMatchManufacturers] = useState<string[]>([]);
  const [scope, setScope] = useState("all");
  const [materialOpen, setMaterialOpen] = useState(false);

  const [upload, setUpload] = useState<UploadState>({ customerId: "", dueDate: isoPlusDays(14), bidName: "", files: [], sample: null });

  const toggleSidebar = () => setCollapsed((c) => { const n = !c; localStorage.setItem(SIDEBAR_KEY, n ? "1" : "0"); return n; });
  const toggleDoc = () => setDocOpen((d) => { const n = !d; localStorage.setItem(DOC_KEY, n ? "1" : "0"); return n; });

  function applyResumedBid(resumed: Bid) {
    setBid(resumed);
    // Rehydrate the Upload step from the saved bid, otherwise it keeps showing
    // the blank new-bid defaults while the step rail shows the real bid.
    setUpload({
      customerId: resumed.customer_id,
      dueDate: (resumed.due_date || "").slice(0, 10) || isoPlusDays(14),
      bidName: resumed.bid_name,
      files: [],
      sample: null,
    });
    const step = resolveResumeStep(resumed);
    setViewStep(step);
    setMaxStep(step);
    setDownloadLinks(resumed.status === "submitted"
      ? { pdf: `/api/bids/${resumed.bid_id}/documents/pdf`, excel: `/api/bids/${resumed.bid_id}/documents/excel` }
      : null);
    setScreen("wizard");
  }

  function syncFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const bidId = params.get("bid");
    const view = params.get("view");
    if (bidId) {
      getBid(bidId).then(applyResumedBid).catch((e) => { setError(String(e)); window.history.replaceState(null, "", window.location.pathname); });
    } else if (view === "all-bids") { setScreen("all-bids"); loadHistory(); }
    else if (view === "matrix") setScreen("matrix");
    else setScreen("wizard");
  }

  useEffect(() => {
    fetchCustomers().then((cs) => { setCustomers(cs); setUpload((u) => u.customerId ? u : { ...u, customerId: cs[0]?.customer_id ?? "" }); }).catch((e) => setError(String(e)));
    fetchSampleDocuments().then(setSampleDocuments).catch((e) => setError(String(e)));
    fetchResponsibilityMatrix().then(setMatrix).catch((e) => setError(String(e)));
    fetchManufacturers().then(setManufacturers).catch((e) => setError(String(e)));
    fetchCurrentUser().then(setCurrentUser).catch((e) => setError(String(e)));
    fetchSettings().then((s) => { setExtractionMethod(s.extraction_method); setMatchSensitivity(s.match_sensitivity); setMatchThreshold(s.match_threshold); }).catch((e) => setError(String(e)));
    syncFromUrl();
    window.addEventListener("popstate", syncFromUrl);
    return () => window.removeEventListener("popstate", syncFromUrl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadHistory = async () => {
    setHistoryLoading(true);
    try { setHistoryBids(await fetchBids()); }
    catch (e) { setError(String(e)); }
    finally { setHistoryLoading(false); }
  };

  const advanceTo = (step: StepId) => {
    setViewStep(step);
    setMaxStep((prev) => (stepIndex(step) > stepIndex(prev) ? step : prev));
  };

  // --- navigation ---
  const activeTab: NavTab = screen === "all-bids" ? "all-bids" : screen === "matrix" ? "matrix" : "workbench";
  const navigate = (tab: NavTab) => {
    if (tab === "all-bids") { setScreen("all-bids"); window.history.pushState(null, "", "?view=all-bids"); loadHistory(); }
    else if (tab === "matrix") { setScreen("matrix"); window.history.pushState(null, "", "?view=matrix"); }
    else { setScreen("wizard"); window.history.pushState(null, "", bid ? `?bid=${bid.bid_id}` : window.location.pathname); }
  };

  const resetToNewBid = () => {
    setBid(null); setDownloadLinks(null); setError(null);
    setRequirementsLoading(false); setLineItemsLoading(false);
    setViewStep("upload"); setMaxStep("upload"); setScreen("wizard");
    setUpload({ customerId: customers[0]?.customer_id ?? "", dueDate: isoPlusDays(14), bidName: "", files: [], sample: null });
    window.history.pushState(null, "", window.location.pathname);
  };

  const resumeBid = async (bidId: string) => {
    setError(null);
    try { const resumed = await getBid(bidId); applyResumedBid(resumed); window.history.pushState(null, "", `?bid=${resumed.bid_id}`); }
    catch (e) { setError(String(e)); }
  };

  // --- upload / extraction ---
  const handleCreateCustomer = async (name: string): Promise<Customer> => {
    const created = await createCustomer(name);
    setCustomers((prev) => [...prev, created]);
    return created;
  };

  // Once the bid exists its documents are server-side, so the Upload step's
  // add/remove go straight to the API and replace the bid with the response.
  const handleAddDocuments = async (files: File[]) => {
    if (!bid || !files.length) return;
    setBusy(true); setError(null);
    try { setBid(await addDocuments(bid.bid_id, files)); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };

  const handleRemoveDocument = async (docId: string) => {
    if (!bid) return;
    setBusy(true); setError(null);
    try { setBid(await deleteDocument(bid.bid_id, docId)); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };

  const commitBidDetails = async (fields: { bid_name?: string; due_date?: string; customer_id?: string }) => {
    if (!bid) return;
    try { setBid(await updateBid(bid.bid_id, fields)); } catch (e) { setError(String(e)); }
  };

  const startExtraction = async () => {
    // If no bid yet, upload the staged files/sample first, then fire extraction.
    setBusy(true); setError(null);
    try {
      let active = bid;
      if (!active) {
        if (!upload.customerId) { setError("Pick an account first."); return; }
        const name = upload.bidName.trim();
        if (upload.files.length) active = await uploadBidFile(upload.files, upload.customerId, upload.dueDate, name);
        else if (upload.sample) active = await uploadSampleBid(upload.sample.file_name, upload.customerId, upload.dueDate, name);
        else { setError("Add a document or pick a sample solicitation."); return; }
        setBid(active);
        // The documents are server-side now; the Upload step reads them off the bid.
        setUpload((u) => ({ ...u, files: [], sample: null }));
      }
      const id = active!.bid_id;
      setRequirementsLoading(true); setLineItemsLoading(true);
      advanceTo("requirements");
      extractRequirements(id).then((b) => setBid((prev) => ({ ...(prev ?? b), requirements: b.requirements, review_verdict: b.review_verdict }))).catch((e) => setError(String(e))).finally(() => setRequirementsLoading(false));
      extractLineItems(id).then((b) => setBid((prev) => ({ ...(prev ?? b), line_items: b.line_items, status: b.status }))).catch((e) => setError(String(e))).finally(() => setLineItemsLoading(false));
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };

  const reextractRequirements = () => {
    if (!bid) return;
    setError(null); setRequirementsLoading(true);
    extractRequirements(bid.bid_id, extractionMethod).then((b) => setBid((prev) => ({ ...(prev ?? b), requirements: b.requirements, review_verdict: b.review_verdict }))).catch((e) => setError(String(e))).finally(() => setRequirementsLoading(false));
  };
  const reextractLineItems = () => {
    if (!bid) return;
    setError(null); setLineItemsLoading(true);
    extractLineItems(bid.bid_id, extractionMethod).then((b) => setBid((prev) => ({ ...(prev ?? b), line_items: b.line_items, status: b.status }))).catch((e) => setError(String(e))).finally(() => setLineItemsLoading(false));
  };

  // --- settings ---
  const saveExtractionMethod = async (m: ExtractionMethodSetting) => {
    setExtractionMethod(m);
    try { const s = await updateSettings({ extraction_method: m }); setExtractionMethod(s.extraction_method); } catch (e) { setError(String(e)); }
  };
  const saveMatchSensitivity = async (s: MatchSensitivity) => {
    setMatchSensitivity(s);
    try { const saved = await updateSettings({ match_sensitivity: s }); setMatchSensitivity(saved.match_sensitivity); setMatchThreshold(saved.match_threshold); } catch (e) { setError(String(e)); }
  };

  // --- line items ---
  const handleUpdateLine = async (lineId: string, fields: { raw_description: string; qty: number; uom: string; given_code: string | null }) => {
    if (!bid) return;
    try { setBid(await updateLineItem(bid.bid_id, lineId, fields)); } catch (e) { setError(String(e)); }
  };
  const handleAddLine = async () => { if (bid) try { setBid(await addLineItem(bid.bid_id, {})); } catch (e) { setError(String(e)); } };
  const handleDeleteLine = async (lineId: string) => { if (bid) try { setBid(await deleteLineItem(bid.bid_id, lineId)); } catch (e) { setError(String(e)); } };

  // --- requirements ---
  const handleUpdateRequirement = async (requirementId: string, fields: RequirementPatch) => {
    if (!bid) return;
    try { setBid(await updateRequirement(bid.bid_id, requirementId, fields)); } catch (e) { setError(String(e)); }
  };
  // Add a clause the extractor missed. term_label + owning_teams + risk are
  // pre-filled from the first matrix term client-side; the reviewer reclassifies
  // via the term dropdown afterward.
  const handleAddRequirement = async () => {
    if (!bid) return;
    const seed = matrix?.terms[0];
    try {
      setBid(await addRequirement(bid.bid_id, {
        term_label: seed?.term_label ?? "New clause",
        raw_text: "",
        owning_teams: seed?.owning_teams ?? [],
        risk_level: seed?.default_risk,
      }));
    } catch (e) { setError(String(e)); }
  };
  const handleDeleteRequirement = async (requirementId: string) => {
    if (!bid) return;
    try { setBid(await deleteRequirement(bid.bid_id, requirementId)); } catch (e) { setError(String(e)); }
  };

  // --- match ---
  const confirmAndMatch = async () => {
    if (!bid) return;
    setMatching(true); setError(null);
    try { setBid(await matchBid(bid.bid_id, matchManufacturers)); advanceTo("match"); }
    catch (e) { setError(String(e)); }
    finally { setMatching(false); }
  };
  const rematch = async (mode: MatchMode) => {
    if (!bid) return;
    setMatching(true); setError(null);
    try { setBid(await matchBid(bid.bid_id, matchManufacturers, mode)); }
    catch (e) { setError(String(e)); }
    finally { setMatching(false); }
  };
  const handleReview = async (lineId: string, code: string, price: number, action: "accepted" | "overridden") => {
    if (!bid) return;
    try { setBid(await reviewLine(bid.bid_id, lineId, code, price, action)); } catch (e) { setError(String(e)); }
  };
  const handleManualMatch = async (lineId: string, code: string) => { if (bid) try { setBid(await manualMatchLine(bid.bid_id, lineId, code)); } catch (e) { setError(String(e)); } };
  const handleNoMatch = async (lineId: string) => { if (bid) try { setBid(await noMatchLine(bid.bid_id, lineId)); } catch (e) { setError(String(e)); } };
  const acceptAll = async () => {
    if (!bid) return;
    setAcceptingAll(true); setError(null);
    try { setBid(await acceptAllLines(bid.bid_id)); } catch (e) { setError(String(e)); } finally { setAcceptingAll(false); }
  };

  // --- generate ---
  const generate = async () => {
    if (!bid) return;
    setSubmitting(true); setError(null);
    try { const r = await submitBid(bid.bid_id); setBid(r.bid); setDownloadLinks({ pdf: r.proposal_pdf_url, excel: r.proposal_excel_url }); }
    catch (e) { setError(String(e)); }
    finally { setSubmitting(false); }
  };

  const openSource = (docId: string) => { setDocFocus((p) => ({ docId, nonce: (p?.nonce ?? 0) + 1 })); setDocOpen(true); };

  // Accept-all counts (mirror server/validation).
  const pendingReviewCount = bid ? bid.line_items.filter((l) => l.review_action === "pending" && l.selected_item_code && l.candidates.find((c) => c.item_code === l.selected_item_code)?.auto_select_eligible).length : 0;
  const exceptionsCount = bid ? bid.line_items.filter((l) => l.review_action === "pending" && l.resolution !== "no_match").length - pendingReviewCount : 0;
  const acceptAllTotal = pendingReviewCount + exceptionsCount;

  const reqApproved = bid ? bid.requirements.filter((r) => r.review_status === "approved").length : 0;

  // Reviewer queue derived from requirement routing.
  const queue = useMemo(() => {
    if (!bid || !bid.requirements.length) return null;
    const counts: Record<string, number> = {};
    bid.requirements.forEach((r) => r.owning_teams.forEach((t) => { counts[t] = (counts[t] ?? 0) + 1; }));
    const teams = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([team, count]) => ({ team, count }));
    return [{ team: "all", count: bid.requirements.length }, ...teams];
  }, [bid]);

  // Top-bar primary action per step.
  const primary: { label: string; onClick: () => void; disabled?: boolean } = (() => {
    switch (viewStep) {
      case "upload": return { label: busy ? "Extracting…" : "Continue → extract", onClick: startExtraction, disabled: busy };
      case "requirements": return { label: "Continue to line items →", onClick: () => advanceTo("line-items") };
      case "line-items": return { label: matching ? "Finding matches…" : "Confirm & find matches →", onClick: confirmAndMatch, disabled: matching || lineItemsLoading };
      case "match": return { label: "Continue to generate →", onClick: () => advanceTo("generate") };
      case "generate": return { label: downloadLinks ? "Download proposal" : submitting ? "Generating…" : "Generate proposal", onClick: () => downloadLinks ? window.open(downloadLinks.pdf, "_blank") : generate(), disabled: submitting };
    }
  })();

  const bidMeta = bid ? `${bid.customer_name}${bid.due_date ? ` · Due ${bid.due_date}` : ""}${(bid.documents?.length ?? 0) > 1 ? ` · ${bid.documents.length} files` : ""}` : "";
  const showDocPane = screen === "wizard" && !!bid && (bid.documents?.length ?? 0) > 0;

  const listHeader = screen === "all-bids"
    ? { title: "All Bids", sub: "Every bid started on this app — pick one up where you left off." }
    : { title: "Compliance Matrix", sub: "BRD Glossary responsibility matrix — who owns which clause types." };

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: C.paper, color: C.ink, fontFamily: F.sans }}>
      <Sidebar
        collapsed={collapsed}
        onToggleCollapse={toggleSidebar}
        active={activeTab}
        onNavigate={navigate}
        onNewBid={resetToNewBid}
        queue={screen === "wizard" ? queue : null}
        scope={scope}
        onScope={(t) => { setScope(t); if (bid) { setScreen("wizard"); advanceTo("requirements"); } }}
        name={currentUser?.name ?? ""}
        email={currentUser?.email ?? ""}
        extractionMethod={extractionMethod}
        matchSensitivity={matchSensitivity}
        matchThreshold={matchThreshold}
        onExtractionMethod={saveExtractionMethod}
        onMatchSensitivity={saveMatchSensitivity}
      />

      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        {screen === "wizard" && bid && (
          <StepRail
            bidName={bid.bid_name || bid.file_name}
            bidId={bid.bid_id}
            meta={bidMeta}
            primaryLabel={primary.label}
            primaryDisabled={primary.disabled}
            onPrimary={primary.onClick}
            viewStep={viewStep}
            maxStep={maxStep}
            onStepClick={(s) => { if (stepIndex(s) <= stepIndex(maxStep)) setViewStep(s); }}
          />
        )}
        {screen === "wizard" && !bid && (
          <div style={{ flex: "none", background: "#fff", borderBottom: `1px solid ${C.rule}`, padding: "12px 18px", display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontFamily: F.serif, fontSize: 19, lineHeight: 1.1 }}>New Bid</div>
              <div style={{ fontSize: 11.5, color: C.inkFaint, marginTop: 3 }}>Upload a solicitation and turn it into a priced, reviewed proposal.</div>
            </div>
            {/* Before a bid exists the step rail (which carries the primary action)
                isn't shown yet, so surface "Continue → extract" here. It's enabled
                once a document is staged. */}
            <button
              onClick={primary.onClick}
              disabled={busy || (upload.files.length === 0 && !upload.sample)}
              title={upload.files.length === 0 && !upload.sample ? "Add a document or pick a sample solicitation first" : undefined}
              style={{
                marginLeft: "auto", flex: "none", background: C.accent, color: "#fff", border: "none",
                borderRadius: 6, padding: "7px 14px", fontSize: 12.5, fontWeight: 600,
                cursor: busy || (upload.files.length === 0 && !upload.sample) ? "default" : "pointer",
                opacity: busy || (upload.files.length === 0 && !upload.sample) ? 0.55 : 1,
              }}
            >{busy ? "Extracting…" : "Continue → extract"}</button>
          </div>
        )}
        {screen !== "wizard" && (
          <div style={{ flex: "none", background: "#fff", borderBottom: `1px solid ${C.rule}`, padding: "12px 18px" }}>
            <div style={{ fontFamily: F.serif, fontSize: 19, lineHeight: 1.1 }}>{listHeader.title}</div>
            <div style={{ fontSize: 11.5, color: C.inkFaint, marginTop: 3 }}>{listHeader.sub}</div>
          </div>
        )}

        <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ flex: 1, overflow: "auto", padding: "14px 18px 18px" }}>
              {error && (
                <div style={{ background: C.alertSoft, border: `1px solid ${C.alertLine}`, color: C.alert, borderRadius: 8, padding: "8px 12px", marginBottom: 12, fontSize: 12.5 }}>{error}</div>
              )}

              {screen === "all-bids" && <AllBidsScreen bids={historyBids} loading={historyLoading} onOpen={resumeBid} />}
              {screen === "matrix" && <MatrixScreen matrix={matrix} onMatrixChange={setMatrix} />}

              {screen === "wizard" && viewStep === "upload" && (
                <UploadScreen
                  customers={customers}
                  sampleDocuments={sampleDocuments}
                  state={upload}
                  onState={setUpload}
                  onCreateCustomer={handleCreateCustomer}
                  busy={busy}
                  bidId={bid?.bid_id ?? null}
                  savedDocuments={bid?.documents ?? []}
                  onAddDocuments={handleAddDocuments}
                  onRemoveDocument={handleRemoveDocument}
                  onCommitDetails={commitBidDetails}
                  customerLocked={!!bid && bid.status !== "uploaded"}
                />
              )}
              {screen === "wizard" && viewStep === "requirements" && bid && (
                <RequirementsScreen bid={bid} matrix={matrix} loading={requirementsLoading} scope={scope} onUpdate={handleUpdateRequirement} onAdd={handleAddRequirement} onDelete={handleDeleteRequirement} onReextract={reextractRequirements} materialOpen={materialOpen} onToggleMaterial={() => setMaterialOpen((o) => !o)} />
              )}
              {screen === "wizard" && viewStep === "line-items" && bid && (
                <LineItemsScreen bid={bid} loading={lineItemsLoading} manufacturers={manufacturers} matchManufacturers={matchManufacturers} onMatchManufacturers={setMatchManufacturers} onUpdateLine={handleUpdateLine} onAddLine={handleAddLine} onDeleteLine={handleDeleteLine} onReextract={reextractLineItems} onOpenSource={openSource} />
              )}
              {screen === "wizard" && viewStep === "match" && bid && (
                <MatchScreen bidId={bid.bid_id} lines={bid.line_items} matching={matching} acceptingAll={acceptingAll} manufacturers={manufacturers} matchManufacturers={matchManufacturers} onMatchManufacturers={setMatchManufacturers} matchThreshold={matchThreshold} matchSensitivity={matchSensitivity} onReview={handleReview} onManualMatch={handleManualMatch} onNoMatch={handleNoMatch} onRematch={rematch} onAcceptAll={acceptAll} acceptAllTotal={acceptAllTotal} exceptionsCount={exceptionsCount} />
              )}
              {screen === "wizard" && viewStep === "generate" && bid && (
                <GenerateScreen bid={bid} reqApproved={reqApproved} reqTotal={bid.requirements.length} submitting={submitting} downloadLinks={downloadLinks} onGenerate={generate} onFix={(step) => advanceTo(step)} />
              )}
            </div>
          </div>

          {showDocPane && bid && (
            <DocumentPane bidId={bid.bid_id} documents={bid.documents} open={docOpen} onToggle={toggleDoc} focus={docFocus} />
          )}
        </div>
      </div>
    </div>
  );
}
