"""Rebuild the showcase bids a new demo starts with, from the sample solicitations.

    python3 src/bootstrap/build_showcase_bids.py --target dev

Drives the target's deployed app through the real pipeline (parse, extract, match, review,
submit), one bid per entry in SHOWCASE, each stopped at a different stage. Then exports their
rows from Lakebase to src/app/server/_shared_data/showcase_bids.json, which the app loads into a
database that has no bids yet (showcase_seed.py). On export:
  - document paths point at the seeded sample files, relative to the documents volume;
  - reviewer emails are replaced with a placeholder;
  - each bid's timestamps move back by its `days_ago`, and its due date is that day plus the
    sample's response window.
The bids it creates stay in the target app. Run it after changing extraction or matching, so the
showcase shows the current pipeline. Needs the target set up (setup_demo.py).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from bundle_cli import BUNDLE_ROOT, DemoConfig, lakebase_connect, resolve, wait_until, workspace_client

FIXTURE = BUNDLE_ROOT / "src" / "app" / "server" / "_shared_data" / "showcase_bids.json"
PLACEHOLDER_REVIEWER = "reviewer@example.com"
STAGES = ("requirements", "line_items", "review", "submitted")
GATEWAY_TIMEOUTS = (502, 504)  # the Apps gateway's HTML error page, not the app's JSON errors

# One bid per stage, oldest first; the remaining samples stay fresh for a live upload.
SHOWCASE = (
    {"sample": "VA-2027-0114_PPE_Wound_Care.pdf", "bid_name": "VA Region 4 PPE and wound care",
     "stage": "submitted", "days_ago": 9},
    {"sample": "DLA-TS-MED-2027-0231_MedSurg_IDIQ.pdf", "bid_name": "DLA med-surg IDIQ",
     "stage": "review", "days_ago": 4},
    {"sample": "UN-HLTH-0892_Field_Clinic_Consumables.xlsx", "bid_name": "UN field clinic consumables",
     "stage": "line_items", "days_ago": 2},
    {"sample": "Premier_Dental_Infection_Control_Renewal.docx", "bid_name": "Dental infection control renewal",
     "stage": "requirements", "days_ago": 0},
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild the showcase bids from the sample solicitations.")
    parser.add_argument("--target", required=True, help="Bundle target whose app builds the bids, e.g. dev.")
    return parser.parse_args()


class AppClient:
    def __init__(self, workspace: Any, app_name: str) -> None:
        import requests

        self.url = workspace.apps.get(app_name).url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(workspace.config.authenticate())

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.request(method, self.url + path, json=body, timeout=600)
        response.raise_for_status()
        return response.json()

    def step(self, bid_path: str, step: str, done: Callable[[dict[str, Any]], bool], body: dict[str, Any] | None = None) -> None:
        """POST a pipeline step. The Apps gateway gives up on a request after 5 minutes while the
        app carries on, so after a gateway timeout wait for the step's result on the bid instead."""
        import requests

        try:
            response = self.session.post(f"{self.url}{bid_path}/{step}", json=body, timeout=600)
            if response.status_code not in GATEWAY_TIMEOUTS or "json" in response.headers.get("content-type", ""):
                response.raise_for_status()
                return
        except (requests.ConnectionError, requests.exceptions.ChunkedEncodingError):
            pass
        print(f"  {step}: the gateway timed out; waiting for the app to finish it", flush=True)
        wait_until(lambda: done(self.call("GET", bid_path)), f"{step} to finish", timeout_s=900, interval_s=15)


