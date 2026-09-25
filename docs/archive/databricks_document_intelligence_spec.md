# Databricks document intelligence upgrade spec

## Purpose

Improve bid/document processing so the codebase uses Databricks document intelligence as a structured
extraction pipeline, not a text-flattening pipeline. The goal is to preserve document structure,
improve extraction quality, and carry source provenance through to the UI.

## Problem

The current flow appears to:

- parse documents,
- flatten the parse into plain text too early,
- run `ai_query` over the flattened text for extraction and routing,
- merge output at the bid level,
- lose page/file provenance in the process.

That creates avoidable problems:

- table extraction is noisy,
- long documents can truncate,
- source traceability is weak,
- routing/classification is brittle,
- the UI cannot explain where a row came from.

## Goals

1. Preserve [`ai_parse_document`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_parse_document) output as structured data.
2. Use [`ai_extract`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_extract) for structured extraction.
3. Use [`ai_classify`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_classify) for constrained routing and labeling.
4. Preserve provenance on every extracted line item and requirement.
5. Expose source traceability in the API and UI.
6. Keep current behavior as a fallback during rollout.

## Non-goals

- No full UI redesign.
- No model fine-tuning or training workflow.
- No rewrite of the bid model from scratch.
- No fully autonomous arbitrary-document extraction.
- No removal of fallback paths until the new path is stable.

## Proposed architecture

### 1. Preserve structured parse output

- Stop flattening [`ai_parse_document`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_parse_document) output immediately.
- Keep the parsed document object as the canonical intermediate representation.
- Derive plain text only when a downstream step truly needs it.

### 2. Classify before extraction

- Use [`ai_classify`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_classify) on parsed output or derived text to identify document type and extraction route.
- Use it for fixed label problems such as:
  - document type
  - owning team fallback
  - category assignment
  - relevance filtering

### 3. Use structured extraction

- Use [`ai_extract`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_extract) for:
  - line items
  - requirements
  - other structured fields
- Apply `ai_extract` one shot per source document by default.
- Normalize the single-document result in application code.
- Do not assume `ai_extract` is a direct drop-in replacement for a variable-length whole-document row array.
- Only introduce chunking later if a specific document proves too large or too irregular for reliable one-shot extraction.
- Reserve [`ai_query`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_query) for recovery only:
  - `ai_extract` returned no rows
  - `ai_extract` returned invalid or unusable schema output
  - `ai_extract` failed on an edge-case layout
- `ai_query` must not be used as a first-pass extractor when `ai_extract` returns usable structured data.

### 4. Preserve provenance end-to-end

Every extracted record should carry:

- `source_doc_id`
- `source_filename`
- `source_page` or `source_pages`
- optional `source_chunk_id` or `source_element_id`
- extraction method
- confidence if available

### 5. Merge at bid level, not provenance level

- Keep multi-file uploads merged into one bid.
- Treat the bid as the container.
- Treat each source document as the provenance root for extracted rows.

## Implementation plan

### Phase 1: Structured parse layer

Create a backend layer that preserves the parsed document structure.

- Add a function like `parse_document()` that returns the structured result from [`ai_parse_document`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_parse_document).
- Keep a wrapper for existing consumers if needed.
- Do not flatten until extraction or rendering requires it.

### Phase 2: Extraction routing

Split extraction by document shape.

- Table-heavy or structured regions:
  - use [`ai_extract`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_extract)
- Prose-heavy regions:
  - use [`ai_query`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_query) as fallback
- Long documents:
  - still run one extraction pass per document unless a later exception path is needed

### Phase 3: Constrained classification

Replace free-form routing fallbacks with [`ai_classify`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_classify).

Use it for:

- owning team fallback
- document type
- requirement category
- other fixed label sets

Keep any existing deterministic keyword/rule pass first if present, then use classification as fallback.

### Phase 4: Provenance propagation

Thread source metadata through:

- upload processing
- parsing
- extraction
- state/store
- API responses
- UI cards/rows

### Phase 5: UI provenance surface

Show provenance in the UI for extracted rows.

- source file name
- source page
- confidence
- extraction method
- jump back to source document when possible

## Data model changes

Add provenance fields to extracted entities.

### Line items

