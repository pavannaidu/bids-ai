"""The SPA shell (index.html) must be served with Cache-Control: no-cache so a
new deploy's content-hashed JS/CSS bundle is picked up without a manual reload.
Without it, browsers serve a stale index.html pointing at an old bundle and
deploys silently don't reach users."""

from __future__ import annotations

from server import main


def test_index_html_is_no_cache():
    response = main.root()
    assert response.headers.get("cache-control") == "no-cache"