def build_bid(app: AppClient, spec: dict[str, Any], samples: dict[str, dict[str, Any]]) -> str:
    sample = samples[spec["sample"]]
    print(f"Building '{spec['bid_name']}' ({spec['stage']}) from {spec['sample']}", flush=True)
    bid = app.call("POST", "/api/bids/upload-sample", {
        "sample_file_name": spec["sample"], "customer_id": sample["customer_id"],
        "due_date": (date.today() + timedelta(days=sample["due_in_days"])).isoformat(), "bid_name": spec["bid_name"],
    })
    bid_id = bid["bid_id"]
    path = f"/api/bids/{bid_id}"
    app.step(path, "extract-requirements", lambda b: bool(b["requirements"]))
    level = STAGES.index(spec["stage"])
    if level >= STAGES.index("line_items"):
        app.step(path, "extract-line-items", lambda b: b["status"] == "matching")
    if level >= STAGES.index("review"):
        app.step(path, "match", lambda b: b["status"] == "pending_review", {})
    bid = app.call("GET", path)
    requirements = bid["requirements"]
    if spec["stage"] == "requirements":
        review_requirements(app, path, requirements[:2])
    elif spec["stage"] == "review":
        review_requirements(app, path, requirements[: len(requirements) // 2])
        review_some_lines(app, path, bid["line_items"])
    elif spec["stage"] == "submitted":
        review_requirements(app, path, requirements)
        app.call("POST", f"{path}/lines/accept-all")
        app.step(path, "submit", lambda b: b["status"] == "submitted")
    return bid_id


def review_requirements(app: AppClient, path: str, requirements: list[dict[str, Any]]) -> None:
    for requirement in requirements:
        app.call("PATCH", f"{path}/requirements/{requirement['requirement_id']}", {"review_status": "approved"})


def review_some_lines(app: AppClient, path: str, lines: list[dict[str, Any]]) -> None:
    """Accept the first few confident matches as matched, leaving the rest for the presenter."""
    confident = [
        line for line in lines
        if line.get("selected_item_code") and any(
            c.get("item_code") == line["selected_item_code"] and c.get("auto_select_eligible") for c in line["candidates"]
        )
    ]
    for line in confident[:5]:
        app.call("POST", f"{path}/lines/{line['line_id']}/review", {
            "selected_item_code": line["selected_item_code"], "proposed_price": line["proposed_price"],
        })


def export(
    workspace: Any, cfg: DemoConfig, bid_ids: list[str], samples: dict[str, dict[str, Any]], exported_at: datetime,
) -> dict[str, Any]:
    volume_root = f"/Volumes/{cfg.catalog}/{cfg.schema}/{cfg.volume}"
    order = {"bids": "bid_id", "bid_line_items": "line_number", "bid_requirements": "seq"}
    exported = []
    with lakebase_connect(workspace, cfg) as conn:
        for bid_id, spec in zip(bid_ids, SHOWCASE):
            rows = {
                table: conn.execute(f"SELECT * FROM bids.{table} WHERE bid_id = %s ORDER BY {column}", [bid_id]).fetchall()
                for table, column in order.items()
            }
            bid = rows["bids"][0]
            shift = exported_at - timedelta(days=spec["days_ago"], hours=3) - bid["created_at"]
            for table_rows in rows.values():
                for row in table_rows:
                    for column in ("created_at", "updated_at", "last_updated_at"):
                        if row.get(column):
                            row[column] += shift
                    for column in ("reviewer_email", "last_updated_by", "assigned_to"):
                        if row.get(column):
                            row[column] = PLACEHOLDER_REVIEWER
            sample = f"sample_bid_documents/{spec['sample']}"
            bid.update({
                "due_date": (bid["created_at"].date() + timedelta(days=samples[spec["sample"]]["due_in_days"])).isoformat(),
                "uploaded_document_path": sample, "proposal_pdf_path": None, "proposal_excel_path": None,
            })
            for document in bid["documents"]:
                assert document["path"].startswith(volume_root), document["path"]
                document["path"] = sample
            exported.append(rows)
    return {"exported_at": exported_at, "bids": exported}


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Can't serialize {type(value).__name__}")


def main() -> None:
    cfg = resolve(parse_args().target)
    workspace = workspace_client()
    app = AppClient(workspace, cfg.app_name)
    samples = {s["file_name"]: s for s in app.call("GET", "/api/sample-documents")["documents"]}
    bid_ids = [build_bid(app, spec, samples) for spec in SHOWCASE]
    fixture = export(workspace, cfg, bid_ids, samples, datetime.now(timezone.utc).replace(microsecond=0))
    FIXTURE.write_text(json.dumps(fixture, indent=1, default=_json_default) + "\n")
    print(f"Wrote {len(bid_ids)} showcase bids to {Path(FIXTURE).relative_to(BUNDLE_ROOT)}.")


if __name__ == "__main__":
    main()