- `source_doc_id`
- `source_filename`
- `source_page` or `source_pages`
- `source_chunk_id` or `source_element_id`
- `extraction_method`
- `confidence`

### Requirements

- `source_doc_id`
- `source_filename`
- `source_page` or `source_pages`
- `source_chunk_id` or `source_element_id`
- `extraction_method`
- `confidence`

### Optional supporting fields

- `doc_type`
- `doc_type_confidence`
- `extraction_status`
- `validation_status`

## Backend/API changes

### Document parsing

- Replace the current parse-to-text-first flow with a structured parse object.
- Keep a text fallback path for compatibility.

### Extraction functions

- Update line-item extraction to accept structured parsed documents.
- Update requirement extraction to accept structured parsed documents.
- Return provenance alongside every extracted record.

### Classification

- Add a `classify_document()` step using [`ai_classify`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_classify).
- Use classification to decide:
  - whether the document is relevant
  - whether to extract line items, requirements, or both
  - whether fallback logic is needed

### Response shape

- Include provenance metadata in API responses.
- The frontend should not need a second lookup to identify the source of a row.

### Backward compatibility

- If structured extraction fails, fall back to the current [`ai_query`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_query) logic.
- Even fallback rows must still include provenance fields.
- The fallback is a recovery path, not a parallel primary path.

## UI changes

Keep this minimal and traceability-focused.

### Row-level provenance

For each line item and requirement:

- show source file name
- show page number
- show extraction method if useful
- make source metadata clickable if possible

### Source viewer

- Allow selecting a source document from an extracted row.
- Jump to the relevant page when supported.

### Bid summary

- Show counts by source document.
- Show extraction status per file.
- Show document type and confidence if available.

### Warning states

- Surface low-confidence extraction.
- Surface missing provenance explicitly.
- Surface fallback usage.

## Test plan

### Unit tests

- Structured parse is preserved and not flattened too early.
- `ai_classify` returns expected constrained labels.
- `ai_extract` output maps into the expected schema.
- Provenance is attached to every extracted row.
- Fallback paths still preserve provenance.

### Integration tests

- Single-file upload still works.
- Multi-file upload creates one bid with multiple source docs.
- Extracted rows link to the correct `source_doc_id`.
- API responses expose source metadata.
- Source-linked rows render correctly in the UI.

### Regression tests

- Existing bid flows still work.
- Current outputs remain compatible where needed.
- No row is emitted without source metadata.

### Metrics to track

- extraction coverage
- percent of rows with provenance
- fallback rate
- classification accuracy on sample docs
- extraction latency per document

## Rollout plan

1. Add schema fields first, keeping them nullable/additive.
2. Persist structured parses without removing the old path.
3. Add classification routing with `ai_classify`.
4. Switch the primary extraction path to `ai_extract`.
5. Restrict `ai_query` to recovery cases only.
6. Thread provenance through API and UI.
7. Remove the legacy text-first path once metrics are stable.

## Acceptance criteria

The work is complete when:

- every extracted line item includes `source_doc_id`
- every extracted requirement includes `source_doc_id`
- parsed documents are stored in structured form
- `ai_extract` is used for primary structured extraction
- `ai_extract` is applied one shot per source document and the result is normalized in code
- `ai_classify` is used for constrained routing/labeling
- `ai_query` is only used as a recovery path when `ai_extract` fails or returns unusable output
- multi-file uploads preserve file-level provenance end-to-end
- the UI displays source file and page metadata
- fallback extraction still includes provenance
- tests cover single-file, multi-file, classification, extraction, and provenance rendering

## Instructions for the coding agent

Implement in this order:

1. Inspect the current server extraction flow.
2. Identify where `ai_parse_document` output is flattened.
3. Refactor to preserve the structured parse.
4. Add provenance fields to models/state/store.
5. Replace routing fallbacks with `ai_classify`.
6. Replace primary extraction with `ai_extract`.
7. Update API payloads.
8. Update the UI to surface provenance.
9. Add tests for single-file and multi-file cases.
10. Measure fallback rate and provenance coverage.

## Databricks references

- [`ai_parse_document`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_parse_document)
- [`ai_extract`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_extract)
- [`ai_classify`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_classify)
- [`ai_query`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_query)
- [AI Functions overview](https://docs.databricks.com/aws/en/large-language-models/ai-functions)
