"""Synthetic Bids AI demo data.

Hand-authored product lines + customer/division rosters (small, curated —
mirrors bids-cpq's demo_data.py style), expanded programmatically into a
few hundred item_catalog rows and a year+ of historical bids / purchase
history so item matching and pricing have real signal to work with.

Deterministic (fixed seed) so re-running seed_demo_data.py reproduces the
same catalog and history.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

_SEED = 20260713
_RNG = random.Random(_SEED)

# ---------------------------------------------------------------------------
# Item catalog base product lines. Each expands across size/pack-size
# variants into full item_catalog rows. Real (well-known) manufacturer names
# are used for realism in this internal sales demo, matching bids-cpq's
# convention of naming real equipment brands.
# ---------------------------------------------------------------------------

BASE_PRODUCTS: list[dict[str, Any]] = [
    dict(category="Exam Gloves", subcategory="Nitrile", manufacturer="Kimberly-Clark", line="Kimtech",
         desc="nitrile exam gloves, powder-free, textured fingertips", uom="BX",
         packs=["100/BX", "10 BX/CS"], sizes=["XS", "S", "M", "L", "XL"], price=(6.25, 9.75)),
    dict(category="Exam Gloves", subcategory="Latex", manufacturer="Medline", line="SensiCare",
         desc="latex exam gloves, powder-free, chlorinated", uom="BX",
         packs=["100/BX", "10 BX/CS"], sizes=["XS", "S", "M", "L", "XL"], price=(7.10, 10.40)),
    dict(category="Exam Gloves", subcategory="Vinyl", manufacturer="Cardinal Health", line="Esteem",
         desc="vinyl exam gloves, powder-free, latex-free", uom="BX",
         packs=["100/BX", "10 BX/CS"], sizes=["XS", "S", "M", "L", "XL"], price=(5.10, 7.60)),
    dict(category="Face Masks", subcategory="Level 1", manufacturer="Halyard", line="Fluidshield",
         desc="ASTM level 1 procedure face mask, ear loop", uom="BX",
         packs=["50/BX", "10 BX/CS"], sizes=[None], price=(4.50, 7.20)),
    dict(category="Face Masks", subcategory="Level 3", manufacturer="Halyard", line="Fluidshield",
         desc="ASTM level 3 fluid-resistant surgical mask, ear loop", uom="BX",
         packs=["50/BX", "10 BX/CS"], sizes=[None], price=(7.80, 11.90)),
    dict(category="Respirators", subcategory="N95", manufacturer="3M", line="Aura",
         desc="N95 particulate respirator, foldable", uom="BX",
         packs=["20/BX", "8 BX/CS"], sizes=["Regular", "Small"], price=(28.00, 46.00)),
    dict(category="Infection Control", subcategory="Surface Wipes", manufacturer="PDI", line="Sani-Cloth",
         desc="surface disinfectant wipes, germicidal, bleach-free", uom="CN",
         packs=["160 ct/CN", "12 CN/CS"], sizes=[None], price=(6.90, 10.20)),
    dict(category="Infection Control", subcategory="Sterilization Pouches", manufacturer="Crosstex", line="SteriKing",
         desc="self-seal sterilization pouches, paper/film", uom="BX",
         packs=["200/BX"], sizes=["3.5x9in", "5.25x10in"], price=(9.50, 14.75)),
    dict(category="Infection Control", subcategory="Indicator Strips", manufacturer="3M", line="Comply",
         desc="steam sterilization chemical indicator strips", uom="BX",
         packs=["100/BX"], sizes=[None], price=(11.00, 16.50)),
    dict(category="Wound Care", subcategory="Gauze", manufacturer="Medline", line="Curity",
         desc="woven gauze sponges, non-sterile", uom="BX",
         packs=["200/BX"], sizes=["4x4in", "2x2in"], price=(3.60, 6.40)),
    dict(category="Wound Care", subcategory="Bandages", manufacturer="3M", line="Coban",
         desc="self-adherent cohesive wrap bandage", uom="BX",
         packs=["36 rolls/BX"], sizes=["2in", "3in", "4in"], price=(38.00, 55.00)),
    dict(category="Wound Care", subcategory="Adhesive Tape", manufacturer="3M", line="Micropore",
         desc="paper surgical tape, hypoallergenic", uom="BX",
         packs=["12 rolls/BX"], sizes=["1in", "2in"], price=(14.00, 21.00)),
    dict(category="Syringes & Needles", subcategory="Syringes", manufacturer="BD", line="Luer-Lok",
         desc="disposable syringe, luer-lok tip, without needle", uom="BX",
         packs=["100/BX"], sizes=["3mL", "5mL", "10mL", "20mL"], price=(9.20, 15.60)),
    dict(category="Syringes & Needles", subcategory="Hypodermic Needles", manufacturer="BD", line="PrecisionGlide",
         desc="hypodermic needle, regular bevel", uom="BX",
         packs=["100/BX"], sizes=["21G", "23G", "25G", "27G"], price=(6.80, 10.10)),
    dict(category="Sutures", subcategory="Absorbable", manufacturer="Ethicon", line="Vicryl",
         desc="coated braided absorbable suture with needle", uom="BX",
         packs=["12/BX"], sizes=["3-0", "4-0", "5-0"], price=(58.00, 84.00)),
    dict(category="Sutures", subcategory="Non-Absorbable", manufacturer="Ethicon", line="Prolene",
         desc="non-absorbable monofilament suture with needle", uom="BX",
         packs=["12/BX"], sizes=["3-0", "4-0", "5-0"], price=(62.00, 90.00)),
    dict(category="Diagnostic Supplies", subcategory="Exam Table Paper", manufacturer="Graham Medical", line="Tidi",
         desc="smooth exam table paper roll, white", uom="CS",
         packs=["12 rolls/CS"], sizes=["18in", "21in"], price=(58.00, 78.00)),
    dict(category="Diagnostic Supplies", subcategory="Tongue Depressors", manufacturer="Puritan", line="Standard",
         desc="wood tongue depressor, non-sterile", uom="BX",
         packs=["500/BX"], sizes=["Adult", "Pediatric"], price=(3.20, 5.10)),
    dict(category="Diagnostic Supplies", subcategory="Specula", manufacturer="Welch Allyn", line="KleenSpec",
         desc="disposable vaginal specula", uom="BX",
         packs=["24/BX"], sizes=["Small", "Medium", "Large"], price=(24.00, 34.00)),
    dict(category="Sharps Management", subcategory="Sharps Containers", manufacturer="Cardinal Health", line="SharpSafety",
         desc="sharps disposal container, locking lid", uom="EA",
         packs=["1 qt", "2 gal", "8 gal", "18 gal"], sizes=[None], price=(4.10, 22.50)),
    dict(category="IV Supplies", subcategory="IV Catheters", manufacturer="BD", line="Insyte",
         desc="peripheral IV catheter, winged", uom="BX",
         packs=["50/BX"], sizes=["16G", "18G", "20G", "22G", "24G"], price=(32.00, 46.00)),
    dict(category="IV Supplies", subcategory="IV Administration Sets", manufacturer="ICU Medical", line="Clearlink",
         desc="IV administration set, needle-free connector", uom="CS",
         packs=["50/CS"], sizes=[None], price=(88.00, 130.00)),
    dict(category="Dental Consumables", subcategory="Impression Material", manufacturer="Dentsply Sirona", line="Aquasil",
         desc="VPS impression material, medium body cartridge", uom="BX",
         packs=["4 cartridges/BX"], sizes=[None], price=(64.00, 96.00)),
    dict(category="Dental Consumables", subcategory="Prophy Paste", manufacturer="Premier Dental", line="Nupro",
         desc="prophylaxis paste with fluoride, unit dose cups", uom="BX",
         packs=["200/BX"], sizes=["Coarse", "Medium", "Fine"], price=(26.00, 38.00)),
    dict(category="Dental Consumables", subcategory="Fluoride Varnish", manufacturer="3M", line="Vanish",
         desc="5% sodium fluoride varnish, unit dose", uom="BX",
         packs=["100/BX"], sizes=[None], price=(48.00, 70.00)),
    dict(category="Dental Consumables", subcategory="Dental Bibs", manufacturer="Tidi", line="Choice",
         desc="patient bib, 2-ply tissue/poly, chain style", uom="CS",
         packs=["500/CS"], sizes=[None], price=(30.00, 42.00)),
    dict(category="Dental Consumables", subcategory="Burs", manufacturer="Brasseler", line="One Series",
         desc="carbide dental burs, friction grip", uom="PK",
         packs=["5/PK"], sizes=["245", "330", "556", "701L"], price=(9.00, 15.00)),
    dict(category="Handpieces", subcategory="High Speed", manufacturer="Midwest", line="RDH",
         desc="high speed dental handpiece, push-button chuck", uom="EA",
         packs=["Each"], sizes=[None], price=(320.00, 480.00)),
    dict(category="Anesthetic", subcategory="Local Anesthetic", manufacturer="Septodont", line="Septocaine",
         desc="4% articaine HCl with epinephrine injection cartridge", uom="BX",
         packs=["50/BX"], sizes=[None], price=(38.00, 54.00)),
    dict(category="Anesthetic", subcategory="Topical", manufacturer="Patterson", line="Benzocaine",
         desc="20% benzocaine topical anesthetic gel", uom="EA",
         packs=["1 jar"], sizes=["Mint", "Cherry"], price=(6.50, 9.80)),
    dict(category="Sterilization Equipment", subcategory="Sterilization Wrap", manufacturer="Halyard", line="KC600",
         desc="sterilization wrap, blue polypropylene", uom="CS",
         packs=["100/CS"], sizes=["15x15in", "20x20in", "24x24in"], price=(42.00, 66.00)),
    dict(category="Patient Positioning", subcategory="Headrest Covers", manufacturer="Tidi", line="Everyday",
         desc="disposable headrest cover, tissue/poly", uom="CS",
         packs=["1000/CS"], sizes=[None], price=(46.00, 64.00)),
    dict(category="Personal Protection", subcategory="Face Shields", manufacturer="3M", line="Secure-Click",
         desc="disposable face shield, anti-fog", uom="BX",
         packs=["25/BX"], sizes=[None], price=(22.00, 34.00)),
    dict(category="Personal Protection", subcategory="Isolation Gowns", manufacturer="Medline", line="AAMI L2",
         desc="fluid-resistant isolation gown, elastic cuff", uom="CS",
         packs=["10/CS"], sizes=["Regular", "XL"], price=(48.00, 72.00)),
    dict(category="Personal Protection", subcategory="Shoe Covers", manufacturer="Medline", line="Non-Skid",
         desc="disposable non-skid shoe cover", uom="CS",
         packs=["300/CS"], sizes=["Regular", "XL"], price=(28.00, 40.00)),
    dict(category="Personal Protection", subcategory="Bouffant Caps", manufacturer="Medline", line="Standard",
         desc="disposable bouffant cap, latex-free", uom="CS",
         packs=["1000/CS"], sizes=["21in", "24in"], price=(24.00, 34.00)),
    dict(category="Lab Supplies", subcategory="Specimen Containers", manufacturer="Globe Scientific", line="Standard",
         desc="sterile specimen container with lid", uom="CS",
         packs=["100/CS"], sizes=["4oz", "8oz"], price=(22.00, 32.00)),
    dict(category="Lab Supplies", subcategory="Blood Collection Tubes", manufacturer="BD", line="Vacutainer",
         desc="blood collection tube, EDTA additive", uom="BX",
         packs=["100/BX"], sizes=["2mL", "4mL", "6mL"], price=(18.00, 28.00)),
    dict(category="Orthodontic Supplies", subcategory="Elastics", manufacturer="American Orthodontics", line="Power Chain",
         desc="orthodontic elastic power chain, continuous", uom="PK",
         packs=["100ft/PK"], sizes=["Short", "Medium", "Long"], price=(8.00, 13.00)),
    dict(category="Orthodontic Supplies", subcategory="Brackets", manufacturer="3M", line="Clarity",
         desc="ceramic orthodontic brackets, mesh base", uom="PK",
         packs=["20/PK"], sizes=[None], price=(90.00, 140.00)),
    dict(category="Cleaning & Disinfection", subcategory="Enzymatic Cleaner", manufacturer="Certol", line="Enzol",
         desc="enzymatic instrument pre-cleaner concentrate", uom="EA",
         packs=["1 gal"], sizes=[None], price=(28.00, 40.00)),
    dict(category="Cleaning & Disinfection", subcategory="Ultrasonic Solution", manufacturer="Certol", line="Vista",
         desc="ultrasonic cleaning solution concentrate", uom="EA",
         packs=["1 gal"], sizes=[None], price=(30.00, 44.00)),
    dict(category="Patient Comfort", subcategory="Cotton Rolls", manufacturer="Richmond Dental", line="Standard",
         desc="non-sterile cotton rolls, medium", uom="BG",
         packs=["2000/BG"], sizes=[None], price=(20.00, 30.00)),
    dict(category="Patient Comfort", subcategory="Saliva Ejectors", manufacturer="Crosstex", line="Standard",
         desc="disposable saliva ejector, clear", uom="BX",
         packs=["100/BX"], sizes=[None], price=(4.50, 7.00)),
]

_ABBREV = {
    "disposable": "disp",
    "sterilization": "steriliz",
    "surgical": "surg",
    "procedure": "proc",
    "particulate": "part",
    "respirator": "resp",
    "concentrate": "conc",
    "diagnostic": "diag",
    "administration": "admin",
    "prophylaxis": "prophy",
}


def _abbreviate(text: str) -> str:
    for full, short in _ABBREV.items():
        text = text.replace(full, short)
    return text


def build_item_catalog_rows() -> list[dict[str, Any]]:
    """Expand BASE_PRODUCTS across size/pack variants into full catalog rows.

    ~95% of rows get no manufacturer/competitor code at all — only a
    free-text description — mirroring the BRD's stated pain point
    ("most bid requests are description only").
    """
    rows: list[dict[str, Any]] = []
    counter = 0
    for product in BASE_PRODUCTS:
        sizes = product["sizes"] or [None]
        for size in sizes:
            for pack in product["packs"]:
                counter += 1
                item_code = f"SKU-{100000 + counter}"
                low, high = product["price"]
                list_price = round(_RNG.uniform(low, high), 2)
                size_prefix = f"{size} " if size else ""
                description_long = (
                    f"{product['manufacturer']} {product['line']} {size_prefix}{product['desc']}, {pack}"
                ).strip()
                description_short = _abbreviate(f"{size_prefix}{product['desc']}, {pack}".strip())[:48]

                manufacturer_item_code = None
                competitor_item_code = None
                if _RNG.random() < 0.05:
                    manufacturer_item_code = f"{product['manufacturer'][:3].upper()}-{_RNG.randint(1000, 9999)}"
                    if _RNG.random() < 0.4:
                        competitor_item_code = f"CMP-{_RNG.randint(10000, 99999)}"

                rows.append(dict(
                    item_code=item_code,
                    manufacturer_name=product["manufacturer"],
                    manufacturer_item_code=manufacturer_item_code,
                    competitor_item_code=competitor_item_code,
                    description_short=description_short,
                    description_long=description_long,
                    category=product["category"],
                    subcategory=product["subcategory"],
                    uom=product["uom"],
                    pack_size=pack,
                    item_size=size,
                    list_price=list_price,
                    is_active=True,
                ))
    return rows


# ---------------------------------------------------------------------------
# Customers & divisions. "Federal - Medical" and "United Nations" are the two
# capacity-constrained verticals named explicitly in the BRD's success
# metrics ("participate in specialty vertical solicitations that we
# do not [service] today due to capacity constraints").
# ---------------------------------------------------------------------------

DIVISIONS: list[dict[str, Any]] = [
    dict(division_id="DIV-CORE", division_name="Core Distribution", vertical="General Distribution", capacity_constrained=False),
    dict(division_id="DIV-FEDMED", division_name="Federal - Medical", vertical="Federal Government", capacity_constrained=True),
    dict(division_id="DIV-UN", division_name="United Nations", vertical="International / NGO", capacity_constrained=True),
    dict(division_id="DIV-GPO-VIZ", division_name="GPO - Vizient", vertical="Group Purchasing Organization", capacity_constrained=False),
    dict(division_id="DIV-GPO-PREM", division_name="GPO - Premier", vertical="Group Purchasing Organization", capacity_constrained=False),
    dict(division_id="DIV-STLOC", division_name="State & Local Government", vertical="State/Local Government", capacity_constrained=True),
    dict(division_id="DIV-IDN", division_name="Regional Health Systems (IDN)", vertical="Integrated Delivery Network", capacity_constrained=False),
]

CUSTOMERS: list[dict[str, Any]] = [
    dict(customer_id="CUST-1001", customer_name="VA Medical Center - Region 4", division_id="DIV-FEDMED", customer_type="Government", region="Southeast"),
    dict(customer_id="CUST-1002", customer_name="Walter Reed Regional Health Command", division_id="DIV-FEDMED", customer_type="Government", region="Mid-Atlantic"),
    dict(customer_id="CUST-1003", customer_name="United Nations Procurement Division", division_id="DIV-UN", customer_type="International/NGO", region="Global"),
    dict(customer_id="CUST-1004", customer_name="UN Refugee Health Logistics Unit", division_id="DIV-UN", customer_type="International/NGO", region="Global"),
    dict(customer_id="CUST-1005", customer_name="Vizient National Contract Group", division_id="DIV-GPO-VIZ", customer_type="GPO", region="National"),
    dict(customer_id="CUST-1006", customer_name="Premier Health Alliance", division_id="DIV-GPO-PREM", customer_type="GPO", region="National"),
    dict(customer_id="CUST-1007", customer_name="State of Ohio Dept. of Rehab & Correction Health Svcs", division_id="DIV-STLOC", customer_type="State Government", region="Midwest"),
    dict(customer_id="CUST-1008", customer_name="Commonwealth of Virginia DOC Medical Services", division_id="DIV-STLOC", customer_type="State Government", region="Mid-Atlantic"),
    dict(customer_id="CUST-1009", customer_name="Metro Regional Health System", division_id="DIV-IDN", customer_type="IDN", region="Northeast"),
    dict(customer_id="CUST-1010", customer_name="Lakeshore Community Health Network", division_id="DIV-IDN", customer_type="IDN", region="Midwest"),
    dict(customer_id="CUST-1011", customer_name="Riverside County Public Health Dept.", division_id="DIV-STLOC", customer_type="County Government", region="West"),
    dict(customer_id="CUST-1012", customer_name="Bureau of Prisons - Central Region", division_id="DIV-FEDMED", customer_type="Government", region="Central"),
    dict(customer_id="CUST-1013", customer_name="Indian Health Service - Southwest Area", division_id="DIV-FEDMED", customer_type="Government", region="Southwest"),
    dict(customer_id="CUST-1014", customer_name="Gulf Coast Community Health Centers", division_id="DIV-CORE", customer_type="Dental/Medical Group", region="South"),
    dict(customer_id="CUST-1015", customer_name="Great Lakes Dental Service Organization", division_id="DIV-CORE", customer_type="Dental Group", region="Midwest"),
    dict(customer_id="CUST-1016", customer_name="Defense Logistics Agency – Troop Support (Medical)", division_id="DIV-FEDMED", customer_type="Government", region="National"),
    dict(customer_id="CUST-1017", customer_name="U.S. Bureau of Prisons – North Central Regional Office", division_id="DIV-FEDMED", customer_type="Government", region="Midwest"),
    dict(customer_id="CUST-1018", customer_name="State of Arizona Dept. of Corrections, Rehabilitation & Reentry", division_id="DIV-STLOC", customer_type="State Government", region="Southwest"),
    dict(customer_id="CUST-1019", customer_name="City of Baltimore Health Department", division_id="DIV-STLOC", customer_type="Municipal Government", region="Mid-Atlantic"),
    dict(customer_id="CUST-1020", customer_name="Indian Health Service – Great Plains Area Office", division_id="DIV-FEDMED", customer_type="Government", region="Great Plains"),
]

_OUTCOMES = ["won", "won", "won", "lost", "lost", "no_bid"]


def build_historical_bid_rows(item_catalog: list[dict[str, Any]], num_rows: int = 1200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start_date = date(2024, 10, 1)
    for i in range(num_rows):
        customer = _RNG.choice(CUSTOMERS)
        item = _RNG.choice(item_catalog)
        outcome = _RNG.choice(_OUTCOMES)
        discount = _RNG.uniform(0.05, 0.22)
        submitted_price = round(item["list_price"] * (1 - discount), 2)
        competitor_price_observed = None
        if outcome in ("won", "lost") and _RNG.random() < 0.6:
            competitor_delta = _RNG.uniform(-0.08, 0.08)
            competitor_price_observed = round(submitted_price * (1 + competitor_delta), 2)
        submitted_date = start_date + timedelta(days=_RNG.randint(0, 620))
        rows.append(dict(
            historical_bid_id=f"HBID-{20000 + i}",
            customer_id=customer["customer_id"],
            division_id=customer["division_id"],
            item_code=item["item_code"],
            qty=_RNG.choice([50, 100, 250, 500, 1000, 2500]),
            submitted_price=submitted_price,
            outcome=outcome,
            competitor_price_observed=competitor_price_observed,
            submitted_date=submitted_date.isoformat(),
        ))
    return rows


def build_customer_purchase_history_rows(item_catalog: list[dict[str, Any]], num_rows: int = 900) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start_date = date(2024, 6, 1)
    for i in range(num_rows):
        customer = _RNG.choice(CUSTOMERS)
        item = _RNG.choice(item_catalog)
        discount = _RNG.uniform(0.0, 0.15)
        last_price_paid = round(item["list_price"] * (1 - discount), 2)
        last_purchase_date = start_date + timedelta(days=_RNG.randint(0, 760))
        rows.append(dict(
            purchase_history_id=f"PH-{30000 + i}",
            customer_id=customer["customer_id"],
            division_id=customer["division_id"],
            item_code=item["item_code"],
            last_price_paid=last_price_paid,
            last_purchase_date=last_purchase_date.isoformat(),
            cumulative_qty=_RNG.choice([25, 50, 100, 250, 500, 1000, 2000]),
        ))
    return rows
