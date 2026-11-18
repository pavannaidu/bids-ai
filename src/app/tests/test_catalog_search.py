"""Catalog search in Lakebase: score scale, rank fusion, the native vs plain-Postgres SQL paths,
the manufacturer pre-filter, and the candidate contract build_weighted_candidates relies on."""

from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch

import pytest

from server import catalog_search
from server.config import get_settings

SETTINGS = get_settings()


def test_semantic_score_matches_vector_search_scale():
    # Measured on the old Vector Search index (gte-large-en): score = 1/(1+L2²) = 1/(3-2·cos).
    for cosine, vs_score in [(0.8911, 0.8191), (0.8227, 0.7374), (0.7424, 0.6590), (0.6205, 0.5680)]:
        assert catalog_search.semantic_score(cosine) == pytest.approx(vs_score, abs=0.0025)
    assert catalog_search.semantic_score(1.0) == 1.0


def test_rrf_is_normalized_over_the_rankings_that_returned_anything():
    fused = catalog_search.reciprocal_rank_fusion([["A", "B"], ["A", "C"]])
    assert fused["A"] == pytest.approx(1.0)
    assert fused["B"] == pytest.approx(fused["C"])
    assert fused["B"] < fused["A"]
    # One empty ranking (e.g. no keyword hits) doesn't cap the top score at 0.5.
    assert catalog_search.reciprocal_rank_fusion([[], ["C"]])["C"] == pytest.approx(1.0)
    assert catalog_search.reciprocal_rank_fusion([[], []]) == {}


def _unit(angle: float) -> list[float]:
    # A 1024-d vector at `angle` radians from the query below (cos = cos(angle)).
    return [math.cos(angle), math.sin(angle)] + [0.0] * 1022


QUERY = _unit(0.0)
CATALOG = {
    "SKU-A": {"item_code": "SKU-A", "description_long": "nitrile exam gloves", "manufacturer_name": "Medline",
              "list_price": 9.5, "embedding": _unit(0.30)},
    "SKU-B": {"item_code": "SKU-B", "description_long": "latex exam gloves", "manufacturer_name": "BD",
              "list_price": 7.0, "embedding": _unit(0.80)},
    "SKU-C": {"item_code": "SKU-C", "description_long": "gauze pads", "manufacturer_name": "Medline",
              "list_price": 3.0, "embedding": _unit(1.20)},
}


class _Cursor:
    """Records SQL; answers the keyword, vector and row-fetch queries from CATALOG."""

    def __init__(self, keyword_hits: list[str], keyword_scores: dict[str, float] | None = None):
        self.calls: list[tuple[str, list]] = []
        self._keyword_hits = keyword_hits
        self._keyword_scores = keyword_scores or {}
        self._rows: list[dict] = []

    def execute(self, sql: str, params=None):
        params = list(params or [])
        self.calls.append((sql, params))
        names = next((p for p in params if isinstance(p, list) and p and isinstance(p[0], str) and not p[0].startswith("SKU")), None)
        visible = [r for r in CATALOG.values() if not names or r["manufacturer_name"] in names]
        if "terms @@" in sql:
            hits = [c for c in self._keyword_hits if c in {r["item_code"] for r in visible}]
            self._rows = [{"item_code": c, "score": self._keyword_scores.get(c, float(i)),
                           "embedding": CATALOG[c]["embedding"]} for i, c in enumerate(hits)]
        elif "item_code = ANY" in sql:
            codes = params[0]
            self._rows = [dict(CATALOG[c]) for c in codes]
        elif "<=>" in sql:
            ranked = sorted(visible, key=lambda r: -catalog_search.cosine_similarity(QUERY, r["embedding"]))
            self._rows = [{"item_code": r["item_code"]} for r in ranked]
        else:
            self._rows = [{"item_code": r["item_code"], "embedding": r["embedding"]} for r in visible]

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _search(*, native: bool, keyword_hits=("SKU-B", "SKU-A"), settings=SETTINGS, manufacturers=None,
            embed_fails=False, keyword_scores=None):
    cursor = _Cursor(list(keyword_hits), keyword_scores)

    class _Conn:
        def cursor(self):
            return cursor

    @contextmanager
    def connect():
        yield _Conn()

    embed = patch("server.catalog_search.embed_query", side_effect=RuntimeError("down")) if embed_fails \
        else patch("server.catalog_search.embed_query", return_value=QUERY)
    with patch("server.catalog_search.lakebase.lakebase_configured", return_value=True), \
            patch("server.catalog_search.lakebase._connect", connect), \
            patch("server.reference_seed.native_search_ready", return_value=native), embed:
        hits = catalog_search.search_catalog(settings, "nitrile exam gloves", manufacturers=manufacturers)
    return hits, cursor.calls


