"""Coverage tests for the sample bid documents: every sample must carry a
non-trivial Terms, Conditions & Certifications section (the raw material for
requirement extraction), that section must survive rendering + text extraction
back out of the file, and its clauses must route across multiple owning teams
via the responsibility matrix.

This guards the regression that shipped the demo: the sample docs were pure
product-line tables with no clauses, so the live "Requirements & routing" step
always showed "none detected". Rendering deps (reportlab / openpyxl / pdfminer)
are skipped if unavailable so the core logic suite still runs in a bare env.
"""

from __future__ import annotations

import pytest

from server._shared_data.responsibility_matrix import RESPONSIBILITY_MATRIX
from server._shared_data.sample_documents import SAMPLE_DOCUMENTS, render_document_bytes

# Every sample should exercise the requirements feature.
MIN_TERMS = 5


def _route(text: str):
    """Mirror of classify_requirement's matrix pass (no ai_query), returning the
    owning teams for the first matching row — used to assert per-doc team spread."""
    haystack = text.lower()
    for term in RESPONSIBILITY_MATRIX:
        if any(keyword in haystack for keyword in term.keywords):
            return term.owning_teams
    return None


@pytest.mark.parametrize("doc", SAMPLE_DOCUMENTS, ids=[d.file_name for d in SAMPLE_DOCUMENTS])
def test_every_sample_has_a_substantive_terms_section(doc):
    assert len(doc.terms) >= MIN_TERMS, f"{doc.file_name} has too few terms ({len(doc.terms)})"


@pytest.mark.parametrize("doc", SAMPLE_DOCUMENTS, ids=[d.file_name for d in SAMPLE_DOCUMENTS])
def test_sample_terms_route_across_multiple_teams(doc):
    teams: set[str] = set()
    for term in doc.terms:
        routed = _route(term)
        if routed:
            teams.update(routed)
    # A realistic solicitation touches more than one internal team; this also
    # catches a doc whose clauses somehow all fail to match the matrix.
    assert len(teams) >= 2, f"{doc.file_name} routes to too few teams: {sorted(teams)}"


def test_pdf_terms_survive_render_and_extraction():
    """Render a PDF sample and pull text back out — the clause section must be
    present in the actual bytes the app will parse, not just in the dataclass."""
    pytest.importorskip("reportlab")
    extract_text = pytest.importorskip("pdfminer.high_level").extract_text
    from io import BytesIO

    pdf_doc = next(d for d in SAMPLE_DOCUMENTS if d.file_format == "pdf" and d.terms)
    content = render_document_bytes(pdf_doc)
    text = extract_text(BytesIO(content))

    assert "Terms, Conditions & Certifications" in text
    # At least a couple of the clause bodies made it into the rendered text.
    hits = sum(1 for term in pdf_doc.terms if term.split(":")[0][:20] in text)
    assert hits >= 2, f"Expected clause headings in extracted PDF text, found {hits}"


def test_excel_and_docx_samples_render_without_error():
    """The non-PDF samples (xlsx, docx) also carry terms now; make sure they
    render end to end so re-seeding won't fail on them."""
    for fmt in ("xlsx", "docx"):
        pytest.importorskip("openpyxl" if fmt == "xlsx" else "docx")
        doc = next((d for d in SAMPLE_DOCUMENTS if d.file_format == fmt and d.terms), None)
        if doc is None:
            continue
        content = render_document_bytes(doc)
        assert content and len(content) > 500
