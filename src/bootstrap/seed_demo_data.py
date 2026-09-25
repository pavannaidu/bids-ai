from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pyspark.sql.types import BooleanType, DoubleType, LongType, StringType, StructField, StructType

from common import get_spark, runtime_file_path, volume_root_path

SCRIPT_FILE = runtime_file_path(globals())
SHARED_ROOT = SCRIPT_FILE.parents[1] / "shared"
if SHARED_ROOT.exists() and str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))

from bids_demo.demo_data import (
    CUSTOMERS,
    DIVISIONS,
    build_customer_purchase_history_rows,
    build_historical_bid_rows,
    build_item_catalog_rows,
)
from bids_demo.sample_documents import SAMPLE_DOCUMENTS, document_manifest, render_document_bytes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed demo Unity Catalog tables and sample bid documents.")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--volume", required=True)
    return parser.parse_args()


# Explicit schemas — several columns (manufacturer_item_code, competitor_item_code,
# competitor_price_observed, item_size) are None for most rows. Spark's dict-based
# createDataFrame infers types from a sample of rows and raises CANNOT_DETERMINE_TYPE
# if that sample happens to be all-null for a column, so we spell out types instead
# of relying on inference.
_TABLE_SCHEMAS: dict[str, StructType] = {
    "item_catalog": StructType([
        StructField("id", LongType(), False),
        StructField("item_code", StringType(), False),
        StructField("manufacturer_name", StringType(), True),
        StructField("manufacturer_item_code", StringType(), True),
        StructField("competitor_item_code", StringType(), True),
        StructField("description_short", StringType(), True),
        StructField("description_long", StringType(), True),
        StructField("category", StringType(), True),
        StructField("subcategory", StringType(), True),
        StructField("uom", StringType(), True),
        StructField("pack_size", StringType(), True),
        StructField("item_size", StringType(), True),
        StructField("list_price", DoubleType(), True),
        StructField("is_active", BooleanType(), True),
    ]),
    "historical_bids": StructType([
        StructField("id", LongType(), False),
        StructField("historical_bid_id", StringType(), False),
        StructField("customer_id", StringType(), True),
        StructField("division_id", StringType(), True),
        StructField("item_code", StringType(), True),
        StructField("qty", LongType(), True),
        StructField("submitted_price", DoubleType(), True),
        StructField("outcome", StringType(), True),
        StructField("competitor_price_observed", DoubleType(), True),
        StructField("submitted_date", StringType(), True),
    ]),
    "customer_purchase_history": StructType([
        StructField("id", LongType(), False),
        StructField("purchase_history_id", StringType(), False),
        StructField("customer_id", StringType(), True),
        StructField("division_id", StringType(), True),
        StructField("item_code", StringType(), True),
        StructField("last_price_paid", DoubleType(), True),
        StructField("last_purchase_date", StringType(), True),
        StructField("cumulative_qty", LongType(), True),
    ]),
    "customers": StructType([
        StructField("id", LongType(), False),
        StructField("customer_id", StringType(), False),
        StructField("customer_name", StringType(), True),
        StructField("division_id", StringType(), True),
        StructField("customer_type", StringType(), True),
        StructField("region", StringType(), True),
    ]),
    "divisions": StructType([
        StructField("id", LongType(), False),
        StructField("division_id", StringType(), False),
        StructField("division_name", StringType(), True),
        StructField("vertical", StringType(), True),
        StructField("capacity_constrained", BooleanType(), True),
    ]),
}


def _ensure_primary_key(spark, fq: str, table_name: str) -> None:
    """Make the table sync-ready: Change Data Feed on + NOT NULL `id` + PRIMARY KEY(id).
    Defensive/idempotent so re-runs (overwrite) don't hard-fail on an existing constraint."""
    constraint = f"{table_name}_pk"
    statements = [
        f"ALTER TABLE {fq} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)",
        f"ALTER TABLE {fq} ALTER COLUMN id SET NOT NULL",
        f"ALTER TABLE {fq} DROP CONSTRAINT IF EXISTS {constraint}",
        f"ALTER TABLE {fq} ADD CONSTRAINT {constraint} PRIMARY KEY (id)",
    ]
    for statement in statements:
        try:
            spark.sql(statement)
        except Exception as exc:  # noqa: BLE001 - defensive/idempotent, matches bids-cpq's pattern
            print(f"  (non-fatal) {statement} -> {exc}")


def main() -> None:
    args = parse_args()
    spark = get_spark()

    spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{args.catalog}`.`{args.schema}`")
    spark.sql(f"CREATE VOLUME IF NOT EXISTS `{args.catalog}`.`{args.schema}`.`{args.volume}`")

    item_catalog_rows = build_item_catalog_rows()
    table_rows = {
        "item_catalog": item_catalog_rows,
        "historical_bids": build_historical_bid_rows(item_catalog_rows),
        "customer_purchase_history": build_customer_purchase_history_rows(item_catalog_rows),
        "customers": CUSTOMERS,
        "divisions": DIVISIONS,
    }

    for table_name, rows in table_rows.items():
        fq = f"`{args.catalog}`.`{args.schema}`.`{table_name}`"
        # Stable surrogate `id` so every table has a primary key. Lakebase synced
        # tables (UC -> Postgres) require a PK on the source Delta table.
        keyed_rows = [{"id": index, **row} for index, row in enumerate(rows)]
        schema = _TABLE_SCHEMAS[table_name]
        ordered_rows = [{field.name: row.get(field.name) for field in schema.fields} for row in keyed_rows]
        dataframe = spark.createDataFrame(ordered_rows, schema=schema)
        dataframe.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fq)
        _ensure_primary_key(spark, fq, table_name)
        print(f"Seeded {fq}: {len(rows)} rows")

    volume_root = volume_root_path(args.catalog, args.schema, args.volume)
    samples_dir = Path(volume_root) / "sample_bid_documents"
    samples_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir = Path(volume_root) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = Path(volume_root) / "generated_proposals"
    generated_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"catalog": args.catalog, "schema": args.schema, "volume": args.volume, "sample_documents": []}
    for document in SAMPLE_DOCUMENTS:
        content = render_document_bytes(document)
        out_path = samples_dir / document.file_name
        out_path.write_bytes(content)
        manifest["sample_documents"].append(document_manifest(document))
        print(f"Wrote sample bid document: {out_path} ({len(content)} bytes)")

    manifest_path = samples_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(
        json.dumps(
            {
                "status": "ok",
                "seeded_tables": sorted(table_rows.keys()),
                "sample_documents_path": str(samples_dir),
                "uploads_path": str(uploads_dir),
                "generated_proposals_path": str(generated_dir),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
