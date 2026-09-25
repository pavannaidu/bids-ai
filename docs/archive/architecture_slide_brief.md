# Bid Intelligence on Databricks — architecture brief for slide design

Reference material for building an architecture slide. Written from a walkthrough of the live
application, so the stage names, field names, and behaviors below are what the app actually does.

Screenshots: `docs/screenshots/`

---

## 1. The problem

A bid (solicitation, RFP, tender) arrives as unstructured documents — PDF, Word, Excel. Someone has
to read every page and do two unrelated jobs at once:

1. **Find the products being requested**, match each to a real catalog SKU, and price it.
2. **Find the legal and commercial clauses**, decide whether the bid is even worth pursuing, and get
   each clause in front of the internal team that owns it.

Done manually, that is page-by-page reading plus a chain of email hand-offs. It doesn't scale, and
nothing about the result is auditable.

The app turns it into a five-stage guided workflow where every AI step is a built-in Databricks SQL
function running on governed data.

---

## 2. The shape of the solution

**One document, two questions.** This is the organizing idea of the whole architecture, and the
strongest hook for a diagram.

A single parsed document fans out into two independent extraction passes that answer two different
questions, travel down two different paths, and rejoin only at the end when the proposal is
generated:

```
                       ┌──────────────────────────────────────────────┐
                       │  "What are they buying?"                     │
                       │  line items → catalog match → price          │
   documents           │                                              │
       │               │                                              │
       ▼               │                                              │
  structured   ────────┤                                              ├────►  proposal
     parse             │                                              │       (PDF + XLSX)
                       │  "What are they demanding?"                  │
                       │  clauses → classify → route to owning team   │
                       │           → materiality verdict              │
                       └──────────────────────────────────────────────┘
```

The left path is a data-matching problem. The right path is a governance and routing problem. Most
document-AI demos only do the left one.

---

## 3. The five stages

The user moves left to right through a stepper. Each stage is a screen. The bid is the container
carrying state across all of them, and any stage can be revisited.

### Stage 1 — Upload

*Screenshot: `01-upload.png`*

The reviewer names the bid, picks the customer account (or creates one inline), sets the submission
deadline, and attaches one or more documents. Documents can be added or removed at any later stage,
not just here.

**Platform:** files land in a **Unity Catalog Volume** — governed file storage, not a bucket the
application manages itself. A bid record is created the moment the first file arrives. Multiple
documents belong to one bid, and each keeps its own identity so everything extracted downstream can
be traced back to the exact file it came from.

**`ai_parse_document`** then converts each file into a *structured* representation with page
boundaries, text spans, and table regions preserved.

> **This is the pivot point of the entire design.** The parse is kept structured rather than
> flattened into a wall of text. Flattening early is what makes table extraction noisy, causes long
> documents to truncate, and destroys any ability to say which page a fact came from. Everything
> good downstream depends on this one decision.

The screen also embeds a **source document viewer**, so the original stays visible next to the
extracted output throughout review.

### Stage 2 — Requirements *(the governance path)*

*Screenshot: `02-requirements.png`*

The non-product content — the clauses. In the live example: 11 requirements, 4 owning teams,
4 flagged high-risk.

**Extraction** (`ai_extract`) pulls each clause with its full text. **Classification**
(`ai_classify`) assigns each clause to a term in a fixed, curated taxonomy of 34 bid terms — payment
terms, indemnification, most favored nation, insurance requirements, anti-lobbying certification,
administrative fee commitments, and so on. Constrained label sets, so the model can only return a
term that actually exists in the matrix.

Each clause card carries:

- the **term** (a dropdown, reclassifiable inline) with an `AI CLASSIFIED` badge
- the **owning team(s)**, from the responsibility matrix
- an automated **risk level** (high / medium / low)
- a **review status** (Pending / In Review / Approved / Rejected / Needs Changes / N/A)
- a free-text **reviewer note**
- **source details**: filename, page number, extraction method
- the **full clause text** as prose, click-to-edit

