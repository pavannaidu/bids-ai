"""The BRD's Glossary of Terms, encoded as a responsibility matrix.

The BRD (§Appendix "Glossary of Terms") is literally a table mapping each kind
of bid/RFP provision to the internal team(s) that own it — Payment Terms to
Business, Indemnification to Corporate Legal, E-Verify to HR, Royalty Fees to
Compliance, Political Contributions to Corporate Affairs, and so on. Some terms
are owned jointly (e.g. Warranty of Products is checked under BOTH Business and
Corporate Legal). That table is the authority for the app's "route each
requirement to the right team(s)" step, which attacks the BRD's #1 named
bottleneck: "multiple handoffs and email threads."

Each row is one recognizable provision: a human-readable `term_label`, the
`keywords` used to detect it in extracted clause text, the `owning_teams` (one
or more of the eight BRD matrix columns), and a coarse `category`. This is
deliberately a small, explicit lookup table — the same design point as the
`_FAMILY_KEYWORDS` compatibility table in the matching code — not a learned
classifier, so routing is deterministic, auditable, and trivially unit-testable.

IMPORTANT — provenance of each field:
  * `owning_teams` and `category` are GROUNDED in the BRD Glossary matrix
    (the checkboxes). This is the authoritative routing.
  * `risk_level` and `risk_rationale` are NOT in the BRD. The BRD Glossary has
    no risk column. These are a CURATED risk-analysis layer this app adds on
    top, in service of the BRD Future State's "AI Risk & Requirement Analysis"
    step — a starting-point severity to flag high-exposure terms for a
    reviewer, not a figure from the customer's document. The UI labels it as an
    automated assessment, distinct from the matrix routing, so the two are
    never conflated.
"""

from __future__ import annotations

from dataclasses import dataclass


# The eight owning teams, named exactly as the BRD Glossary matrix columns.
TEAM_BUSINESS = "Business"
TEAM_LEGAL = "Corporate Legal"
TEAM_REGULATORY = "Regulatory"
TEAM_HR = "HR"
TEAM_COMPLIANCE = "Compliance"
TEAM_RISK = "Risk Management"
TEAM_TAX = "Tax"
TEAM_CORP_AFFAIRS = "Corporate Affairs"

TEAMS: tuple[str, ...] = (
    TEAM_BUSINESS,
    TEAM_LEGAL,
    TEAM_REGULATORY,
    TEAM_HR,
    TEAM_COMPLIANCE,
    TEAM_RISK,
    TEAM_TAX,
    TEAM_CORP_AFFAIRS,
)

RISK_HIGH = "high"
RISK_MEDIUM = "medium"
RISK_LOW = "low"


@dataclass(frozen=True)
class MatrixTerm:
    """One recognizable provision from the BRD Glossary matrix.

    `owning_teams` and `category` come from the BRD Glossary (a term can be
    owned by more than one team). `risk_level` / `risk_rationale` are this
    app's curated risk-analysis layer, NOT from the BRD — see the module
    docstring.
    """

    term_label: str
    keywords: tuple[str, ...]  # lowercase phrases; a clause matches if it contains any
    owning_teams: tuple[str, ...]  # one or more of the eight BRD matrix columns
    category: str  # legal | pricing | compliance | insurance | business | hr | regulatory | tax
    risk_level: str
    risk_rationale: str


