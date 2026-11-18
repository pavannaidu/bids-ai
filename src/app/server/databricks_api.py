"""Document intelligence, matching, and pricing for the Bids AI workflow.

Document parsing, extraction, and classification use the Databricks AI
Functions REST API. The structured-model recovery path calls Foundation Model
APIs directly, while product matching searches the catalog in Lakebase (catalog_search.py).
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import quote

from .config import Settings, get_match_threshold
from . import catalog_search, reference

logger = logging.getLogger("bids")


# --------------------------------------------------------------------------- #
# Databricks REST transport (app service-principal auth via WorkspaceClient)
# --------------------------------------------------------------------------- #


_workspace_client = None


def _get_workspace_client():
    from databricks.sdk import WorkspaceClient

    global _workspace_client
    if _workspace_client is None:
        _workspace_client = WorkspaceClient()
    return _workspace_client


def _post_json(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST JSON through the SDK's authenticated REST client."""
    response = _get_workspace_client().api_client.do("POST", path=path, body=body)
    if not isinstance(response, dict):
        raise RuntimeError(f"Databricks API returned an unexpected response for {path}")
    return response


def _call_ai_function(function_name: str, body: dict[str, Any]) -> dict[str, Any]:
    return _post_json(f"/api/2.0/ai-functions/{function_name}", body)


_fmapi_temperature_ok: dict[str, bool] = {}
# Newer Claude models (e.g. Sonnet 5.5) reject response_format ("structured output is not
# supported ... forced tool use"). For those, the JSON Schema goes into the prompt instead.
_fmapi_response_format_ok: dict[str, bool] = {}


def _schema_in_prompt(prompt: str, response_format: dict[str, Any]) -> str:
    schema = response_format.get("json_schema", {}).get("schema", response_format)
    return (
        f"{prompt}\n\nReply with only a JSON object (no markdown, no commentary) that matches "
        f"this JSON Schema:\n{json.dumps(schema)}"
    )


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _fmapi_structured_output(
    settings: Settings,
    prompt: str,
    response_format: dict[str, Any],
) -> Any:
    """Invoke the configured Foundation Model endpoint for JSON output: strict structured
    output where the model supports it, otherwise the schema in the prompt."""
    endpoint = settings.model_serving_endpoint
    path = f"/serving-endpoints/{quote(endpoint, safe='')}/invocations"
    body: dict[str, Any] = {
        "messages": [{"role": "user", "content": prompt}],
        "response_format": response_format,
        "stream": False,
    }
    if _fmapi_response_format_ok.get(endpoint) is False:
        del body["response_format"]
        body["messages"] = [{"role": "user", "content": _schema_in_prompt(prompt, response_format)}]
    if _fmapi_temperature_ok.get(endpoint) is not False:
        body["temperature"] = 0.0

    # Each fallback drops one parameter the endpoint rejects and retries, so this ends.
    while True:
        try:
            response = _post_json(path, body)
            break
        except Exception as exc:
            error = str(exc).lower()
            if "response_format" in body and "structured output is not supported" in error:
                logger.warning(
                    "Endpoint %s rejects structured output; putting the JSON schema in the prompt.",
                    endpoint,
                )
                _fmapi_response_format_ok[endpoint] = False
                del body["response_format"]
                body["messages"] = [{"role": "user", "content": _schema_in_prompt(prompt, response_format)}]
            elif "temperature" in body and "temperature" in error:
                logger.warning(
                    "Endpoint %s rejects temperature; retrying FMAPI without it.",
                    endpoint,
                )
                _fmapi_temperature_ok[endpoint] = False
                body.pop("temperature")
            else:
                raise
    _fmapi_temperature_ok[endpoint] = "temperature" in body
    _fmapi_response_format_ok[endpoint] = "response_format" in body

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("FMAPI response did not contain a completion choice")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    if "response_format" not in body and isinstance(content, str):
        content = _strip_code_fence(content)
    parsed = _loads_variant(content)
    if not isinstance(parsed, (dict, list)):
        raise RuntimeError("FMAPI structured output was not valid JSON")
    return parsed


# --------------------------------------------------------------------------- #
# Step 1: parse documents through the AI Functions REST API while preserving
# structured page/element output for provenance.
# --------------------------------------------------------------------------- #


_AI_PARSE_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".png", ".jpg", ".jpeg", ".tiff"}

# ai_parse_document / ai_extract / ai_classify are known-flaky on this deployment
# (occasional empty results). Bound a couple of retries on the parse call itself.
_PARSE_MAX_ATTEMPTS = 3
# A row's text must be at least this many chars before we try to attribute it to
# a page — shorter needles match too many spans to be meaningful.
_MIN_PAGE_MATCH_LEN = 12

# An ordered list of (source_page | None, element_text) spans from a parsed doc.
PageSpans = list  # list[tuple[int | None, str]]


def _loads_variant(value: Any) -> Any:
    """Decode JSON values that may be strings or double-encoded strings."""
    for _ in range(2):
        if not isinstance(value, str):
            return value
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return value


def _scalar(value: Any) -> Any:
    """Unwrap an ai_extract field value to its underlying scalar. ai_extract
    v2.1 can return a field as an object carrying provenance/confidence
    (e.g. {"value": "Gloves", "citations": [...]}) rather than a bare value; a
    list of such (repeated field). Normalize to the plain scalar so downstream
    string/int handling is uniform. FMAPI rows (already flat) pass through."""
    if isinstance(value, dict):
        for key in ("value", "text", "content"):
            if key in value:
                return value[key]
        return ""
    if isinstance(value, list):
        return _scalar(value[0]) if value else ""
    return value


def _scalar_str(value: Any) -> str:
    """_scalar + coerce to a stripped string ("" for None/empty)."""
    scalar = _scalar(value)
    return str(scalar).strip() if scalar is not None else ""


def _scalar_int(value: Any, default: int) -> int:
    """_scalar + best-effort int, falling back to default on anything odd."""
    scalar = _scalar(value)
    try:
        return int(scalar)
    except (TypeError, ValueError):
        return default


def parse_document(settings: Settings, volume_path: str, content: bytes) -> dict[str, Any]:
    """Parse an uploaded bid document into a structured intermediate:

        {
          "text":        str,          # flat text (for the model call + rendering)
          "page_spans":  [(page|None, text), ...],  # ordered element spans w/ page
          "source_kind": "ai_parse_document" | "excel" | "raw_json",
          "parse_error": str | None,
        }

    Excel bid templates aren't supported by ai_parse_document, so they're read
    with openpyxl and carry no page geometry (page_spans=[]). Everything else
    goes through ai_parse_document, whose `document.elements[]` carry the text
    and page ids used for provenance. Never raises — a totally failed parse
    returns empty text/spans so the caller can trigger recovery instead of 500ing
    (the endpoint is flaky)."""
    suffix = "." + volume_path.rsplit(".", 1)[-1].lower() if "." in volume_path else ""
    if suffix in (".xlsx", ".xls"):
        return {"text": _flatten_excel(content), "page_spans": [], "source_kind": "excel", "parse_error": None}

    parsed = _run_parse(settings, volume_path)
    if parsed is None:
        return {"text": "", "page_spans": [], "source_kind": "ai_parse_document",
                "parse_error": f"ai_parse_document returned no rows for {volume_path}"}

    data = _loads_variant(parsed)
    parse_error = None
    if isinstance(data, dict) and data.get("error_status"):
        parse_error = json.dumps(data["error_status"])
    text, spans = _index_parsed_document(parsed)
    source_kind = "ai_parse_document" if spans else "raw_json"
    return {"text": text, "page_spans": spans, "source_kind": source_kind, "parse_error": parse_error}