**The materiality verdict.** Above the clause list, the bid is labeled *material* or *immaterial*
with the reasoning shown: *"Material — 6 trigger clauses present; route to Business, Corporate Legal,
Compliance for review."* The trigger clauses that fired are listed as chips. This is a fast triage
read — does this bid need senior review before anyone spends hours pricing it?

Note the deliberate separation: **team routing** comes from the business-owned responsibility matrix,
while **risk level** is an automated assessment the tool adds. The UI says so explicitly. The
distinction between "what the business decided" and "what the AI suggested" is never blurred.

A **Re-extract** button re-runs just this pass.

### Stage 3 — Line Items *(the product path)*

*Screenshot: `03-line-items.png`*

The products being requested, as an editable table: description, quantity, unit of measure, and any
customer-supplied product code. Table-heavy pages are where `ai_extract` earns its keep.

Every row has a **source details** popover showing the source filename (clickable, jumps to the
document), the page number, and an extraction-method badge (`AI EXTRACT`).

The screen surfaces its own weak spot in plain language: *"16 of 16 didn't come with a product code,
so give those a closer look."* Everything is editable before matching runs, and this pass is
independently re-runnable too.

### Stage 4 — Match

*Screenshot: `04-match.png`*

Each extracted line has to become a real catalog SKU. This is the most sophisticated screen in the
app.

**Retrieval:** a **Mosaic AI Vector Search** index over a multi-million-item product catalog, kept
current by **Delta Sync with managed embeddings** — the index follows the source table, so there's no
separate embedding pipeline to operate. Where the extracted text names a manufacturer, that becomes a
**pre-filter on the vector query** rather than a post-hoc re-rank, so the search space narrows before
scoring.

**Two-signal ranking.** Each candidate shows its raw semantic score *and* how business history moved
it, in one sentence:

> *"89% catalog match, boosted by purchase/bid history to 98%."*
> *"this customer last bought it 2025-12-31 at $9.37; bid on this item 2x before, won 1/2"*

Semantic similarity finds plausible products. Purchase and bid history — what this customer actually
bought, at what price, and what we've won before — decides among them. Candidates are tagged
`PURCHASE HISTORY` or `CATALOG` so the reviewer sees which signal is in play.

**Honest disagreement.** The system flags its own semantic mismatches rather than burying them:

> *"⚠ Query asks for ASTM level 3, catalog item is level 1"*

**The guardrail.** Each candidate's *unboosted* semantic score is tested against a sensitivity
threshold **before** business boosting is applied. Lines that clear it are eligible for auto-selection
and bulk accept. Lines that don't are held back with an explicit reason, and a human has to look. A
confident wrong match is worse than an admitted unknown, so the system is built to admit it.

**Explicit resolution.** Every line ends in a named state — accepted match, or `NO MATCH` /
*"No catalog match"* with the consequence spelled out: *"it will appear blank (unpriced) in the
proposal."* A reviewer can also run a manual catalog search for any line. Nothing sits silently
unresolved.

**Pricing** happens on this screen: proposed price per line, marked `reviewer-selected` when a human
overrode it, with list price shown alongside for reference.

### Stage 5 — Generate

The finished output, produced automatically from the reviewed lines:

- a **proposal PDF**, previewed inline
- a **customer submission spreadsheet** (XLSX) in the real external quote layout — proper column
  names, header block, totals row

A document a person can actually send, not a data dump.

---

## 4. Two supporting surfaces

### Compliance Matrix

*Screenshot: `06-matrix.png`*

An editable grid: **34 bid terms × 8 owning teams** (Business, Corporate Legal, Regulatory, HR,
Compliance, Risk Management, Tax, Corporate Affairs), plus a default risk level and a *material
trigger* flag per term.

**Why this matters architecturally:** each term's description is the text the classifier matches
against. Editing a description, or adding a term, changes how future bids are routed. The taxonomy
the AI classifies against is owned and tunable by the business, in the app, with no code change and
no redeployment. The UI states this outright: *"Each term's description is what the AI uses to
classify clauses at upload — so editing it, or adding a term, changes how future bids are routed."*

