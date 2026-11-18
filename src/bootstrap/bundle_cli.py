"""Local helpers shared by setup_demo.py and teardown_demo.py.

These run on your machine, not as bundle jobs. Every name comes from the target's resolved
bundle config (`databricks bundle validate -o json`), so nothing here is hardcoded.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUNDLE_ROOT = Path(__file__).resolve().parents[2]
APP_KEY = "bids_demo_app"
APP_SCHEMAS = ("bids", "bids_ref")  # created by setup in the Lakebase database; the app fills them


@dataclass(frozen=True)
class DemoConfig:
    target: str
    host: str
    catalog: str
    schema: str  # existing UC schema; the bundle creates the documents volume in it
    volume: str
    app_name: str  # existing app the bundle deploys to
    lakebase_project_id: str  # existing Lakebase project
    lakebase_branch: str
    lakebase_database_id: str  # database id in that branch

    @property
    def lakebase_project(self) -> str:
        return f"projects/{self.lakebase_project_id}"

    @property
    def lakebase_branch_name(self) -> str:
        return f"{self.lakebase_project}/branches/{self.lakebase_branch}"

    @property
    def lakebase_database_name(self) -> str:
        return f"{self.lakebase_branch_name}/databases/{self.lakebase_database_id}"

    def lakebase_project_url(self, workspace: Any) -> str:
        # The Lakebase UI addresses projects by uid, not by id.
        return f"{self.host}/lakebase/projects/{workspace.postgres.get_project(self.lakebase_project).uid}"


def bundle(target: str, *args: str, capture: bool = False) -> str:
    """Run `databricks bundle <args> -t <target>` from the bundle root; raises on failure."""
    cmd = ["databricks", "bundle", *args, "-t", target]
    if not capture:
        print("\n$ " + " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, cwd=BUNDLE_ROOT, check=True, text=True, stdout=subprocess.PIPE if capture else None
    )
    return result.stdout or ""


def resolve(target: str) -> DemoConfig:
    config = json.loads(bundle(target, "validate", "-o", "json", capture=True))
    # SDK clients use the target's workspace profile.
    profile = config["workspace"].get("profile")
    if profile:
        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
    variables = {name: spec.get("value") for name, spec in config["variables"].items()}
    return DemoConfig(
        target=target,
        host=workspace_client().config.host.rstrip("/"),
        catalog=variables["catalog"],
        schema=variables["schema"],
        volume=config["resources"]["volumes"]["bids_demo_documents"]["name"],
        app_name=variables["app_name"],
        lakebase_project_id=variables["lakebase_project"],
        lakebase_branch=variables["lakebase_branch"],
        lakebase_database_id=variables["lakebase_database"],
    )


def app_is_bound(target: str) -> bool:
    summary = json.loads(bundle(target, "summary", "-o", "json", capture=True))
    return bool(summary["resources"]["apps"][APP_KEY].get("id"))


def workspace_client() -> Any:
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


def lakebase_connect(workspace: Any, cfg: DemoConfig) -> Any:
    """Autocommit psycopg connection to the demo's Lakebase database as the current user."""
    import psycopg
    from psycopg.rows import dict_row

    endpoint = next(
        e for e in workspace.postgres.list_endpoints(cfg.lakebase_branch_name)
        if "READ_WRITE" in str(e.status.endpoint_type)
    )
    dbname = workspace.postgres.get_database(cfg.lakebase_database_name).status.postgres_database
    token = workspace.postgres.generate_database_credential(endpoint=endpoint.name).token
    return psycopg.connect(
        host=endpoint.status.hosts.host, port=5432, dbname=dbname, user=workspace.current_user.me().user_name,
        password=token, sslmode="require", autocommit=True, row_factory=dict_row,
    )


def app_schema_owners(conn: Any) -> dict[str, str]:
    """Owner role of each of the app's schemas that exists."""
    rows = conn.execute(
        "SELECT nspname, pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname = ANY(%s)",
        [list(APP_SCHEMAS)],
    ).fetchall()
    return {row["nspname"]: row["owner"] for row in rows}


def wait_until(done: Callable[[], bool], what: str, timeout_s: int = 1800, interval_s: int = 15) -> None:
    deadline = time.monotonic() + timeout_s
    while not done():
        if time.monotonic() > deadline:
            raise TimeoutError(f"Timed out after {timeout_s}s waiting for {what}.")
        print(f"  waiting for {what}…", flush=True)
        time.sleep(interval_s)
