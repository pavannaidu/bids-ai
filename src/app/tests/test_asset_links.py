"""The app links out to the Databricks assets behind it (sidebar "Databricks assets" menu), and
registers dbdemos-tracker only inside Databricks Apps without ever blocking startup."""

from __future__ import annotations

import re
import sys
import types
from dataclasses import replace
from unittest.mock import patch

from fastapi import FastAPI

from server import assets, main
from server.config import get_settings

HOST = "https://my-workspace.cloud.databricks.example"


def test_links_are_built_from_the_host_settings_and_lakebase_endpoint():
    settings = replace(
        get_settings(), catalog="cat", schema_name="demo", bid_documents_volume="docs",
        model_serving_endpoint="llm-ep", embedding_endpoint="embed-ep",
    )
    endpoint = "projects/bids-ai-demo-dev/branches/production/endpoints/primary"
    with patch("server.assets.lakebase_project_uid", return_value="7e789735-uid"):
        links = {link["label"]: link for link in assets.asset_links(settings, HOST, endpoint)}

    assert links["Lakebase project"]["url"] == f"{HOST}/lakebase/projects/7e789735-uid"
    assert links["Lakebase project"]["detail"] == "bids-ai-demo-dev"
    assert links["Bid documents volume"]["url"] == f"{HOST}/explore/data/volumes/cat/demo/docs"
    assert links["Bid documents volume"]["detail"] == "cat.demo.docs"
    assert links["Extraction model endpoint"]["url"] == f"{HOST}/ml/endpoints/llm-ep"
    assert links["Embedding model endpoint"]["url"] == f"{HOST}/ml/endpoints/embed-ep"
    assert all(link["url"].startswith(HOST + "/") for link in links.values())


def test_lakebase_link_falls_back_to_the_project_list():
    endpoint = "projects/bids-ai-demo-dev/branches/production/endpoints/primary"
    with patch("server.assets.lakebase_project_uid", return_value=None):
        links = {link["label"]: link for link in assets.asset_links(get_settings(), HOST, endpoint)}
    assert links["Lakebase project"]["url"] == f"{HOST}/lakebase/projects"


def test_no_lakebase_link_without_an_endpoint():
    labels = {link["label"] for link in assets.asset_links(get_settings(), HOST, None)}
    assert "Lakebase project" not in labels
    assert assets.lakebase_project_id("not-a-resource-name") is None


def test_host_from_databricks_apps_env_gets_a_scheme(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "my-workspace.cloud.databricks.example/")
    assert assets.workspace_host() == HOST


def test_no_links_without_a_workspace(monkeypatch):
    monkeypatch.setattr(assets, "workspace_host", lambda: None)
    assert assets.list_assets() == {"assets": []}


def _fake_tracker(monkeypatch, add_tracker_fastapi):
    module = types.ModuleType("dbdemos_tracker")
    module.Tracker = types.SimpleNamespace(add_tracker_fastapi=add_tracker_fastapi)
    monkeypatch.setitem(sys.modules, "dbdemos_tracker", module)


def test_tracker_is_not_registered_outside_databricks_apps(monkeypatch):
    calls = []
    _fake_tracker(monkeypatch, lambda *args, **kwargs: calls.append(args))
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    main._register_usage_tracker(FastAPI())
    assert calls == []


def test_tracker_counts_page_loads_only(monkeypatch):
    calls = []
    _fake_tracker(monkeypatch, lambda app, demo_name, **kwargs: calls.append((demo_name, kwargs)))
    monkeypatch.setenv("DATABRICKS_APP_NAME", "bids-app")
    main._register_usage_tracker(FastAPI())

    [(demo_name, kwargs)] = calls
    assert demo_name == "hls-bids-ai"
    tracked = lambda path: any(re.match(p, path) for p in kwargs["patterns"])  # noqa: E731
    assert tracked("/")
    assert not tracked("/api/bids") and not tracked("/static/assets/index.js") and not tracked("/health")


def test_tracker_failure_never_blocks_startup(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("no workspace id")

    _fake_tracker(monkeypatch, boom)
    monkeypatch.setenv("DATABRICKS_APP_NAME", "bids-app")
    main._register_usage_tracker(FastAPI())  # logs, doesn't raise
