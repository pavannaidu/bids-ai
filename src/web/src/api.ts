import type {
  AppSettings,
  Bid,
  BidSummary,
  CandidateMatch,
  CurrentUser,
  Customer,
  ExtractionMethodSetting,
  MatchMode,
  MatchSensitivity,
  ResponsibilityMatrix,
  ReviewStatus,
  RiskLevel,
  SampleDocument,
} from "./types";

interface BlockingLineDetail {
  line_number: number;
  reasons: string[];
}

async function asJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const raw = await response.text();
    let message = raw || `Request failed: ${response.status}`;
    try {
      const body = JSON.parse(raw) as { detail?: unknown };
      const detail = body?.detail;
      if (detail && typeof detail === "object" && Array.isArray((detail as { blocking_lines?: unknown }).blocking_lines)) {
        const structured = detail as { message?: string; blocking_lines: BlockingLineDetail[] };
        const lines = structured.blocking_lines
          .map((b) => `Line ${b.line_number} (${b.reasons.join(", ")})`)
          .join("; ");
        message = `${structured.message ?? "Cannot generate proposal"} — ${lines}`;
      } else if (typeof detail === "string") {
        message = detail;
      }
    } catch {
      // raw wasn't JSON — keep the plain-text message already set above
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export async function fetchCustomers(): Promise<Customer[]> {
  const res = await fetch("/api/customers");
  const data = await asJson<{ customers: Customer[] }>(res);
  return data.customers;
}

export async function createCustomer(name: string): Promise<Customer> {
  const res = await fetch("/api/customers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customer_name: name }),
  });
  const data = await asJson<{ customer: Customer }>(res);
  return data.customer;
}

export async function fetchSampleDocuments(): Promise<SampleDocument[]> {
  const res = await fetch("/api/sample-documents");
  const data = await asJson<{ documents: SampleDocument[] }>(res);
  return data.documents;
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const res = await fetch("/api/me");
  return asJson<CurrentUser>(res);
}

export async function fetchBids(): Promise<BidSummary[]> {
  const res = await fetch("/api/bids");
  const data = await asJson<{ bids: BidSummary[] }>(res);
  return data.bids;
}

export async function uploadBidFile(files: File[], customerId: string, dueDate: string, bidName: string): Promise<Bid> {
  const form = new FormData();
  // Field name must be "files" to match the backend's list[UploadFile] param.
  files.forEach((file) => form.append("files", file));
  const params = new URLSearchParams({ customer_id: customerId, due_date: dueDate, bid_name: bidName });
  const res = await fetch(`/api/bids/upload?${params.toString()}`, {
    method: "POST",
    body: form,
  });
  return asJson<Bid>(res);
}

export async function uploadSampleBid(
  sampleFileName: string,
  customerId: string,
  dueDate: string,
  bidName: string,
): Promise<Bid> {
  const res = await fetch("/api/bids/upload-sample", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sample_file_name: sampleFileName, customer_id: customerId, due_date: dueDate, bid_name: bidName,
    }),
  });
  return asJson<Bid>(res);
}

// Optional `manufacturers` restricts Vector Search to those brands' catalog
// items before ranking (pre-search filter, match-ANY) — used when a
// solicitation mandates preferred/awarded manufacturers. Empty = unconstrained.
// `mode` (a re-run scope) is only sent when provided — the first run omits it and
// the server defaults to "unmatched". A mode forces a JSON body even with no
// manufacturer filter, so "all" reaches the server on its own.
export async function matchBid(
  bidId: string, manufacturers: string[] = [], mode?: MatchMode,
): Promise<Bid> {
  const body: { manufacturers?: string[]; mode?: MatchMode } = {};
  if (manufacturers.length) body.manufacturers = manufacturers;
  if (mode) body.mode = mode;
  const res = await fetch(
    `/api/bids/${bidId}/match`,
    Object.keys(body).length
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : { method: "POST" },
  );
  return asJson<Bid>(res);
}

export async function fetchManufacturers(): Promise<string[]> {
  const res = await fetch("/api/catalog/manufacturers");
  const data = await asJson<{ manufacturers: string[] }>(res);
  return data.manufacturers;
}

// Phase-2 extraction, split out of upload so each call stays under the gateway.
// Fired in parallel after the Upload step; each returns the updated bid. Pass a
// `method` to force ai_extract/ai_query for a re-extraction; omit it to use the
// global default (backs the Requirements-step "Re-extract" control).
function extractBody(method?: ExtractionMethodSetting): RequestInit {
  return method
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ method }) }
    : { method: "POST" };
}

export async function extractRequirements(bidId: string, method?: ExtractionMethodSetting): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/extract-requirements`, extractBody(method));
  return asJson<Bid>(res);
}

export async function extractLineItems(bidId: string, method?: ExtractionMethodSetting): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/extract-line-items`, extractBody(method));
  return asJson<Bid>(res);
}

// App-level settings (Settings pane). GET reads the current global default;
// PATCH sets it (process-local on the server — resets on redeploy).
export async function fetchSettings(): Promise<AppSettings> {
  const res = await fetch("/api/settings");
  return asJson<AppSettings>(res);
}

