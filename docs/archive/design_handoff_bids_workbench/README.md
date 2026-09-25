# Handoff: Bids AI — Reviewer Workbench redesign

## Overview

A redesign of the Bids AI document-intelligence app (React + Vite frontend in `src/web/`). The existing app is a 5-step wizard rendered in a ~1040px centered column, with one tall card per record. This redesign converts it into a **full-width workbench**: dense tables instead of card stacks, a persistent step rail carrying progress, and a collapsible source-document pane on the right.

Primary user: a bid analyst working a solicitation end-to-end, plus specialist reviewers (Corporate Legal, Business, Compliance) who only act on the clauses routed to their team.

Problems this addresses, in priority order given by the user:
1. No way to see review progress at a glance.
2. Requirements cards are repetitive and tall (11 cards ≈ 4,000px of scroll).
3. Line-item descriptions truncated in narrow inputs.
4. All Bids has no filters, grouping, or sorting.
5. Compliance matrix table is cut off horizontally (8 team checkbox columns).
6. Match step is an endless scroll with no bulk accept.

## About the design files

The files in this bundle are **design references created in HTML** — a prototype showing intended look and behavior, not production code to copy. `Bids AI Workbench.dc.html` is a single self-contained page (a "Design Component": a template plus a small logic class, rendered by `support.js`). All styling is inline; there is no stylesheet, no build step, and no component library.

The task is to **recreate this design inside the existing `bids-ai` React/Vite frontend**, using its established patterns: real `.tsx` components under `src/web/src/components/`, the existing class-based CSS in `src/web/src/index.css`, and the existing API layer (`acceptAllLines`, `addDocuments`, `repriceLine`, `searchCatalog`, etc. already imported by `App.tsx`). Do not port the inline styles verbatim — map them onto the existing CSS custom properties, which already define this exact palette.

## Fidelity

**High-fidelity.** Colors, typography, spacing, density, and interaction states are final and should be matched closely. The palette and type are deliberately the app's *existing* green/Georgia theme (the user explicitly chose to keep it rather than move to a different brand system), so most values below already exist as CSS variables in `src/web/src/index.css` (`--paper`, `--paper-raise`, `--ink`, `--rule`, etc.). Prefer the existing variables over new literals.

Content in the prototype (bid names, clause text, catalog products, prices) is **representative sample data** modeled on the real seeded records. Wire it to real data; do not ship the literals.

---

## Design tokens

Taken from `src/web/src/index.css` (`:root`) and used throughout.

| Token | Value | Use |
|---|---|---|
| Paper / app background | `#f5f7f6` | Page background, expanded-row background |
| Paper raised | `#ffffff` | Cards, table rows, panes |
| Ink | `#14211e` | Primary text |
| Ink secondary | `#4b5c57` | Labels, secondary text |
| Ink muted | `#7e8c87` | Metadata, captions, placeholder |
| Ink disabled | `#a8b3af` | Unreached step labels, disabled icons |
| Rule | `#d8dfdc` | 1px borders, table gridlines |
| Wash | `#eef2f0` | Table headers, chips, inactive tabs, progress track |
| Brand deep | `#1f4d43` | Sidebar background, primary text on light, hover fill |
| Brand | `#2f6f62` | Primary buttons, progress fill, active step dot, focus border |
| Brand tint | `#dceae6` | Selected rows, "approved" pills, focus ring, hover on light |
| Brand soft | `#bcd6cf` | Confidence bars, dashed dropzone border, hover borders |
| Warn deep | `#8a5620` | Amber text ("Material", guarded state) |
| Warn | `#c97c2e` | Amber borders, guarded left-border, selected-candidate ring, medium risk dot |
| Warn tint | `#f7e6d2` | Amber fills (banner, pills) |
| Danger | `#b5533c` | High risk, reject, delete hover, destructive menu item |
| Danger tint | `#f5e1dc` | High-risk pill fill, delete hover fill |
| Danger border | `#e3c2b8` | High-risk pill border |

Radii: `4px` (chips/badges), `5px` (small buttons, inline inputs), `6px` (buttons, selects), `8px` (popovers, sample cards), `10px` (cards, table containers), `999px` (pills).

Shadows: popovers `0 8px 22px rgba(20,33,30,.16)`; user menu `0 10px 26px rgba(20,33,30,.22)`; provenance tooltip `0 6px 18px rgba(20,33,30,.14)`; document paper `0 1px 3px rgba(20,33,30,.08)`.