This is the answer to "how do we keep the AI aligned with our policies as they change."

### All Bids

*Screenshot: `07-all-bids.png`*

Every bid with its pipeline state — `MATCHING`, `PENDING_REVIEW`, `SUBMITTED` — line-item count, due
date, and a Resume button. Work is durable and picked up where it was left.

---

## 5. The platform underneath

| Layer | Component | Role |
|---|---|---|
| Governed file landing | **Unity Catalog Volume** | Source documents |
| Document parsing | **`ai_parse_document`** | Structured parse, page spans preserved |
| Extraction | **`ai_extract`** | Line items and clauses, one pass per document |
| Classification | **`ai_classify`** | Constrained routing to owning teams |
| Retrieval | **Mosaic AI Vector Search** | Catalog match, Delta Sync managed embeddings |
| Application state | **Lakebase** (managed Postgres) | Bids, extracted rows, reviewer decisions, overrides |
| Analytics | **Delta tables in Unity Catalog** | Catalog, reference data, extracted output as history |
| Application | **Databricks App** | FastAPI + React, platform-native identity and permissions |
| Inference | **Model serving endpoint** | Backs the AI functions |
| Reporting | **AI/BI dashboard** | Throughput, coverage, match rates, pipeline by stage |
| Governance | **Unity Catalog** | One boundary across all of the above |

**Two constraints worth knowing (both learned the hard way):**

- The SQL AI functions require a serving endpoint that supports **batch inference**. Not every
  foundation-model endpoint does, and the failure mode is silent — extraction quietly returns nothing
  rather than erroring.
- `ai_extract` exposes **no sampling controls** (only citations, confidence scores, instructions, and
  version), so run-to-run variance can't be tuned away at that layer. This is why the re-extract
  buttons exist.

---

## 6. The three claims a technical audience will test

**"Provenance is real, not decorative."** Every extracted row — line item and clause alike — carries
source filename, page number, extraction method, and confidence, threaded from parse through the API
to the UI. The reviewer clicks a row and lands on the source page. Fallback extraction paths carry
provenance too. No row is emitted without it.

**"The AI's confidence is separated from the business's judgment."** Semantic score is shown
separately from history boosting. AI-assigned risk is labeled as distinct from matrix-assigned team
ownership. Reviewer overrides are stored as decisions, not overwrites, so the gap between what the
system proposed and what a human chose stays visible and auditable.

**"It refuses to guess."** The guardrail tests unboosted semantic score against a threshold and holds
back weak lines with a stated reason. Semantic mismatches are surfaced as warnings. `NO MATCH` is a
first-class outcome with its downstream consequence spelled out.

---

## 7. Slide framing options

**A. "One document, two questions."** *(recommended)* The fan-out at extraction is the genuinely
distinctive thing here, and it makes a naturally symmetrical diagram: one parse, two paths, rejoining
at the proposal. Left path is data matching; right path is governance and routing.

**B. "Unstructured in, governed rows out."** Four horizontal bands — documents → structured parse →
AI extraction → governed tables — with Unity Catalog as a spine down the side. Simplest to read,
least distinctive.

**C. "Every row knows where it came from."** Provenance as the hero. A single line item on the right,
with a thread tracing back through extraction, parse, page, and file. The trust story rather than the
pipeline story. Strong for an audience whose real objection is auditability.

### Databricks brand palette

| Token | Hex |
|---|---|
| Lava (primary accent) | `#FF3621` |
| Navy (text, structure) | `#1B3139` |
| Oat Light (background) | `#F9F7F4` |
| Blue (secondary) | `#2272B4` |
| Green (secondary) | `#00A972` |

Typeface: DM Sans (fall back to Barlow, then Arial). Flat design, thin lines, generous white space.
No gradients, no 3D, no drop shadows, no stock icons.

---

## 8. Closing line

The point isn't that AI can read a document. The point is that reading the document is one governed
step inside a platform that already holds the catalog, the purchase history, the reviewer decisions,
and the audit trail. Consumption-based, on infrastructure the organization already runs. No second
platform, no per-bot licensing.
