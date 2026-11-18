# Setup and operations

## Prerequisites

The bundle deploys into existing resources and never creates or deletes them. Provision them once
(the commands below use the defaults from `databricks.yml`), or point the bundle variables at
resources you already have (`--var name=value`).

| Resource | Bundle variable (default) | Required configuration |
|---|---|---|
| Lakebase project | `lakebase_project` (`bids-ai-demo`) | Lakebase Autoscaling, **Postgres 17** (16+ is needed for Lakebase Search). Compute autoscaling 0.5–1 CU, scale to zero after 30 minutes idle. **Lakebase Search enabled** (see below). |
| Branch | `lakebase_branch` (`production`) | The project's default branch, created with the project. |
| Database | `lakebase_database` (`bids-ai`) | Postgres name `bids_ai`, owned by your Lakebase role. Setup creates the app's `bids` and `bids_ref` schemas in it; keep the database dedicated to the demo. |
| UC schema | `catalog`, `schema` (`pavan_naidu_catalog.bids_ai`) | Any schema; the bundle creates the `bid_documents` volume in it. |
| Databricks App | `app_name` (`bids-ai-demo`) | Any compute size (Medium is enough). Setup binds it to the bundle, then deploys its code, environment and resources. |
| Model serving | `model_serving_endpoint`, `embedding_endpoint` | `databricks-claude-sonnet-5-5` and `databricks-gte-large-en` available in the workspace. |

Create them with the Databricks CLI (`-p <profile>` on each command for a non-default profile):

```bash
databricks postgres create-project bids-ai-demo --json '{"spec": {"display_name": "Bids AI demo",
  "pg_version": 17, "default_endpoint_settings": {"autoscaling_limit_min_cu": 0.5,
  "autoscaling_limit_max_cu": 1, "suspend_timeout_duration": "1800s"}}}'
databricks postgres list-roles projects/bids-ai-demo/branches/production     # your role's name
databricks postgres create-database projects/bids-ai-demo/branches/production --database-id bids-ai \
  --json '{"spec": {"postgres_database": "bids_ai", "role": "projects/bids-ai-demo/branches/production/roles/<your-role>"}}'
databricks schemas create bids_ai <catalog>
databricks apps create bids-ai-demo
```

Then enable Lakebase Search on the project (one console click, below).

**Permissions for whoever runs setup and teardown:**
- **Lakebase:** project owner, or a member of `databricks_superuser`. Setup creates the app's
  schemas and grants the app access to them and to the database. Teardown drops the schemas, which
  only their owner can do, so run it as the user who ran setup.
- **Unity Catalog:** `CREATE VOLUME` on the schema, and `MANAGE` (or ownership) on the catalog and
  schema, to grant the app's service principal `USE CATALOG`, `USE SCHEMA` and access to the
  volume.
- **App:** `CAN_MANAGE`.

**Locally:** the Databricks CLI, and Python 3.11+ with `databricks-sdk==0.156.0` and
`psycopg[binary]==3.3.6`.

## Set up and tear down

```bash
databricks auth login --host https://<your-workspace>.cloud.databricks.com --profile FEVM
python3 -m pip install "databricks-sdk==0.156.0" "psycopg[binary]==3.3.6"

python3 src/bootstrap/setup_demo.py --target dev      # deploy the demo; safe to re-run
python3 src/bootstrap/teardown_demo.py --target dev   # remove what setup created; asks to confirm (--yes skips it)
```

`setup_demo.py`:
1. Checks the prerequisites exist.
2. Binds the existing app to the bundle (first run only).
3. Deploys the bundle: the `bid_documents` volume, the seed job, and the app's configuration and
   resources. It retries on a transient deploy error.
4. Runs the seed job, which writes the sample solicitations to the volume.
5. Grants the app's service principal `USE CATALOG`, `USE SCHEMA`, and `READ VOLUME` and
   `WRITE VOLUME` on the documents volume.
6. Prepares the Lakebase database: grants the app `CONNECT` and `CREATE` on it, and creates the
   app's `bids` and `bids_ref` schemas, owned by you, for the app to create its tables in.