Type:
- UI sans: system stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif`).
- Display serif: **Georgia** — used only for screen titles, the bid name, and document body text.
- Mono: `ui-monospace, Menlo, monospace` — used for IDs, numerals, page refs, product codes, pills, and all-caps eyebrow labels.
- Scale: `9px`/`9.5px` (uppercase eyebrows, tracked `.05em`), `10.5px`–`11px` (metadata), `11.5px`–`12px` (secondary UI), `12.5px` (body/table), `13px`–`16px` (section titles), `19px` (bid name).
- Tabular numerals (`font-variant-numeric: tabular-nums`) on every numeric column.

Density: table rows `6–9px` vertical padding; card padding `12–16px`; grid gaps `6px` (control clusters), `10–18px` (layout).

---

## Layout shell

Three columns in a `display:flex; height:100vh; overflow:hidden` root.

**1. Nav sidebar** — `212px` expanded / `62px` collapsed, background `#1f4d43`, text `rgba(255,255,255,.92)`, padding `14px 10px`.
- Brand row: white `BA` monogram (6px radius, mono 12px) + "Bids AI" (13.5px, 600). A `«` button (26×26, `rgba(255,255,255,.08)`) collapses it. **When collapsed the BA monogram itself becomes the expand button** — there is no separate toggle row.
- Nav items: **Workbench** (trend/pipeline icon), **All Bids** (stacked bars), **Matrix** (grid). 18px inline SVGs, 1.6 stroke, `currentColor`. Active item: `rgba(255,255,255,.16)` fill, white text, 600 weight. Hover: `rgba(255,255,255,.1)`. Collapsed: icon only, centered.
- **Reviewer queue** panel (`rgba(255,255,255,.07)`, 8px radius, hidden when collapsed): "All teams · 11", "Corporate Legal · 5", "Business · 5", "Compliance · 1". Selecting one filters the Requirements table to that team's clauses and switches the header note to "N clauses routed to <team> — your queue". Counts come from the routing data, not hardcoded.
- Bottom, above the profile: **+ New bid** — full-width white button, `#1f4d43` text, 7px radius, `margin-top:auto`.
- **Profile / settings menu**: avatar + "Pavan Naidu" / "Bids team · Reviewer" + `▲`. Opens *upward* (`bottom: calc(100% + 8px)`), 280px wide. Contents: "SIGNED IN AS" eyebrow + email; divider; "SETTINGS" eyebrow; **Default extraction method** select (`ai_extract` | `ai_query`) with help text; **Match sensitivity** select (Aggressive | Balanced (default) | Conservative) with help text naming the minimum semantic score (0.55 / 0.70 / 0.85). Settings are edited inline in the popover — **no modal dialog**. No sign-out item.

**2. Main column** — `flex:1; min-width:0`.

**3. Document pane / rail** — right edge, wizard screens only. See "Source document pane".

### Top bar (wizard screens only)

White, `1px solid #d8dfdc` bottom border.
- Row 1 (`padding: 10px 18px 8px`): bid name in Georgia 19px; bid id as a mono 10.5px chip on `#eef2f0`; below it a 11.5px muted line — customer · due date (**no filename**; it lives in the document pane). Right: the single primary action, `#2f6f62` fill, white, 600, 12.5px — label changes per step ("Continue → extract", "Continue to line items →", "Confirm & find matches →", "Continue to generate →", "Download proposal").
- Row 2 — **step rail**: 5 equal-width buttons (`flex:1; min-width:130px`), each an 18px circular dot + mono 10.5px uppercase label.
  - Steps: Upload · Requirements · Line items · Match · Generate.
  - **Dot state is driven by the furthest step reached, not the current step.** Reached: `#2f6f62` fill, white numeral. Not reached: `#eef2f0` fill, `#a8b3af` numeral, `1px solid #d8dfdc`, `cursor:not-allowed`, non-clickable. Active additionally gets `box-shadow: 0 0 0 3px #dceae6` and a `2px solid #2f6f62` bottom border on the button.
  - **Numerals only — never swap to a checkmark.** Moving backward from Match to Requirements must leave Match and Generate green and clickable so the user can jump in both directions.

On **All Bids** and **Matrix** the whole bid header and step rail are replaced by a simple page header (Georgia 19px title + 11.5px subtitle) and the document pane is hidden.