# Ordered most-specific-first so multi-word provisions (e.g. "most favored
# nation") — and the HR criminal-background QUESTION vs. the Legal criminal-
# background INVESTIGATION — are tested before broader phrases that might also
# appear in them. classify_requirement() returns the first row whose keyword is
# present. owning_teams follows the BRD Glossary checkboxes exactly (including
# the joint Business+Legal ownership of Warranty of Products); risk_level /
# risk_rationale are this app's curated layer, not from the BRD.
RESPONSIBILITY_MATRIX: tuple[MatrixTerm, ...] = (
    # --- HR criminal-background QUESTION — must precede the Legal criminal-
    #     background INVESTIGATION row below, since both contain "criminal
    #     background"; the BRD routes the "does the company perform..." question
    #     to HR and the investigation requirement to Corporate Legal. ---------
    MatrixTerm(
        "Does the company perform criminal backgrounds?", (
            "perform criminal background", "does the company perform", "do you perform criminal",
        ),
        (TEAM_HR,), "hr", RISK_MEDIUM,
        "Whether the company runs criminal background checks is an HR process question.",
    ),

    # --- Corporate Legal ----------------------------------------------------
    MatrixTerm(
        "Indemnification", ("indemnif", "hold harmless"),
        (TEAM_LEGAL,), "legal", RISK_HIGH,
        "Uncapped indemnity obligations are a material liability exposure requiring counsel review.",
    ),
    MatrixTerm(
        "IP Infringement", ("ip infringement", "intellectual property", "patent infringement", "infringement"),
        (TEAM_LEGAL,), "legal", RISK_HIGH,
        "IP infringement warranties can create open-ended defense obligations.",
    ),
    MatrixTerm(
        "Power of Attorney", ("power of attorney",),
        (TEAM_LEGAL,), "legal", RISK_HIGH,
        "Granting power of attorney delegates binding authority and must be reviewed by counsel.",
    ),
    MatrixTerm(
        "Debarment", ("debarment", "debarred", "suspension and debarment"),
        (TEAM_LEGAL,), "compliance", RISK_HIGH,
        "Debarment certifications carry federal contracting eligibility and False Claims Act exposure.",
    ),
    MatrixTerm(
        "Litigation", ("litigation", "pending lawsuits", "legal proceedings"),
        (TEAM_LEGAL,), "legal", RISK_HIGH,
        "Disclosure of pending litigation must be verified by counsel before certifying.",
    ),
    MatrixTerm(
        "Anti-Trust Violations", ("anti-trust", "antitrust", "collusion", "collusive"),
        (TEAM_LEGAL,), "legal", RISK_HIGH,
        "Anti-trust / non-collusion certifications carry criminal and civil exposure.",
    ),
    MatrixTerm(
        "Stark Law Violations", ("stark law", "physician self-referral", "anti-kickback", "kickback"),
        (TEAM_LEGAL,), "compliance", RISK_HIGH,
        "Stark Law / anti-kickback provisions are high-risk healthcare-regulatory exposure.",
    ),
    MatrixTerm(
        "Criminal Background Investigation", ("criminal background", "background investigation", "background check"),
        (TEAM_LEGAL,), "compliance", RISK_HIGH,
        "Criminal background investigation requirements are a Corporate Legal certification.",
    ),
    MatrixTerm(
        "Anti-Lobbying", ("anti-lobbying", "lobbying certification", "byrd amendment", "lobbying"),
        (TEAM_LEGAL,), "compliance", RISK_MEDIUM,
        "Anti-lobbying certifications (e.g. Byrd Amendment) require a formal legal attestation.",
    ),

    # --- Business, commercial terms -----------------------------------------
    MatrixTerm(
        "Most Favored Nation", (
            "most favored nation", "most favored customer", "most-favored", "mfn",
            "best price", "no less favorable",
        ),
        (TEAM_BUSINESS,), "pricing", RISK_HIGH,
        "MFN / best-price clauses bind pricing across the whole book of business — major commercial risk.",
    ),
    MatrixTerm(
        "Payment Terms", ("payment terms", "net 30", "net 45", "net 60", "net-30", "days from invoice"),
        (TEAM_BUSINESS,), "pricing", RISK_MEDIUM,
        "Payment terms affect working capital and DSO.",
    ),
    MatrixTerm(
        "Payment Method", ("payment method", "electronic funds", "ach", "purchasing card", "p-card"),
        (TEAM_BUSINESS,), "business", RISK_LOW,
        "Payment method is an operational finance detail.",
    ),
    MatrixTerm(
        "Firm Pricing", ("firm pricing", "firm fixed price", "price firm", "prices shall remain firm", "firm-fixed"),
        (TEAM_BUSINESS,), "pricing", RISK_MEDIUM,
        "Firm-pricing periods transfer cost-inflation risk to the vendor for the locked term.",
    ),
    MatrixTerm(
        "Price Reduction", ("price reduction", "price decrease", "price reductions clause"),
        (TEAM_BUSINESS,), "pricing", RISK_MEDIUM,
        "Price-reduction clauses can ratchet pricing down over the contract term.",
    ),
    MatrixTerm(
        "Firm Markup (GPO)", ("firm markup", "gpo markup", "fixed markup", "cost plus"),
        (TEAM_BUSINESS,), "pricing", RISK_MEDIUM,
        "A fixed GPO markup caps margin on the covered lines.",
    ),
    # Warranty of Products is checked under BOTH Business and Corporate Legal in
    # the BRD Glossary — a genuinely joint-ownership term.
    MatrixTerm(
        "Warranty of Products", ("warranty of products", "product warranty", "warrant that all products", "warranty"),
        (TEAM_BUSINESS, TEAM_LEGAL), "business", RISK_MEDIUM,
        "Product warranty scope drives replacement/return obligations and legal warranty exposure.",
    ),
    MatrixTerm(
        "Delivery Terms (FOB)", ("fob destination", "fob shipper", "fob origin", "f.o.b", "freight on board", "delivery terms"),
        (TEAM_BUSINESS,), "business", RISK_MEDIUM,
        "FOB Destination shifts freight cost and in-transit risk to the vendor vs. FOB Shipper's Dock.",
    ),
    MatrixTerm(
        "Bid Allows Deviations", ("deviation", "exceptions to specification", "alternate bid", "or equal"),
        (TEAM_BUSINESS,), "business", RISK_LOW,
        "Whether deviations/substitutions are permitted governs how we can respond.",
    ),
    MatrixTerm(
        "Piggyback Provision", ("piggyback", "cooperative purchasing", "cooperative contract", "intergovernmental"),
        (TEAM_BUSINESS,), "business", RISK_MEDIUM,
        "Piggyback / cooperative-purchasing clauses extend pricing to other entities.",
    ),
    MatrixTerm(
        "Manufacturer Price Increase Letter", ("price increase letter", "manufacturer price increase", "proof of price increase"),
        (TEAM_BUSINESS,), "business", RISK_LOW,
        "Documentary proof required to pass through manufacturer price increases.",
    ),
    MatrixTerm(
        "Authorized Distributor Letter", ("authorized distributor", "letter of authorization", "authorized dealer"),
        (TEAM_BUSINESS,), "business", RISK_LOW,
        "Proof of authorized-distributor status from the manufacturer.",
    ),
    MatrixTerm(
        "Doing Business Data Form", ("doing business data", "business data form", "vendor information form"),
        (TEAM_BUSINESS,), "business", RISK_LOW,
        "Administrative vendor-registration form.",
    ),
    MatrixTerm(
        "EDGAR Certifications", ("edgar", "sec filing", "securities and exchange"),
        (TEAM_BUSINESS,), "business", RISK_LOW,
        "EDGAR/SEC-filing certification is a routine corporate disclosure attestation.",
    ),
    MatrixTerm(
        "Administrative Fee Commitments", ("administrative fee", "admin fee"),
        (TEAM_BUSINESS,), "pricing", RISK_MEDIUM,
        "Administrative-fee commitments reduce net realized margin.",
    ),
    MatrixTerm(
        "Rebate Commitments", ("rebate",),
        (TEAM_BUSINESS,), "pricing", RISK_MEDIUM,
        "Rebate commitments are a direct margin give-back.",
    ),
    MatrixTerm(
        "Transaction Fee Commitments", ("transaction fee",),
        (TEAM_BUSINESS,), "pricing", RISK_MEDIUM,
        "Per-transaction fees erode margin at volume.",
    ),

    # --- HR -----------------------------------------------------------------
    MatrixTerm(
        "E-Verify", ("e-verify", "everify", "employment eligibility verification"),
        (TEAM_HR,), "hr", RISK_MEDIUM,
        "E-Verify participation is an employment-eligibility program owned by HR.",
    ),
    MatrixTerm(
        "Affirmative Action Plan", ("affirmative action", "equal opportunity", "eeo ", "ofccp"),
        (TEAM_HR,), "hr", RISK_MEDIUM,
        "Affirmative-action / EEO plans are HR-owned compliance obligations.",
    ),

    # --- Compliance ---------------------------------------------------------
    MatrixTerm(
        "Royalty Fees", ("royalty", "royalties"),
        (TEAM_COMPLIANCE,), "compliance", RISK_MEDIUM,
        "Royalty-fee arrangements require compliance review for permissibility.",
    ),
    MatrixTerm(
        "Marketing Fees", ("marketing fee", "marketing contribution", "promotional allowance"),
        (TEAM_COMPLIANCE,), "compliance", RISK_MEDIUM,
        "Marketing-fee arrangements require compliance review under fair-market-value rules.",
    ),

    # --- Corporate Affairs --------------------------------------------------
    MatrixTerm(
        "Political Contributions", ("political contribution", "campaign contribution", "pay-to-play", "pay to play"),
        (TEAM_CORP_AFFAIRS,), "compliance", RISK_MEDIUM,
        "Political-contribution disclosures ('pay-to-play') are owned by Corporate Affairs.",
    ),

    # --- Insurance (Risk Management) — common in bids, implied by the BRD's
    #     'insurance requirements' functional requirement even where the
    #     Glossary sample didn't enumerate a row for it. ----------------------
    MatrixTerm(
        "Insurance Requirements", (
            "insurance", "liability coverage", "commercial general liability",
            "workers compensation", "workers' compensation", "certificate of insurance", "umbrella policy",
        ),
        (TEAM_RISK,), "insurance", RISK_MEDIUM,
        "Minimum insurance / coverage requirements are owned by Risk Management.",
    ),

    # --- Tax ----------------------------------------------------------------
    MatrixTerm(
        "Tax Exemption / Withholding", ("tax exempt", "tax-exempt", "sales tax", "tax withholding", "w-9", "tax id"),
        (TEAM_TAX,), "tax", RISK_LOW,
        "Tax-exemption and withholding provisions are owned by Tax.",
    ),
)