// Partial settings PATCH — send only the fields being changed.
export async function updateSettings(
  fields: { extraction_method?: ExtractionMethodSetting; match_sensitivity?: MatchSensitivity },
): Promise<AppSettings> {
  const res = await fetch("/api/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  return asJson<AppSettings>(res);
}

export async function deleteDocument(bidId: string, docId: string): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/documents/${docId}`, { method: "DELETE" });
  return asJson<Bid>(res);
}

// Edit a staged bid's metadata (Upload step). Only the provided fields change;
// customer_id is only accepted before extraction runs (backend 409 otherwise).
export async function updateBid(
  bidId: string,
  fields: { bid_name?: string; due_date?: string; customer_id?: string },
): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  return asJson<Bid>(res);
}

// Add one or more documents to a staged bid (Upload step).
export async function addDocuments(bidId: string, files: File[]): Promise<Bid> {
  const form = new FormData();
  // Field name must be "files" to match the backend's list[UploadFile] param.
  files.forEach((file) => form.append("files", file));
  const res = await fetch(`/api/bids/${bidId}/documents`, { method: "POST", body: form });
  return asJson<Bid>(res);
}

export async function repriceLine(
  bidId: string,
  lineId: string,
  itemCode: string,
): Promise<{ item_code: string; proposed_price: number | null; pricing_basis: string }> {
  const params = new URLSearchParams({ item_code: itemCode });
  const res = await fetch(`/api/bids/${bidId}/lines/${lineId}/price?${params.toString()}`, { method: "POST" });
  return asJson(res);
}

export async function updateLineItem(
  bidId: string,
  lineId: string,
  fields: { raw_description: string; qty: number; uom: string; given_code: string | null },
): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/lines/${lineId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  return asJson<Bid>(res);
}

export async function getBid(bidId: string): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}`);
  return asJson<Bid>(res);
}

export async function reviewLine(
  bidId: string,
  lineId: string,
  selectedItemCode: string,
  proposedPrice: number,
  reviewAction: "accepted" | "overridden",
): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/lines/${lineId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      selected_item_code: selectedItemCode,
      proposed_price: proposedPrice,
      review_action: reviewAction,
    }),
  });
  return asJson<Bid>(res);
}

export async function acceptAllLines(bidId: string): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/lines/accept-all`, { method: "POST" });
  return asJson<Bid>(res);
}

export async function submitBid(bidId: string): Promise<{ bid: Bid; proposal_pdf_url: string; proposal_excel_url: string }> {
  const res = await fetch(`/api/bids/${bidId}/submit`, { method: "POST" });
  return asJson(res);
}

export async function addLineItem(
  bidId: string,
  fields: { raw_description?: string; qty?: number; uom?: string; given_code?: string | null },
): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/lines`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  return asJson<Bid>(res);
}

export async function deleteLineItem(bidId: string, lineId: string): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/lines/${lineId}`, { method: "DELETE" });
  return asJson<Bid>(res);
}

export async function searchCatalog(
  bidId: string, lineId: string, q: string, manufacturers: string[] = [],
): Promise<CandidateMatch[]> {
  const params = new URLSearchParams({ q });
  // Repeatable query param: ?manufacturers=3M&manufacturers=Medline (match-ANY).
  manufacturers.forEach((m) => params.append("manufacturers", m));
  const res = await fetch(`/api/bids/${bidId}/lines/${lineId}/search?${params.toString()}`);
  const data = await asJson<{ candidates: CandidateMatch[] }>(res);
  return data.candidates;
}

export async function manualMatchLine(bidId: string, lineId: string, itemCode: string): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/lines/${lineId}/manual-match`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_code: itemCode }),
  });
  return asJson<Bid>(res);
}

// Mark a line as having no catalog match. No reason needed; the backend clears
// code/price and resolves the line (it renders blank in the proposal).
export async function noMatchLine(bidId: string, lineId: string): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/lines/${lineId}/no-match`, { method: "POST" });
  return asJson<Bid>(res);
}

export async function fetchResponsibilityMatrix(): Promise<ResponsibilityMatrix> {
  const res = await fetch("/api/responsibility-matrix");
  return asJson<ResponsibilityMatrix>(res);
}

// Add or edit a matrix term (Compliance Matrix page). The server returns the
// full merged matrix so the caller can replace its state in one shot.
export async function upsertMatrixTerm(term: {
  term_label: string;
  owning_teams: string[];
  default_risk: RiskLevel;
  description: string;
  is_trigger: boolean;
}): Promise<ResponsibilityMatrix> {
  const res = await fetch("/api/responsibility-matrix/terms", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(term),
  });
  return asJson<ResponsibilityMatrix>(res);
}

export async function deleteMatrixTerm(termLabel: string): Promise<ResponsibilityMatrix> {
  const res = await fetch("/api/responsibility-matrix/terms", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ term_label: termLabel }),
  });
  return asJson<ResponsibilityMatrix>(res);
}

export interface RequirementPatch {
  term_label?: string;
  raw_text?: string;
  category?: string;
  risk_level?: RiskLevel;
  owning_teams?: string[];
  review_status?: ReviewStatus;
  note?: string;
}

export async function updateRequirement(
  bidId: string,
  requirementId: string,
  fields: RequirementPatch,
): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/requirements/${requirementId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  return asJson<Bid>(res);
}

export async function addRequirement(
  bidId: string,
  fields: { term_label: string; raw_text?: string; category?: string; risk_level?: RiskLevel; owning_teams?: string[] },
): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/requirements`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  return asJson<Bid>(res);
}

export async function deleteRequirement(bidId: string, requirementId: string): Promise<Bid> {
  const res = await fetch(`/api/bids/${bidId}/requirements/${requirementId}`, { method: "DELETE" });
  return asJson<Bid>(res);
}