### Source document pane

- Collapsed (default): a `38px` vertical rail on the right edge — white, `border-left: 1px solid #d8dfdc`, a document SVG, and the word "DOCUMENT" in `writing-mode: vertical-rl`, mono 10px, tracked `.1em`. Hover `#dceae6`.
- Expanded: `400px`, white.
  - **Tab strip** (`#eef2f0`, horizontally scrollable) — one tab per document in the bid, max 170px each, showing a file-type chip + shortened name. Active tab: white fill, `inset 0 2px 0 #2f6f62`, `#14211e` text.
  - Sub-header: full filename, page stepper `← 1 / 12 →`, and a `✕` that collapses the pane.
  - Body: the page rendered as paper on `#f5f7f6` — white sheet, 2px radius, `26px 24px` padding, Georgia 10.5px at 1.75 line-height.
  - Footer: "Document N of M in this bid" + "Open full document".
- **Deliberately a plain side-by-side reader.** There is no click-to-source highlighting and no page jumping from clauses or line items — the user removed that on purpose. Selecting a document on the Upload step swaps which file the pane shows.

---

## Screens

### 1. Upload

Two columns: `minmax(320px, 420px)` details card + flexible right column.

**Bid details card** — Bid name (optional) text input; "Bidding on behalf of" account select with an inline `+ New account` button; Submission deadline date input (mono). Footer note above a dashed rule: extraction starts on continue; requirements land first so reviewers can start on clauses while line items parse.

**Documents card** — header with live count and `+ Add document`; a dashed dropzone (`1.5px dashed #bcd6cf`, 10px radius, `#f5f7f6`, hover `#dceae6` + `#2f6f62` border) reading "Drag & drop bid documents here / PDF, DOCX, XLSX · multiple files per bid"; then one row per staged document — type chip, name, page/parse status, `✕` remove. Selected document: `#2f6f62` border, `#dceae6` fill.

**Sample solicitations card** — `repeat(auto-fit, minmax(230px, 1fr))` grid of 6 seeded government solicitations (title, agency, PDF chip). Clicking one replaces the staged document set.

### 2. Requirements & routing

Header: Georgia 16px title; the **Material flag** as a toggle pill (mono 10px uppercase, `#f7e6d2` on `#c97c2e` border) with a caret; a scope note on its own line ("11 clauses · 4 teams · routed by the BRD responsibility matrix"); right side — `Re-extract` then filter chips **All / Pending / High risk / Approved** (active chip: `#1f4d43` fill, white).

**Expanded material banner** (toggled by the pill): `#f7e6d2` on `1px solid #c97c2e`, 10px radius. Contains the verdict "Material — needs review", a right-aligned "Route to: <teams>", the sentence "N trigger clauses present; route to <teams> for review.", one chip per trigger clause (`#c97c2e` fill, white, pill), and an italic 11px note that this triage routing is a routing signal distinct from the per-clause risk levels below. **Clicking a trigger chip opens that clause's row.**

**Progress toolbar** (top of the table, 10px top radius, no bottom border): "N / M approved" + a `6px` progress bar (max 320px, `#eef2f0` track, `#2f6f62` fill) + risk legend dots (high `#b5533c`, medium `#c97c2e`, low `#d8dfdc`) + "N selected", **Approve selected**, **Reassign team**.

**Table** — `grid-template-columns: 34px 178px minmax(200px,1fr) 130px 84px 106px`, `min-width: 900px`, columns: checkbox · Term · Clause · Team · Risk · Status. Header row `#eef2f0`, mono 9.5px uppercase. Row: risk dot + term (600), clause truncated to one line, team, risk pill, status pill (Approved = `#dceae6`/`#1f4d43`; Pending = `#eef2f0`/`#7e8c87`).

**Expanded row** — click anywhere on the row (checkbox click must `stopPropagation`). Reveals `minmax(280px,1fr) 300px`: left = full clause at 12.5px/1.55 capped at `74ch`, an "AI CLASSIFIED" badge, "Page N · confidence N%", an "Edit clause" button, and the why-this-routes explanation; right = a review-note input and three verdicts — **Approve** (filled), **Needs changes** (`#8a5620` text), **Reject** (`#b5533c` on `#e3c2b8`). Critically, the clause cell keeps its grid track when expanded (`visibility:hidden`, **not** `display:none`) so columns don't shift.

Select-all in the header applies to the *currently filtered* rows only.

