from __future__ import annotations

import argparse
import json
import sys
import uuid

from common import get_spark, runtime_file_path

SCRIPT_FILE = runtime_file_path(globals())
SHARED_ROOT = SCRIPT_FILE.parents[1] / "shared"
if SHARED_ROOT.exists() and str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))

from bids_demo import TABLE_NAMES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grant the Databricks App's service principal read access to the demo catalog/volume/Lakebase.")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--volume", required=True)
    parser.add_argument("--app-client-id", required=True)
    parser.add_argument("--index-name", default="item_catalog_index")
    parser.add_argument("--lakebase-instance", default="")
    parser.add_argument("--lakebase-database", default="bids_ai")
    return parser.parse_args()


def _grant_postgres_ref_access(*, instance: str, database: str, principal: str) -> str | None:
    """UC SELECT grants (above) don't propagate into Postgres ACLs for
    Lakebase-synced tables — the app's own Postgres role needs an explicit
    GRANT on the synced `*bids_ref` schema too, or every reference-data read
    the app makes 500s with 'no synced reference schema found' even though
    the schema/tables clearly exist."""
    if not instance:
        print("  (skipped) no --lakebase-instance given; not granting Postgres-side access.")
        return None

    import psycopg
    from databricks.sdk import WorkspaceClient

    workspace = WorkspaceClient()
    db_instance = workspace.database.get_database_instance(name=instance)
    host = db_instance.read_write_dns
    me = workspace.current_user.me().user_name
    token = workspace.database.generate_database_credential(
        request_id=str(uuid.uuid4()), instance_names=[instance]
    ).token

    with psycopg.connect(
        host=host, port=5432, dbname=database, user=me, password=token,
        sslmode="require", autocommit=True,
    ) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE %s "
            "ORDER BY length(schema_name) DESC LIMIT 1",
            ("%bids_ref",),
        )
        row = cur.fetchone()
        if not row:
            print("  (non-fatal) no *bids_ref schema found yet in Postgres — sync may not have run.")
            return None
        ref_schema = row[0]
        cur.execute(f'GRANT USAGE ON SCHEMA "{ref_schema}" TO "{principal}"')
        cur.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{ref_schema}" TO "{principal}"')
        # Cover tables synced *after* this grant runs (e.g. a later bundle deploy).
        cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{ref_schema}" GRANT SELECT ON TABLES TO "{principal}"')
        return ref_schema


def main() -> None:
    args = parse_args()
    spark = get_spark()
    principal = args.app_client_id

    spark.sql(f"GRANT USE CATALOG ON CATALOG `{args.catalog}` TO `{principal}`")
    spark.sql(f"GRANT USE SCHEMA ON SCHEMA `{args.catalog}`.`{args.schema}` TO `{principal}`")
    for table_name in TABLE_NAMES:
        spark.sql(f"GRANT SELECT ON TABLE `{args.catalog}`.`{args.schema}`.`{table_name}` TO `{principal}`")
    # The Vector Search Delta Sync index is itself a UC-registered, queryable object.
    try:
        spark.sql(f"GRANT SELECT ON TABLE `{args.catalog}`.`{args.schema}`.`{args.index_name}` TO `{principal}`")
    except Exception as exc:  # noqa: BLE001 - index may not exist yet on first bundle deploy
        print(f"  (non-fatal) could not grant on index: {exc}")
    spark.sql(f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{args.catalog}`.`{args.schema}`.`{args.volume}` TO `{principal}`")

    granted_ref_schema = None
    try:
        granted_ref_schema = _grant_postgres_ref_access(
            instance=args.lakebase_instance, database=args.lakebase_database, principal=principal,
        )
    except Exception as exc:  # noqa: BLE001 - non-fatal; app falls back to in-memory data if this fails
        print(f"  (non-fatal) Postgres-side grant failed: {exc}")

    print(json.dumps({
        "status": "ok",
        "granted_principal": principal,
        "granted_tables": list(TABLE_NAMES),
        "granted_postgres_ref_schema": granted_ref_schema,
    }, indent=2))


if __name__ == "__main__":
    main()