def _run_parse(settings: Settings, volume_path: str) -> Any | None:
    """Run REST ai-parse-document with bounded retries."""
    body = {"content": volume_path, "options": {"version": "2.0"}}
    for attempt in range(_PARSE_MAX_ATTEMPTS):
        try:
            parsed = _call_ai_function("ai-parse-document", body)
        except Exception:
            logger.exception("ai_parse_document call failed (attempt %d) for %s", attempt + 1, volume_path)
            parsed = None
        if parsed and parsed.get("document"):
            return parsed
        time.sleep(1.0 * (attempt + 1))
    return None


def _element_page(element: dict[str, Any]) -> int | None:
    """The 1-based page an element sits on, from its first bbox's page_id
    (ai_parse_document page ids are 0-based). None if absent/non-numeric."""
    bboxes = element.get("bbox")
    if not isinstance(bboxes, list) or not bboxes or not isinstance(bboxes[0], dict):
        return None
    try:
        return int(bboxes[0].get("page_id")) + 1
    except (TypeError, ValueError):
        return None


def _index_parsed_document(parsed: Any) -> tuple[str, list[tuple[int | None, str]]]:
    """Walk `document.elements[]` into (flat_text, page_spans). Each element
    contributes one span of (page, text). Falls back to the legacy flat-text
    extractor (and empty spans) when there are no structured elements."""
    data = _loads_variant(parsed)
    document = data.get("document", data) if isinstance(data, dict) else {}
    elements = document.get("elements") if isinstance(document, dict) else None
    if not isinstance(elements, list) or not elements:
        return _flatten_parsed_document(parsed), []

    spans: list[tuple[int | None, str]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        text = (element.get("content") or element.get("description") or "").strip()
        if not text:
            continue
        spans.append((_element_page(element), text))
    flat = "\n\n".join(text for _, text in spans)
    return flat, spans


def _match_page(needle: str, spans: list[tuple[int | None, str]]) -> int | None:
    """Best-effort page attribution for an extracted row. Returns a page only
    when the row's text can be pinned to a SINGLE page; prefers null over a wrong
    page. Strategy: exact containment on one page wins; containment on multiple
    pages is ambiguous -> null; otherwise a token-overlap tiebreak with a floor."""
    if not spans or not needle:
        return None
    norm = " ".join(needle.lower().split())
    if len(norm) < _MIN_PAGE_MATCH_LEN:
        return None

    contained = {pg for pg, text in spans if pg is not None and norm in " ".join(text.lower().split())}
    if len(contained) == 1:
        return next(iter(contained))
    if len(contained) > 1:
        return None  # spans across pages — don't guess

    needle_tokens = set(norm.split())
    best_page, best_ratio = None, 0.0
    for pg, text in spans:
        if pg is None:
            continue
        span_tokens = set(" ".join(text.lower().split()).split())
        ratio = (len(needle_tokens & span_tokens) / len(needle_tokens)) if needle_tokens else 0.0
        if ratio > best_ratio:
            best_page, best_ratio = pg, ratio
    return best_page if best_ratio >= 0.6 else None


def _flatten_excel(content: bytes) -> str:
    from io import BytesIO

    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(content), data_only=True)
    lines = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(values_only=True):
            cells = [str(v) for v in row if v is not None and str(v).strip()]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _flatten_parsed_document(parsed: Any) -> str:
    try:
        data = json.loads(parsed) if isinstance(parsed, str) else parsed
    except (json.JSONDecodeError, TypeError):
        return str(parsed)

    if not isinstance(data, dict):
        return str(data)

    document = data.get("document", data)
    pages = document.get("pages") if isinstance(document, dict) else None
    if isinstance(pages, list) and pages:
        chunks = []
        for page in pages:
            if isinstance(page, dict):
                chunks.append(page.get("content") or page.get("text") or "")
        text = "\n\n".join(chunk for chunk in chunks if chunk)
        if text.strip():
            return text

    # Fall back to any top-level "content"/"text" field, else the raw JSON.
    for key in ("content", "text", "markdown"):
        value = document.get(key) if isinstance(document, dict) else None
        if isinstance(value, str) and value.strip():
            return value
    return json.dumps(data)


def parse_document_to_text(settings: Settings, volume_path: str, content: bytes) -> str:
    """Back-compat thin wrapper: just the flat text of a parsed document, for
    consumers that don't need the structured page spans."""
    return parse_document(settings, volume_path, content)["text"]


def _as_parsed(parsed: dict[str, Any] | str) -> dict[str, Any]:
    """Accept either a structured parse dict (from parse_document) or a bare text
    string (Excel path / older callers / tests) and normalize to the dict shape."""
    if isinstance(parsed, str):
        return {"text": parsed, "page_spans": []}
    return parsed


# --------------------------------------------------------------------------- #
# Line-item extraction: ai_extract (primary) -> FMAPI (recovery) -> heuristic.
# --------------------------------------------------------------------------- #

# ai_extract v2.1 schema: a top-level "line_items" array of item objects. Field
# descriptions steer the model — notably that given_code is a MANUFACTURER /
# CATALOG part number only, NOT the document's own row/line label (e.g. a
# "Line 002" / "Item 5" token printed next to each row must never land here).
_LINE_ITEMS_EXTRACT_SCHEMA = json.dumps({
    "line_items": {"type": "array", "items": {"type": "object", "properties": {
        "line_number": {"type": "integer", "description": "The row/line number printed in the document for this item."},
        "raw_description": {"type": "string", "description": "The item description exactly as written — do not paraphrase, normalize, or expand abbreviations."},
        "qty": {"type": "integer", "description": "Integer quantity for this line; 1 if not stated."},
        "uom": {"type": "string", "description": "Unit-of-measure abbreviation exactly as written (e.g. BX, CS, EA, DZ); empty string if none is given."},
        "given_code": {
            "type": "string",
            "description": (
                "A manufacturer or competitor PART/CATALOG number explicitly present for this item "
                "(e.g. 'HN34263', '49068-01'). Do NOT include the document's own line/row label such "
                "as 'Line 002', 'Item 5', or a bare row number. Empty if no real product code is given."
            ),
        },
    }}}
})

