Subject: Bids AI — follow-up questions on product data and historical bid data

Thanks again for the detailed answers on the sizing assumptions — they've already helped us update volume and bid-size figures in the demand plan. Two of your answers raised follow-up questions we want to close out before we finalize the plan, since they touch the parts of the architecture we build first: the product catalog and the historical bid reference data.

## 1. Product catalog / data unification

**What we know today:**

- There isn't one catalog — bids draw from multiple catalogs, plus divisional customers pull item specifics from at least six additional systems: FED, MIN, DSM, DSL, MPH, MTX.
- Equipment-related bids are sourced from NES, separate from JDE, which appears to cover standard bids.
- Our current sizing assumes a single ~2M-SKU catalog refreshed weekly. That figure may still be roughly right in aggregate, but it doesn't yet account for pulling from this many distinct sources.

Unifying this product data into one place is foundational to the initiative — matching accuracy and catalog freshness both depend on it, so we want to get the source landscape right before finalizing scope.

**Questions for you:**

- For each source (FED, MIN, DSM, DSL, MPH, MTX, NES, JDE): what platform is it — ERP, PIM, homegrown database, spreadsheet/flat-file export? Cloud or on-prem?
- Is the ~2M SKU figure the combined, de-duplicated count across all sources, or does each system carry its own item count with overlap between them?
- Is there a common identifier (SKU, manufacturer code, catalog item code) that lets us join records across systems, or will we need fuzzy/semantic matching across differently structured item masters?
- Does each source refresh weekly, or does that cadence only hold for one system (e.g., JDE) while others update on a different schedule?
- Who owns each system, and does an existing extract, API, or replication feed already exist for it — or would we need to build a new connector per source?
- For equipment bids routed to NES instead of JDE: is there a reliable signal at intake (document type, product category, customer flag) that tells us which source to match against, or does that require manual tagging today?
- Is there already a catalog consolidation or MDM effort underway independent of this project? If so, what's its timeline relative to our target go-live?
- Any known data quality gaps across these sources — missing attributes, inconsistent units of measure, pricing tied to a specific system?

## 2. Historical bid data

**What we know today:**

- Historical bid data isn't readily available in a structured, accessible form.
- It currently lives on Mdrive, and the organization is mid-migration to Salesforce.

**Questions for you:**

- What does the Mdrive archive actually contain — raw bid documents/PDFs, spreadsheets, structured records, or a mix?
- Roughly how far back does the archive go, and roughly how many historical bids are we talking about?
- What's the scope of the Salesforce migration — will it carry over the full historical archive and attachments, or only active/go-forward records from a certain date?
- Once migrated, will historical bids land as structured fields (award status, price, customer) or just as attached documents in Salesforce?
- Is there a data owner for the Mdrive archive who could help us understand structure or provide a sample extract?
- Given that historical bid/pricing context is part of the matching experience, would you be open to sharing even a partial or sample dataset for an early pilot while the full migration completes?
- Are there any retention or compliance constraints on how far back historical bid data can be used?

Happy to jump on a call with the right data owners on your side if that's faster than working through this over email.
