# Roboyo / UiPath proposal — component-by-component mapping

Reference for Q&A during/after the live demo. The demo itself should lead with the BRD's own
Current State → Future State MVP flow (BRD §6/§7), not a scripted takedown of Roboyo's proposal —
but if a specific line item comes up, here's the direct Databricks-native answer.

| Roboyo / UiPath component (Apr 2026 proposal) | Databricks-native equivalent in this demo |
|---|---|
| RPA — "Bid Collection" (screen-scrape/poll bid portals) | Upload / `ai_parse_document` ingestion step. A production build would add Lakeflow Connect/Autoloader watching a mailbox, SharePoint, or portal drop — governed file arrival, not a screen-scraping bot. |
| RPA — "Case ID Creation" | A `bids` row created the moment a document is uploaded (`POST /api/bids/upload*`), same governed Delta/Postgres estate as everything else — no separate case-management system. |
| UiPath Maestro (workflow orchestration) | The app's own request flow today; a production build would add a Lakeflow Job for batch/async stages. Same workflow engine you already run production jobs on. |
| UiPath IXP (Intelligent Document Processing) | `ai_parse_document` + a schema-constrained `ai_query` extraction pass — built-in SQL functions, not a separately licensed product with its own model and its own bill. |
| RPA — "Manual disbursement to respective stakeholders" (the BRD Current State's email-thread bottleneck) | The Requirements & routing step — a second `ai_query` pass extracts the non-product clauses (legal, pricing, compliance, insurance, HR) and routes each to its owning team via the BRD Glossary responsibility matrix, with high-risk terms flagged. Replaces the manual review + email hand-offs with a governed, per-clause routing view — no RPA bots forwarding attachments. |
| Agents & Action Center (human-in-the-loop) | The Bid Workspace review screen — weighted candidate cards, accept/override, editable pricing — backed by governed Lakebase/Delta tables instead of a proprietary queue. |
| AI Reporting & Queue Management | The Lakeview dashboard — same AI/BI tooling the customer's other Databricks workstreams (pricing, supply chain) already use, not a separate reporting layer bolted onto RPA queues. |
| UiPath License Assortment (~$307K quoted: RPA units, Action Center bundle, Agent Units, AI Units) | Consumption-based serverless compute + Foundation Model API usage on the Databricks platform you already own — no new platform, no new per-bot licensing model. |
| "No long-term central data architecture" (explicit scope exclusion in Roboyo's own solution design assumptions) | Everything here lands in Unity Catalog / Delta from the first line item — the opposite design point, and the same governed estate the CDO's "single source of truth" initiative is already standardizing on. |

**The one-sentence version:** You don't need a second platform with its own licensing model
to solve a data + AI problem — it needs to point AI at data that's already landing in Databricks.