# Extra steering passed to ai_extract via the `instructions` option.
_LINE_ITEMS_INSTRUCTIONS = (
    "This is a bid/solicitation for a medical and dental distributor. Extract product line items. "
    "given_code is ONLY a real manufacturer/catalog part number — never the document's own row or "
    "line label (e.g. 'Line 002', 'Item 5'). Leave given_code empty when a line has no genuine product code."
)

# Strict structured-output schema for the direct Foundation Model API fallback.
_LINE_ITEMS_FMAPI_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "line_items",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "line_number": {"type": "integer"},
                    "raw_description": {"type": "string"},
                    "qty": {"type": "integer"},
                    "uom": {"type": "string"},
                    "given_code": {"type": "string"},
                },
                "required": ["line_number", "raw_description", "qty", "uom", "given_code"],
                "additionalProperties": False,
            }}},
            "required": ["items"],
            "additionalProperties": False,
        },
    },
}

_LINE_ITEMS_PROMPT = (
    "You are extracting line items from a bid/solicitation document for a medical and dental "
    "distributor. Return every distinct line item you can find as a JSON array. For each line "
    "item, include: line_number (the row/line number printed in the document), raw_description (the item "
    "description exactly as written, do not paraphrase), qty (integer, default 1 if not given), "
    "uom (unit of measure abbreviation as written, empty string if not given), and given_code "
    "(a manufacturer or competitor part/catalog number ONLY if one is explicitly present in the "
    "text, otherwise an empty string — most lines will not have one). "
    "IMPORTANT: given_code must be a real product/catalog number (e.g. 'HN34263'); it must NEVER be the "
    "document's own row/line label such as 'Line 002', 'Item 5', or a bare row number — leave it empty in that case. "
    "Return ONLY the JSON array, no commentary.\n\n"
    "DOCUMENT:\n{document_text}"
)


def extract_line_items(settings: Settings, parsed: dict[str, Any] | str) -> list[dict[str, Any]]:
    """Turn a parsed document into structured bid line items, carrying provenance.

    Primary path is ai_extract (structured, schema-constrained). If that returns
    nothing usable it recovers through direct FMAPI, then to a heuristic
    line split. Every returned row is stamped with how it was extracted
    (extraction_method) and its best-effort source_page. The BRD's "95%
    description only" line items become real, queryable, traceable rows here."""
    parsed = _as_parsed(parsed)
    text = parsed.get("text") or ""
    spans = parsed.get("page_spans") or []

    items: list[dict[str, Any]] | None = None
    method = "ai_extract"
    if settings.use_ai_extract:
        items = _line_items_ai_extract(settings, text)
    if not items:  # flag off, or ai_extract returned nothing usable -> recover
        recovered = _line_items_fmapi(settings, text)
        if recovered:
            items, method = recovered, "fmapi"
    if not items:  # both AI paths empty/failed -> keep the demo alive
        items, method = _heuristic_line_split(text), "heuristic"

    normalized = []
    for i, item in enumerate(items or [], start=1):
        # ai_extract may wrap each field in a {value,...} object; _scalar_* unwrap
        # it. FMAPI / heuristic rows are already flat and pass through.
        raw_description = _scalar_str(item.get("raw_description"))
        given_code = _scalar_str(item.get("given_code"))
        normalized.append({
            "line_id": f"line-{uuid.uuid4().hex[:8]}",
            "line_number": _scalar_int(item.get("line_number"), i),
            "raw_description": raw_description,
            "qty": _scalar_int(item.get("qty"), 1) or 1,
            "uom": _scalar_str(item.get("uom")),
            "given_code": given_code or None,
            "source_page": _match_page(raw_description, spans),
            "extraction_method": method,
            "confidence": None,  # ai_extract's line schema carries no per-row score
        })
    return [item for item in normalized if item["raw_description"]]


def _line_items_ai_extract(settings: Settings, document_text: str) -> list[dict[str, Any]] | None:
    """ai_extract primary path. Returns the raw item list, or None on
    exception / error_message / empty result (each of which triggers recovery)."""
    if not document_text.strip():
        return None
    try:
        data = _call_ai_function("ai-extract", {
            "content": document_text,
            "schema": json.loads(_LINE_ITEMS_EXTRACT_SCHEMA),
            "options": {"version": "2.1", "instructions": _LINE_ITEMS_INSTRUCTIONS},
        })
    except Exception:
        logger.exception("ai_extract line-item extraction failed; will recover with FMAPI.")
        return None
    if not isinstance(data, dict) or data.get("error_message"):
        return None
    response = data.get("response")
    items = response.get("line_items") if isinstance(response, dict) else None
    return items if isinstance(items, list) and items else None


def _line_items_fmapi(settings: Settings, document_text: str) -> list[dict[str, Any]] | None:
    """Direct Foundation Model API recovery path for line items."""
    if not document_text.strip():
        return None
    try:
        parsed = _fmapi_structured_output(
            settings,
            _LINE_ITEMS_PROMPT.format(document_text=document_text),
            _LINE_ITEMS_FMAPI_RESPONSE_FORMAT,
        )
    except Exception:
        logger.exception("FMAPI line-item recovery failed; will fall back to heuristic split.")
        return None
    items = parsed.get("items", parsed) if isinstance(parsed, dict) else parsed
    return items if isinstance(items, list) and items else None


def _heuristic_line_split(document_text: str) -> list[dict[str, Any]]:
    """Best-effort fallback if the model call fails: one "line item" per
    non-trivial text line. Keeps the demo alive even if both AI paths fail."""
    lines = []
    for raw_line in document_text.splitlines():
        cleaned = raw_line.strip(" -•\t")
        if len(cleaned) < 8 or cleaned.lower().startswith(("solicitation", "vendors shall", "response due")):
            continue
        lines.append({"raw_description": cleaned, "qty": 1, "uom": ""})
    return lines[:25]


# --------------------------------------------------------------------------- #
# Step 2: "historical bid review" + "proposed item match" — catalog search
# candidate generation, boosted by historical bids / purchase history.
# --------------------------------------------------------------------------- #


_STOPWORDS = {
    "a", "an", "the", "of", "for", "with", "and", "or", "to", "in", "on", "at", "by",
    "item", "items", "each", "per", "unit", "units", "misc", "miscellaneous", "supply", "supplies",
}


def _is_low_specificity(raw_description: str) -> bool:
    """A description with fewer than 2 meaningful (non-stopword) tokens carries too
    little signal to trust an automated match, no matter how the embedding or
    purchase history score it — e.g. "table" or "item" alone."""
    tokens = re.findall(r"[a-z0-9]+", raw_description.lower())
    meaningful = [t for t in tokens if t not in _STOPWORDS and len(t) > 1]
    return len(meaningful) < 2


