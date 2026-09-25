"""Generates the two outputs the BRD asks for explicitly: a proposal PDF and
a customer submission Excel file — the last arrow in the Future State MVP
flow ("Human in the loop review... submit")."""

from __future__ import annotations

from io import BytesIO
from typing import Any


def _matched_candidate(line: dict[str, Any]) -> dict[str, Any] | None:
    """The candidate a line was matched to and priced against, looked up from the
    line's candidate list by whichever item_code ended up selected."""
    selected = line.get("selected_item_code")
    return next(
        (c for c in (line.get("candidates") or []) if c.get("item_code") == selected),
        None,
    )


def _matched_product_fields(line: dict[str, Any]) -> tuple[str, str]:
    """The catalog product a line was matched to, split into
    (manufacturer, web_description) — as opposed to raw_description, which is just
    the customer's own wording from the solicitation. The proposal Excel keeps
    these in two separate columns."""
    candidate = _matched_candidate(line)
    if not candidate:
        return "", "—"
    return candidate.get("manufacturer_name") or "", candidate.get("description_long") or "—"


def _matched_product_description(line: dict[str, Any]) -> str:
    """Manufacturer + description folded into one cell (used by the proposal PDF,
    which keeps a single 'Product' column)."""
    manufacturer, description = _matched_product_fields(line)
    return f"{manufacturer} — {description}" if manufacturer else description


def render_proposal_pdf(bid: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    # Plain strings in a Platypus Table never wrap — a cell wider than its column
    # just overflows into the next one instead of dropping to a second line (this
    # is what made a long description visibly collide with the qty/UOM columns).
    # Every long-text cell below is wrapped in a Paragraph using this style so
    # ReportLab actually wraps it within its column instead of overflowing.
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=7.5, leading=9)

    story = [
        Paragraph("Bid Proposal", styles["Title"]),
        Paragraph(f"Customer: {bid['customer_name']}", styles["Heading2"]),
        Paragraph(f"Solicitation Reference: {bid.get('solicitation_ref') or bid['bid_id']}", styles["Normal"]),
        Spacer(1, 0.25 * inch),
    ]
    table_data = [["Line", "Item", "Product", "Qty", "UOM", "Price", "Requested product"]]
    total = 0.0
    for line in bid["line_items"]:
        # A no-match line still appears on the proposal (the customer's requested
        # product stays visible), but with BLANK Item / Product / Price cells —
        # never silently omitted, never priced.
        if line.get("resolution") == "no_match":
            table_data.append([
                str(line["line_number"]),
                "",
                Paragraph("", cell_style),
                str(line.get("qty") or 1),
                line.get("uom") or "",
                "",
                Paragraph(line["raw_description"], cell_style),
            ])
            continue
        price = line.get("proposed_price") or 0.0
        total += price * (line.get("qty") or 1)
        table_data.append([
            str(line["line_number"]),
            line.get("selected_item_code") or "—",
            Paragraph(_matched_product_description(line), cell_style),
            str(line.get("qty") or 1),
            line.get("uom") or "",
            f"${price:,.2f}" if line.get("proposed_price") is not None else "TBD",
            Paragraph(line["raw_description"], cell_style),
        ])
    # Usable width on a letter page with SimpleDocTemplate's default 1in left/right
    # margins is 6.5in; these sum to 6.0in, leaving headroom instead of the old
    # layout's 6.6in (already wider than its own frame before any text overflow).
    col_widths = [0.35 * inch, 0.65 * inch, 2.0 * inch, 0.35 * inch, 0.4 * inch, 0.65 * inch, 1.6 * inch]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14191f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f4")]),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(f"<b>Estimated Total: ${total:,.2f}</b>", styles["Normal"]))
    doc.build(story)
    return buffer.getvalue()


