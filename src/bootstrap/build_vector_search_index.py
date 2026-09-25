from __future__ import annotations

import argparse
import time

from databricks.vector_search.client import VectorSearchClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create/update the Vector Search endpoint + index over item_catalog.")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--endpoint-name", required=True)
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--index-name", default="item_catalog_index")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = VectorSearchClient(disable_notice=True)

    existing_endpoints = {e["name"] for e in client.list_endpoints().get("endpoints", [])}
    if args.endpoint_name not in existing_endpoints:
        print(f"Creating Vector Search endpoint {args.endpoint_name}...")
        client.create_endpoint(name=args.endpoint_name, endpoint_type="STANDARD")

    for attempt in range(60):
        status = client.get_endpoint(args.endpoint_name).get("endpoint_status", {}).get("state")
        if status == "ONLINE":
            print("Endpoint is ONLINE.")
            break
        print(f"  endpoint status={status}, waiting... ({attempt + 1}/60)")
        time.sleep(10)

    source_table = f"{args.catalog}.{args.schema}.item_catalog"
    index_name = f"{args.catalog}.{args.schema}.{args.index_name}"

    existing_indexes = {i["name"] for i in client.list_indexes(args.endpoint_name).get("vector_indexes", [])}
    if index_name in existing_indexes:
        print(f"Index {index_name} already exists — triggering sync.")
        client.get_index(args.endpoint_name, index_name).sync()
        print("Sync triggered.")
        return

    print(f"Creating Delta Sync index {index_name} over {source_table}...")
    client.create_delta_sync_index(
        endpoint_name=args.endpoint_name,
        source_table_name=source_table,
        index_name=index_name,
        pipeline_type="TRIGGERED",
        primary_key="id",
        embedding_source_column="description_long",
        embedding_model_endpoint_name="databricks-gte-large-en",
    )
    print("Index created. Initial sync runs automatically for a new TRIGGERED index.")


if __name__ == "__main__":
    main()