# --------------------------------------------------------------------------- #
# Compatibility checks — guard against catalog search's semantic similarity
# (plus purchase/bid history boosting) ranking a plausible-sounding but wrong
# product above the correct one, e.g. "isolation gown" matching gloves, or an
# ASTM level 3 mask query matching a level 1 mask. Family/clinical-level
# contradictions are "hard" (the candidate is very likely the wrong product,
# so it can never outrank a compatible one); UOM/size/gauge contradictions are
# "soft" (may be the right product in a different pack/size — kept visible,
# just penalized and flagged for manual review).
# --------------------------------------------------------------------------- #

_FAMILY_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bisolation\s+gowns?\b|\bgowns?\b"), "gown"),
    (re.compile(r"\bgloves?\b"), "glove"),
    (re.compile(r"\b(?:iv\s+)?admin(?:istration)?\s+sets?\b"), "administration set"),
    (re.compile(r"\bblood\s+collection\b|\bvacutainer|\btubes?\b"), "blood collection"),
    (re.compile(r"\bmasks?\b"), "mask"),
]


def _detect_family_signal(text: str) -> str | None:
    """Small, explicit keyword table rather than a learned classifier —
    scoped to the families the audit named plus a couple of easily-confused
    neighbors. Returns the matched family keyword, or None if no rule fires."""
    lowered = text.lower()
    for pattern, family in _FAMILY_KEYWORDS:
        if pattern.search(lowered):
            return family
    return None


def _detect_mask_level(text: str) -> int | None:
    lowered = text.lower()
    if "mask" not in lowered and "astm" not in lowered:
        return None
    match = re.search(r"level\s*([123])\b", lowered)
    return int(match.group(1)) if match else None


def _detect_gauge(text: str) -> int | None:
    match = re.search(r"\b(\d{1,2})\s*(?:g\b|gauge\b)", text.lower())
    return int(match.group(1)) if match else None


_SIZE_VOCAB = {"xs", "s", "m", "l", "xl", "small", "medium", "large"}
# "medium"/"m" etc. are the same size, just spelled differently between a
# requester's free text and the catalog's abbreviated item_size — normalize
# both sides to the same token before comparing, or every such pair falsely
# flags as a size mismatch.
_SIZE_ALIASES = {"small": "s", "medium": "m", "large": "l"}


def _normalize_size(token: str) -> str:
    return _SIZE_ALIASES.get(token, token)


def _detect_size_token(text: str) -> str | None:
    tokens = re.findall(r"[a-z0-9.]+", text.lower())
    for token in tokens:
        if token in _SIZE_VOCAB:
            return _normalize_size(token)
    return None


def _normalize_product_code(value: Any) -> str:
    """Normalize presentation-only differences while retaining code identity."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _is_exact_code_match(given_code: str | None, catalog_row: dict[str, Any]) -> bool:
    normalized = _normalize_product_code(given_code)
    if not normalized:
        return False
    return normalized in {
        _normalize_product_code(catalog_row.get("item_code")),
        _normalize_product_code(catalog_row.get("manufacturer_item_code")),
        _normalize_product_code(catalog_row.get("competitor_item_code")),
    }


def _hard_compatibility_reason(line_item: dict[str, Any], catalog_row: dict[str, Any]) -> str | None:
    """Family and clinical-level checks only — a contradiction here means the
    candidate is very likely the *wrong product*, not just the wrong variant."""
    query_text = line_item["raw_description"]
    catalog_text = " ".join(
        str(v) for v in (catalog_row.get("category"), catalog_row.get("subcategory"), catalog_row.get("description_long"))
        if v
    ).lower()

    family = _detect_family_signal(query_text)
    if family and family not in catalog_text:
        return f"Query suggests '{family}', but catalog item isn't categorized as one"

    query_level = _detect_mask_level(query_text)
    if query_level is not None:
        catalog_level = _detect_mask_level(catalog_text)
        if catalog_level is not None and catalog_level != query_level:
            return f"Query asks for ASTM level {query_level}, catalog item is level {catalog_level}"

    return None


def _soft_compatibility_reason(line_item: dict[str, Any], catalog_row: dict[str, Any]) -> str | None:
    """UOM/size/gauge checks — a mismatch may still be the right product in a
    different pack/size, so it's penalized and flagged rather than excluded."""
    requested_uom = (line_item.get("uom") or "").strip().upper()
    catalog_uom = (catalog_row.get("uom") or "").strip().upper()
    if requested_uom and catalog_uom and requested_uom != catalog_uom:
        return f"Requested UOM '{requested_uom}' differs from catalog UOM '{catalog_uom}'"

    catalog_text = str(catalog_row.get("item_size") or "") + " " + str(catalog_row.get("description_long") or "")
    query_gauge = _detect_gauge(line_item["raw_description"])
    if query_gauge is not None:
        catalog_gauge = _detect_gauge(catalog_text)
        if catalog_gauge is not None and catalog_gauge != query_gauge:
            return f"Requested {query_gauge}g, catalog item is {catalog_gauge}g"

    query_size = _detect_size_token(line_item["raw_description"])
    if query_size is not None:
        catalog_size = _normalize_size((catalog_row.get("item_size") or "").strip().lower())
        if catalog_size and query_size != catalog_size:
            return f"Requested size '{query_size}' differs from catalog size '{catalog_size}'"

    return None


