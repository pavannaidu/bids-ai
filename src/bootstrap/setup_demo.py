"""Set up the Bids AI demo on a bundle target. Safe to re-run: every step converges.

    python3 src/bootstrap/setup_demo.py --target dev

Runs on your machine and drives the bundle. Undo it with teardown_demo.py.

Prerequisites (bundle variables; this script checks they exist and never creates or deletes them):
an existing Unity Catalog `schema` in `catalog`, an existing Databricks App `app_name`, and an
existing Lakebase project `lakebase_project` with database `lakebase_database` on branch
`lakebase_branch`. For native matching indexes, enable Lakebase Search on that project in the
Lakebase UI (project Settings > Lakebase Search).

  1. Check the prerequisites exist.
  2. Bind the existing app to the bundle (first run only), so deploys update its code and config.
  3. Deploy the bundle: the bid documents volume in the schema, the seed job, and the app's config
     and resources (Lakebase database, volume, model endpoints, AI Functions). A transient deploy
     error is retried.
  4. Seed the sample bid documents into the volume (files overwritten in place).
  5. Grant the app's service principal USE CATALOG, USE SCHEMA, and READ and WRITE VOLUME on the
     documents volume (again, since teardown deletes the volume). All idempotent. A grant you aren't
     allowed to make is skipped when the app already has the privilege through `account users`.
  6. Prepare the Lakebase database for the app: grant its service principal CONNECT and CREATE on
     the database (again, in case the database was recreated since the deploy first granted it),
     and create the app's `bids` and `bids_ref` schemas, owned by you, for the app to create its
     tables in. Postgres lets only a schema's owner drop it with the tables someone else created
     inside, which is how teardown removes them.
  7. Deploy and start the app. At startup it creates its tables, seeds the reference data (item
     catalog, bid and purchase history, customers, divisions), reseeding only when the data
     changed; embeds the catalog; and, when Lakebase Search is enabled, builds the BM25 and vector
     indexes. Nothing is synced from the lakehouse.
  8. Wait for the reference data and report which search backend is active.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import Any

from bundle_cli import (
    APP_KEY, APP_SCHEMAS, DemoConfig, app_is_bound, app_schema_owners, bundle, lakebase_connect, resolve, wait_until,
    workspace_client,
)

DEPLOY_ATTEMPTS = 3
NATIVE_INDEXES = ("item_catalog_bm25", "item_catalog_cosine")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set up the Bids AI demo (safe to re-run).")
    parser.add_argument("--target", required=True, help="Bundle target to set up, e.g. dev.")
    return parser.parse_args()


def check_prerequisites(workspace: Any, cfg: DemoConfig) -> None:
    from databricks.sdk.errors import NotFound

    checks = [
        (f"Unity Catalog schema {cfg.catalog}.{cfg.schema}", lambda: workspace.schemas.get(f"{cfg.catalog}.{cfg.schema}")),
        (f"Databricks App {cfg.app_name}", lambda: workspace.apps.get(cfg.app_name)),
        (f"Lakebase project {cfg.lakebase_project_id}", lambda: workspace.postgres.get_project(cfg.lakebase_project)),
        (f"Lakebase database {cfg.lakebase_database_name}", lambda: workspace.postgres.get_database(cfg.lakebase_database_name)),
    ]
    missing = []
    for what, get in checks:
        try:
            get()
        except NotFound:
            missing.append(what)
    if missing:
        sys.exit("Missing prerequisites (create them, or point the bundle variables at existing ones):\n  - "
                 + "\n  - ".join(missing))


def deploy_bundle(target: str) -> None:
    for attempt in range(1, DEPLOY_ATTEMPTS + 1):
        try:
            bundle(target, "deploy")
            return
        except subprocess.CalledProcessError:
            if attempt == DEPLOY_ATTEMPTS:
                raise
            print(f"Deploy failed (attempt {attempt}/{DEPLOY_ATTEMPTS}); retrying in 30s.", flush=True)
            time.sleep(30)


def grant_uc_access(workspace: Any, cfg: DemoConfig) -> None:
    from databricks.sdk.errors import PermissionDenied
    from databricks.sdk.service.catalog import PermissionsChange, Privilege

    principal = workspace.apps.get(cfg.app_name).service_principal_client_id
    volume = f"{cfg.catalog}.{cfg.schema}.{cfg.volume}"
    for securable, name, privileges in (
        ("catalog", cfg.catalog, [Privilege.USE_CATALOG]),
        ("schema", f"{cfg.catalog}.{cfg.schema}", [Privilege.USE_SCHEMA]),
        # The app's WRITE_VOLUME resource lands on the volume that existed when a deploy applied the
        # app's resources; teardown deletes the volume, and the next deploy doesn't grant it again.
        ("volume", volume, [Privilege.READ_VOLUME, Privilege.WRITE_VOLUME]),
    ):
        listed = ", ".join(p.value.replace("_", " ") for p in privileges)
        try:
            workspace.grants.update(
                securable_type=securable, full_name=name,
                changes=[PermissionsChange(principal=principal, add=privileges)],
            )
            print(f"Granted the app service principal {listed} on {name}.")
        except PermissionDenied:
            # In a shared catalog you may not be allowed to grant, but everyone may already have it.
            everyone = workspace.grants.get_effective(securable, name, principal="account users")
            held = {p.privilege for a in everyone.privilege_assignments or [] for p in a.privileges or []}
            if not set(privileges) <= held:
                sys.exit(f"You can't grant {listed} on {securable} {name}, and the app doesn't get it through "
                         f"`account users`. Ask an owner of {name} to grant it to the app's service principal "
                         f"{principal}, then re-run.")
            print(f"The app gets {listed} on {name} through `account users`.")


def prepare_lakebase(workspace: Any, cfg: DemoConfig) -> None:
    principal = workspace.apps.get(cfg.app_name).service_principal_client_id
    with lakebase_connect(workspace, cfg) as conn:
        # The deploy attaches the database to the app, which creates the app's Postgres role.
        wait_until(
            lambda: conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [principal]).fetchone() is not None,
            "the app's Postgres role", timeout_s=300, interval_s=10,
        )
        session = conn.execute("SELECT current_user AS me, current_database() AS db").fetchone()
        me = session["me"]
        # The app's CAN_CONNECT_AND_CREATE: granted when a deploy attaches the database, and lost if the
        # database is recreated after that.
        conn.execute(f'GRANT CONNECT, CREATE ON DATABASE "{session["db"]}" TO "{principal}"')
        for schema in APP_SCHEMAS:
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        for schema, owner in app_schema_owners(conn).items():
            if owner == me:
                conn.execute(f'GRANT USAGE, CREATE ON SCHEMA "{schema}" TO "{principal}"')
            else:
                print(f"Schema {schema} is owned by {owner}, not you, so only {owner} can drop it at teardown.")
    print(f"Prepared {cfg.lakebase_database_name} for the app: its database grants and schemas {', '.join(APP_SCHEMAS)}.")


def lakebase_status(workspace: Any, cfg: DemoConfig) -> dict[str, Any]:
    with lakebase_connect(workspace, cfg) as conn:
        cur = conn.cursor()
        cur.execute("SELECT to_regclass('bids_ref.item_catalog') IS NOT NULL AS ready")
        if not cur.fetchone()["ready"]:
            return {"items": 0, "embedded": 0, "search_enabled": False, "native": False}
        cur.execute("SELECT count(*) AS items, count(embedding) AS embedded FROM bids_ref.item_catalog")
        status = dict(cur.fetchone())
        # Installed by the app once Lakebase Search is enabled (the extensions are listed even before).
        cur.execute("SELECT count(*) AS n FROM pg_extension WHERE extname IN ('lakebase_text', 'lakebase_vector')")
        status["search_enabled"] = cur.fetchone()["n"] == 2
        cur.execute(
            "SELECT count(*) AS n FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = ANY(%s) AND i.indisvalid AND i.indisready",
            [list(NATIVE_INDEXES)],
        )
        status["native"] = cur.fetchone()["n"] == len(NATIVE_INDEXES)
        return status


def main() -> None:
    cfg = resolve(parse_args().target)
    print(
        f"Setting up target '{cfg.target}': app {cfg.app_name}, Lakebase {cfg.lakebase_database_name}, "
        f"documents /Volumes/{cfg.catalog}/{cfg.schema}/{cfg.volume}"
    )
    workspace = workspace_client()
    check_prerequisites(workspace, cfg)

    if not app_is_bound(cfg.target):
        bundle(cfg.target, "deployment", "bind", APP_KEY, cfg.app_name, "--auto-approve")
    deploy_bundle(cfg.target)
    bundle(cfg.target, "run", "seed_demo_data")
    grant_uc_access(workspace, cfg)
    prepare_lakebase(workspace, cfg)
    bundle(cfg.target, "run", APP_KEY)

    def seeded() -> bool:
        status = lakebase_status(workspace, cfg)
        return status["items"] > 0 and status["embedded"] == status["items"]

    try:
        wait_until(seeded, "the app to seed and embed the reference data", timeout_s=900)
    except TimeoutError:
        sys.exit(f"The app didn't finish seeding its reference data; check `databricks apps logs {cfg.app_name}`.")
    status = lakebase_status(workspace, cfg)
    print(f"\nReference data: {status['items']} catalog items, all embedded.")
    if status["native"]:
        print("Catalog search: Lakebase Search (native BM25 + vector indexes).")
    elif status["search_enabled"]:
        print("Lakebase Search is enabled but its indexes aren't built yet; re-run this script to restart the app.")
    else:
        print(
            "Catalog search: plain Postgres ranking. To use Lakebase Search, open "
            f"{cfg.lakebase_project_url(workspace)} > Settings > Lakebase Search > Enable (one-time; it restarts the "
            "project's compute), then re-run this script so the app builds the indexes."
        )
    print(f"\nSetup of '{cfg.target}' complete. App: {workspace.apps.get(cfg.app_name).url}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(
            f"\nSetup stopped: `{' '.join(map(str, exc.cmd))}` failed (exit {exc.returncode}). "
            "Fix the cause and re-run; every step is safe to repeat."
        )