def default_team_for_category(category: str) -> str:
    """Best-guess owning team when a clause's category is known but its exact
    wording didn't match any matrix keyword — used by the ai_suggested
    fallback so a routed team is always proposed for a human to confirm."""
    return {
        "legal": TEAM_LEGAL,
        "pricing": TEAM_BUSINESS,
        "business": TEAM_BUSINESS,
        "compliance": TEAM_COMPLIANCE,
        "insurance": TEAM_RISK,
        "hr": TEAM_HR,
        "regulatory": TEAM_REGULATORY,
        "tax": TEAM_TAX,
    }.get((category or "").lower(), TEAM_BUSINESS)


# Review-workflow statuses a reviewer can move a requirement through. Kept here
# (next to TEAMS) so the /api/responsibility-matrix payload is the single source
# of truth the frontend reads for its dropdowns — no duplicated list in TS.
REVIEW_STATUSES: tuple[str, ...] = (
    "pending",
    "in_review",
    "approved",
    "rejected",
    "needs_changes",
    "not_applicable",
)


def matrix_payload() -> dict:
    """The responsibility matrix as a JSON-serializable payload for the app's
    /api/responsibility-matrix endpoint: every canonical term with its owning
    team(s) and default risk, plus the flat team and status option lists. Drives
    the frontend's Team->Term cascade and Term->Team/Risk pre-fill, so the matrix
    stays defined once here (Python) rather than duplicated in the UI."""
    return {
        "terms": [
            {
                "term_label": term.term_label,
                "owning_teams": list(term.owning_teams),
                "default_risk": term.risk_level,
                "category": term.category,
            }
            for term in RESPONSIBILITY_MATRIX
        ],
        "teams": list(TEAMS),
        "statuses": list(REVIEW_STATUSES),
    }