def build_weighted_candidates(
    settings: Settings, line_item: dict[str, Any], customer_id: str | None, top_k: int = 3,
    manufacturers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Returns the top_k weighted candidates for one line item — never a
    single collapsed answer, per the BRD's acceptance criteria. Optional
    manufacturers restrict catalog search to those brands' items before ranking
    (match-ANY across the list — e.g. a solicitation's awarded manufacturers)."""
    query_text = line_item["raw_description"].strip()
    given_code = (line_item.get("given_code") or "").strip()
    if given_code and _normalize_product_code(given_code) not in _normalize_product_code(query_text):
        query_text = f"{query_text} {given_code}".strip()
    hits = catalog_search.search_catalog(settings, query_text, manufacturers=manufacturers)

    item_codes = [h["item_code"] for h in hits]
    historical = reference.get_historical_bids_for_items(item_codes, customer_id)
    purchased = reference.get_purchase_history_for_items(item_codes, customer_id)
    catalog_rows = reference.get_item_catalog_rows(item_codes)

    exact_code_matches = set()
    for hit in hits:
        code = hit["item_code"]
        catalog_row = {**hit, **(catalog_rows.get(code) or {})}
        catalog_row.setdefault("item_code", code)
        if _is_exact_code_match(given_code, catalog_row):
            exact_code_matches.add(code)
    unique_exact_code = next(iter(exact_code_matches)) if len(exact_code_matches) == 1 else None

    scored = []
    for hit in hits:
        code = hit["item_code"]
        catalog_row = {**hit, **(catalog_rows.get(code) or {})}
        catalog_row.setdefault("item_code", code)
        retrieval_score = float(hit.get("_retrieval_score", hit.get("_score")) or 0.0)
        # Legacy unit fixtures expose only `_score`; production hybrid hits
        # always expose `_retrieval_score`, so their RRF score can never leak
        # into the semantic-confidence guardrail.
        semantic_raw = hit.get("_semantic_score")
        if "_semantic_score" not in hit and "_retrieval_score" not in hit:
            semantic_raw = hit.get("_score")
        semantic_score = float(semantic_raw) if semantic_raw is not None else None

        soft_reason = _soft_compatibility_reason(line_item, catalog_row)
        hard_reason = _hard_compatibility_reason(line_item, catalog_row)
        adjusted_retrieval = retrieval_score * (0.7 if soft_reason else 1.0)

        history_bits = []
        purchase_frac = 0.0
        if code in purchased:
            purchase_frac = 0.6 * settings.max_history_boost_fraction
            recent = purchased[code][0]
            history_bits.append(
                f"this customer last bought it {recent['last_purchase_date']} at ${recent['last_price_paid']:.2f}"
            )
        bid_frac = 0.0
        if code in historical:
            wins = sum(1 for b in historical[code] if b["outcome"] == "won")
            total = len(historical[code])
            bid_frac = (0.4 * settings.max_history_boost_fraction) * (min(total, 3) / 3)
            history_bits.append(f"bid on this item {total}x before, won {wins}/{total}")
        # Bounded to a small fraction of the candidate's own retrieval strength —
        # history can only ever act as a tie-breaker between close candidates,
        # never flip a large, genuine semantic gap (unlike the old additive
        # +0.15/+0.10 formula, which could).
        history_boost_fraction = min(purchase_frac + bid_frac, settings.max_history_boost_fraction)

        final_score = round(min(adjusted_retrieval * (1 + history_boost_fraction), 1.0), 3)
        scored.append({
            "item_code": code,
            "description_long": hit["description_long"],
            "manufacturer_name": hit.get("manufacturer_name"),
            "category": hit.get("category"),
            "list_price": hit.get("list_price"),
            "score": final_score,
            "retrieval_score": round(retrieval_score, 3),
            "semantic_score": round(semantic_score, 3) if semantic_score is not None else None,
            "source": "purchase_history" if code in purchased else "catalog",
            "history_snippet": "; ".join(history_bits),
            "compatible": hard_reason is None,
            "review_flag": hard_reason or soft_reason,
            "exact_code_match": code == unique_exact_code,
        })

    # A unique exact product-code match is authoritative for ranking, but still
    # must pass every compatibility guard before it can be auto-selected.
    scored.sort(
        key=lambda c: (c["exact_code_match"], c["compatible"], c["score"]),
        reverse=True,
    )
    top = scored[:top_k]
    for candidate in top:
        candidate["rationale"] = _rationale_for_candidate(line_item, candidate)

    # Gate confidence on the *unboosted* semantic score — purchase/bid history
    # can rank and price a plausible match, but must never single-handedly
    # turn a weak semantic match into a "confident" one. A description too
    # generic to carry any real signal (e.g. "table") is forced down this same
    # path regardless of what catalog search returned for it.
    low_specificity = _is_low_specificity(line_item["raw_description"])
    top_semantic = (top[0].get("semantic_score") or 0.0) if top else 0.0
    top_is_exact = bool(top and top[0].get("exact_code_match"))
    if not top or low_specificity or (not top_is_exact and top_semantic < settings.match_confidence_threshold):
        fallback = _general_knowledge_fallback(settings, line_item)
        if fallback:
            if low_specificity:
                top = [fallback]
            elif len(top) < top_k:
                top.append(fallback)

    # Guardrail annotation: mark whether each candidate is safe to AUTO-select
    # (the match endpoint / bulk-accept honor this; a reviewer can always pick
    # manually regardless). Threshold is the effective match-sensitivity mode,
    # applied to the UNBOOSTED semantic score.
    threshold = get_match_threshold()
    for candidate in top:
        eligible, reason = _auto_select_eligibility(candidate, low_specificity, threshold)
        candidate["auto_select_eligible"] = eligible
        candidate["guard_reason"] = reason
    return top


def _auto_select_eligibility(
    candidate: dict[str, Any], low_specificity: bool, threshold: float,
) -> tuple[bool, str | None]:
    """Decide whether a candidate may be auto-selected, with a reason code when
    not. A candidate is eligible only when ALL hold: it's a real catalog /
    purchase-history hit (never a general-knowledge fallback), the line isn't
    low-specificity, and it's hard-compatible with no soft/UOM warning. A
    unique exact product-code match is then eligible directly; all other hits
    require an available unboosted semantic score at or above the threshold.
    Reasons, most-severe first: not_catalog_source, low_specificity,
    hard_incompatibility, uom_mismatch, confidence_unavailable,
    below_confidence_threshold."""
    if candidate.get("source") not in ("catalog", "purchase_history"):
        return False, "not_catalog_source"
    if low_specificity:
        return False, "low_specificity"
    if not candidate.get("compatible", True):
        return False, "hard_incompatibility"
    if candidate.get("review_flag"):  # a soft (UOM/size/gauge) warning survived
        return False, "uom_mismatch"
    if candidate.get("exact_code_match"):
        return True, None
    if candidate.get("semantic_score") is None:
        return False, "confidence_unavailable"
    if float(candidate["semantic_score"]) < threshold:
        return False, "below_confidence_threshold"
    return True, None


def _rationale_for_candidate(line_item: dict[str, Any], candidate: dict[str, Any]) -> str:
    """A short, single-line confidence explanation. Leads with the SEMANTIC match
    (pure-ANN cosine similarity — the calibrated "how close" number the guard gates
    on), not the hybrid RRF rank score, which saturates near 100% for the top hit
    regardless of true similarity. Purchase/bid history facts are shown separately
    by the UI (candidate["history_snippet"]) — deliberately not repeated here."""
    retrieval_score = float(candidate.get("retrieval_score", candidate["score"]) or 0.0)
    semantic = candidate.get("semantic_score")
    if candidate.get("exact_code_match"):
        head = "Exact product-code match"
        if semantic is not None:
            return f"{head} · semantic match {float(semantic):.0%}."
        return f"{head} · hybrid rank relevance {retrieval_score:.0%}."
    # Semantic unavailable (ANN confidence pass failed) — fall back to a rank-only
    # phrasing, explicitly labeled so the number isn't mistaken for match quality.
    if semantic is None:
        return f"Hybrid rank relevance {retrieval_score:.0%} (semantic score unavailable)."
    return f"Semantic match {float(semantic):.0%} · hybrid rank relevance {retrieval_score:.0%}."


def _general_knowledge_fallback(settings: Settings, line_item: dict[str, Any]) -> dict[str, Any] | None:
    """Low internal confidence -> a minimal placeholder candidate signalling
    "no confident catalog match". Kept deliberately terse (no verbose
    model-generated "most likely…" sentence): the reviewer just needs to know
    the catalog didn't resolve it, then either search manually or pick the
    always-available "No catalog match" option. `settings` is unused now but
    retained for signature stability with the caller."""
    return {
        "item_code": "",
        "description_long": "No confident catalog match",
        "manufacturer_name": None,
        "category": None,
        "list_price": None,
        "score": 0.0,
        "retrieval_score": None,
        "semantic_score": None,
        "source": "general_knowledge",
        "history_snippet": "",
        "rationale": "No catalog match found — search manually or mark as no catalog match.",
    }


# --------------------------------------------------------------------------- #
# Step 3: "apply appropriate pricing" — historical price first, purchase
# history second, list-price margin rule last. (Vistex integration is a
# future phase per the BRD; this is the seam where it would plug in.)
# --------------------------------------------------------------------------- #


def propose_price(item_code: str, customer_id: str | None) -> dict[str, Any]:
    if not item_code:
        return {"proposed_price": None, "pricing_basis": "no catalog match — manual pricing required"}

    purchased = reference.get_purchase_history_for_items([item_code], customer_id)
    if item_code in purchased:
        recent = purchased[item_code][0]
        return {
            "proposed_price": recent["last_price_paid"],
            "pricing_basis": f"last price paid by this customer ({recent['last_purchase_date']})",
        }

    historical = reference.get_historical_bids_for_items([item_code], customer_id=None)
    won_bids = [b for b in historical.get(item_code, []) if b["outcome"] == "won"]
    if won_bids:
        avg_price = round(sum(b["submitted_price"] for b in won_bids) / len(won_bids), 2)
        return {
            "proposed_price": avg_price,
            "pricing_basis": f"average of {len(won_bids)} historically won bid(s) for this item",
        }

    catalog_row = reference.get_item_catalog_rows([item_code]).get(item_code)
    if catalog_row:
        margin_price = round(float(catalog_row["list_price"]) * 0.85, 2)
        return {"proposed_price": margin_price, "pricing_basis": "list price less standard margin rule (no history)"}

    return {"proposed_price": None, "pricing_basis": "no pricing evidence found — manual pricing required"}


# --------------------------------------------------------------------------- #
# Step 4: "extract legal, pricing, compliance, insurance and business
# requirements" + "AI Risk & Requirement Analysis" + route to the owning team.
# A second extraction pass over the SAME parsed document text pulls out
# non-product clauses/terms/certifications; each is then classified against the
# editable responsibility matrix.
# --------------------------------------------------------------------------- #


# Direct FMAPI recovery schema.
# Extraction only pulls the clause + a short label; routing to a matrix term is a
# separate ai_classify pass (classify_requirements), so no `category` here.
_REQUIREMENTS_FMAPI_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "requirements",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"requirements": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "term_label": {"type": "string"},
                    "raw_text": {"type": "string"},
                },
                "required": ["term_label", "raw_text"],
                "additionalProperties": False,
            }}},
            "required": ["requirements"],
            "additionalProperties": False,
        },
    },
}

