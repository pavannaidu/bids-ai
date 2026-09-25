from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Customer(BaseModel):
    customer_id: str
    customer_name: str
    division_id: str
    customer_type: str
    region: str


class CreateCustomerRequest(BaseModel):
    """A new account created from the Upload step's "New account" quick-add.
    Name only — id, division, type and region are filled in server-side."""

    customer_name: str


class MatrixTermUpsertRequest(BaseModel):
    """Add or edit a responsibility-matrix term from the Compliance Matrix page.
    term_label is the key: an existing seeded label edits that term in place; a
    new label adds a custom term. `description` is the natural-language
    definition fed to ai_classify — editing it (or adding a custom term) changes
    how future uploads are classified into the taxonomy."""

    term_label: str
    owning_teams: list[str] = Field(default_factory=list)
    default_risk: Literal["high", "medium", "low"] = "medium"
    description: str = ""
    # Whether this term makes a bid "material" (Extract-step triage banner).
    is_trigger: bool = False


class MatrixTermDeleteRequest(BaseModel):
    """Remove a matrix overlay row: a seeded term reverts to its BRD default; a
    custom term disappears. Sent in the request body (term labels contain spaces
    and '?', so they don't belong in the URL path)."""

    term_label: str


# How the row's TEXT was pulled out of the document — distinct from a
# requirement's `source` (which is how it was ROUTED). "ai_extract" is the
# primary structured path; "ai_query" is the recovery fallback; "heuristic" is
# the last-resort line split; "manual" is a reviewer-added row.
ExtractionMethod = Literal["ai_extract", "ai_query", "heuristic", "manual"]


class Provenance(BaseModel):
    """Source-traceability fields carried by every extracted line item and
    requirement, so the UI can show where a row came from. All optional/nullable
    (older rows and manual additions may lack some). `source_page` is best-effort
    — null when the row's text couldn't be attributed to a single page."""

    source_doc_id: str | None = None
    source_filename: str | None = None
    source_page: int | None = None
    extraction_method: ExtractionMethod = "ai_extract"
    confidence: float | None = None


class ExtractedLineItem(Provenance):
    """A line item as pulled out of the uploaded document, before matching."""

    line_id: str
    line_number: int
    raw_description: str
    qty: int = 1
    uom: str = ""
    given_code: str | None = None


class CandidateMatch(BaseModel):
    """One weighted candidate for a line item. Never returned as a lone
    answer — always part of a top-3 ranked list, per the BRD's acceptance
    criteria ("weighted output proposals for a human in the loop's review")."""

    item_code: str
    description_long: str
    manufacturer_name: str | None = None
    category: str | None = None
    list_price: float | None = None
    score: float
    retrieval_score: float | None = None
    semantic_score: float | None = None
    source: Literal["catalog", "purchase_history", "general_knowledge", "manual_search"]
    rationale: str
    history_snippet: str = ""
    review_flag: str | None = None
    # Guardrail: whether this candidate is safe to AUTO-select (match endpoint /
    # bulk-accept honor it). guard_reason is a code when not eligible
    # (below_confidence_threshold / confidence_unavailable / uom_mismatch /
    # hard_incompatibility / low_specificity / not_catalog_source). A reviewer
    # may still pick manually.
    auto_select_eligible: bool = False
    guard_reason: str | None = None


class PricedLineItem(Provenance):
    line_id: str
    line_number: int
    raw_description: str
    qty: int = 1
    uom: str = ""
    given_code: str | None = None
    candidates: list[CandidateMatch] = Field(default_factory=list)
    selected_item_code: str | None = None
    proposed_price: float | None = None
    pricing_basis: str = ""
    review_action: Literal["pending", "accepted", "overridden"] = "pending"
    reviewer_email: str | None = None
    # Guardrail resolution: "pending" (no decision), "catalog_match" (a catalog
    # product is selected + priced), or "no_match" (reviewer determined the
    # catalog has no fit — no code/price; the line renders BLANK in the proposal).
    resolution: Literal["pending", "catalog_match", "no_match"] = "pending"


