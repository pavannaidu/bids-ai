"""Unity Catalog Volume file I/O for the app.

Databricks Apps run in a plain container, not on a Databricks Runtime
cluster — there's no FUSE-mounted `/Volumes/...` filesystem here the way
there is in a notebook or job. Reading/writing Volume files from the app
itself has to go through the Files API instead of `pathlib`/`open()`.
"""

from __future__ import annotations

import io

from databricks.sdk import WorkspaceClient

_client: WorkspaceClient | None = None


def _workspace_client() -> WorkspaceClient:
    global _client
    if _client is None:
        _client = WorkspaceClient()
    return _client


def read_volume_file(path: str) -> bytes:
    response = _workspace_client().files.download(path)
    return response.contents.read()


def write_volume_file(path: str, content: bytes) -> None:
    _workspace_client().files.upload(path, io.BytesIO(content), overwrite=True)


def delete_volume_file(path: str) -> None:
    _workspace_client().files.delete(path)