# ai_extract v2.1 schema: a top-level "requirements" array. Field descriptions
# steer the model; the matrix glossary of provisions to look for is passed
# separately via the `instructions` option (see _requirements_extract_instructions).
_REQUIREMENTS_EXTRACT_SCHEMA = json.dumps({
    "requirements": {"type": "array", "items": {"type": "object", "properties": {
        "term_label": {
            "type": "string",
            "description": "A short name for the provision (e.g. 'Indemnification', 'Payment Terms').",
        },
        "raw_text": {
            "type": "string",
            "description": "The clause text as written — quoted or closely paraphrased, not summarized.",
        },
    }}}
})

_REQUIREMENTS_PROMPT = (
    "You are reviewing a bid/RFP/solicitation for a medical and dental distributor. "
    "IGNORE the product line items (gloves, masks, syringes, etc.) — those are handled separately. "
    "Extract every distinct NON-product requirement, clause, term, condition, or certification the "
    "vendor would have to review or attest to. These include legal terms (indemnification, IP "
    "infringement, power of attorney, debarment, litigation disclosure, anti-trust/non-collusion, "
    "Stark law / anti-kickback), commercial/pricing terms (payment terms, firm pricing, most favored "
    "nation / best price, delivery/FOB terms, rebates, administrative/marketing/transaction fees, "
    "piggyback/cooperative purchasing), compliance and HR items (E-Verify, affirmative action, "
    "criminal background, political contributions, anti-lobbying), insurance/coverage requirements, "
    "and tax provisions. Return a JSON array; for each item include: term_label (a short name for the "
    "provision) and raw_text (the clause text as written, quoted or closely paraphrased). "
    "Return ONLY the JSON array, no commentary.\n\n"
    "DOCUMENT:\n{document_text}"
)

# Core steering for the requirements ai_extract `instructions` option — the same
# "ignore product items, pull non-product clauses" guidance the FMAPI prompt
# carries, minus the JSON-array formatting rules (ai_extract's schema handles shape).
# Kept in sync with _REQUIREMENTS_PROMPT: both now enumerate the same provision
# families so the primary (ai_extract) and recovery (FMAPI) paths have matched
# recall. The enumeration is illustrative, not a whitelist — the model must still
# extract anything clause-like that isn't listed.
_REQUIREMENTS_EXTRACT_STEER = (
    "This is a bid/RFP/solicitation for a medical and dental distributor. "
    "IGNORE the product line items (gloves, masks, syringes, etc.) — those are handled separately. "
    "Extract every distinct NON-product requirement, clause, term, condition, or certification the "
    "vendor would have to review or attest to. These include: legal terms (indemnification, IP "
    "infringement, power of attorney, debarment, litigation disclosure, anti-trust/non-collusion, "
    "Stark law / anti-kickback); commercial and pricing terms (payment terms, firm pricing, most "
    "favored nation / best price, delivery/FOB terms, rebates, administrative/marketing/transaction "
    "fees, piggyback/cooperative purchasing); compliance and HR items (E-Verify, affirmative action, "
    "criminal background, political contributions, anti-lobbying); insurance/coverage requirements; "
    "and tax provisions. This list is illustrative, not exhaustive — extract any other clause-like "
    "provision you find, even if it is not named above. Emit one entry per distinct provision; do not "
    "merge unrelated clauses or split a single clause into duplicates. term_label is a short name for "
    "the provision (e.g. 'Indemnification', 'Payment Terms'); raw_text is the clause text as written "
    "(quoted or closely paraphrased, not summarized)."
)


