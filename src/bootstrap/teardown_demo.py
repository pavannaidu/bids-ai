"""Remove what setup_demo.py creates for a bundle target. Safe to re-run: every step skips what's
already gone.

    python3 src/bootstrap/teardown_demo.py --target dev         # asks you to confirm
    python3 src/bootstrap/teardown_demo.py --target dev --yes   # no prompt

DESTRUCTIVE: drops the app's `bids` and `bids_ref` schemas in the Lakebase database (every bid,
requirement and account created in the app, and the reference data) and deletes the bid
documents volume with its files.

What setup created, and how each goes:
  - the app's Postgres schemas `bids` and `bids_ref` (owned by whoever ran setup), with the tables
    and Lakebase Search indexes the app created in them: dropped here, after the app is stopped.
    Only their owner can drop them, so this stops first, deleting nothing, if you don't own them;
  - the app service principal's USE CATALOG / USE SCHEMA grants: revoked here;
  - the binding between the bundle and the existing app: removed here (`bundle deployment unbind`),
    so `bundle destroy` leaves the app itself in place;
  - the bid documents volume, the seed job and the bundle's workspace files: `bundle destroy`.
Never touched (prerequisites): the catalog and schema, the app, the Lakebase project and
database, and the model serving endpoints. The app is left stopped.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Any

from bundle_cli import (
    APP_KEY, APP_SCHEMAS, DemoConfig, app_is_bound, app_schema_owners, bundle, lakebase_connect, resolve,
    workspace_client,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove what setup_demo.py creates (safe to re-run).")
    parser.add_argument("--target", required=True, help="Bundle target to tear down, e.g. dev.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    return parser.parse_args()


def confirm(cfg: DemoConfig) -> None:
    print(f"Teardown permanently deletes, for target '{cfg.target}':")
    print(f"  - schemas {', '.join(APP_SCHEMAS)} in Lakebase {cfg.lakebase_database_name}, with every bid created in the app")
    print(f"  - volume {cfg.catalog}.{cfg.schema}.{cfg.volume} with its files, and the seed job")
    print(f"It stops app {cfg.app_name} and keeps it, the schema and the Lakebase project.")
    if input(f"Type the target name ({cfg.target}) to continue: ").strip() != cfg.target:
        sys.exit("Aborted; nothing was deleted.")


def stop_app(workspace: Any, cfg: DemoConfig) -> str | None:
    from databricks.sdk.errors import NotFound

    try:
        app = workspace.apps.get(cfg.app_name)
    except NotFound:
        print(f"App {cfg.app_name} doesn't exist; skipping its stop and grants.")
        return None
    state = app.compute_status.state.value if app.compute_status and app.compute_status.state else ""
    if state not in ("STOPPED", "STOPPING"):
        workspace.apps.stop_and_wait(cfg.app_name)
        print(f"Stopped app {cfg.app_name}.")
    return app.service_principal_client_id


def check_schema_owner(workspace: Any, cfg: DemoConfig) -> None:
    with lakebase_connect(workspace, cfg) as conn:
        me = conn.execute("SELECT current_user AS me").fetchone()["me"]
        others = {schema: owner for schema, owner in app_schema_owners(conn).items() if owner != me}
    if others:
        sys.exit(
            "Nothing was deleted: only a schema's owner can drop it, and you don't own "
            + ", ".join(f"{schema} (owner {owner})" for schema, owner in others.items())
            + ". Run teardown as that user. If the owner is the app's service principal (the app created the "
            "schemas before setup did), reset the Lakebase database instead: delete it and create it again as in "
            "docs/setup.md, Prerequisites."
        )


def drop_app_schemas(workspace: Any, cfg: DemoConfig) -> None:
    with lakebase_connect(workspace, cfg) as conn:
        for schema in APP_SCHEMAS:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    print(f"Dropped schemas {', '.join(APP_SCHEMAS)} in {cfg.lakebase_database_name}.")


def revoke_grants(workspace: Any, cfg: DemoConfig, principal: str) -> None:
    from databricks.sdk.errors import NotFound
    from databricks.sdk.service.catalog import PermissionsChange, Privilege

    for securable, name, privilege in (
        ("schema", f"{cfg.catalog}.{cfg.schema}", Privilege.USE_SCHEMA),
        ("catalog", cfg.catalog, Privilege.USE_CATALOG),
    ):
        try:
            workspace.grants.update(
                securable_type=securable, full_name=name,
                changes=[PermissionsChange(principal=principal, remove=[privilege])],
            )
        except NotFound:
            pass
    print("Revoked the app service principal's USE SCHEMA and USE CATALOG.")


def main() -> None:
    args = parse_args()
    cfg = resolve(args.target)
    workspace = workspace_client()
    if not args.yes:
        confirm(cfg)

    check_schema_owner(workspace, cfg)
    principal = stop_app(workspace, cfg)
    drop_app_schemas(workspace, cfg)
    if principal:
        revoke_grants(workspace, cfg, principal)
    if app_is_bound(cfg.target):
        bundle(cfg.target, "deployment", "unbind", APP_KEY)
    bundle(cfg.target, "destroy", "--auto-approve")
    print(f"\nTeardown of '{cfg.target}' complete.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(
            f"\nTeardown stopped: `{' '.join(map(str, exc.cmd))}` failed (exit {exc.returncode}). "
            "Fix the cause and re-run; every step is safe to repeat."
        )
