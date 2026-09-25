# Guardrail-first catalog matching

## Objective

Prevent low-confidence or incompatible catalog suggestions from being silently selected, priced, or bulk-accepted. Let a reviewer either select a catalog product deliberately or record that no catalog product is available.

## Product decision: settings-level match sensitivity

Expose a global **Match sensitivity** control in Settings, backed by the existing confidence threshold used by Vector Search ranking.

| Sensitivity | Auto-match threshold | Intended use |
| --- | ---: | --- |
| Conservative | 0.80 | Customer files and high-risk demos; fewer auto-matches, more reviewer exceptions. |
| Balanced (default) | 0.70 | Normal demo use; auto-select only clearly credible, compatible matches. |
| Permissive | 0.60 | Internal exploration only; still never bypasses UOM or hard-compatibility guardrails. |

Implementation notes:

- Persist the selected sensitivity and numeric threshold in the application settings store; do not leave it process-local, because it affects review decisions and should survive a redeploy.
- Include the effective threshold and sensitivity label in the bid's audit metadata at match time. A bid should not change meaning because a later global setting changes.
- Keep an advanced numeric threshold out of the demo UI initially. The three named modes make the decision understandable and avoid false precision.
- Apply the threshold to the **unboosted semantic score**, not the history-boosted final score. Historical purchases can rank close candidates, but cannot create confidence where semantic evidence is weak.
- Sensitivity controls only automated behavior. A reviewer may still use full catalog search and deliberately choose a lower-scoring product.

The existing `BIDS_MATCH_CONFIDENCE_THRESHOLD` is currently defaulted to `0.55`, but it does not prevent `main.py` from selecting the top candidate. The implementation below makes the setting authoritative for automatic selection and bulk acceptance.

## Resolution model

Add a persisted per-line resolution state:

- `pending`: no reviewer decision yet.
- `catalog_match`: a catalog product is selected and priced.
- `no_catalog_product`: reviewer has determined the product is unavailable in the catalog; the bid line is represented as `NO BID` / exception.

For `no_catalog_product`, persist:

- no `selected_item_code`
- no proposed price
- reviewer email and timestamp
- a required short reason/note

The line is resolved, not silently ignored.

## Backend work

### 1. Model and persistence

Update:

- `src/app/server/models.py`
- `src/app/server/lakebase.py`
- `src/web/src/types.ts`

Add `resolution` and `no_product_reason` to the line model and Lakebase table/read-write mapping. Backfill existing rows as `catalog_match` when they have a selected catalog code; otherwise use `pending`.

### 2. Candidate eligibility

In `src/app/server/databricks_api.py`, add a clear `auto_select_eligible` result for each candidate/line. A candidate is eligible only when all conditions are true:

- its unboosted semantic score meets the bid's saved threshold
- it passes hard compatibility checks
- it has no UOM mismatch or other soft compatibility warning
- it is a real catalog or purchase-history candidate, never a general-knowledge fallback
- the requested description is not low-specificity

Continue to return candidate scores, compatibility flags, and reason codes. For guarded lines, return a clear reason such as `below_confidence_threshold`, `uom_mismatch`, `hard_incompatibility`, or `low_specificity`.

### 3. Match endpoint

In `src/app/server/main.py` (`match_bid`):

- select and price only an `auto_select_eligible` top candidate
- leave guarded lines unselected and `pending`
- retain a “No confident catalog match — reviewer decision required” candidate/status for the UI
- record the threshold/sensitivity used for the bid

### 4. Explicit no-product endpoint

Add:

`POST /api/bids/{bid_id}/lines/{line_id}/no-product`

The request requires a reason. It clears code/price, sets `resolution=no_catalog_product`, records the reviewer, and returns the updated bid.

### 5. Bulk acceptance

Change `lines_eligible_for_bulk_accept` in `src/app/server/validation.py` so it returns only lines that are:

- still pending
- selected with a catalog item
- `auto_select_eligible`
- free of UOM and compatibility warnings

The endpoint must rely on this server-side rule; UI filtering is only convenience.

### 6. Submission and documents

Update submission validation:

- `catalog_match` requires item code, valid price, and reviewer decision.
- `no_catalog_product` requires reviewer decision and reason, but no item code or price.
- `pending` blocks submission.

Update `src/app/server/documents.py` so PDF and XLSX retain every source line. A no-product row must show `NO BID` and its exception reason; it must never be silently omitted.

## Frontend work

### Settings

In the existing Settings UI/API:

- add the three match-sensitivity choices
- show the current numeric threshold as read-only helper text
- explain that sensitivity affects automated match selection, not manual catalog search

### Match review

Update `src/web/src/components/MatchReviewCard.tsx`:

- clearly label guarded lines: “No confident catalog match — reviewer decision required”
- show the reason and threshold, for example “Top semantic score 62%; Balanced requires 70%”
- retain **Search full catalog** for reviewer-led lower-score selection
- add **No catalog product available** with a required reason and confirmation
- hide/disable price editing for a no-product resolution

Update `src/web/src/App.tsx`:

- rename the button to `Accept eligible matches (N)`
- show an exceptions summary: `X lines need manual selection or no-product resolution`
- ensure its count mirrors the backend eligibility predicate

Update `SubmitBar.tsx` to distinguish unresolved pending lines from resolved no-product exceptions.

## Tests

Backend:

- 69% semantic score is not auto-selected or bulk-accepted under Balanced.
- 70% compatible, UOM-matching score is auto-selected and bulk-eligible.
- UOM mismatch is never auto-selected or bulk-eligible at any sensitivity.
- Hard incompatibility is never auto-selected.
- Manual catalog selection remains allowed below threshold.
- No-product resolution requires a reason and allows submission once all other lines are resolved.
- PDF/XLSX output renders no-product rows as `NO BID` with a reason.
- A bid retains the threshold in effect at its match run after global settings change.

Frontend:

- guarded card shows reason and no unsafe default selection.
- no-product action clears the product/price and resolves the line.
- bulk-accept count excludes guarded lines.
- proposal generation remains disabled while any line is pending.

## Acceptance criteria

- 42–62% unrelated candidates are not preselected.
- UOM-mismatch candidates cannot be bulk-accepted.
- Reviewers can still intentionally search and select any catalog product.
- Reviewers can resolve an unavailable item as `No catalog product available`.
- Bulk acceptance acts only on safe matches.
- Customer artifacts include every bid line, including `NO BID` exceptions.