def _requirements_extract_instructions() -> str:
    """Build the ai_extract `instructions` string, grounding extraction in the
    SAME editable matrix taxonomy that classification uses. Reads the MERGED
    matrix payload (seeded + overrides) exactly like _build_classify_labels(), so
    custom terms / edited descriptions flow into extraction too. The glossary is
    framed as guidance ("common provisions to look for", non-exhaustive) — it
    boosts recall/consistency WITHOUT constraining term_label to these exact
    strings (canonicalization stays in the separate ai_classify pass)."""
    try:
        payload = reference.matrix_payload()
        lines = []
        for term in payload["terms"]:
            label = term["term_label"]
            desc = (term.get("description") or "").strip() or label
            lines.append(f"- {label}: {desc}")
        glossary = "\n".join(lines)
    except Exception:
        # Never let a matrix read failure sink extraction — fall back to the
        # core steering alone (still far better than today's no-instructions call).
        logger.exception("Could not build matrix glossary for requirements extraction instructions.")
        return _REQUIREMENTS_EXTRACT_STEER
    return (
        f"{_REQUIREMENTS_EXTRACT_STEER}\n\n"
        "Common provisions to look for include (non-exhaustive — extract anything clause-like even if "
        "it isn't listed here):\n"
        f"{glossary}"
    )


def extract_requirements(settings: Settings, parsed: dict[str, Any] | str) -> list[dict[str, Any]]:
    """Pull the NON-product clauses out of a solicitation — legal terms,
    pricing/commercial conditions, compliance certifications, insurance
    requirements, HR attestations. Counterpart to extract_line_items(); both run
    over the same parsed document.

    Primary path is ai_extract; it recovers through direct FMAPI ONLY on a
    hard failure (exception / error_message / invalid shape) — an empty result is
    NOT a trigger, because a bid can legitimately have zero requirements (unlike
    line items). Requirements are additive: on total failure this returns []
    rather than blocking the product flow. Each row carries its extraction_method
    and best-effort source_page."""
    parsed = _as_parsed(parsed)
    text = parsed.get("text") or ""
    spans = parsed.get("page_spans") or []
    if not text.strip():
        return []

    items: list[dict[str, Any]] = []
    method = "ai_extract"
    if settings.use_ai_extract:
        items, hard_fail = _requirements_ai_extract(settings, text)
    else:
        items, hard_fail = [], True  # flag off -> go straight to FMAPI
    if hard_fail:
        items = _requirements_fmapi(settings, text)
        method = "fmapi"

    normalized = []
    seen: set[str] = set()
    for item in items or []:
        # ai_extract may wrap each field in a {value,...} object; _scalar_str
        # unwraps it. FMAPI rows are already flat and pass through.
        raw_text = _scalar_str(item.get("raw_text"))
        term_label = _scalar_str(item.get("term_label"))
        if not raw_text and not term_label:
            continue
        # The model occasionally emits the same clause twice; dedupe on the
        # normalized clause text (lowercased, whitespace-collapsed) so a doubled
        # clause becomes a single row. First occurrence wins.
        dedup_key = " ".join((raw_text or term_label).lower().split())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        normalized.append({
            "requirement_id": f"req-{uuid.uuid4().hex[:8]}",
            "term_label": term_label or "Requirement",
            "raw_text": raw_text or term_label,
            "source_page": _match_page(raw_text or term_label, spans),
            "extraction_method": method,
        })
    return normalized


def _requirements_ai_extract(settings: Settings, document_text: str) -> tuple[list[dict[str, Any]], bool]:
    """ai_extract primary path for requirements. Returns (items, hard_fail).
    hard_fail=True (exception / error_message / non-dict response) triggers the
    FMAPI recovery; an empty-but-well-formed result is (,False) — no recovery,
    since zero requirements is legitimate.

    NOTE: ai_extract exposes no sampling parameter, so determinism on this path
    rests on the instructions being stable run-to-run — see
    _requirements_extract_instructions(), which reads the merged matrix. If
    variance remains unacceptable, flip BIDS_USE_AI_EXTRACT off to route through
    the temperature=0 FMAPI path instead."""
    try:
        data = _call_ai_function("ai-extract", {
            "content": document_text,
            "schema": json.loads(_REQUIREMENTS_EXTRACT_SCHEMA),
            "options": {"version": "2.1", "instructions": _requirements_extract_instructions()},
        })
    except Exception:
        logger.exception("ai_extract requirement extraction failed; will recover with FMAPI.")
        return [], True
    if not isinstance(data, dict) or data.get("error_message"):
        return [], True
    response = data.get("response")
    if not isinstance(response, dict):
        return [], True
    items = response.get("requirements")
    return (items if isinstance(items, list) else []), False


def _requirements_fmapi(settings: Settings, document_text: str) -> list[dict[str, Any]]:
    """Direct Foundation Model API recovery path for requirements."""
    try:
        parsed = _fmapi_structured_output(
            settings,
            _REQUIREMENTS_PROMPT.format(document_text=document_text),
            _REQUIREMENTS_FMAPI_RESPONSE_FORMAT,
        )
    except Exception:
        logger.exception("FMAPI requirement recovery failed; returning no requirements.")
        return []
    items = parsed.get("requirements", parsed) if isinstance(parsed, dict) else parsed
    return items if isinstance(items, list) else []


# --------------------------------------------------------------------------- #
# Requirement routing: ai_classify EVERY clause into the matrix term taxonomy.
# No keyword matching. The taxonomy is the MERGED matrix (seeded + user
# overrides via reference.matrix_payload), so editing a term's description /
# teams / risk — or adding a custom term — changes how future uploads classify.
# --------------------------------------------------------------------------- #

# Escape label so ai_classify (which always returns one of the given labels) can
# say "none of these fit" instead of force-mapping an unrelated clause.
_ESCAPE_LABEL = "__none__"
_ESCAPE_DESCRIPTION = "None of the standard provisions above — unclear, unrelated, or a generic clause."
# A classified clause below this confidence is treated as unmatched (left for a
# human to route) rather than trusted.
_CLASSIFY_CONFIDENCE_THRESHOLD = 0.45
_UNMATCHED_RATIONALE = (
    "Not confidently matched to a standard provision — routed for a human to confirm the owning team."
)
# ai_classify accepts 2–500 labels; guard against an over-large custom matrix.
_MAX_CLASSIFY_LABELS = 480
_MAX_CLASSIFY_WORKERS = 8


