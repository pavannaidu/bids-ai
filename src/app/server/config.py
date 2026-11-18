from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


def _as_search_mode(value: str | None) -> str:
    mode = (value or "hybrid").strip().lower()
    return mode if mode in ("hybrid", "ann") else "hybrid"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"BIDS_{name}") or default


@dataclass(frozen=True)
class Settings:
    databricks_app_name: str
    catalog: str
    schema_name: str
    bid_documents_volume: str
    # Catalog search: "hybrid" (BM25 + vector, fused) or "ann" (vector only, the rollback switch).
    search_mode: str
    model_serving_endpoint: str
    # Embeds catalog descriptions and search queries for semantic matching.
    embedding_endpoint: str
    match_confidence_threshold: float
    max_history_boost_fraction: float
    # When True (default), extraction uses REST ai_extract. When False, it calls
    # the configured Foundation Model endpoint directly with structured output.
    use_ai_extract: bool

    @property
    def volume_root(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema_name}/{self.bid_documents_volume}"

    @property
    def uploads_path(self) -> str:
        return f"{self.volume_root}/uploads"

    @property
    def generated_proposals_path(self) -> str:
        return f"{self.volume_root}/generated_proposals"

    @property
    def sample_documents_path(self) -> str:
        return f"{self.volume_root}/sample_bid_documents"


# Runtime override for the extraction default, settable from the Settings pane.
# None means "use the env-driven Settings.use_ai_extract". Process-local (resets
# on redeploy/restart) by design — the frozen, lru_cache'd Settings stays as the
# deploy-time baseline; this layer sits outside it so a runtime toggle doesn't
# have to bust the cache or mutate a frozen dataclass.
_runtime_use_ai_extract: bool | None = None


def get_extraction_default() -> bool:
    """Effective default: REST ai_extract (True) or direct FMAPI (False)."""
    if _runtime_use_ai_extract is not None:
        return _runtime_use_ai_extract
    return get_settings().use_ai_extract


def set_extraction_default(value: bool) -> None:
    """Set the process-local extraction default (from PATCH /api/settings)."""
    global _runtime_use_ai_extract
    _runtime_use_ai_extract = value


# Match sensitivity — the named auto-select confidence modes. The threshold is
# compared against a candidate's UNBOOSTED semantic score (history can rank a
# close candidate, but must never manufacture confidence). Guards automated
# selection / bulk-accept only; a reviewer can always search + pick any product.
MATCH_SENSITIVITY_THRESHOLDS: dict[str, float] = {
    "conservative": 0.80,
    "balanced": 0.70,
    "permissive": 0.60,
}
_DEFAULT_MATCH_SENSITIVITY = "balanced"

# Process-local like _runtime_use_ai_extract (resets on redeploy by design).
_runtime_match_sensitivity: str | None = None


def get_match_sensitivity() -> str:
    """Effective match-sensitivity mode (conservative/balanced/permissive).
    Runtime override wins; otherwise the balanced default."""
    return _runtime_match_sensitivity or _DEFAULT_MATCH_SENSITIVITY


def set_match_sensitivity(mode: str) -> None:
    """Set the process-local match sensitivity (from PATCH /api/settings).
    Raises ValueError on an unknown mode."""
    global _runtime_match_sensitivity
    if mode not in MATCH_SENSITIVITY_THRESHOLDS:
        raise ValueError(f"Unknown match sensitivity {mode!r}; expected one of {sorted(MATCH_SENSITIVITY_THRESHOLDS)}.")
    _runtime_match_sensitivity = mode


def get_match_threshold() -> float:
    """The numeric auto-select threshold for the effective sensitivity mode."""
    return MATCH_SENSITIVITY_THRESHOLDS[get_match_sensitivity()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        databricks_app_name=os.environ.get("DATABRICKS_APP_NAME", "bids-ai-demo-dev"),
        catalog=_env("CATALOG", "pavan_naidu_catalog"),
        schema_name=_env("SCHEMA", "bids_ai_demo_dev"),
        bid_documents_volume=_env("VOLUME", "bid_documents"),
        search_mode=_as_search_mode(_env("SEARCH_MODE") or None),
        # The fallback uses strict structured output on this endpoint.
        model_serving_endpoint=_env("MODEL_SERVING_ENDPOINT", "databricks-claude-sonnet-5-5"),
        embedding_endpoint=_env("EMBEDDING_ENDPOINT", "databricks-gte-large-en"),
        match_confidence_threshold=_as_float(_env("MATCH_CONFIDENCE_THRESHOLD") or None, 0.55),
        max_history_boost_fraction=_as_float(_env("MAX_HISTORY_BOOST_FRACTION") or None, 0.12),
        use_ai_extract=_as_bool(_env("USE_AI_EXTRACT") or None, True),
    )
