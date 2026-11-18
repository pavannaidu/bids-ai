"""Catalog search for line-item matching, served from Lakebase.

Hybrid retrieval over bids_ref.item_catalog: a BM25 keyword ranking and a vector-similarity
ranking (databricks-gte-large-en embeddings of description_long), fused with reciprocal-rank
fusion. With Lakebase Search enabled on the project, both rankings use its native indexes
(lakebase_bm25 and lakebase_ann, built by reference_seed.py). Otherwise plain Postgres full-text
ranking and exact cosine similarity produce the same kind of result for the small demo catalog.

Candidates keep the contract build_weighted_candidates relies on:
 - _retrieval_score: the ranking signal (normalized RRF in hybrid mode, the semantic score in
   ann mode). _score mirrors it for manual-search callers.
 - _semantic_score: the confidence the match-sensitivity thresholds (0.6/0.7/0.8) were calibrated
   against. That was Vector Search's score, 1/(1 + L2²), which for these normalized embeddings is
   1/(3 − 2·cosine); it's computed exactly for every candidate.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import quote

from . import lakebase
from .config import Settings

logger = logging.getLogger("bids")

REF = lakebase.REF_SCHEMA
RRF_K = 60
BRANCH_POOL = 50  # candidates taken from each ranking before fusion
EMBEDDING_DIM = 1024
EMBED_BATCH = 16
CATALOG_COLUMNS = (
    "item_code", "manufacturer_item_code", "competitor_item_code", "description_short",
    "description_long", "manufacturer_name", "category", "subcategory", "uom", "pack_size",
    "item_size", "list_price",
)
# Any of the query's words: a bid line rarely contains every word of a catalog entry.
_ANY_WORD_QUERY = "replace(plainto_tsquery('simple', %s)::text, '&', '|')::tsquery"


def semantic_score(cosine: float) -> float:
    """Vector Search's 1/(1 + L2²) for normalized embeddings, expressed via cosine similarity."""
    return 1.0 / (3.0 - 2.0 * cosine)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """RRF over the non-empty rankings, normalized so a code ranked first in all of them is 1.0."""
    used = [r for r in rankings if r]
    scores: dict[str, float] = {}
    for ranking in used:
        for rank, code in enumerate(ranking, start=1):
            scores[code] = scores.get(code, 0.0) + 1.0 / (k + rank)
    best = len(used) / (k + 1)
    return {code: score / best for code, score in scores.items()} if used else {}


# --------------------------------------------------------------------------- #
# Embeddings (Foundation Model API, called as the app's service principal)
# --------------------------------------------------------------------------- #

_query_cache: OrderedDict[tuple[str, str], tuple[float, list[float]]] = OrderedDict()
_query_lock = threading.Lock()
_QUERY_TTL_S = 600
_QUERY_CACHE_SIZE = 256


def embed_texts(endpoint: str, texts: list[str]) -> list[list[float]]:
    from .databricks_api import _post_json

    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        response = _post_json(f"/serving-endpoints/{quote(endpoint, safe='')}/invocations", {"input": batch})
        data = sorted(response.get("data") or [], key=lambda item: item.get("index", 0))
        # Values come back as JSON numbers, some of them integers (e.g. 0); store all as floats.
        vectors.extend([float(x) for x in item.get("embedding") or []] for item in data)
    if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIM for v in vectors):
        raise RuntimeError(f"Embedding endpoint {endpoint} returned unexpected vectors.")
    return vectors


def embed_query(settings: Settings, text: str) -> list[float]:
    key = (settings.embedding_endpoint, text)
    now = time.monotonic()
    with _query_lock:
        hit = _query_cache.get(key)
        if hit and hit[0] > now:
            _query_cache.move_to_end(key)
            return hit[1]
    vector = embed_texts(settings.embedding_endpoint, [text])[0]
    with _query_lock:
        _query_cache[key] = (now + _QUERY_TTL_S, vector)
        while len(_query_cache) > _QUERY_CACHE_SIZE:
            _query_cache.popitem(last=False)
    return vector


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #

def _manufacturer_filter(names: list[str]) -> tuple[str, list[Any]]:
    return (" AND manufacturer_name = ANY(%s)", [names]) if names else ("", [])


def _keyword_ranking(cur, text: str, names: list[str], native: bool, query_vector: list[float] | None) -> list[str]:
    where, params = _manufacturer_filter(names)
    # Lower is better for both: BM25 distance natively, negated ts_rank_cd otherwise.
    if native:
        score = f"terms <@> to_bm25query(to_tsvector('simple', %s), '{REF}.item_catalog_bm25')"
    else:
        score = f"-ts_rank_cd(terms, {_ANY_WORD_QUERY})"
    cur.execute(
        f"SELECT item_code, {score} AS score, embedding FROM {REF}.item_catalog "
        f"WHERE terms @@ {_ANY_WORD_QUERY}{where} ORDER BY score, item_code LIMIT %s",
        [text, text, *params, BRANCH_POOL],
    )
    rows = cur.fetchall()

    # Keywords often can't tell catalog variants apart ("size medium" vs XS/S/M/L gloves score
    # the same), so ties go to the more semantically similar item rather than item-code order.
    def key(row: dict[str, Any]) -> tuple[float, float, str]:
        similarity = cosine_similarity(query_vector, row["embedding"]) if query_vector and row.get("embedding") else 0.0
        return (round(float(row["score"]), 6), -similarity, row["item_code"])

    return [row["item_code"] for row in sorted(rows, key=key)]


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.7g}" for v in vector) + "]"