def render_customer_submission_excel(bid: dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Bid Submission"

    # Column names for the customer submission file.
    # (Sort / Customer Description / Item # / Catalog Description / Manufacturer /
    # UOM / Qty / Bid Price / Extended Bid Price / Comments), restricted to the
    # fields we actually extract — no empty placeholder columns for attributes we
    # don't have (Size, Strength, Case Size, Vendor Part, Customer UOM/Factor).
    headers = [
        "Sort", "Customer Description", "Item #", "Catalog Description",
        "Manufacturer Description", "UOM", "Customer Quantity",
        "Bid Price", "Extended Bid Price", "Comments",
    ]
    # 1-based column indices for the cells we write per row / in the total row.
    COL_EXTENDED = headers.index("Extended Bid Price") + 1  # 9
    COL_BID_PRICE = headers.index("Bid Price") + 1  # 8

    # Header block: customer, solicitation ref, date, and the headline Total Bid
    # Price — placed in the last two columns of the header rows, top-right.
    sheet["A1"] = bid["customer_name"]
    sheet["A1"].font = Font(bold=True, size=14)
    sheet["A2"] = f"Solicitation Reference: {bid.get('solicitation_ref') or bid['bid_id']}"
    date_value = bid.get("due_date") or (bid.get("created_at") or "")[:10]
    sheet["A3"] = f"Date: {date_value}"

    total = sum(
        (line.get("proposed_price") or 0.0) * (line.get("qty") or 1)
        for line in bid["line_items"]
        if line.get("resolution") != "no_match" and line.get("proposed_price") is not None
    )
    total_label = sheet.cell(row=1, column=COL_BID_PRICE, value="Total Bid Price:")
    total_label.font = Font(bold=True)
    total_label.alignment = Alignment(horizontal="right")
    total_value = sheet.cell(row=1, column=COL_EXTENDED, value=round(total, 2))
    total_value.font = Font(bold=True)
    total_value.number_format = "$#,##0.00"

    header_row = 5
    for col, header in enumerate(headers, start=1):
        cell = sheet.cell(row=header_row, column=col, value=header)
        cell.font = Font(bold=True)

    wrap = Alignment(wrap_text=True, vertical="top")
    row = header_row
    for line in bid["line_items"]:
        row += 1
        qty = line.get("qty") or 1
        # No-match line: Sort + Customer Description present, but Item # / Catalog
        # Description / Manufacturer / prices blank, with a "No catalog match" note
        # — so the customer sees every line they asked for, unpriced.
        if line.get("resolution") == "no_match":
            sheet.cell(row=row, column=1, value=line["line_number"])
            sheet.cell(row=row, column=2, value=line["raw_description"]).alignment = wrap
            sheet.cell(row=row, column=6, value=line.get("uom") or "")
            sheet.cell(row=row, column=7, value=qty)
            sheet.cell(row=row, column=10, value="No catalog match")
            continue
        manufacturer, web_description = _matched_product_fields(line)
        price = line.get("proposed_price")
        sheet.cell(row=row, column=1, value=line["line_number"])
        sheet.cell(row=row, column=2, value=line["raw_description"]).alignment = wrap
        sheet.cell(row=row, column=3, value=line.get("selected_item_code") or "")
        sheet.cell(row=row, column=4, value=web_description).alignment = wrap
        sheet.cell(row=row, column=5, value=manufacturer)
        sheet.cell(row=row, column=6, value=line.get("uom") or "")
        sheet.cell(row=row, column=7, value=qty)
        price_cell = sheet.cell(row=row, column=8, value=price)
        ext_cell = sheet.cell(row=row, column=9, value=round(price * qty, 2) if price is not None else None)
        price_cell.number_format = "$#,##0.00"
        ext_cell.number_format = "$#,##0.00"

    # Total row, matching the header's Total Bid Price (parity with the PDF's
    # "Estimated Total").
    total_row = row + 1
    label = sheet.cell(row=total_row, column=COL_BID_PRICE, value="Total Bid Price:")
    label.font = Font(bold=True)
    label.alignment = Alignment(horizontal="right")
    total_cell = sheet.cell(row=total_row, column=COL_EXTENDED, value=round(total, 2))
    total_cell.font = Font(bold=True)
    total_cell.number_format = "$#,##0.00"

    sheet.column_dimensions["B"].width = 40  # Customer Description
    sheet.column_dimensions["D"].width = 50  # Catalog Description
    sheet.column_dimensions["E"].width = 28  # Manufacturer Description
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
