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

    `owning_teams` come from the BRD Glossary (a term can be owned by more than
    one team). `description` is a natural-language definition of the provision —
    it is the label description fed to `ai_classify`, which classifies each
    extracted clause into this taxonomy (see databricks_api.classify_requirements).
    `risk_level` / `risk_rationale` are this app's curated risk-analysis layer,
    NOT from the BRD — see the module docstring.

    `keywords` is retained on the dataclass for back-compat (every row is a
    6-tuple) but is NO LONGER READ — classification is ai_classify-only. Kept to
    avoid restructuring all 34 rows.
    """

    term_label: str
    keywords: tuple[str, ...]  # DEPRECATED / unused — classification is ai_classify-only now
    owning_teams: tuple[str, ...]  # one or more of the eight BRD matrix columns
    description: str  # natural-language definition of the provision; the ai_classify label description
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
        (TEAM_HR,),
        "A vendor questionnaire QUESTION asking whether the company performs criminal background "
        "checks on its employees (an HR process question), not a requirement to run background checks.",
        RISK_MEDIUM,
        "Whether the company runs criminal background checks is an HR process question.",
    ),

    # --- Corporate Legal ----------------------------------------------------
    MatrixTerm(
        "Indemnification", ("indemnif", "hold harmless"),
        (TEAM_LEGAL,),
        "The vendor must indemnify, defend, or hold the buyer harmless from claims, losses, damages, "
        "or liabilities. Includes hold-harmless and defense obligations.",
        RISK_HIGH,
        "Uncapped indemnity obligations are a material liability exposure requiring counsel review.",
    ),
    MatrixTerm(
        "IP Infringement", ("ip infringement", "intellectual property", "patent infringement", "infringement"),
        (TEAM_LEGAL,),
        "Warranties or obligations regarding intellectual-property, patent, trademark, or copyright "
        "infringement — that goods do not infringe and the vendor will defend infringement claims.",
        RISK_HIGH,
        "IP infringement warranties can create open-ended defense obligations.",
    ),
    MatrixTerm(
        "Power of Attorney", ("power of attorney",),
        (TEAM_LEGAL,),
        "A clause requiring the vendor to grant a power of attorney or otherwise delegate binding "
        "legal authority to act on its behalf.",
        RISK_HIGH,
        "Granting power of attorney delegates binding authority and must be reviewed by counsel.",
    ),
    MatrixTerm(
        "Debarment", ("debarment", "debarred", "suspension and debarment"),
        (TEAM_LEGAL,),
        "A certification that the vendor is not debarred, suspended, or excluded from federal or "
        "state contracting or from participation in government programs.",
        RISK_HIGH,
        "Debarment certifications carry federal contracting eligibility and False Claims Act exposure.",
    ),
    MatrixTerm(
        "Litigation", ("litigation", "pending lawsuits", "legal proceedings"),
        (TEAM_LEGAL,),
        "A requirement to disclose pending or threatened litigation, lawsuits, legal proceedings, "
        "or material disputes involving the vendor.",
        RISK_HIGH,
        "Disclosure of pending litigation must be verified by counsel before certifying.",
    ),
    MatrixTerm(
        "Anti-Trust Violations", ("anti-trust", "antitrust", "collusion", "collusive"),
        (TEAM_LEGAL,),
        "An anti-trust or non-collusion certification — that the bid was prepared independently, "
        "without collusion, price-fixing, or bid-rigging with competitors. Includes certificates of "
        "independent price determination.",
        RISK_HIGH,
        "Anti-trust / non-collusion certifications carry criminal and civil exposure.",
    ),
    MatrixTerm(
        "Stark Law Violations", ("stark law", "physician self-referral", "anti-kickback", "kickback"),
        (TEAM_LEGAL,),
        "Provisions invoking the federal physician self-referral (Stark) law or the Anti-Kickback "
        "Statute — prohibiting improper remuneration, kickbacks, or self-referral in healthcare.",
        RISK_HIGH,
        "Stark Law / anti-kickback provisions are high-risk healthcare-regulatory exposure.",
    ),
    MatrixTerm(
        "Criminal Background Investigation", ("criminal background", "background investigation", "background check"),
        (TEAM_LEGAL,),
        "A REQUIREMENT that the vendor conduct criminal background investigations or checks on "
        "personnel assigned to the contract (a mandated obligation, not a questionnaire question).",
        RISK_HIGH,
        "Criminal background investigation requirements are a Corporate Legal certification.",
    ),
    MatrixTerm(
        "Anti-Lobbying", ("anti-lobbying", "lobbying certification", "byrd amendment", "lobbying"),
        (TEAM_LEGAL,),
        "An anti-lobbying certification (e.g. the Byrd Amendment) — that appropriated federal funds "
        "were not used to lobby for the award.",
        RISK_MEDIUM,
        "Anti-lobbying certifications (e.g. Byrd Amendment) require a formal legal attestation.",
    ),

    # --- Business, commercial terms -----------------------------------------
    MatrixTerm(
        "Most Favored Nation", (
            "most favored nation", "most favored customer", "most-favored", "mfn",
            "best price", "no less favorable",
        ),
        (TEAM_BUSINESS,),
        "A most-favored-nation, most-favored-customer, or best-price guarantee — that prices offered "
        "are no less favorable than those given to any other customer.",
        RISK_HIGH,
        "MFN / best-price clauses bind pricing across the whole book of business — major commercial risk.",
    ),
    MatrixTerm(
        "Payment Terms", ("payment terms", "net 30", "net 45", "net 60", "net-30", "days from invoice"),
        (TEAM_BUSINESS,),
        "The payment terms / timing — e.g. Net 30/45/60 days from invoice or receipt, and any early-"
        "payment discount.",
        RISK_MEDIUM,
        "Payment terms affect working capital and DSO.",
    ),
    MatrixTerm(
        "Payment Method", ("payment method", "electronic funds", "ach", "purchasing card", "p-card"),
        (TEAM_BUSINESS,),
        "The method or mechanism of payment — electronic funds transfer/ACH, purchasing card (P-card), "
        "check, or credit card acceptance.",
        RISK_LOW,
        "Payment method is an operational finance detail.",
    ),
    MatrixTerm(
        "Firm Pricing", ("firm pricing", "firm fixed price", "price firm", "prices shall remain firm", "firm-fixed"),
        (TEAM_BUSINESS,),
        "A requirement that prices remain firm / fixed for a stated period or the contract term "
        "(firm-fixed pricing, no increases).",
        RISK_MEDIUM,
        "Firm-pricing periods transfer cost-inflation risk to the vendor for the locked term.",
    ),
    MatrixTerm(
        "Price Reduction", ("price reduction", "price decrease", "price reductions clause"),
        (TEAM_BUSINESS,),
        "A price-reduction clause requiring the vendor to pass through price decreases or match lower "
        "prices during the term.",
        RISK_MEDIUM,
        "Price-reduction clauses can ratchet pricing down over the contract term.",
    ),
    MatrixTerm(
        "Firm Markup (GPO)", ("firm markup", "gpo markup", "fixed markup", "cost plus"),
        (TEAM_BUSINESS,),
        "A fixed or firm markup / cost-plus percentage over cost applied to the covered lines "
        "(common in GPO contracts).",
        RISK_MEDIUM,
        "A fixed GPO markup caps margin on the covered lines.",
    ),
    # Warranty of Products is checked under BOTH Business and Corporate Legal in
    # the BRD Glossary — a genuinely joint-ownership term.
    MatrixTerm(
        "Warranty of Products", ("warranty of products", "product warranty", "warrant that all products", "warranty"),
        (TEAM_BUSINESS, TEAM_LEGAL),
        "A product warranty — that goods are free from defects in materials and workmanship, are "
        "merchantable/fit for purpose, and will be repaired or replaced if defective.",
        RISK_MEDIUM,
        "Product warranty scope drives replacement/return obligations and legal warranty exposure.",
    ),
    MatrixTerm(
        "Delivery Terms (FOB)", ("fob destination", "fob shipper", "fob origin", "f.o.b", "freight on board", "delivery terms"),
        (TEAM_BUSINESS,),
        "Delivery / shipping terms — FOB destination vs. origin, freight responsibility, and who bears "
        "in-transit risk and shipping cost.",
        RISK_MEDIUM,
        "FOB Destination shifts freight cost and in-transit risk to the vendor vs. FOB Shipper's Dock.",
    ),
    MatrixTerm(
        "Bid Allows Deviations", ("deviation", "exceptions to specification", "alternate bid", "or equal"),
        (TEAM_BUSINESS,),
        "Whether the bid permits deviations, exceptions to specification, substitutions, alternates, "
        "or 'or-equal' products.",
        RISK_LOW,
        "Whether deviations/substitutions are permitted governs how we can respond.",
    ),
    MatrixTerm(
        "Piggyback Provision", ("piggyback", "cooperative purchasing", "cooperative contract", "intergovernmental"),
        (TEAM_BUSINESS,),
        "A piggyback / cooperative-purchasing / intergovernmental clause letting other entities buy "
        "off this contract at the same pricing.",
        RISK_MEDIUM,
        "Piggyback / cooperative-purchasing clauses extend pricing to other entities.",
    ),
    MatrixTerm(
        "Manufacturer Price Increase Letter", ("price increase letter", "manufacturer price increase", "proof of price increase"),
        (TEAM_BUSINESS,),
        "A requirement to provide a manufacturer's price-increase letter or documentary proof before "
        "passing through a price increase.",
        RISK_LOW,
        "Documentary proof required to pass through manufacturer price increases.",
    ),
    MatrixTerm(
        "Authorized Distributor Letter", ("authorized distributor", "letter of authorization", "authorized dealer"),
        (TEAM_BUSINESS,),
        "A requirement to provide a letter proving authorized-distributor or authorized-dealer status "
        "from the manufacturer.",
        RISK_LOW,
        "Proof of authorized-distributor status from the manufacturer.",
    ),
    MatrixTerm(
        "Doing Business Data Form", ("doing business data", "business data form", "vendor information form"),
        (TEAM_BUSINESS,),
        "An administrative vendor-registration or 'doing business' data / information form to be "
        "completed by the vendor.",
        RISK_LOW,
        "Administrative vendor-registration form.",
    ),
    MatrixTerm(
        "EDGAR Certifications", ("edgar", "sec filing", "securities and exchange"),
        (TEAM_BUSINESS,),
        "A certification referencing EDGAR or SEC securities filings / corporate disclosure.",
        RISK_LOW,
        "EDGAR/SEC-filing certification is a routine corporate disclosure attestation.",
    ),
    MatrixTerm(
        "Administrative Fee Commitments", ("administrative fee", "admin fee"),
        (TEAM_BUSINESS,),
        "A commitment to pay an administrative fee (often a percentage of sales) to a GPO, cooperative, "
        "or contracting entity.",
        RISK_MEDIUM,
        "Administrative-fee commitments reduce net realized margin.",
    ),
    MatrixTerm(
        "Rebate Commitments", ("rebate",),
        (TEAM_BUSINESS,),
        "A commitment to pay rebates or volume/growth incentives back to the buyer.",
        RISK_MEDIUM,
        "Rebate commitments are a direct margin give-back.",
    ),
    MatrixTerm(
        "Transaction Fee Commitments", ("transaction fee",),
        (TEAM_BUSINESS,),
        "A commitment to pay a per-transaction or per-order fee (e.g. to an e-procurement or marketplace "
        "platform).",
        RISK_MEDIUM,
        "Per-transaction fees erode margin at volume.",
    ),

    # --- HR -----------------------------------------------------------------
    MatrixTerm(
        "E-Verify", ("e-verify", "everify", "employment eligibility verification"),
        (TEAM_HR,),
        "A requirement to participate in E-Verify or otherwise verify employment eligibility of "
        "workers.",
        RISK_MEDIUM,
        "E-Verify participation is an employment-eligibility program owned by HR.",
    ),
    MatrixTerm(
        "Affirmative Action Plan", ("affirmative action", "equal opportunity", "eeo ", "ofccp"),
        (TEAM_HR,),
        "An affirmative-action, equal-employment-opportunity (EEO), or OFCCP compliance obligation "
        "or plan requirement.",
        RISK_MEDIUM,
        "Affirmative-action / EEO plans are HR-owned compliance obligations.",
    ),

    # --- Compliance ---------------------------------------------------------
    MatrixTerm(
        "Royalty Fees", ("royalty", "royalties"),
        (TEAM_COMPLIANCE,),
        "A requirement to pay royalties or royalty fees on sales under the contract.",
        RISK_MEDIUM,
        "Royalty-fee arrangements require compliance review for permissibility.",
    ),
    MatrixTerm(
        "Marketing Fees", ("marketing fee", "marketing contribution", "promotional allowance"),
        (TEAM_COMPLIANCE,),
        "A requirement to pay marketing fees, promotional allowances, or marketing contributions.",
        RISK_MEDIUM,
        "Marketing-fee arrangements require compliance review under fair-market-value rules.",
    ),

    # --- Corporate Affairs --------------------------------------------------
    MatrixTerm(
        "Political Contributions", ("political contribution", "campaign contribution", "pay-to-play", "pay to play"),
        (TEAM_CORP_AFFAIRS,),
        "A disclosure of political or campaign contributions, or a pay-to-play certification.",
        RISK_MEDIUM,
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
        (TEAM_RISK,),
        "Minimum insurance / coverage requirements — commercial general liability, workers' "
        "compensation, umbrella, or a certificate of insurance the vendor must carry.",
        RISK_MEDIUM,
        "Minimum insurance / coverage requirements are owned by Risk Management.",
    ),

    # --- Tax ----------------------------------------------------------------
    MatrixTerm(
        "Tax Exemption / Withholding", ("tax exempt", "tax-exempt", "sales tax", "tax withholding", "w-9", "tax id"),
        (TEAM_TAX,),
        "Tax-related provisions — sales-tax exemption, tax withholding, W-9 / tax-ID submission.",
        RISK_LOW,
        "Tax-exemption and withholding provisions are owned by Tax.",
    ),
)


# The seeded term labels, in matrix order. The editable-matrix overlay uses this
# to decide whether an edited label is an OVERRIDE of a seeded term or a new
# CUSTOM term (see reference.matrix_payload / upsert_matrix_term).
TERM_LABELS: tuple[str, ...] = tuple(term.term_label for term in RESPONSIBILITY_MATRIX)


# --- BRD triage: "material" trigger clauses ---------------------------------
# A bid is MATERIAL (must go to Corporate Legal / Business-Terms review) if it
# contains ANY of these provisions — the internal bid-triage rule.
# This is a curated SUBSET of the matrix above, keyed by exact term_label so it
# stays the single source of truth and is trivially unit-testable against
# RESPONSIBILITY_MATRIX. It is deliberately NOT "risk_level == high": that would
# wrongly pull in Criminal Background Investigation / Power of Attorney and, more
# importantly, would EXCLUDE the medium-risk fee terms (Administrative Fee,
# Rebate, Marketing, Royalty) that the triage sheet explicitly names as triggers.
# This is a BRD triage-routing signal, distinct from the app's automated
# risk_level layer (see module docstring).
# TODO: Data privacy and Principal Place of Business (PPB) are BRD triggers too
#       but are not yet matrix terms — add rows for them, then list here.
REVIEW_TRIGGER_TERMS: frozenset[str] = frozenset({
    "Most Favored Nation",
    "Indemnification",
    "IP Infringement",
    "Litigation",
    "Debarment",
    "Administrative Fee Commitments",
    "Rebate Commitments",
    "Anti-Trust Violations",
    "Stark Law Violations",
    "Marketing Fees",
    "Royalty Fees",
})


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
                "description": term.description,
                "risk_rationale": term.risk_rationale,
                # Whether this provision makes a bid "material" (BRD triage). Seeded
                # from REVIEW_TRIGGER_TERMS so that set stays the source of truth;
                # editable per-term via the Matrix page (reference.matrix_payload
                # merges an override flag on top).
                "is_trigger": term.term_label in REVIEW_TRIGGER_TERMS,
            }
            for term in RESPONSIBILITY_MATRIX
        ],
        "teams": list(TEAMS),
        "statuses": list(REVIEW_STATUSES),
    }


def compute_review_verdict(requirements: list[dict], trigger_terms_set: set[str] | None = None) -> dict:
    """The bid's material/immaterial triage verdict, derived from its extracted
    requirements: MATERIAL (route to Corporate Legal / Business-Terms review) if
    any requirement is a trigger clause, else IMMATERIAL (the bids team can
    proceed). A requirement counts as a trigger if EITHER its matched_term (matrix
    rows) OR its term_label (manual / relabeled rows) is in the trigger set.

    `trigger_terms_set` is the set of trigger term_labels — the caller passes the
    MERGED matrix's editable trigger set (reference.trigger_terms()); when None it
    falls back to the seeded REVIEW_TRIGGER_TERMS (keeps this a pure, unit-testable
    default). This is a BRD TRIAGE-ROUTING signal, grounded in the customer's own
    review process (like the matrix's owning_teams) — distinct from the app's
    automated per-clause risk_level layer, which it never reads. Recomputed on
    every read so the banner tracks the current clause set + trigger config live.
    """
    active_triggers = trigger_terms_set if trigger_terms_set is not None else REVIEW_TRIGGER_TERMS
    triggered = [
        r for r in requirements
        if r.get("matched_term") in active_triggers
        or r.get("term_label") in active_triggers
    ]

    seen: set[str] = set()
    trigger_terms: list[str] = []
    for r in triggered:
        label = r.get("matched_term") or r.get("term_label")
        if label and label not in seen:
            seen.add(label)
            trigger_terms.append(label)

    routed = {team for r in triggered for team in (r.get("owning_teams") or [])}
    review_teams = [t for t in TEAMS if t in routed]  # canonical order, stable output

    material = bool(triggered)
    if material:
        teams_phrase = ", ".join(review_teams) if review_teams else TEAM_LEGAL
        summary = (
            f"Material — {len(trigger_terms)} trigger clause"
            f"{'' if len(trigger_terms) == 1 else 's'} present; "
            f"route to {teams_phrase} for review."
        )
    else:
        summary = "Immaterial — no trigger clauses detected; the bids team can proceed."

    return {
        "material": material,
        "trigger_terms": trigger_terms,
        "review_teams": review_teams,
        "summary": summary,
    }