def test_hybrid_fuses_keyword_and_vector_rankings_with_exact_semantic_scores():
    hits, calls = _search(native=False)
    assert [h["item_code"] for h in hits] == ["SKU-A", "SKU-B", "SKU-C"]
    top = hits[0]
    assert top["_retrieval_score"] == pytest.approx(
        (1 / 62 + 1 / 61) / (2 / 61), abs=1e-6)  # 2nd by keyword, 1st by vector
    assert top["_score"] == top["_retrieval_score"]
    assert top["_semantic_score"] == pytest.approx(catalog_search.semantic_score(math.cos(0.30)), abs=1e-6)
    assert top["list_price"] == 9.5 and "embedding" not in top
    # Plain Postgres path: ts_rank_cd keyword ranking, exact cosine computed in the app.
    assert any("ts_rank_cd" in sql for sql, _ in calls)
    assert not any("<@>" in sql or "<=>" in sql for sql, _ in calls)


def test_native_path_uses_lakebase_search_operators():
    _, calls = _search(native=True)
    keyword_sql = next(sql for sql, _ in calls if "terms @@" in sql)
    vector_sql = next(sql for sql, _ in calls if "<=>" in sql)
    assert "<@> to_bm25query(to_tsvector('simple', %s), 'bids_ref.item_catalog_bm25')" in keyword_sql
    assert "embedding::vector(1024) <=> %s::vector(1024)" in vector_sql


def test_keyword_ranking_matches_any_query_word():
    _, calls = _search(native=False)
    keyword_sql = next(sql for sql, _ in calls if "terms @@" in sql)
    assert "replace(plainto_tsquery('simple', %s)::text, '&', '|')::tsquery" in keyword_sql


def test_manufacturer_filter_applies_inside_both_rankings():
    hits, calls = _search(native=False, manufacturers=["Medline", " ", ""])
    filtered = [(sql, params) for sql, params in calls if "manufacturer_name = ANY(%s)" in sql]
    assert len(filtered) == 2  # keyword and vector branches
    assert all(["Medline"] in params for _, params in filtered)
    assert {h["manufacturer_name"] for h in hits} == {"Medline"}


def test_no_manufacturer_means_no_filter():
    _, calls = _search(native=False)
    assert not any("manufacturer_name = ANY" in sql for sql, _ in calls)


def test_ann_mode_ranks_by_vector_only_and_reports_the_semantic_score():
    hits, calls = _search(native=False, settings=replace(SETTINGS, search_mode="ann"))
    assert not any("terms @@" in sql for sql, _ in calls)
    assert [h["item_code"] for h in hits] == ["SKU-A", "SKU-B", "SKU-C"]
    assert all(h["_retrieval_score"] == h["_semantic_score"] for h in hits)


def test_embedding_failure_falls_back_to_keywords_without_semantic_scores():
    hits, _ = _search(native=False, embed_fails=True)
    assert [h["item_code"] for h in hits] == ["SKU-B", "SKU-A"]
    assert all(h["_semantic_score"] is None for h in hits)  # never auto-selected


def test_without_lakebase_search_uses_the_in_process_catalog():
    with patch("server.catalog_search.lakebase.lakebase_configured", return_value=False):
        hits = catalog_search.search_catalog(SETTINGS, "nitrile exam gloves", num_results=5, manufacturers=["Medline"])
    assert hits and all(h["manufacturer_name"] == "Medline" for h in hits)
    assert all(h["_semantic_score"] is None for h in hits)


def test_embed_texts_batches_and_validates_dimensions():
    calls = []

    def fake_post(path, body):
        calls.append(len(body["input"]))
        return {"data": [{"index": i, "embedding": [0.1] * 1024} for i in range(len(body["input"]))]}

    with patch("server.databricks_api._post_json", side_effect=fake_post):
        vectors = catalog_search.embed_texts("embed-ep", [f"t{i}" for i in range(35)])
    assert len(vectors) == 35 and calls == [16, 16, 3]

    with patch("server.databricks_api._post_json", return_value={"data": [{"index": 0, "embedding": [0.1] * 8}]}):
        with pytest.raises(RuntimeError):
            catalog_search.embed_texts("embed-ep", ["t"])


def test_embed_texts_returns_floats_even_when_the_endpoint_sends_integers():
    response = {"data": [{"index": 0, "embedding": [0, 1] + [0.5] * 1022}]}
    with patch("server.databricks_api._post_json", return_value=response):
        [vector] = catalog_search.embed_texts("embed-ep", ["t"])
    assert all(isinstance(v, float) for v in vector)


def test_keyword_ties_go_to_the_semantically_closer_item():
    # Equal keyword scores (variants the words can't tell apart): semantics decides, not item code.
    hits, _ = _search(native=False, keyword_hits=("SKU-B", "SKU-A"), keyword_scores={"SKU-A": -1.0, "SKU-B": -1.0},
                      settings=SETTINGS)
    assert hits[0]["item_code"] == "SKU-A"


def test_equal_fused_scores_go_to_the_semantically_closer_item():
    # SKU-B is 1st by keyword and 2nd by vector, SKU-A the reverse: equal RRF, A is closer.
    hits, _ = _search(native=False, keyword_hits=("SKU-B", "SKU-A"))
    assert hits[0]["_retrieval_score"] == hits[1]["_retrieval_score"]
    assert [h["item_code"] for h in hits[:2]] == ["SKU-A", "SKU-B"]
