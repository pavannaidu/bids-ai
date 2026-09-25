"""Builds and deploys the Bids AI showcase dashboard.

Two kinds of tiles, deliberately not blurred together:
 - Illustrative (BRD-target) tiles: match-rate comparison, prep-time trend,
   on-time submission trend. These are literal constants tied to numbers the
   BRD itself states (legacy <5%, CAT ~50%, prep time 8hr->less than 3hr,
   95% on-time target) — there's no production system yet to measure these
   from, so they're framed as targets, not measurements.
 - Real, computed tiles: historical bid outcomes by division (from
   historical_bids joined to divisions) and avg submitted vs. list price by
   category (from historical_bids joined to item_catalog) — genuine
   aggregates over the synthetic historical dataset.

Run:
    DATABRICKS_CONFIG_PROFILE=FEVM python3 dashboard/build_dashboard.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lakeview_builder import LakeviewDashboard  # noqa: E402

from databricks.sdk import WorkspaceClient  # noqa: E402

CATALOG = "pavan_naidu_catalog"
SCHEMA = "bids_ai_demo_dev"
WAREHOUSE_ID = "fb3b5c1dee0b9d55"
OUT_PATH = Path(__file__).resolve().parent / "bid_showcase_dashboard.lvdash.json"


def build() -> LakeviewDashboard:
    dashboard = LakeviewDashboard("Bids AI — Showcase")

    # --- Illustrative datasets (BRD-stated baselines / targets) -----------
    dashboard.add_dataset(
        "match_rate_comparison",
        "Match Rate Comparison (illustrative — legacy/CAT per BRD; Databricks AI is this showcase's target)",
        "SELECT 'Legacy tool' AS approach, 5.0 AS match_rate_pct, 1 AS sort_order "
        "UNION ALL SELECT 'CAT tool (code given only)', 50.0, 2 "
        "UNION ALL SELECT 'Databricks AI (this showcase)', 90.0, 3",
    )
    dashboard.add_dataset(
        "prep_time_trend",
        "Proposal Prep Time Trend (illustrative — toward the BRD's <3hr target)",
        "SELECT 'Week 1' AS week_label, 8.0 AS avg_prep_hours, 1 AS sort_order "
        "UNION ALL SELECT 'Week 2', 6.8, 2 "
        "UNION ALL SELECT 'Week 3', 5.4, 3 "
        "UNION ALL SELECT 'Week 4', 4.2, 4 "
        "UNION ALL SELECT 'Week 5', 3.3, 5 "
        "UNION ALL SELECT 'Week 6', 2.7, 6",
    )
    dashboard.add_dataset(
        "on_time_trend",
        "On-Time Submission Rate Trend (illustrative — toward the BRD's 95% target)",
        "SELECT 'Week 1' AS week_label, 61.0 AS on_time_pct, 1 AS sort_order "
        "UNION ALL SELECT 'Week 2', 70.0, 2 "
        "UNION ALL SELECT 'Week 3', 78.0, 3 "
        "UNION ALL SELECT 'Week 4', 85.0, 4 "
        "UNION ALL SELECT 'Week 5', 91.0, 5 "
        "UNION ALL SELECT 'Week 6', 96.0, 6",
    )

    # --- Real, computed datasets over the synthetic historical data --------
    dashboard.add_dataset(
        "bid_outcomes_by_division",
        "Historical Bid Outcomes by Division",
        f"SELECT d.division_name, d.capacity_constrained, hb.outcome, hb.historical_bid_id "
        f"FROM `{CATALOG}`.`{SCHEMA}`.historical_bids hb "
        f"JOIN `{CATALOG}`.`{SCHEMA}`.divisions d ON hb.division_id = d.division_id",
    )
    dashboard.add_dataset(
        "price_by_category",
        "Avg Submitted vs. List Price by Category",
        f"SELECT ic.category, "
        f"'Submitted price' AS metric, AVG(hb.submitted_price) AS avg_price "
        f"FROM `{CATALOG}`.`{SCHEMA}`.historical_bids hb "
        f"JOIN `{CATALOG}`.`{SCHEMA}`.item_catalog ic ON hb.item_code = ic.item_code "
        f"GROUP BY ic.category "
        f"UNION ALL "
        f"SELECT ic.category, 'List price' AS metric, AVG(ic.list_price) AS avg_price "
        f"FROM `{CATALOG}`.`{SCHEMA}`.historical_bids hb "
        f"JOIN `{CATALOG}`.`{SCHEMA}`.item_catalog ic ON hb.item_code = ic.item_code "
        f"GROUP BY ic.category",
    )

    # --- Layout: row 1, the two headline tiles -----------------------------
    dashboard.add_bar_chart(
        "match_rate_comparison", "approach", "match_rate_pct", "AVG",
        title="Item-Match Rate: Legacy vs. CAT Tool vs. Databricks AI",
        position={"x": 0, "y": 0, "width": 3, "height": 4},
        colors=["#FF3621", "#FFAB00", "#00A972"],
    )
    dashboard.add_line_chart(
        "prep_time_trend", "week_label", "avg_prep_hours", "AVG",
        title="Proposal Prep Time — Toward the <3hr Target",
        position={"x": 3, "y": 0, "width": 3, "height": 4},
    )

    # --- Row 2 ---------------------------------------------------------------
    dashboard.add_line_chart(
        "on_time_trend", "week_label", "on_time_pct", "AVG",
        title="On-Time Submission Rate — Toward the 95% Target",
        position={"x": 0, "y": 4, "width": 3, "height": 4},
    )
    dashboard.add_bar_chart(
        "bid_outcomes_by_division", "division_name", "historical_bid_id", "COUNT",
        title="Historical Bid Outcomes by Division (incl. capacity-constrained verticals)",
        position={"x": 3, "y": 4, "width": 3, "height": 4},
        color_field="outcome",
    )

    # --- Row 3 ---------------------------------------------------------------
    dashboard.add_bar_chart(
        "price_by_category", "category", "avg_price", "AVG",
        title="Avg Submitted Price vs. List Price by Category (margin signal)",
        position={"x": 0, "y": 8, "width": 6, "height": 4},
        color_field="metric",
    )

    return dashboard


def main() -> None:
    dashboard = build()
    OUT_PATH.write_text(dashboard.to_json())
    print(f"Wrote {OUT_PATH}")

    client = WorkspaceClient()
    me = client.current_user.me().user_name
    payload = dashboard.get_api_payload(warehouse_id=WAREHOUSE_ID, parent_path=f"/Users/{me}")

    existing = client.api_client.do(
        "GET", "/api/2.0/lakeview/dashboards", query={"page_size": 100}
    ).get("dashboards", [])
    match = next((d for d in existing if d.get("display_name") == payload["display_name"]), None)

    if match:
        dashboard_id = match["dashboard_id"]
        client.api_client.do(
            "PATCH", f"/api/2.0/lakeview/dashboards/{dashboard_id}",
            body={"display_name": payload["display_name"], "serialized_dashboard": payload["serialized_dashboard"]},
        )
        print(f"Updated existing dashboard {dashboard_id}")
    else:
        created = client.api_client.do("POST", "/api/2.0/lakeview/dashboards", body=payload)
        dashboard_id = created["dashboard_id"]
        print(f"Created dashboard {dashboard_id}")

    client.api_client.do("POST", f"/api/2.0/lakeview/dashboards/{dashboard_id}/published", body={"embed_credentials": False})
    print(f"Published. View at: {client.config.host}/dashboardsv3/{dashboard_id}/published")


if __name__ == "__main__":
    main()
