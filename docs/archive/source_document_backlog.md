# Source document listing — improvement backlog

Ideas for evolving the Extract-step **Source document** viewer (`SourceDocumentViewer.tsx`),
captured 2026-07-22 after shipping multi-file upload + the inline PDF / open-button viewer.
Not committed work — a menu to pull from later.

## Framing

The Extract step exists so a reviewer can **trust the AI's parse** and **route clauses** to the
owning teams. So the source listing should be the app's **verification + provenance surface** —
connecting extracted line items / requirements back to where they came from — not just a passive
file browser. Most gaps below are about traceability, trust signals, and real bid workflow.

## Ranked ideas

| # | Idea | Why it matters (PM lens) | Rough effort | Notes / dependencies |
|---|---|---|---|---|
| 1 ⭐ | **Provenance — which file did this line/clause come from?** Tag each line item + requirement with its `source_doc_id`; show a file badge on each row; click to open + select that doc in the viewer. | Closes the core trust loop. With several files merged into one flat bid, there's currently **no way** to trace a wrong-looking line back to its source doc. Makes the multi-file feature actually useful. | v1 low, v2 medium | `source_doc_id` is known for free during the `_process_upload` merge loop. **v2** (deep-link to page via `#page=N`) depends on `ai_parse_document` returning page locations — verify first. |
| 2 | **Parse health per file.** On each file tab: `RFP-Base.pdf → 12 items · 4 clauses`. | A file contributing **0** items is a signal — boilerplate T&Cs (fine) or a silent parse failure (bad, invisible today). High trust payoff, cheap. | Low | Counts already computed during the merge loop. Pairs naturally with #1 (shared per-file data). |
| 3 | **Add / remove documents after bid creation.** "Add a document" re-parses just that file and merges it in; remove a mis-uploaded file. | Government solicitations get **amendments + Q&A addenda constantly**, and they're binding. Real workflow is incremental, not upload-once. Genuine ops need, not a nicety. | Medium | Re-parse/merge path already exists in `_process_upload`. Remove needs row surgery + a delete path (no delete-bid endpoint exists yet). |
| 4 | **Document role/type, not "first = primary".** Tag each file: primary solicitation / amendment / pricing template / T&Cs / Q&A (user-set or inferred). | "Primary" is arbitrarily the first upload today. Roles improve the history label, viewer ordering, and per-role review. Also fixes ugly filenames (show a clean title vs `BOP-NCR-2027-0087_….pdf`). | Medium | Adds a field to the `documents` JSONB entries. |
| 5 | **Scale the layout past ~4 files.** Swap horizontal tabs for a compact left-rail file list (name · format · item count) with preview on the right. | Tabs break at 6–8 files; real packets (solicitation + several amendments) need room, and the rail hosts #2/#4 metadata cleanly. | Medium | Layout change to `SourceDocumentViewer.tsx` + CSS. |

## Lower priority / more ambitious

- **Search + highlight in the doc** — find the AI-extracted clause text highlighted in the source. Powerful for verification; bigger build.
- **Side-by-side review** — doc on the left, extracted items on the right. Strong demo moment; larger layout change.
- **Download-all packet** — one click to grab the full solicitation set.

## Suggested sequencing

- **#1 + #2 as one pass** — most trust for the least code; they share the same per-file data computed during the merge. Makes the multi-file feature earn its keep. *(Recommended first.)*
- **#3** — highest real-world value if this goes past demo into actual bid ops.
- **#4 / #5** — polish that matters once files pile up.