### 3. Line items

Header: title, live count note, manufacturer multi-select, `Re-extract`, `+ Add line`.

**Manufacturer filter** (shared with Match): a button showing "All manufacturers" / the single name / "N manufacturers", opening a 210px checkbox popover with an "All manufacturers" reset row. **Multi-select, not a single-value select.**

**Table** — `grid-template-columns: 62px minmax(240px,1fr) 80px 70px 110px 58px`, `min-width: 840px`: # + provenance · Description · Qty · UOM · Code given · Actions.
- Description, Qty, UOM, and Code are **editable in place**: borderless inputs (`border: 1px solid transparent`, transparent background) that reveal a `#d8dfdc` border and white fill on hover, `#2f6f62` on focus. The description gets the flexible track so it never truncates.
- **Provenance ⓘ** next to the row number. On hover, a 250px popover: file icon, source document name (`#1f4d43`, 600), "Page N", and an "AI EXTRACT" chip. This replaces a dedicated Page column and scales to bids with several documents.
- Actions: an icon-only trash button (`#7e8c87`; hover `#f5e1dc` fill, `#e3c2b8` border, `#b5533c`) — not 16 shouting "Delete" buttons.
- `+ Add line` appends a blank row; the header count updates live.

### 4. Match & price

Header: title; a note ("N of 16 lines matched at X% or better · 1 guarded"); then a wrapping control row — filter chips **All 16 / Needs decision · N / Accepted · N**; a divider; the manufacturer multi-select; **Re-run matching ▾**; **Accept matches & clear remaining (N) →**.

> Every control in this row must be `flex:none` with `white-space:nowrap`, and the row itself `flex-wrap:wrap` — otherwise labels get squeezed into vertical text at ~900px.

**Re-run matching menu** — 290px popover, two options, each a title + description: "Re-match unresolved only / Keeps your accepted / no-catalog-match picks." and "Re-match all (discard my picks)" in `#b5533c` / "Clears every candidate and selection, re-matches from scratch."

**Table** — `grid-template-columns: 34px minmax(240px,1fr) 230px 116px 84px 100px`, `min-width: 1000px`: # · Requested line (description + "Qty N UOM") · Selected match (code in mono `#1f4d43` + product name) · Confidence · Price · State.
- Confidence renders as a 100×16 bar: `#eef2f0` track, `#bcd6cf` fill (`#c97c2e` when guarded), percentage right-aligned inside it.
- **Guarded rows** (below threshold) get a `3px solid #c97c2e` left border and a "Decide" pill. Accepted rows get an "Accepted" pill in brand tint.

**Expanded row** — guarded rows lead with an amber callout explaining the guard ("Top semantic score 74%; Balanced requires 70% and a unit-of-measure check that this candidate fails."). Then the candidate list: each candidate is a radio row with a source badge (**Catalog** = brand tint; **Purchase history** = wash), product code, manufacturer, name, a note (last price / historical win record), and a relevance bar on the right. The selected candidate gets `#c97c2e` border + `#f7e6d2` fill.
- The score label is just **"Relevance"** everywhere — do not reintroduce "match relevance" / "voted relevance" variants.
- For a line with **no** confident match, the first candidate must render an explicit empty state ("No catalog candidate cleared the threshold", code `—`, guidance to search / pick history / mark no-bid). Do **not** derive a manufacturer or product name from the "No confident catalog match…" sentence.
- Footer actions: `Search catalog →`, `No catalog match`, a "Proposed price" input, the pricing provenance note, and **Accept & next** on the right.

### 5. Generate

A wrapping flex layout: proposal card `flex: 1 1 460px; min-width: 0`; right rail `flex: 1 1 220px; min-width: 200px; max-width: 280px` — **the rail must wrap below the proposal at narrow widths**, never sit off-pane.

**Generated proposal card** — header (`#eef2f0`): "GENERATED PROPOSAL" eyebrow, generation stamp ("Generated <ts> · v3 · pricing from Balanced strategy"), and `Download XLSX` / `Download PDF` / **Regenerate**. Body (Georgia, own `overflow-x:auto`): document title, a metadata line (customer · solicitation · submitter · due date), then the priced table.

Table columns (`min-width: 620px`): **Line · Item · Product · Qty · UOM · Price · Requested product**. The "Requested product" column carries the original solicitation wording so a reviewer can audit the substitution at a glance. Header rule is `1px solid #14211e`; rows separate on `#eef2f0`; the total row closes with another `1px solid #14211e` and a mono 15px bold figure.

