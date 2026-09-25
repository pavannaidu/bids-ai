"""Synthetic incoming bid solicitations — the documents a presenter uploads
live during the demo. Line-item text is deliberately written the way a real
requester would phrase it (abbreviated, reordered, inconsistent casing) — not
a verbatim copy of any item_catalog description — so matching has to do real
semantic work. ~95% of lines carry no manufacturer/competitor code at all,
mirroring the BRD's stated pain point; a couple of lines include one, to show
that fast path too.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from .demo_data import BASE_PRODUCTS, _abbreviate


@dataclass
class SampleBidLine:
    raw_text: str
    qty: int
    uom: str
    given_code: str | None = None


@dataclass
class SampleBidDocument:
    file_name: str
    file_format: str  # "pdf" | "xlsx" | "docx"
    title: str
    customer_name: str
    customer_id: str
    solicitation_ref: str
    due_in_days: int
    lines: list[SampleBidLine] = field(default_factory=list)
    # Non-product clauses/terms/certifications the solicitation attaches beyond
    # the product line items — the raw material for the app's requirement
    # extraction + team-routing step (BRD "extract legal, pricing, compliance,
    # insurance and business requirements"). Rendered as a "Terms, Conditions &
    # Certifications" section after the line-item table.
    terms: list[str] = field(default_factory=list)


# A realistic, varied library of BRD Glossary provisions, phrased the way a
# government contracting office would write them into a solicitation's terms
# section. Each government sample draws a random (fixed-seed) subset of these,
# so the documents are meaningfully complex and exercise routing across all
# eight teams — legal, business/pricing, HR, compliance, risk management, tax,
# corporate affairs. Not every sample carries all of them.
_COMMON_GOV_TERMS: list[str] = [
    # --- Corporate Legal ---
    "Indemnification: The Contractor shall indemnify, defend, and hold harmless the Agency and its "
    "officers, agents, and employees from any and all claims, damages, losses, and liabilities, "
    "including reasonable attorneys' fees, arising out of or resulting from performance of this contract.",
    "Intellectual Property Infringement: The Contractor warrants that the goods furnished do not infringe "
    "any patent, copyright, or trademark, and shall defend and indemnify the Government against any claim "
    "of infringement arising from their use.",
    "Debarment and Suspension: The Contractor certifies that neither it nor any of its principals are "
    "presently debarred, suspended, proposed for debarment, or declared ineligible for the award of "
    "contracts by any federal agency.",
    "Litigation Disclosure: The Contractor shall disclose any pending or threatened litigation, "
    "administrative proceeding, or investigation that could materially affect its ability to perform.",
    "Non-Collusion / Anti-Trust: The Contractor certifies that its bid was arrived at independently and "
    "without collusion, and that it has not violated any federal or state anti-trust laws.",
    "Stark Law / Anti-Kickback Compliance: The Contractor warrants that no arrangement under this contract "
    "violates the federal physician self-referral (Stark) law or the Anti-Kickback Statute.",
    "Power of Attorney: Where required, the Contractor shall furnish a duly executed power of attorney "
    "evidencing the authority of the individual signing on its behalf.",
    "Anti-Lobbying Certification: Pursuant to 31 U.S.C. 1352, the Contractor certifies that no federally "
    "appropriated funds have been paid or will be paid to influence any federal officer in connection "
    "with the award of this contract.",
    # --- Business / pricing ---
    "Payment Terms: Net 30 days from receipt of a proper invoice. Any prompt-payment discount offered "
    "shall be clearly stated in the response.",
    "Firm Pricing: All unit prices shall remain firm and fixed for the twelve (12) month base period of "
    "the contract and shall not be subject to escalation.",
    "Delivery Terms: All deliveries shall be F.O.B. Destination, freight prepaid and included in the unit "
    "price, to the receiving location(s) designated on each order.",
    "Most Favored Customer: The Contractor warrants that the prices offered herein are no less favorable "
    "than those extended to any other customer purchasing like quantities under similar conditions.",
    "Price Reduction: If the Contractor reduces its prices to any comparable customer during the contract "
    "term, the same reduction shall be extended to the Agency retroactively to the effective date.",
    "Piggyback / Cooperative Purchasing: Other public entities may purchase from any resulting contract "
    "under the same terms and pricing (cooperative / intergovernmental purchasing clause).",
    "Warranty of Products: The Contractor warrants that all products furnished are new, of merchantable "
    "quality, and free from defects in material and workmanship for the manufacturer's warranty period.",
    "Administrative Fee: The Contractor agrees to remit a quarterly administrative fee equal to one "
    "percent (1%) of net sales under any resulting contract.",
    "Authorized Distributor Letter: The Contractor shall provide a letter from the manufacturer certifying "
    "that it is an authorized distributor of the products offered.",
    # --- HR ---
    "E-Verify: The Contractor certifies that it participates in the federal E-Verify program to confirm "
    "the employment eligibility of all persons employed under this contract.",
    "Affirmative Action / EEO: The Contractor shall comply with all applicable Equal Employment "
    "Opportunity and affirmative action requirements, including the maintenance of a written affirmative "
    "action plan where required.",
    # --- Compliance ---
    "Royalty Fees: Any royalty or licensing fee embedded in the offered pricing shall be separately "
    "disclosed and is subject to compliance review.",
    "Marketing Fees: Any marketing, promotional, or advertising allowance associated with this contract "
    "shall be disclosed and shall comply with applicable fair-market-value requirements.",
    # --- Corporate Affairs ---
    "Political Contributions: The Contractor shall disclose all reportable political contributions in "
    "accordance with applicable state 'pay-to-play' disclosure requirements.",
    # --- Risk Management ---
    "Insurance Requirements: The Contractor shall maintain Commercial General Liability coverage of not "
    "less than $1,000,000 per occurrence, Workers' Compensation insurance as required by law, and furnish "
    "a Certificate of Insurance naming the Government as additional insured prior to award.",
    # --- Tax ---
    "Tax Exemption: The Agency is exempt from federal excise and state sales tax; the Contractor shall not "
    "include such taxes in its pricing and shall accept the Agency's tax-exemption certificate.",
]


SAMPLE_DOCUMENTS: list[SampleBidDocument] = [
    SampleBidDocument(
        file_name="VA-2027-0114_PPE_Wound_Care.pdf",
        file_format="pdf",
        title="PPE & Wound Care Supplies Solicitation",
        customer_name="VA Medical Center - Region 4",
        customer_id="CUST-1001",
        solicitation_ref="VA-2027-0114",
        due_in_days=12,
        lines=[
            SampleBidLine("Nitrile exam gloves, powder free, size medium, box of 100ct", 200, "BX"),
            SampleBidLine("Surgical face masks ASTM level 3 w/ ear loops", 150, "BX"),
            SampleBidLine("N-95 particulate respirators, foldable, regular size", 40, "BX"),
            SampleBidLine("Sharps disposal containers, 8 gallon, locking lid", 60, "EA"),
            SampleBidLine("Self-adherent cohesive wrap bandage, 4 inch", 30, "BX"),
            SampleBidLine("Woven gauze sponges 4x4, non-sterile", 80, "BX"),
            SampleBidLine("Paper surgical tape, 1 inch, hypoallergenic", 50, "BX"),
            SampleBidLine("Disp isolation gowns, fluid resistant, XL", 45, "CS"),
            SampleBidLine("Non-skid shoe covers, regular", 60, "CS"),
            SampleBidLine("IV catheters 20 gauge, winged", 100, "BX"),
            SampleBidLine("IV admin sets w/ needle-free connector", 40, "CS"),
            SampleBidLine("Exam table paper roll, 21 inch, white, smooth", 20, "CS"),
            SampleBidLine("Disposable vaginal specula, medium", 25, "BX"),
            SampleBidLine("Surface disinfectant wipes, germicidal", 90, "CN"),
            SampleBidLine("Steam sterilization indicator strips", 15, "BX"),
        ],
        terms=[
            "Indemnification: The Contractor shall indemnify, defend, and hold harmless the Department of "
            "Veterans Affairs, its officers and employees, from any claims, damages, or liabilities, "
            "including reasonable attorneys' fees, arising from the Contractor's performance under this "
            "solicitation.",
            "Payment Terms: Invoices shall be paid Net 45 days in accordance with the Prompt Payment Act.",
            "Firm Pricing: Unit prices shall remain firm for the twelve (12) month base period; no price "
            "escalation will be accepted during the base period.",
            "Delivery Terms: All items shall be delivered F.O.B. Destination to the VA Medical Center "
            "receiving dock; freight and handling shall be included in the unit price.",
            "Insurance: The Contractor shall carry Commercial General Liability insurance of at least "
            "$1,000,000 per occurrence and provide a Certificate of Insurance naming the Government as "
            "additional insured prior to award.",
            "E-Verify Certification: The Contractor certifies participation in the E-Verify program for "
            "verification of employment eligibility of all employees performing under this contract.",
            "Debarment: The Contractor certifies that it and its principals are not presently debarred, "
            "suspended, or proposed for debarment from participation in federal procurement.",
            "Stark Law / Anti-Kickback: The Contractor warrants that no arrangement under this contract "
            "violates the federal physician self-referral (Stark) law or the Anti-Kickback Statute.",
            "Most Favored Customer: The Contractor certifies that pricing offered is no less favorable "
            "than that offered to any commercial customer for comparable quantities.",
            "Anti-Lobbying Certification: Pursuant to 31 U.S.C. 1352, the Contractor certifies that no "
            "appropriated funds have been paid to influence a federal officer in connection with this award.",
            "Intellectual Property Infringement: The Contractor warrants that the goods furnished do not "
            "infringe any patent or trademark and shall defend the Government against any infringement claim.",
            "Affirmative Action / EEO: The Contractor shall maintain a written affirmative action plan and "
            "comply with all applicable Equal Employment Opportunity requirements.",
            "Political Contributions: The Contractor shall disclose reportable political contributions in "
            "accordance with applicable pay-to-play requirements.",
            "Tax Exemption: The Department of Veterans Affairs is exempt from federal excise and state sales "
            "tax; such taxes shall not be included in the Contractor's pricing.",
        ],
    ),
    SampleBidDocument(
        file_name="UN-HLTH-0892_Field_Clinic_Consumables.xlsx",
        file_format="xlsx",
        title="Field Clinic Consumables RFQ",
        customer_name="United Nations Procurement Division",
        customer_id="CUST-1003",
        solicitation_ref="UN-HLTH-0892",
        due_in_days=8,
        lines=[
            SampleBidLine("exam gloves nitrile pwd free size L 100/bx", 500, "BX"),
            SampleBidLine("syringes 5ml luer lock no needle", 300, "BX"),
            SampleBidLine("hypodermic needles 23g", 200, "BX"),
            SampleBidLine("IV catheter, BD Insyte 20g winged (BD ref BD-4521)", 150, "BX", given_code="BD-4521"),
            SampleBidLine("iv administration set needle free", 80, "CS"),
            SampleBidLine("gauze sponges 4x4 non sterile", 250, "BX"),
            SampleBidLine("coban wrap 3in", 60, "BX"),
            SampleBidLine("surgical tape 2in hypoallergenic", 70, "BX"),
            SampleBidLine("N95 mask foldable small", 100, "BX"),
            SampleBidLine("procedure mask level 1 ear loop", 200, "BX"),
            SampleBidLine("sharps container 2 gal", 90, "EA"),
            SampleBidLine("specimen containers 4oz sterile", 120, "CS"),
        ],
        terms=[
            "Payment Terms: Payment shall be made Net 60 days from receipt of goods at the designated "
            "field-clinic destination and acceptance by the receiving officer.",
            "Delivery Terms: Delivery shall be DDP (Delivered Duty Paid) to the in-country warehouse; all "
            "freight, insurance, and customs duties are included in the offered unit price.",
            "Warranty of Products: All products shall be new, unexpired, and carry a minimum remaining "
            "shelf life of 24 months at the time of delivery.",
            "Insurance Requirements: The Contractor shall carry marine cargo and Commercial General "
            "Liability insurance covering the full value of goods in transit.",
            "Anti-Corruption: The Contractor certifies compliance with anti-corruption and anti-bribery "
            "standards and shall not offer any improper payment to secure this award.",
            "Most Favored Customer: Prices shall be no less favorable than those offered to any other "
            "humanitarian or governmental buyer for comparable volumes.",
        ],
    ),
    SampleBidDocument(
        file_name="Premier_Dental_Infection_Control_Renewal.docx",
        file_format="docx",
        title="Annual Dental & Infection Control Contract Renewal",
        customer_name="Premier Health Alliance",
        customer_id="CUST-1006",
        solicitation_ref="PHA-DEN-2027",
        due_in_days=21,
        lines=[
            SampleBidLine("impression material medium body cartridges", 40, "BX"),
            SampleBidLine("prophy paste fluoride unit dose cups medium grit", 60, "BX"),
            SampleBidLine("fluoride varnish 5% unit dose", 50, "BX"),
            SampleBidLine("dental bibs 2 ply chain style", 30, "CS"),
            SampleBidLine("carbide burs FG assorted", 100, "PK"),
            SampleBidLine("sterilization pouches self seal 5.25x10", 80, "BX"),
            SampleBidLine("autoclave chemical indicator strips", 40, "BX"),
            SampleBidLine("cotton rolls non sterile medium", 60, "BG"),
            SampleBidLine("saliva ejectors disposable clear", 100, "BX"),
            SampleBidLine("topical anesthetic gel benzocaine 20% mint", 25, "EA"),
            SampleBidLine("articaine local anesthetic cartridges 4%", 70, "BX"),
            SampleBidLine("orthodontic elastic power chain continuous", 40, "PK"),
            SampleBidLine("ceramic ortho brackets mesh base", 15, "PK"),
            SampleBidLine("enzymatic instrument cleaner concentrate 1 gal", 20, "EA"),
        ],
        terms=[
            "Administrative Fee: As a group purchasing organization contract, the Contractor shall remit a "
            "quarterly administrative fee of two percent (2%) of net purchases by member facilities.",
            "Rebate Commitments: Any tiered volume rebates shall be described, including thresholds and the "
            "rebate percentage at each tier.",
            "Firm Pricing: Contract pricing shall remain firm for the initial twelve-month renewal term.",
            "Price Reduction: The Contractor shall extend to members any price decrease offered to "
            "comparable customers during the contract term.",
            "Most Favored Nation: The Contractor warrants that member pricing represents its best price for "
            "like quantities and comparable terms.",
            "Marketing Fees: Any promotional or marketing allowance associated with this agreement shall be "
            "disclosed and comply with fair-market-value requirements.",
            "Royalty Fees: Any royalty or licensing fee embedded in offered pricing shall be separately "
            "disclosed for compliance review.",
            "Warranty of Products: All products shall be warranted free from defects for the manufacturer's "
            "stated warranty period.",
        ],
    ),
]


# ---------------------------------------------------------------------------
# Extra government-agency bid solicitations — randomly assembled (fixed seed,
# so it's reproducible) from the same product catalog used to seed
# item_catalog, so their line items are guaranteed to have real matches.
# Rendered as PDFs only, mirroring the classic "scanned/typed bid letter"
# format a contracting office would actually send.
# ---------------------------------------------------------------------------

_GOV_SEED = 20260714
_GOV_RNG = random.Random(_GOV_SEED)

_GOV_AGENCIES: list[dict[str, Any]] = [
    dict(
        file_name="DLA-TS-MED-2027-0231_MedSurg_IDIQ.pdf",
        title="Medical-Surgical Consumables IDIQ Solicitation",
        customer_name="Defense Logistics Agency – Troop Support (Medical)",
        customer_id="CUST-1016",
        solicitation_ref="DLA-TS-MED-2027-0231",
        due_in_days=18,
        num_lines=16,
    ),
    dict(
        file_name="BOP-NCR-2027-0087_Institutional_MedSupply_RFQ.pdf",
        title="Institutional Medical Supply Replenishment RFQ",
        customer_name="U.S. Bureau of Prisons – North Central Regional Office",
        customer_id="CUST-1017",
        solicitation_ref="BOP-NCR-2027-0087",
        due_in_days=14,
        num_lines=13,
    ),
    dict(
        file_name="AZ-ADCRR-2027-0456_Correctional_Health_Supply_Bid.pdf",
        title="Statewide Correctional Health Services Supply Bid",
        customer_name="State of Arizona Dept. of Corrections, Rehabilitation & Reentry",
        customer_id="CUST-1018",
        solicitation_ref="AZ-ADCRR-2027-0456",
        due_in_days=21,
        num_lines=15,
    ),
    dict(
        file_name="BAL-HD-2027-0192_PublicHealth_Clinics_Solicitation.pdf",
        title="Municipal Public Health Clinics Supply Solicitation",
        customer_name="City of Baltimore Health Department",
        customer_id="CUST-1019",
        solicitation_ref="BAL-HD-2027-0192",
        due_in_days=10,
        num_lines=11,
    ),
    dict(
        file_name="IHS-GP-2027-0339_AreaOffice_MedConsumables.pdf",
        title="Area Office Medical Consumables Solicitation",
        customer_name="Indian Health Service – Great Plains Area Office",
        customer_id="CUST-1020",
        solicitation_ref="IHS-GP-2027-0339",
        due_in_days=25,
        num_lines=14,
    ),
]

_GOV_QTY_CHOICES = {
    "EA": [5, 10, 15, 20, 25, 30, 40, 50],
    "_default": [25, 40, 50, 60, 80, 100, 150, 200, 250, 300, 400, 500],
}


def _requester_line(product: dict[str, Any], rng: random.Random) -> SampleBidLine:
    """Rephrase a catalog base product the way a requesting office would type
    it into a bid letter: lowercase, abbreviated, manufacturer/line name
    dropped, random size/pack — never a verbatim catalog description."""
    size = rng.choice(product["sizes"])
    pack = rng.choice(product["packs"])
    size_prefix = f"{size} " if size else ""
    raw_text = _abbreviate(f"{size_prefix}{product['desc']}, {pack}".strip())

    given_code = None
    if rng.random() < 0.05:
        given_code = f"{product['manufacturer'][:3].upper()}-{rng.randint(1000, 9999)}"
        raw_text = f"{raw_text} (mfr ref {given_code})"

    uom = product["uom"]
    qty = rng.choice(_GOV_QTY_CHOICES.get(uom, _GOV_QTY_CHOICES["_default"]))
    return SampleBidLine(raw_text, qty, uom, given_code=given_code)


def _build_government_bid_documents() -> list[SampleBidDocument]:
    documents = []
    for agency in _GOV_AGENCIES:
        products = _GOV_RNG.sample(BASE_PRODUCTS, agency["num_lines"])
        lines = [_requester_line(product, _GOV_RNG) for product in products]
        # A deterministic subset of the standard government provisions per
        # document, so each sample has a realistic, complex, and varied terms
        # section (8–14 clauses spanning multiple owning teams) for the
        # requirement-routing step to work over.
        num_terms = _GOV_RNG.randint(8, min(14, len(_COMMON_GOV_TERMS)))
        terms = _GOV_RNG.sample(_COMMON_GOV_TERMS, num_terms)
        documents.append(
            SampleBidDocument(
                file_name=agency["file_name"],
                file_format="pdf",
                title=agency["title"],
                customer_name=agency["customer_name"],
                customer_id=agency["customer_id"],
                solicitation_ref=agency["solicitation_ref"],
                due_in_days=agency["due_in_days"],
                lines=lines,
                terms=terms,
            )
        )
    return documents


SAMPLE_DOCUMENTS.extend(_build_government_bid_documents())


def render_pdf(document: SampleBidDocument) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"<b>{document.customer_name}</b>", styles["Title"]),
        Paragraph(document.title, styles["Heading2"]),
        Paragraph(f"Solicitation Reference: {document.solicitation_ref}", styles["Normal"]),
        Paragraph(f"Response due: {document.due_in_days} days from issue", styles["Normal"]),
        Spacer(1, 0.25 * inch),
        Paragraph(
            "Vendors shall provide item description, unit price, and delivery lead time for each "
            "line below. Manufacturer part numbers are not required and are frequently unavailable "
            "to the requesting office.",
            styles["Normal"],
        ),
        Spacer(1, 0.2 * inch),
    ]
    table_data = [["Line", "Description", "Qty", "UOM"]]
    for i, line in enumerate(document.lines, start=1):
        table_data.append([str(i), line.raw_text, str(line.qty), line.uom])
    table = Table(table_data, colWidths=[0.5 * inch, 4.2 * inch, 0.7 * inch, 0.7 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14191f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f4")]),
    ]))
    story.append(table)

    if document.terms:
        story.append(Spacer(1, 0.3 * inch))
        story.append(Paragraph("Section II — Terms, Conditions & Certifications", styles["Heading2"]))
        story.append(Paragraph(
            "The following terms apply to any resulting award. Vendors shall review and confirm "
            "compliance in their response.",
            styles["Normal"],
        ))
        story.append(Spacer(1, 0.12 * inch))
        term_style = ParagraphStyle("term", parent=styles["Normal"], spaceAfter=6)
        for i, term in enumerate(document.terms, start=1):
            story.append(Paragraph(f"{i}. {term}", term_style))

    doc.build(story)
    return buffer.getvalue()


def render_xlsx(document: SampleBidDocument) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "RFQ Lines"
    sheet["A1"] = document.customer_name
    sheet["A1"].font = Font(bold=True, size=14)
    sheet["A2"] = document.title
    sheet["A3"] = f"Solicitation Reference: {document.solicitation_ref}"
    sheet["A4"] = f"Response due: {document.due_in_days} days from issue"

    header_row = 6
    headers = ["Line", "Description", "Qty", "UOM", "Unit Price", "Extended Price"]
    for col, header in enumerate(headers, start=1):
        cell = sheet.cell(row=header_row, column=col, value=header)
        cell.font = Font(bold=True)

    for i, line in enumerate(document.lines, start=1):
        row = header_row + i
        sheet.cell(row=row, column=1, value=i)
        sheet.cell(row=row, column=2, value=line.raw_text)
        sheet.cell(row=row, column=3, value=line.qty)
        sheet.cell(row=row, column=4, value=line.uom)
        # Unit Price / Extended Price left blank — this is the vendor's pricing template.

    sheet.column_dimensions["B"].width = 55

    if document.terms:
        terms_row = header_row + len(document.lines) + 3
        heading = sheet.cell(row=terms_row, column=1, value="Section II — Terms, Conditions & Certifications")
        heading.font = Font(bold=True, size=12)
        for i, term in enumerate(document.terms, start=1):
            sheet.cell(row=terms_row + i, column=1, value=f"{i}. {term}")

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def render_docx(document: SampleBidDocument) -> bytes:
    from docx import Document as DocxDocument
    from docx.shared import Pt

    docx_doc = DocxDocument()
    docx_doc.add_heading(document.customer_name, level=0)
    docx_doc.add_heading(document.title, level=1)
    meta = docx_doc.add_paragraph()
    meta.add_run(f"Solicitation Reference: {document.solicitation_ref}\n").bold = True
    meta.add_run(f"Response due: {document.due_in_days} days from issue")

    docx_doc.add_paragraph(
        "Vendors shall provide a firm unit price for each item below. Item descriptions reflect "
        "clinical/operational terminology used by the requesting office; manufacturer part numbers "
        "are provided only where already known to the requester."
    )

    table = docx_doc.add_table(rows=1, cols=4)
    table.style = "Light Grid Accent 1"
    header_cells = table.rows[0].cells
    for cell, text in zip(header_cells, ["Line", "Description", "Qty", "UOM"]):
        cell.text = text
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.font.bold = True
                run.font.size = Pt(10)

    for i, line in enumerate(document.lines, start=1):
        row_cells = table.add_row().cells
        row_cells[0].text = str(i)
        row_cells[1].text = line.raw_text
        row_cells[2].text = str(line.qty)
        row_cells[3].text = line.uom

    if document.terms:
        docx_doc.add_heading("Section II — Terms, Conditions & Certifications", level=1)
        docx_doc.add_paragraph(
            "The following terms apply to any resulting award. Vendors shall review and confirm "
            "compliance in their response."
        )
        for i, term in enumerate(document.terms, start=1):
            docx_doc.add_paragraph(f"{i}. {term}")

    buffer = BytesIO()
    docx_doc.save(buffer)
    return buffer.getvalue()


_RENDERERS = {"pdf": render_pdf, "xlsx": render_xlsx, "docx": render_docx}


def render_document_bytes(document: SampleBidDocument) -> bytes:
    return _RENDERERS[document.file_format](document)


def document_manifest(document: SampleBidDocument) -> dict[str, Any]:
    return {
        "file_name": document.file_name,
        "file_format": document.file_format,
        "title": document.title,
        "customer_name": document.customer_name,
        "customer_id": document.customer_id,
        "solicitation_ref": document.solicitation_ref,
        "due_in_days": document.due_in_days,
        "line_count": len(document.lines),
        "lines_with_given_code": sum(1 for line in document.lines if line.given_code),
    }