class RequirementItem(Provenance):
    """A non-product clause/term/certification pulled out of the same
    solicitation, classified against the BRD's Glossary responsibility matrix
    and routed to the team that owns it. This is the BRD's "extract legal,
    pricing, compliance, insurance and business requirements" + "AI Risk &
    Requirement Analysis" step, made visible per clause instead of buried in
    email handoffs.

    Two distinct provenance axes: `extraction_method` (from Provenance) is how
    the clause TEXT was pulled; `source` below is how it was ROUTED to a team."""

    requirement_id: str
    term_label: str
    raw_text: str
    category: str = ""
    # One or more owning teams (grounded in the BRD Glossary matrix; some terms
    # are jointly owned, e.g. Warranty of Products -> Business + Corporate Legal).
    # Editable/overridable per bid; the Term the reviewer picks pre-fills these.
    owning_teams: list[str] = Field(default_factory=list)
    # risk_level / risk_rationale are a curated risk-analysis layer this app adds
    # on top of the routing — NOT part of the BRD Glossary (which has no risk column).
    risk_level: Literal["high", "medium", "low"] = "medium"
    risk_rationale: str = ""
    matched_term: str | None = None
    # "ai_classified": ai_classify confidently mapped the clause to this matrix term.
    # "ai_suggested": no confident match (escape label / below the confidence floor) —
    #   left unassigned for a human to route.
    # "manual": a reviewer added this requirement by hand.
    # "matrix": legacy value on rows predating ai_classify taxonomy classification.
    source: Literal["matrix", "ai_classified", "ai_suggested", "manual"] = "matrix"
    # Review-workflow status. Legacy values (acknowledged/routed) from earlier
    # rows are coerced to the nearest new value by the store on read.
    review_status: Literal[
        "pending", "in_review", "approved", "rejected", "needs_changes", "not_applicable"
    ] = "pending"
    note: str = ""
    assigned_to: str | None = None
    last_updated_by: str | None = None
    last_updated_at: str | None = None


class Bid(BaseModel):
    bid_id: str
    file_name: str
    customer_id: str
    customer_name: str
    solicitation_ref: str = ""
    # "parsing" transient at create; "uploaded" = files staged + parsed, extraction
    # not yet run; "matching" = line items extracted, ready to match.
    status: Literal["parsing", "uploaded", "matching", "pending_review", "submitted"] = "parsing"
    created_at: str
    line_items: list[PricedLineItem] = Field(default_factory=list)
    requirements: list[RequirementItem] = Field(default_factory=list)
    proposal_pdf_path: str | None = None
    proposal_excel_path: str | None = None


class UploadBidResponse(BaseModel):
    bid: Bid


class MatchBidResponse(BaseModel):
    bid: Bid


class ReviewLineRequest(BaseModel):
    selected_item_code: str
    proposed_price: float
    review_action: Literal["accepted", "overridden"] = "accepted"


class UpdateLineItemRequest(BaseModel):
    """A presenter's correction to a line item's extracted text, made before
    matching runs — ai_parse_document/ai_query won't always get it right."""

    raw_description: str
    qty: int = 1
    uom: str = ""
    given_code: str | None = None


class ManualMatchRequest(BaseModel):
    """A presenter's manual catalog pick for a line with no confident auto-match."""

    item_code: str


class UpdateRequirementRequest(BaseModel):
    """A partial edit to one requirement on a bid. Every field is optional — only
    the ones provided are changed; the store stamps the reviewer + timestamp."""

    term_label: str | None = None
    raw_text: str | None = None
    category: str | None = None
    risk_level: Literal["high", "medium", "low"] | None = None
    owning_teams: list[str] | None = None
    review_status: Literal[
        "pending", "in_review", "approved", "rejected", "needs_changes", "not_applicable"
    ] | None = None
    note: str | None = None


class AddRequirementRequest(BaseModel):
    """A reviewer adding a requirement the AI missed. term_label is a matrix
    term; owning_teams/risk_level are pre-filled from it client-side but sent
    explicitly so the row is self-contained."""

    term_label: str
    raw_text: str = ""
    category: str = ""
    risk_level: Literal["high", "medium", "low"] = "medium"
    owning_teams: list[str] = Field(default_factory=list)


class SubmitBidResponse(BaseModel):
    bid: Bid
    proposal_pdf_url: str
    proposal_excel_url: str