**Right rail** — a *Summary* card (Lines priced, Requirements approved, Total bid value) and a *Before you submit* card listing only real blockers, each with a `Fix →` that navigates to the offending step and opens the offending row. This replaced an earlier full-page pre-flight checklist; keep it small and secondary.

### All Bids

Page header + a filter row: search input (bid name, ID, file, customer) and chips **All / My queue / In review / Matching / Due this week**.

Table (`minmax(240px,1fr) 210px 110px 80px 110px 140px`, `min-width: 940px`): Bid (name + mono id) · Customer · Stage pill (Submitted = brand tint; In review = amber; Matching = wash) · Lines · Due (mono; **`#b5533c` bold when within ~a week**) · Review progress (mini bar + percentage; full bar turns `#2f6f62` at 100%).

### Compliance matrix

Page header + filter input + `+ Add term`.

Table (`200px minmax(260px,1fr) 200px 90px 78px`, `min-width: 900px`): Term · Description (used by the classifier) · Owning team(s) · Default risk · Material trigger. Every cell after the description is **editable**:
- **Owning team(s)**: a chip-list button opening a 210px checkbox popover over the full team list (Business, Compliance, Corporate Affairs, Corporate Legal, HR, Risk Management, Tax, Quality). Multi-select — a term can be owned by several teams. This replaces the original 8 boolean columns, which is what was causing the horizontal clipping.
- **Default risk**: a select (high / medium / low) whose text color tracks the value (`#b5533c` / `#8a5620` / `#4b5c57`).
- **Material trigger**: a 15px checkbox, `accent-color: #2f6f62`.

---

## Interactions & behavior

- **Step navigation**: track `maxStep` (furthest reached) separately from `step` (current). `primaryAction` advances both; clicking a reached step only changes `step`.
- **Expansion**: Requirements and Match keep a single expanded row (`expandedReq` / `expandedMatch`); clicking the open row closes it. Approving from within a row collapses it.
- **Bulk approve**: applies to checked rows within the active filter, then clears the selection.
- **Bulk accept**: "Accept matches & clear remaining" marks every line at or above the sensitivity threshold accepted, leaving guarded lines for the reviewer.
- **Popovers** (provenance, manufacturer, teams, re-run, user menu) are local state, one open at a time per control. In production they should close on outside click and `Escape`; the prototype omits that.
- **Hover**: table rows `#f5f7f6`; secondary buttons `#bcd6cf` border + `#14211e` text; primary buttons `#1f4d43`; sidebar items `rgba(255,255,255,.1)`.
- **Responsive**: every table has an explicit `min-width` and a scrolling wrapper; every toolbar wraps. Nothing may be squeezed below its text width — this was a repeated defect during design.

## State

`screen` (wizard | allbids | matrix) · `step` · `maxStep` · `docOpen` · `docs[]` · `activeDoc` · `sidebarCollapsed` · `scope` (reviewer team) · `reqFilter` · `matchFilter` · `mfrSel[]` · `expandedReq` · `expandedMatch` · `selected{}` · `approved{}` · `accepted{}` · `lineEdits[]` · `matrixEdits[]` · `materialOpen` · `userMenuOpen` · `extractMethod` · `sensitivity` · popover-open flags.

In the real app most of this is server state — bid, documents, requirements, line items, candidates, and the compliance matrix all come from the existing API layer. Only filters, expansion, selection, and popover visibility are genuinely local.

## Assets

No external assets. All icons are inline SVGs written for this design (18px / 1.6 stroke, `currentColor`): plus, stacked bars, grid, trend line, document, trash, info, chevrons. If the codebase already has an icon set, use it — these are placeholders matching the weight, not brand assets. No images and no emoji.

## Files

- `Bids AI Workbench.dc.html` — the full prototype (template + logic class). Open it directly in a browser.
- `support.js` — the runtime that renders it. Not part of the target implementation.

Reference files in the source repo: `src/web/src/App.tsx` (flow + API calls), `src/web/src/index.css` (tokens, existing classes), `src/web/src/components/` (`MatchReviewCard.tsx`, `BidDetailsCard.tsx`, `CollapsibleCard.tsx`, `Sidebar.tsx`, `UploadScreen.tsx`) — the components this redesign replaces.