7. Deploys and starts the app. At startup the app creates its tables, seeds and embeds the
   reference data, builds the Lakebase Search indexes when available, and loads the
   [showcase bids](#showcase-bids) into a database with no bids.
8. Waits until the catalog is embedded, then reports which search backend is active.

`teardown_demo.py` removes only what setup created:
1. Stops the app.
2. Drops the app's `bids` and `bids_ref` schemas.
3. Revokes the app's grants.
4. Unbinds the app.
5. Runs `databricks bundle destroy`, which deletes the documents volume with its files and the seed
   job.

It leaves the prerequisites in place. **The schema drop deletes every bid, requirement and account
created in the app.** Teardown checks first that you own both schemas, and stops without deleting
anything if you don't. Schemas the app created itself, before setup created them, are owned by the
app's service principal and can't be dropped by anyone else. To clear those, reset the database:
delete it (`databricks postgres delete-database projects/bids-ai-demo/branches/production/databases/bids-ai`),
create it again as in [Prerequisites](#prerequisites), and re-run setup.

## Enable Lakebase Search (once per project)

Lakebase Search can only be enabled in the Lakebase UI: open the project (`setup_demo.py` prints the
link), then **Settings > Lakebase Search > Enable**. It can't be turned off, and enabling it restarts
the project's compute. Then re-run `setup_demo.py`; the app restarts and builds the BM25 and vector
indexes. Until then, catalog search runs on plain Postgres ranking with the same results shape.

## Frontend

The UI is prebuilt into `src/app/static/`. After changing `src/web/`, rebuild it before running setup:

```bash
cd src/web && npm install && npm run build
```

Keep `src/web/package-lock.json` on public `https://registry.npmjs.org/` URLs. With a registry
mirror in `~/.npmrc`, `npm install` writes the mirror's host into `resolved`, so switch those back
before committing.

## Showcase bids

A new demo opens with four bids already in **All Bids**, built from the sample solicitations and
left at different stages:

| Bid | Sample | Stage |
|---|---|---|
| VA Region 4 PPE and wound care | `VA-2027-0114_PPE_Wound_Care.pdf` | Submitted, proposal ready |
| DLA med-surg IDIQ | `DLA-TS-MED-2027-0231_MedSurg_IDIQ.pdf` | Matched, some lines and requirements reviewed |
| UN field clinic consumables | `UN-HLTH-0892_Field_Clinic_Consumables.xlsx` | Requirements and line items extracted, not matched |
| Dental infection control renewal | `Premier_Dental_Infection_Control_Renewal.docx` | Requirements extracted, under review |

The other four samples are left for a live upload. The app loads the showcase bids from
`src/app/server/_shared_data/showcase_bids.json` into any database with no bids (so again after a
teardown and setup), with their dates moved up to the present. After changing extraction or
matching, rebuild them with `python3 src/bootstrap/build_showcase_bids.py --target dev`: it creates
the bids through the app's API and rewrites the file. The bids it creates stay in that app, next to
any showcase bids the app loaded before, so run it against a database with no bids when you can.

## Sample bids for live upload

`sample_bids/` holds six PDFs you can drag into the app during a demo, without the "Load a sample"
button: a VA Medical Center solicitation plus five government bid letters (DLA Troop Support,
Bureau of Prisons, Arizona DOC, City of Baltimore Health Dept., Indian Health Service). They're
generated by `_build_government_bid_documents()` in
`src/app/server/_shared_data/sample_documents.py` (fixed seed, reproducible). The seed job writes
the same documents, plus an XLSX and a DOCX, to the volume for the in-app sample picker.

## Local development and tests

Without Lakebase env vars (`PGHOST`, `PGUSER`), the app uses an in-memory store and the in-process
synthetic catalog (`server/state.py`, `server/reference.py`), and catalog search falls back to word
overlap. That's enough to iterate on the API and UI without a workspace. Document intelligence still
calls the AI Functions and model endpoints, so live flows need a valid `DATABRICKS_CONFIG_PROFILE`.

```bash
cd src/app
python3 -m pip install -r requirements.txt -r requirements-test.txt
python3 -m pytest tests
```

## Repo layout

- `databricks.yml`, `resources/`: the Asset Bundle (app, seed job, documents volume)
- `src/app/`: the Databricks App
  - `server/`: the FastAPI backend
  - `server/_shared_data/`: the synthetic data and sample documents
  - `static/`: the built UI
  - `tests/`
- `src/web/`: the React (Vite + TypeScript) frontend source
- `src/bootstrap/`: `setup_demo.py`, `teardown_demo.py` and `build_showcase_bids.py` (run
  locally), and the sample-document seed job
- `sample_bids/`: PDFs for live upload
- `docs/`: this documentation
