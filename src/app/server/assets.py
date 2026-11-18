"""Links from the app to the Databricks assets that power it. The sidebar's "Databricks assets"
menu lists them and opens each one in the workspace, so a viewer can click from any screen into
the Lakebase project that holds the catalog, bid history and the app's own data (with Lakebase
Search indexes for matching), the Unity Catalog volume with the bid documents, and the model
serving endpoints for extraction and embeddings.

Every link is built at runtime from the workspace host (DATABRICKS_HOST, injected by Databricks
Apps), the Lakebase endpoint the app's postgres resource injects (LAKEBASE_ENDPOINT), and the
app's settings, which come from bundle variables in resources/app.yml. No workspace URL or
resource name is hardcoded.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from urllib.parse import quote

from fastapi import APIRouter

from .config import Settings, get_settings

router = APIRouter()
logger = logging.getLogger("bids")


def workspace_host() -> str | None:
    """The workspace URL: DATABRICKS_HOST in Databricks Apps, else the local SDK profile's host."""
    host = os.environ.get("DATABRICKS_HOST", "").strip()
    if not host:
        try:
            from databricks.sdk import WorkspaceClient

            host = WorkspaceClient().config.host or ""
        except Exception:  # noqa: BLE001 - no workspace configured (local dev without a profile)
            return None
    host = host.rstrip("/")
    return host if host.startswith(("http://", "https://")) else f"https://{host}"


def lakebase_project_id(endpoint: str | None) -> str | None:
    """`projects/<id>/branches/<branch>/endpoints/<endpoint>` -> `<id>`."""
    parts = (endpoint or "").split("/")
    return parts[1] if len(parts) >= 2 and parts[0] == "projects" and parts[1] else None


@lru_cache(maxsize=4)
def lakebase_project_uid(project_id: str) -> str | None:
    """The Lakebase UI addresses projects by uid (`/lakebase/projects/<uid>`), not by id."""
    try:
        from databricks.sdk import WorkspaceClient

        return WorkspaceClient().postgres.get_project(f"projects/{project_id}").uid
    except Exception:  # noqa: BLE001 - fall back to the project list
        logger.warning("Couldn't look up Lakebase project %s; linking to the project list.", project_id, exc_info=True)
        return None


def asset_links(settings: Settings, host: str, lakebase_endpoint: str | None = None) -> list[dict[str, str]]:
    def url(*parts: str) -> str:
        return host + "/" + "/".join(quote(part, safe="") for part in parts)

    catalog, schema, volume = settings.catalog, settings.schema_name, settings.bid_documents_volume
    links = []
    project = lakebase_project_id(lakebase_endpoint)
    if project:
        uid = lakebase_project_uid(project)
        links.append({"group": "Lakebase", "label": "Lakebase project", "detail": project,
                      "url": url("lakebase", "projects", uid) if uid else url("lakebase", "projects")})
    links += [
        {"group": "Unity Catalog", "label": "Bid documents volume", "detail": f"{catalog}.{schema}.{volume}",
         "url": url("explore", "data", "volumes", catalog, schema, volume)},
        {"group": "AI", "label": "Extraction model endpoint", "detail": settings.model_serving_endpoint,
         "url": url("ml", "endpoints", settings.model_serving_endpoint)},
        {"group": "AI", "label": "Embedding model endpoint", "detail": settings.embedding_endpoint,
         "url": url("ml", "endpoints", settings.embedding_endpoint)},
    ]
    return links


@router.get("/api/assets")
def list_assets() -> dict[str, object]:
    host = workspace_host()
    if not host:
        return {"assets": []}
    return {"assets": asset_links(get_settings(), host, os.environ.get("LAKEBASE_ENDPOINT"))}