def _vector_ranking(cur, vector: list[float], names: list[str], native: bool) -> list[str]:
    where, params = _manufacturer_filter(names)
    if native:
        cur.execute(
            f"SELECT item_code FROM {REF}.item_catalog WHERE embedding IS NOT NULL{where} "
            f"ORDER BY embedding::vector({EMBEDDING_DIM}) <=> %s::vector({EMBEDDING_DIM}) LIMIT %s",
            [*params, _vector_literal(vector), BRANCH_POOL],
        )
        return [row["item_code"] for row in cur.fetchall()]
    # Exact cosine, computed here: the demo catalog is ~120 rows.
    cur.execute(f"SELECT item_code, embedding FROM {REF}.item_catalog WHERE embedding IS NOT NULL{where}", params)
    scored = sorted(
        ((cosine_similarity(vector, row["embedding"]), row["item_code"]) for row in cur.fetchall()),
        key=lambda pair: (-pair[0], pair[1]),
    )
    return [code for _, code in scored[:BRANCH_POOL]]


def _fetch_rows(cur, codes: list[str]) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    cur.execute(
        f"SELECT {', '.join(CATALOG_COLUMNS)}, embedding FROM {REF}.item_catalog WHERE item_code = ANY(%s)",
        [codes],
    )
    return {row["item_code"]: lakebase._floatify(row) for row in cur.fetchall()}


def search_catalog(
    settings: Settings, query_text: str, num_results: int = 25,
    manufacturers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Top catalog candidates for a query, best first. `manufacturers` restricts the search to
    those brands (match-ANY)."""
    names = [m.strip() for m in (manufacturers or []) if m and m.strip()]
    if not lakebase.lakebase_configured():
        return _search_in_memory(query_text, num_results, names)
    ann_only = settings.search_mode == "ann"
    try:
        query_vector: list[float] | None = embed_query(settings, query_text)
    except Exception:
        logger.warning("Query embedding failed; catalog search uses keywords only.", exc_info=True)
        query_vector = None
    from .reference_seed import native_search_ready

    native = native_search_ready()
    with lakebase._connect() as conn, conn.cursor() as cur:
        keyword = [] if ann_only else _keyword_ranking(cur, query_text, names, native, query_vector)
        vector = _vector_ranking(cur, query_vector, names, native) if query_vector else []
        fused = {} if ann_only else reciprocal_rank_fusion([keyword, vector])
        order = vector if ann_only else sorted(fused, key=lambda code: (-fused[code], code))
        rows = _fetch_rows(cur, order[:num_results])

    hits = []
    for code in order[:num_results]:
        row = rows.get(code)
        if not row:
            continue
        embedding = row.get("embedding")
        semantic = (
            round(semantic_score(cosine_similarity(query_vector, embedding)), 6)
            if query_vector and embedding else None
        )
        hit = {column: row.get(column) for column in CATALOG_COLUMNS}
        hit["_retrieval_score"] = semantic if ann_only else round(fused[code], 6)
        hit["_score"] = hit["_retrieval_score"]
        hit["_semantic_score"] = semantic
        hits.append(hit)
    # Equal fused scores (e.g. two items swapping ranks between the rankings) go to the more
    # semantically similar one.
    hits.sort(key=lambda h: (-(h["_retrieval_score"] or 0.0), -(h["_semantic_score"] or 0.0), h["item_code"]))
    return hits


def _search_in_memory(query_text: str, num_results: int, names: list[str]) -> list[dict[str, Any]]:
    """Local dev without Lakebase: word-overlap ranking over the in-process synthetic catalog.
    No semantic score, so nothing found this way is ever auto-selected."""
    from . import reference

    words = set(re.findall(r"[a-z0-9]+", query_text.lower()))
    scored = []
    for row in reference.fallback_item_catalog():
        if names and row.get("manufacturer_name") not in names:
            continue
        text = " ".join(str(row.get(c) or "") for c in CATALOG_COLUMNS[:6]).lower()
        overlap = len(words & set(re.findall(r"[a-z0-9]+", text)))
        if overlap:
            scored.append((overlap / max(len(words), 1), row))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["item_code"]))
    return [
        {**{c: row.get(c) for c in CATALOG_COLUMNS}, "_retrieval_score": round(score, 6),
         "_score": round(score, 6), "_semantic_score": None}
        for score, row in scored[:num_results]
    ]
