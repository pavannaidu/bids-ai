export interface CurrentUser {
  email: string;
  name: string;
  authenticated: boolean;
}

export interface Customer {
  customer_id: string;
  customer_name: string;
  division_id: string;
  customer_type: string;
  region: string;
}

export interface SampleDocument {
  file_name: string;
  file_format: string;
  title: string;
  customer_name: string;
  customer_id: string;
  solicitation_ref: string;
  due_in_days: number;
  line_count: number;
  lines_with_given_code: number;
}

export interface CandidateMatch {
  item_code: string;
  description_long: string;
  manufacturer_name: string | null;
  category: string | null;
  list_price: number | null;
  score: number;
  retrieval_score?: number | null;
  semantic_score?: number | null;
  source: "catalog" | "purchase_history" | "general_knowledge" | "manual_search";
  rationale: string;
  history_snippet: string;
  review_flag?: string | null;
  // Guardrail: whether this candidate is safe to auto-select; guard_reason is a
  // code when not (below_confidence_threshold / confidence_unavailable /
  // uom_mismatch / hard_incompatibility / low_specificity / not_catalog_source).
  auto_select_eligible?: boolean;
  guard_reason?: string | null;
}

export type MatchSensitivity = "conservative" | "balanced" | "permissive";

export type LineResolution = "pending" | "catalog_match" | "no_match";

// Re-run scope for /match: "unmatched" preserves human-resolved lines, "all"
// discards every pick and re-matches from scratch.
export type MatchMode = "unmatched" | "all";

// How a row's TEXT was pulled from the document (distinct from a requirement's
// `source`, which is how it was routed). "ai_extract" is the primary path;
// "ai_query" is the recovery fallback; "heuristic" is a last-resort line split;
// "manual" is a reviewer-added row.
export type ExtractionMethod = "ai_extract" | "ai_query" | "heuristic" | "manual";

// The two extraction methods a user can choose for a (re-)extraction — the
// primary structured path vs. the legacy prompt path. Subset of ExtractionMethod
// (the auto-only "heuristic"/"manual" values aren't user-selectable).
export type ExtractionMethodSetting = "ai_extract" | "ai_query";

// App-level settings surfaced from the backend (GET /api/settings): the global
// default extraction method + the match sensitivity (and its effective numeric
// threshold, for read-only helper text).
export interface AppSettings {
  extraction_method: ExtractionMethodSetting;
  match_sensitivity: MatchSensitivity;
  match_threshold: number;
}

// Source-traceability carried by every extracted line item and requirement.
// All optional — older rows / manual additions may lack some; source_page is
// best-effort (null when the row couldn't be pinned to one page).
export interface Provenance {
  source_doc_id?: string | null;
  source_filename?: string | null;
  source_page?: number | null;
  extraction_method?: ExtractionMethod;
  confidence?: number | null;
}

export interface PricedLineItem extends Provenance {
  line_id: string;
  line_number: number;
  raw_description: string;
  qty: number;
  uom: string;
  given_code: string | null;
  candidates: CandidateMatch[];
  selected_item_code: string | null;
  proposed_price: number | null;
  pricing_basis: string;
  review_action: "pending" | "accepted" | "overridden";
  reviewer_email: string | null;
  resolution?: LineResolution;
}

export type RiskLevel = "high" | "medium" | "low";

export type ReviewStatus =
  | "pending"
  | "in_review"
  | "approved"
  | "rejected"
  | "needs_changes"
  | "not_applicable";

export interface RequirementItem extends Provenance {
  requirement_id: string;
  term_label: string;
  raw_text: string;
  // Grounded in the BRD Glossary matrix; a term can be jointly owned. Editable per bid.
  owning_teams: string[];
  // risk_level/risk_rationale are an automated risk-analysis layer, not from the BRD Glossary.
  // Empty string = not assessed yet (unclassified rows) — the UI shows "—".
  risk_level: RiskLevel | "";
  risk_rationale: string;
  matched_term: string | null;
  source: "matrix" | "ai_classified" | "ai_suggested" | "manual";
  review_status: ReviewStatus;
  note: string;
  assigned_to: string | null;
  last_updated_by: string | null;
  last_updated_at: string | null;
}

export interface MatrixTerm {
  term_label: string;
  owning_teams: string[];
  default_risk: RiskLevel;
  // Natural-language definition of the provision — the label description fed to
  // ai_classify at upload time. Editing it changes how future uploads classify.
  description: string;
  // Whether this term makes a bid "material" (drives the Extract-step
  // Material/Immaterial banner). Editable per-term on the Matrix page.
  is_trigger: boolean;
  // Curated risk rationale (read-only; from the seeded matrix). May be absent.
  risk_rationale?: string;
  // How this term relates to the seeded BRD matrix: "seeded" = untouched,
  // "seeded_override" = a seeded term the user edited (can Reset), "custom" =
  // a user-added term (can Remove). Absent on older payloads.
  origin?: "seeded" | "seeded_override" | "custom";
}

export interface ResponsibilityMatrix {
  terms: MatrixTerm[];
  teams: string[];
  statuses: ReviewStatus[];
}

// Derived material/immaterial triage verdict (BRD review-routing signal),
// computed server-side from the bid's requirements. See compute_review_verdict.
export interface ReviewVerdict {
  material: boolean;
  trigger_terms: string[];
  review_teams: string[];
  summary: string;
}

export interface SourceDocument {
  doc_id: string;
  file_name: string;
  path: string;
  file_format: string;
}

export interface Bid {
  bid_id: string;
  file_name: string;
  bid_name: string;
  customer_id: string;
  customer_name: string;
  solicitation_ref: string;
  due_date: string;
  status: "parsing" | "uploaded" | "matching" | "pending_review" | "submitted";
  created_at: string;
  line_items: PricedLineItem[];
  requirements: RequirementItem[];
  proposal_pdf_path: string | null;
  proposal_excel_path: string | null;
  uploaded_document_path: string | null;
  documents: SourceDocument[];
  review_verdict?: ReviewVerdict;
}

export interface BidSummary {
  bid_id: string;
  file_name: string;
  bid_name: string;
  customer_name: string;
  status: Bid["status"];
  due_date: string;
  created_at: string;
  line_item_count: number;
}