def _build_classify_labels() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Build (labels, index) from the MERGED matrix payload. `labels` is the
    {term_label: description} map handed to ai_classify (description falls back
    to the term_label itself when empty — e.g. a custom term with no description
    — so every label has a non-empty definition), plus the escape label.
    `index` maps term_label -> the full payload term (teams/risk/rationale)."""
    payload = reference.matrix_payload()
    labels: dict[str, str] = {}
    index: dict[str, dict[str, Any]] = {}
    for term in payload["terms"]:
        label = term["term_label"]
        labels[label] = (term.get("description") or "").strip() or label
        index[label] = term
    if len(labels) > _MAX_CLASSIFY_LABELS:
        # Extremely unlikely (34 seeded + custom); keep the call valid + log it.
        dropped = len(labels) - _MAX_CLASSIFY_LABELS
        logger.warning("Matrix has %d terms; capping ai_classify labels at %d (dropping %d).",
                       len(labels), _MAX_CLASSIFY_LABELS, dropped)
        labels = dict(list(labels.items())[:_MAX_CLASSIFY_LABELS])
    labels[_ESCAPE_LABEL] = _ESCAPE_DESCRIPTION
    return labels, index


def _decode_routing(raw: Any) -> dict[str, Any]:
    """Decode one REST ai-classify response."""
    data = _loads_variant(raw)
    response = data.get("response") if isinstance(data, dict) else None
    if isinstance(response, list) and response and isinstance(response[0], dict):
        value = _scalar_str(response[0].get("value") or response[0].get("label"))
        score = response[0].get("confidence_score")
        return {"value": value, "confidence": float(score) if isinstance(score, (int, float)) else None}
    return {"value": "", "confidence": None}


def _classify_per_clause(settings: Settings, clauses: list[str], labels: dict[str, str]) -> list[dict | None]:
    """Classify clauses concurrently while preserving input order."""
    def classify_one(clause: str) -> dict | None:
        try:
            response = _call_ai_function("ai-classify", {
                "content": clause,
                "labels": labels,
                "options": {"version": "2.1", "enable_confidence_scores": True},
            })
            routing = _decode_routing(response)
            return routing if routing.get("value") else None
        except Exception:
            logger.exception("Per-clause ai_classify failed; leaving this clause unmatched.")
            return None

    workers = min(_MAX_CLASSIFY_WORKERS, len(clauses))
    if workers <= 1:
        return [classify_one(clause) for clause in clauses]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ai-classify") as pool:
        return list(pool.map(classify_one, clauses))


def _apply_routing(routing: dict | None, index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Turn one decoded routing into requirement routing fields. A confident,
    in-taxonomy match sets matched_term (so the Material banner keeps firing) and
    inherits the term's teams/risk/rationale. The escape label, an unknown label,
    or a below-threshold score -> unmatched (source='ai_suggested', no team)."""
    unmatched = {
        "term_label": None,
        "owning_teams": [],
        # No term matched -> no basis to assert a risk. Empty = "not assessed"
        # (the UI shows "—"); a reviewer sets it when they route the clause.
        "risk_level": "",
        "risk_rationale": _UNMATCHED_RATIONALE,
        "matched_term": None,
        "source": "ai_suggested",
        "confidence": (routing or {}).get("confidence"),
    }
    if not routing:
        return unmatched
    value, conf = routing.get("value"), routing.get("confidence")
    if value == _ESCAPE_LABEL or value not in index:
        return unmatched
    if conf is not None and conf < _CLASSIFY_CONFIDENCE_THRESHOLD:
        return unmatched
    term = index[value]
    return {
        "term_label": value,
        "owning_teams": list(term.get("owning_teams") or []),
        "risk_level": term.get("default_risk", "medium"),
        "risk_rationale": term.get("risk_rationale", ""),
        "matched_term": value,  # canonical term -> keeps compute_review_verdict firing
        "source": "ai_classified",
        "confidence": conf,
    }


def classify_requirements(settings: Settings, requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify every extracted requirement into the matrix taxonomy through
    concurrent REST ai-classify calls. Reads the MERGED matrix payload, so
    matrix edits drive classification. Returns a routing dict per requirement,
    aligned to the input order. Individual call failures remain unmatched."""
    if not requirements:
        return []
    labels, index = _build_classify_labels()
    clauses = [(r.get("raw_text") or r.get("term_label") or "") for r in requirements]
    routings = _classify_per_clause(settings, clauses, labels)
    return [_apply_routing(routings[i], index) for i in range(len(requirements))]


def extract_and_classify_requirements(settings: Settings, parsed: dict[str, Any] | str) -> list[dict[str, Any]]:
    """Extract the non-product clauses, then ai_classify each into a matrix term
    — the full requirements pass, ready to persist. A confident match adopts the
    canonical term_label + its teams/risk/rationale; an unmatched clause keeps the
    model's label with no team for a reviewer to route. Extraction provenance
    (source_page / extraction_method) is preserved. Returns [] on total failure
    so it never breaks the product upload path."""
    requirements = extract_requirements(settings, parsed)
    if not requirements:
        return []
    routings = classify_requirements(settings, requirements)
    classified = []
    for req, routing in zip(requirements, routings):
        matched = routing.get("matched_term") is not None
        classified.append({
            "requirement_id": req["requirement_id"],
            # Canonical term when classified; keep the model's label when unmatched.
            "term_label": routing["term_label"] if matched else req["term_label"],
            "raw_text": req["raw_text"],
            "owning_teams": routing["owning_teams"],
            "risk_level": routing["risk_level"],
            "risk_rationale": routing["risk_rationale"],
            "matched_term": routing["matched_term"],
            "source": routing["source"],
            # Provenance threaded through from extraction.
            "source_page": req.get("source_page"),
            "extraction_method": req.get("extraction_method", "ai_extract"),
            "confidence": routing.get("confidence"),
        })
    return classified


# Fixed doc-type labels for the optional classify_document() step below.
_DOC_TYPE_LABELS = {
    "solicitation": "An RFP/RFQ/bid/tender inviting a vendor to quote or propose.",
    "product_list": "A price list, line-item schedule, or product catalog.",
    "contract": "A contract, agreement, terms & conditions, or addendum.",
    "other": "Anything else — a cover letter, form, or unrelated document.",
}


def classify_document(settings: Settings, parsed: dict[str, Any] | str) -> dict[str, Any]:
    """OPTIONAL / DEFERRED — advisory document-type classification via ai_classify.

    Returns {"doc_type": str|None, "doc_type_confidence": float|None}. NOT wired
    into the upload critical path: a flaky/wrong classify must never gate a
    document's rows (see the spec's "fallback is recovery, not a parallel primary"
    and the "no autonomous document routing" non-goal). When adopted, call this
    once per file in _process_upload and write the result onto that file's entry
    in the `documents` JSONB manifest (no migration needed) to drive the UI's
    per-document type/confidence surface."""
    parsed = _as_parsed(parsed)
    text = (parsed.get("text") or "").strip()
    if not text or not settings.use_ai_extract:
        return {"doc_type": None, "doc_type_confidence": None}
    try:
        data = _call_ai_function("ai-classify", {
            "content": text[:20000],
            "labels": _DOC_TYPE_LABELS,
            "options": {"version": "2.1", "enable_confidence_scores": True},
        })
    except Exception:
        logger.exception("ai_classify document-type call failed (advisory; ignored).")
        return {"doc_type": None, "doc_type_confidence": None}
    routing = _decode_routing(data)
    return {
        "doc_type": routing.get("value") or None,
        "doc_type_confidence": routing.get("confidence"),
    }
