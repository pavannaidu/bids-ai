# Architecture

One Databricks Asset Bundle (`databricks.yml`, `resources/`) deploys the demo into existing
resources (see [setup.md](setup.md#prerequisites)): it deploys the app's code and configuration,
and creates only the bid documents volume and a job that writes the sample solicitations.

| Component | What it is | Where it comes from |
|---|---|---|
| App `bids-ai-demo` | FastAPI backend (`src/app/server/`) serving the React UI (`src/web/`, built into `src/app/static/`) | Existing app (`app_name`); the bundle deploys its code and config (`resources/app.yml`) |
| Lakebase project `bids-ai-demo` | Postgres 17, scale-to-zero; database `bids_ai` holds all tabular data | Existing (`lakebase_project`, `lakebase_branch`, `lakebase_database`) |
| UC schema `bids_ai` | Holds the documents volume | Existing (`catalog`, `schema`) |
| Volume `bid_documents` | Sample solicitations, uploads, generated proposals | Created by the bundle (`resources/volumes.yml`) |
| Job `seed_demo_data` | Writes the 8 sample solicitations into the volume | Created by the bundle (`resources/jobs.yml`, `src/bootstrap/seed_demo_data.py`) |
| Model serving | `databricks-claude-sonnet-5-5` (extraction), `databricks-gte-large-en` (embeddings) | Workspace endpoints, attached as app resources |
| AI Functions | `system.ai.ai_parse_document`, `ai_extract`, `ai_classify` | Attached as app resources |

## Data

Everything tabular lives in the app's Lakebase database, in two schemas. Setup creates them, owned
by whoever runs it so that teardown can drop them, and the app creates and owns the tables in them
as its service principal:

- **`bids_ref`: reference data**, created and seeded directly in Lakebase by
  `src/app/server/reference_seed.py` from the synthetic generators in
  `src/app/server/_shared_data/demo_data.py`. Nothing is synced from the lakehouse.
  - `item_catalog`: 119 items, 24 manufacturers. It carries a keyword column (`terms`, a
    `tsvector`) and a 1024-d `embedding` of each description.
  - `historical_bids` (1,200 rows), `customer_purchase_history` (900), `customers` (20),
    `divisions` (7).
  - It reseeds only when the generated data or the table definitions change (a hash in
    `seed_state`), so restarts and redeploys are no-ops.
- **`bids`: transactional data:** bids, their source documents, line items with candidates and
  review decisions, requirements, app-created accounts, and responsibility-matrix overrides.
  - A database with no bids gets four showcase bids, one per review stage, from
    `src/app/server/_shared_data/showcase_bids.json` (`showcase_seed.py`). They were built with the
    app from the sample solicitations by `src/bootstrap/build_showcase_bids.py`.

The documents volume holds `sample_bid_documents/`, `uploads/<bid>/…` and
`generated_proposals/<bid>/…`.

## Workflow

1. **Upload:** files go to the volume. `ai_parse_document` returns structured elements with
   page spans, which every later step uses for provenance (document, file, page, method,
   confidence).
2. **Requirements:** `ai_extract` pulls clauses, grounded in the responsibility-matrix glossary.
   `ai_classify` routes each clause to a matrix term, which sets the owning teams and risk.
   A curated set of trigger terms marks a bid **material**, which then needs review.
3. **Line items:** `ai_extract` first. If it returns nothing, the direct Foundation Model API call
   on Claude Sonnet 5.5 recovers it. That model rejects `response_format` and `temperature`, so the
   JSON schema goes into the prompt. As a last resort the text is split heuristically. The
   Settings menu can switch the default extraction method at runtime.
4. **Match:** see below. A reviewer accepts, overrides (manual catalog search), or marks
   "no catalog product" per line.
5. **Generate:** proposal PDF (reportlab) and Excel quote (openpyxl), written to the volume.

## How matching works

`src/app/server/catalog_search.py` runs hybrid retrieval in Postgres over `bids_ref.item_catalog`:

- **Keyword ranking:** `tsvector` with the `simple` configuration, which keeps size letters like
  S/M/L that `english` drops as stopwords, plus an any-word query. With Lakebase Search it uses the
  native BM25 index (`lakebase_bm25`, score `terms <@> to_bm25query(...)`); otherwise
  `ts_rank_cd`.
- **Vector ranking:** cosine distance between the query embedding and each item's
  `databricks-gte-large-en` embedding. With Lakebase Search there's a native ANN index
  (`lakebase_ann`, `vector_cosine_ops`). For the small catalog, Postgres may still choose an exact
  scan, which returns the same results.
- **Fusion:** reciprocal-rank fusion (k = 60), normalized so an item ranked first in both lists
  scores 1.0. Ties go to the more semantically similar item. Manufacturer filters apply inside
  both rankings.
- **Confidence:** every candidate carries a semantic score, `1 / (3 − 2·cosine)`. That's the scale
  the earlier Vector Search implementation reported, so the match-sensitivity thresholds keep their
  meaning: auto-select at 0.60 (permissive), 0.70 (balanced, the default) or 0.80 (conservative).
- **Ranking:** history boosts are capped at 12% and never raise confidence. Exact product-code
  matches rank first. Compatibility checks (size, gauge, mask level, unit of measure) block or
  demote plausible but wrong items.
- **Fallbacks:** below 0.55 a general-knowledge suggestion is added for the reviewer. Without
  embeddings, search falls back to keywords only, and those candidates are never auto-selected.
- `BIDS_SEARCH_MODE=ann` switches to vector-only retrieval as a rollback. `/api/settings` reports
  whether the native Lakebase Search indexes are in use (`catalog_search`).

## Security and identity

The app reaches everything as its own service principal, through bundle-declared app resources:
- Lakebase: `CAN_CONNECT_AND_CREATE`, with OAuth database credentials minted at runtime.
- The volume: `WRITE_VOLUME`.
- The serving endpoints: `CAN_QUERY`.
- The AI Functions: `EXECUTE`.

In Unity Catalog, setup grants `USE CATALOG`, `USE SCHEMA`, and `READ VOLUME` and `WRITE VOLUME` on
the volume. In Postgres it grants `CONNECT` and `CREATE` on the database, and `USAGE` and `CREATE` on
the two schemas it creates. The volume and database grants repeat the app resources' permissions,
which a deploy applies only to the volume and database that exist at that moment: teardown deletes
the volume, and a database can be recreated. Teardown drops the schemas, revokes the catalog and
schema grants, and deletes the volume with its grant. There are no secrets in code or config.

## In-app links and usage tracking

- The sidebar's **Databricks assets** menu opens the Lakebase project, the documents volume and
  the two model endpoints (`GET /api/assets`, `src/app/server/assets.py`). Links are built at runtime
  from the workspace host and the app's settings.
- Usage is counted with [dbdemos-tracker](https://github.com/databricks-field-eng/dbdemos-tracker)
  (id `hls-bids-ai`):
  - Only app page loads count, not API calls.
  - Only `@databricks.com` users are counted, sent as a SHA-256 hash.
  - It's active only inside Databricks Apps.
