"""
GreenWatt — Score 10 Leads
Lead magnet tool: gate form → CSV upload → field mapping → scoring → results + CTA
"""

import os, csv, io, json, hashlib, uuid, time
from datetime import datetime
from flask import Flask, request, jsonify, render_template
import urllib.request
import urllib.parse

# Load .env file if present (for local dev and EC2 deployment)
from pathlib import Path
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    os.environ.setdefault(key, value)

app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================

TRESTLE_API_KEY = os.environ.get("TRESTLE_API_KEY")
BATCHDATA_API_KEY = os.environ.get("BATCHDATA_API_KEY")
TRUSTEDFORM_API_KEY = os.environ.get("TRUSTEDFORM_API_KEY")  # Enables Fraud & Behavioral pillar TF data
LAMBDA_API_URL = os.environ.get("LAMBDA_API_URL")  # e.g. https://abc123.execute-api.us-east-1.amazonaws.com/Prod/validate

# Scoring modes (priority: Lambda > Direct APIs > Demo)
if LAMBDA_API_URL:
    SCORING_MODE = "lambda"
    DEMO_MODE = False
elif TRESTLE_API_KEY and BATCHDATA_API_KEY:
    SCORING_MODE = "direct"
    DEMO_MODE = False
else:
    SCORING_MODE = "demo"
    DEMO_MODE = True

MAX_LEADS = 10
PROSPECTS = {}  # In-memory store: token -> prospect data

TIER_THRESHOLDS = [("Gold", 75), ("Silver", 53), ("Bronze", 25)]

# Column auto-detection aliases
FIELD_ALIASES = {
    "first_name": ["first_name", "firstname", "first", "fname", "given_name", "givenname"],
    "last_name": ["last_name", "lastname", "last", "lname", "surname", "family_name", "familyname"],
    "email": ["email", "email_address", "emailaddress", "e-mail", "e_mail"],
    "phone": ["phone", "phone_number", "phonenumber", "telephone", "tel", "mobile", "cell", "phone1"],
    "address": ["address", "street", "street_address", "address1", "address_line_1", "streetaddress", "addr"],
    "city": ["city", "town"],
    "state": ["state", "st", "state_code", "province", "region"],
    "zip": ["zip", "zipcode", "zip_code", "postal", "postal_code", "postalcode"],
    "trustedform_url": ["trustedform_url", "trustedform", "trusted_form", "trusted_form_url", "tf_url", "xxTrustedFormCertUrl", "xxtrustedformcerturl", "cert_url", "trusted_form_cert_id", "trustedform_cert_id", "trustedform_cert_url", "trusted_form_cert_url", "tf_cert_url", "tf_cert_id"],
}

# ============================================================
# SCORING CONFIG — Per-Vertical (Trestle + BatchData + TrustedForm)
# ============================================================

# Field score definitions — 22 fields across 5 pillars
# Sources: Trestle (contactability + identity + fraud), BatchData (identity + fraud + property),
#          TrustedForm (fraud + behavioral). Cross-API intermingling is intentional.
FIELD_SCORES = {
    # ═══════════════════════════════════════════════════
    # A. CONTACTABILITY — Can we reach this person?
    # Sources: Trestle phone + email
    # ═══════════════════════════════════════════════════
    "trestle.phone.is_valid": {
        "pillar": "contactability",
        "values": {"true": 40, "false": "HARD_KILL"},
        "null_penalty": -20,
        "max_points": 40,
    },
    "trestle.phone.contact_grade": {
        "pillar": "contactability",
        "values": {"A": 120, "B": 90, "C": 50, "D": 20, "F": -40},
        "null_penalty": -15,
        "max_points": 120,
    },
    "trestle.phone.activity_score": {
        "pillar": "contactability",
        "ranges": [
            (80, 100, 60), (60, 79, 40), (40, 59, 20), (20, 39, -20), (0, 19, -40),
        ],
        "null_penalty": -10,
        "max_points": 60,
    },
    "trestle.phone.line_type": {
        "pillar": "contactability",
        "values": {
            "Mobile": 60, "Landline": 25, "FixedVOIP": -10,
            "NonFixedVOIP": -50,
        },
        "null_penalty": -10,
        "max_points": 60,
    },
    "trestle.email.is_valid": {
        "pillar": "contactability",
        "values": {"true": 20, "false": -10},
        "null_penalty": 0,
        "max_points": 20,
    },
    "batchdata.address_valid": {
        "pillar": "contactability",
        "values": {True: 20, False: -15, "true": 20, "false": -15},
        "null_penalty": 0,
        "max_points": 20,
    },
    "batchdata.mailing_vacant": {
        "pillar": "contactability",
        "values": {True: -25, False: 10, "true": -25, "false": 10},
        "null_penalty": 0,
        "max_points": 10,
    },

    # ═══════════════════════════════════════════════════
    # B. IDENTITY — Is this person who they say they are?
    # Sources: Trestle name matches + BatchData owner status
    # ═══════════════════════════════════════════════════
    "trestle.phone.name_match": {
        "pillar": "identity",
        "values": {"true": 60, "false": -40},
        "null_penalty": -10,
        "max_points": 60,
    },
    "trestle.email.name_match": {
        "pillar": "identity",
        "values": {"true": 30, "false": -15},
        "null_penalty": 0,
        "max_points": 30,
    },
    "trestle.address.name_match": {
        "pillar": "identity",
        "values": {"true": 50, "false": -30},
        "null_penalty": -10,
        "max_points": 50,
    },
    "trestle.address.is_valid": {
        "pillar": "identity",
        "values": {"true": 30, "false": -20},
        "null_penalty": 0,
        "max_points": 30,
    },
    "batchdata.owner_occupied": {
        "pillar": "identity",
        "values": {
            "confirmed_owner": 40, "probable_owner": 20,
            "probable_renter": -15, "confirmed_renter": -30,
        },
        "null_penalty": -10,
        "max_points": 40,
    },
    "batchdata.bd_homeowner": {
        "pillar": "identity",
        "values": {True: 15, False: -5, "true": 15, "false": -5},
        "null_penalty": 0,
        "max_points": 15,
    },

    # ═══════════════════════════════════════════════════
    # C. FRAUD & LEGAL — Is this lead legitimate?
    # Sources: Trestle litigator + TrustedForm form + BatchData flags
    # ═══════════════════════════════════════════════════
    "trestle.litigator_risk": {
        "pillar": "fraud_legal",
        "values": {"true": -60, "false": 20},
        "null_penalty": 0,
        "max_points": 20,
    },
    "trustedform.form_input_method": {
        "pillar": "fraud_legal",
        "values": {
            "typing_only": 50, "typing_autofill": 40,
            "autofill_only": 15, "typing_paste": -30,
            "paste_only": -50, "pre-populated_only": "HARD_KILL",
            "empty": -40,
        },
        "null_penalty": 0,
        "max_points": 50,
    },
    "batchdata.corporate_owned": {
        "pillar": "fraud_legal",
        "values": {True: -20, False: 10, "true": -20, "false": 10},
        "null_penalty": 0,
        "max_points": 10,
    },
    "batchdata.inherited": {
        "pillar": "fraud_legal",
        "values": {True: -15, False: 5, "true": -15, "false": 5},
        "null_penalty": 0,
        "max_points": 5,
    },

    # ═══════════════════════════════════════════════════
    # D. BEHAVIORAL — Lead intent & behavior signals
    # Sources: TrustedForm timing + BatchData propensity/demographics
    # ═══════════════════════════════════════════════════
    "trustedform.age_seconds": {
        "pillar": "behavioral",
        "ranges": [
            (0, 299, 50), (300, 3599, 25), (3600, 86399, -20),
            (86400, 999999999, -60),
        ],
        "null_penalty": 0,
        "max_points": 50,
    },
    "trustedform.confirmed_owner": {
        "pillar": "behavioral",
        "values": {
            "verified": 40, "named_account": 20,
            "no_verified_account": -10,
        },
        "null_penalty": 0,
        "max_points": 40,
    },
    "batchdata.sale_propensity": {
        "pillar": "behavioral",
        "ranges": [
            (0, 30, 25), (30, 60, 10), (60, 80, -5), (80, 100, -20),
        ],
        "null_penalty": 0,
        "max_points": 25,
    },
    "batchdata.absentee_owner": {
        "pillar": "behavioral",
        "values": {True: -15, False: 10, "true": -15, "false": 10},
        "null_penalty": 0,
        "max_points": 10,
    },

    # ═══════════════════════════════════════════════════
    # E. PROPERTY & FINANCIAL — Qualified property?
    # Sources: BatchData property + valuation + quickLists + Trestle address validation
    # ═══════════════════════════════════════════════════
    "trestle.address.property_confirmed": {
        "pillar": "property_financial",
        "values": {"true": 15, "false": -10},
        "null_penalty": 0,
        "max_points": 15,
    },
    "batchdata.property_type": {
        "pillar": "property_financial",
        "values": {
            "Single Family Residential": 40, "Residential": 30,
            "Townhouse": 25, "Condominium": 15,
            "Multi-Family": -10, "Commercial": -20,
            "Mobile/Manufactured": -40,
        },
        "null_penalty": -10,
        "max_points": 40,
    },
    "batchdata.estimated_value": {
        "pillar": "property_financial",
        "ranges": [
            (600000, 9999999, 50), (400000, 599999, 40),
            (250000, 399999, 30), (150000, 249999, 15),
            (100000, 149999, 0), (0, 99999, -20),
        ],
        "null_penalty": -5,
        "max_points": 50,
    },
    "batchdata.year_built": {
        "pillar": "property_financial",
        "ranges": [
            (0, 1989, 25), (1990, 2004, 20), (2005, 2015, 10), (2016, 2100, 5),
        ],
        "null_penalty": 0,
        "max_points": 25,
    },
    "batchdata.free_and_clear": {
        "pillar": "property_financial",
        "values": {True: 15, False: 5, "true": 15, "false": 5},
        "null_penalty": 0,
        "max_points": 15,
    },
    "batchdata.high_equity": {
        "pillar": "property_financial",
        "values": {True: 20, False: -10, "true": 20, "false": -10},
        "null_penalty": 0,
        "max_points": 20,
    },
    "batchdata.tax_lien": {
        "pillar": "property_financial",
        "values": {True: -30, False: 10, "true": -30, "false": 10},
        "null_penalty": 0,
        "max_points": 10,
    },
    "batchdata.equity_percent": {
        "pillar": "property_financial",
        "ranges": [
            (60, 100, 25), (40, 59, 15), (20, 39, 5), (0, 19, -10),
        ],
        "null_penalty": 0,
        "max_points": 25,
    },
    "batchdata.ltv": {
        "pillar": "property_financial",
        "ranges": [
            (0, 60, 20), (60, 80, 10), (80, 90, 0), (90, 200, -20),
        ],
        "null_penalty": 0,
        "max_points": 20,
    },
}

# Per-vertical configs — weights from backtest dispo data (contactability is #1 predictor)
VERTICAL_CONFIGS = {
    # Validated verticals (solar: 1,093 leads, roofing: 68, windows: 118)
    "Solar":           {"pillar_weights": {"contactability": 0.30, "identity": 0.20, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": False, "hard_kill_mobile": True},
    "Roofing":         {"pillar_weights": {"contactability": 0.30, "identity": 0.25, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.20}, "hard_kill_renter": True,  "hard_kill_mobile": True},
    "Windows":         {"pillar_weights": {"contactability": 0.30, "identity": 0.20, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    # Financial verticals — identity weighs more, renter/mobile not hard kills
    "Insurance":       {"pillar_weights": {"contactability": 0.25, "identity": 0.30, "fraud_legal": 0.15, "behavioral": 0.15, "property_financial": 0.15}, "hard_kill_renter": False, "hard_kill_mobile": False},
    "Mortgage":        {"pillar_weights": {"contactability": 0.20, "identity": 0.35, "fraud_legal": 0.15, "behavioral": 0.15, "property_financial": 0.15}, "hard_kill_renter": False, "hard_kill_mobile": False},
    # Unvalidated — nearest validated vertical, conservative defaults
    "HVAC":            {"pillar_weights": {"contactability": 0.30, "identity": 0.20, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Siding":          {"pillar_weights": {"contactability": 0.30, "identity": 0.25, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.20}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Gutters":         {"pillar_weights": {"contactability": 0.35, "identity": 0.15, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Painting":        {"pillar_weights": {"contactability": 0.35, "identity": 0.15, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Plumbing":        {"pillar_weights": {"contactability": 0.35, "identity": 0.15, "fraud_legal": 0.10, "behavioral": 0.20, "property_financial": 0.20}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Flooring":        {"pillar_weights": {"contactability": 0.30, "identity": 0.20, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Bath Remodel":    {"pillar_weights": {"contactability": 0.25, "identity": 0.25, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Kitchen Remodel": {"pillar_weights": {"contactability": 0.25, "identity": 0.25, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
}


# ============================================================
# API CLIENTS
# ============================================================

def call_trestle(lead):
    """Call Trestle Real Contact API. Returns normalized dict or None values on failure."""
    result = {
        "phone.is_valid": None, "phone.contact_grade": None, "phone.activity_score": None,
        "phone.line_type": None, "phone.name_match": None,
        "email.is_valid": None, "email.name_match": None,
        "address.name_match": None, "address.is_valid": None, "litigator_risk": None,
    }
    try:
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        params = {
            "phone": lead.get("phone", ""),
            "name": name,
            "email": lead.get("email", ""),
            "address.street_line_1": lead.get("address", ""),
            "address.city": lead.get("city", ""),
            "address.state_code": lead.get("state", ""),
            "address.postal_code": lead.get("zip", ""),
        }
        url = f"https://api.trestleiq.com/1.1/real_contact?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"x-api-key": TRESTLE_API_KEY})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        # Extract phone fields
        phone = data.get("phone", {}) if isinstance(data.get("phone"), dict) else {}
        result["phone.is_valid"] = str(phone.get("is_valid")).lower() if phone.get("is_valid") is not None else None
        result["phone.contact_grade"] = phone.get("contact_grade")
        result["phone.activity_score"] = phone.get("activity_score")
        result["phone.line_type"] = phone.get("line_type")
        result["phone.name_match"] = str(phone.get("name_match")).lower() if phone.get("name_match") is not None else None

        # Extract email fields
        email_data = data.get("email", {}) if isinstance(data.get("email"), dict) else {}
        result["email.is_valid"] = str(email_data.get("is_valid")).lower() if email_data.get("is_valid") is not None else None
        result["email.name_match"] = str(email_data.get("name_match")).lower() if email_data.get("name_match") is not None else None

        # Extract address fields
        address = data.get("address", {}) if isinstance(data.get("address"), dict) else {}
        result["address.name_match"] = str(address.get("name_match")).lower() if address.get("name_match") is not None else None
        is_valid = address.get("is_valid")
        result["address.is_valid"] = str(is_valid).lower() if is_valid is not None else None

        # Litigator risk from add_ons
        add_ons = data.get("add_ons", {}) or {}
        litigator = add_ons.get("litigator_checks", {}) or {}
        is_lit = litigator.get("phone.is_litigator_risk")
        result["litigator_risk"] = str(is_lit).lower() if is_lit is not None else None

    except Exception as e:
        print(f"  Trestle API error: {e}")

    return result


def call_batchdata(lead):
    """Call BatchData Property Lookup. Returns normalized dict or None values on failure."""
    result = {
        "owner_occupied": None, "property_type": None,
        "estimated_value": None, "year_built": None,
        "free_and_clear": None, "high_equity": None, "tax_lien": None,
        "corporate_owned": None, "inherited": None, "absentee_owner": None,
        "mailing_vacant": None, "address_valid": None,
        "equity_percent": None, "ltv": None,
        "sale_propensity": None, "owner_name": None,
        "bd_age": None, "bd_homeowner": None,
    }
    try:
        body = json.dumps({"requests": [{"address": {
            "street": lead.get("address", ""),
            "city": lead.get("city", ""),
            "state": lead.get("state", ""),
            "zip": lead.get("zip", ""),
        }}]}).encode()

        req = urllib.request.Request(
            "https://api.batchdata.com/api/v1/property/lookup/all-attributes",
            data=body,
            headers={
                "Authorization": f"Bearer {BATCHDATA_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        props = (data.get("results", {}).get("properties") or [None])[0]
        if not props:
            return result

        # Owner status — use quickLists.ownerOccupied (matches production extraction)
        owner = props.get("owner", {}) or {}
        quick = props.get("quickLists", {}) or {}
        occupied = quick.get("ownerOccupied", owner.get("ownerOccupied"))
        if occupied is True or str(occupied).lower() in ("yes", "true", "y"):
            result["owner_occupied"] = "confirmed_owner"
        elif occupied is False or str(occupied).lower() in ("no", "false", "n"):
            result["owner_occupied"] = "confirmed_renter"
        else:
            result["owner_occupied"] = "probable_owner"

        # Property type
        general = props.get("general", {}) or {}
        ptype = general.get("propertyTypeDetail") or general.get("propertyTypeCategory", "")
        land_use = general.get("standardizedLandUseCode", "")
        if "Single Family" in str(ptype):
            result["property_type"] = "Single Family Residential"
        elif "Residential" in str(ptype) and "Multi" not in str(ptype):
            result["property_type"] = "Residential"
        elif "Condo" in str(ptype):
            result["property_type"] = "Condominium"
        elif "Town" in str(ptype):
            result["property_type"] = "Townhouse"
        elif "Commercial" in str(ptype):
            result["property_type"] = "Commercial"
        elif str(land_use) in ("R43", "R50"):
            result["property_type"] = "Mobile/Manufactured"
        elif "Multi" in str(ptype):
            result["property_type"] = "Multi-Family"
        else:
            result["property_type"] = str(ptype) if ptype else None

        # Value
        val = props.get("valuation", {}) or {}
        result["estimated_value"] = val.get("estimatedValue")

        # Year built
        building = props.get("building", {}) or {}
        result["year_built"] = building.get("yearBuilt")

        # QuickLists flags
        result["free_and_clear"] = quick.get("freeAndClear")
        result["high_equity"] = quick.get("highEquity")
        result["tax_lien"] = quick.get("taxDefault")
        result["corporate_owned"] = quick.get("corporateOwned")
        result["inherited"] = quick.get("inherited")
        result["absentee_owner"] = quick.get("absenteeOwner")
        result["mailing_vacant"] = quick.get("mailingVacant")
        result["address_valid"] = True  # If BatchData returned property data, address is valid

        # Owner name (for display in identity pillar)
        owner_names = []
        for o in (owner.get("owners") or owner.get("names") or []):
            n = o.get("fullName") or o.get("name", "")
            if n:
                owner_names.append(n)
        if not owner_names and owner.get("fullName"):
            owner_names = [owner["fullName"]]
        result["owner_name"] = "; ".join(owner_names) if owner_names else None

        # Equity & LTV
        result["equity_percent"] = val.get("equityPercent")
        lien = props.get("openLien", {}) or {}
        lien_balance = lien.get("totalOpenLienBalance")
        est_val = result["estimated_value"]
        if lien_balance and est_val and est_val > 0:
            result["ltv"] = round(lien_balance / est_val * 100, 1)

        # Intel
        intel = props.get("intel", {}) or {}
        result["sale_propensity"] = intel.get("salePropensity")

        # Demographics
        demo = props.get("demographics", {}) or {}
        result["bd_age"] = demo.get("age")
        result["bd_homeowner"] = demo.get("homeowner")

    except Exception as e:
        print(f"  BatchData API error: {e}")

    return result


# ============================================================
# TRUSTEDFORM API
# ============================================================

def call_trustedform(cert_url):
    """Call TrustedForm Insights API to get form behavior data.
    Returns dict with form_input_method, age_seconds, confirmed_owner."""
    import base64
    result = {"form_input_method": None, "age_seconds": None, "confirmed_owner": None}

    if not cert_url or not TRUSTEDFORM_API_KEY:
        return result

    try:
        # Extract cert ID from URL
        cert_id = cert_url.rstrip("/").split("/")[-1]
        if not cert_id or len(cert_id) < 10:
            return result

        url = f"https://cert.trustedform.com/{cert_id}"
        auth = base64.b64encode(f"API:{TRUSTEDFORM_API_KEY}".encode()).decode()

        body = json.dumps({
            "scan": ["insights"],
            "insights": {
                "properties": ["form_input_method", "age_seconds", "confirmed_owner"]
            }
        }).encode()

        req = urllib.request.Request(url, data=body, headers={
            "Authorization": f"Basic {auth}",
            "Api-Version": "4.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }, method="POST")

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        props = (data.get("insights", {}).get("properties") or {})

        # Normalize form_input_method (array → category)
        methods = props.get("form_input_method", [])
        if isinstance(methods, list) and methods:
            has_typing = "typing" in methods
            has_autofill = "autofill" in methods
            has_paste = "paste" in methods
            has_prepop = "pre-populated" in methods
            if has_prepop and not has_typing:
                result["form_input_method"] = "pre-populated_only"
            elif has_paste and not has_typing and not has_autofill:
                result["form_input_method"] = "paste_only"
            elif has_typing and has_paste:
                result["form_input_method"] = "typing_paste"
            elif has_typing and has_autofill:
                result["form_input_method"] = "typing_autofill"
            elif has_autofill and not has_typing:
                result["form_input_method"] = "autofill_only"
            elif has_typing:
                result["form_input_method"] = "typing_only"
            else:
                result["form_input_method"] = "empty"
        else:
            result["form_input_method"] = "empty"

        result["age_seconds"] = props.get("age_seconds")

        # Normalize confirmed_owner
        raw_owner = props.get("confirmed_owner", "")
        if isinstance(raw_owner, str):
            lower = raw_owner.lower()
            if "verified owner" in lower:
                result["confirmed_owner"] = "verified"
            elif "named account" in lower:
                result["confirmed_owner"] = "named_account"
            elif "no verified" in lower:
                result["confirmed_owner"] = "no_verified_account"

    except Exception as e:
        print(f"  TrustedForm API error: {e}")

    return result


# ============================================================
# SCORING ENGINE
# ============================================================

def evaluate_field(value, field_config):
    """Evaluate a single field against its scoring config. Returns point value or 'HARD_KILL'."""
    if value is None:
        return field_config.get("null_penalty", 0)

    # Value-based matching
    if "values" in field_config:
        # Try exact match first
        if value in field_config["values"]:
            return field_config["values"][value]
        # Try string conversion
        str_val = str(value).lower()
        for k, v in field_config["values"].items():
            if str(k).lower() == str_val:
                return v
        return field_config.get("null_penalty", 0)

    # Range-based matching
    if "ranges" in field_config:
        try:
            num_val = float(value)
            for low, high, points in field_config["ranges"]:
                if low <= num_val <= high:
                    return points
        except (ValueError, TypeError):
            pass
        return field_config.get("null_penalty", 0)

    return 0


def get_api_value(field_key, trestle_data, batchdata_data, trustedform_data=None):
    """Extract a value from API results by field key."""
    # Aliases — same underlying data, different pillar context
    FIELD_ALIASES_INTERNAL = {
        "trestle.address.property_confirmed": "trestle.address.is_valid",
    }
    resolved_key = FIELD_ALIASES_INTERNAL.get(field_key, field_key)
    if resolved_key.startswith("trestle."):
        key = resolved_key.replace("trestle.", "")
        return trestle_data.get(key)
    elif field_key.startswith("batchdata."):
        key = field_key.replace("batchdata.", "")
        return batchdata_data.get(key)
    elif field_key.startswith("trustedform."):
        if trustedform_data is None:
            return None
        key = field_key.replace("trustedform.", "")
        return trustedform_data.get(key)
    return None


def check_hard_kills(trestle_data, batchdata_data, vertical):
    """Check hard-kill conditions. Returns (is_killed, reason) tuple."""
    config = VERTICAL_CONFIGS[vertical]

    # Phone Grade F
    grade = trestle_data.get("phone.contact_grade")
    if grade == "F":
        return True, "Phone Grade F"

    # Activity < 30
    activity = trestle_data.get("phone.activity_score")
    if activity is not None:
        try:
            if float(activity) < 30:
                return True, "Phone Activity Score Below 30"
        except (ValueError, TypeError):
            pass

    # Commercial property
    ptype = batchdata_data.get("property_type")
    if ptype == "Commercial":
        return True, "Commercial Property"

    # Confirmed renter (home services only)
    if config["hard_kill_renter"]:
        owner = batchdata_data.get("owner_occupied")
        if owner == "confirmed_renter":
            return True, "Confirmed Renter"

    # Mobile/Manufactured (solar/roofing only)
    if config["hard_kill_mobile"]:
        if ptype == "Mobile/Manufactured":
            return True, "Mobile/Manufactured Home"

    # NonFixedVOIP + Grade F combo (from v4.1 cross-vertical learnings)
    line_type = trestle_data.get("phone.line_type")
    if line_type == "NonFixedVOIP" and grade == "F":
        return True, "NonFixedVOIP + Grade F"

    return False, None


REASON_LABELS = {
    "trestle.phone.is_valid": ("Phone Valid", {"true": "Yes", "false": "No"}),
    "trestle.phone.contact_grade": ("Phone Grade", {"A": "A (Excellent)", "B": "B (Good)", "C": "C (Fair)", "D": "D (Poor)", "F": "F (Very Poor)"}),
    "trestle.phone.activity_score": ("Phone Activity", {}),
    "trestle.phone.line_type": ("Line Type", {}),
    "trestle.phone.name_match": ("Phone Name Match", {"true": "Yes", "false": "No"}),
    "trestle.email.is_valid": ("Email Valid", {"true": "Yes", "false": "No"}),
    "trestle.email.name_match": ("Email Name Match", {"true": "Yes", "false": "No"}),
    "trestle.address.name_match": ("Address Name Match", {"true": "Yes", "false": "No"}),
    "trestle.address.is_valid": ("Address Valid", {"true": "Yes", "false": "No"}),
    "batchdata.bd_homeowner": ("Homeowner", {True: "Yes", False: "No", "true": "Yes", "false": "No"}),
    "trestle.litigator_risk": ("Litigator Risk", {"true": "Yes ⚠️", "false": "No"}),
    "batchdata.address_valid": ("Address Verified", {True: "Yes", False: "No", "true": "Yes", "false": "No"}),
    "batchdata.mailing_vacant": ("Mailing Vacant", {True: "Yes ⚠️", False: "No", "true": "Yes ⚠️", "false": "No"}),
    "batchdata.owner_occupied": ("Ownership", {"confirmed_owner": "Owner", "probable_owner": "Probable Owner", "probable_renter": "Probable Renter", "confirmed_renter": "Renter"}),
    "batchdata.property_type": ("Property Type", {}),
    "batchdata.estimated_value": ("Property Value", {}),
    "batchdata.year_built": ("Year Built", {}),
    "batchdata.free_and_clear": ("Free & Clear", {True: "Yes", False: "No", "true": "Yes", "false": "No"}),
    "batchdata.high_equity": ("High Equity", {True: "Yes", False: "No", "true": "Yes", "false": "No"}),
    "batchdata.tax_lien": ("Tax Lien", {True: "Yes ⚠️", False: "No", "true": "Yes ⚠️", "false": "No"}),
    "batchdata.sale_propensity": ("Sale Propensity", {}),
    "batchdata.corporate_owned": ("Corporate Owned", {True: "Yes ⚠️", False: "No", "true": "Yes ⚠️", "false": "No"}),
    "batchdata.inherited": ("Inherited", {True: "Yes", False: "No", "true": "Yes", "false": "No"}),
    "trustedform.form_input_method": ("Form Input", {}),
    "trustedform.age_seconds": ("Lead Age (seconds)", {}),
    "trustedform.confirmed_owner": ("TF Verified Owner", {"verified": "Verified ✓", "named_account": "Named Account", "no_verified_account": "Not Verified"}),
    "batchdata.absentee_owner": ("Absentee Owner", {True: "Yes", False: "No", "true": "Yes", "false": "No"}),
    "batchdata.equity_percent": ("Equity %", {}),
    "batchdata.ltv": ("Loan-to-Value", {}),
    "trestle.address.property_confirmed": ("Property Confirmed", {"true": "Yes", "false": "No"}),
}


def score_lead(lead_data, vertical, trestle_data, batchdata_data, trustedform_data=None):
    """Score a single lead. Returns full result dict.

    Hard-killed leads still get full pillar scoring — the hard kill only
    overrides the final tier (Reject) and score (0). This way the UI always
    shows what we actually know about the lead.
    """
    config = VERTICAL_CONFIGS[vertical]
    weights = config["pillar_weights"]

    # Check hard kills (but don't return early — still score pillars)
    killed, kill_reason = check_hard_kills(trestle_data, batchdata_data, vertical)

    # Score each field, accumulate by pillar
    pillar_raw = {p: 0 for p in weights}
    pillar_max = {p: 0 for p in weights}
    pillar_has_data = {p: False for p in weights}  # Track if we got real data for each pillar
    reasons = []

    for field_key, field_config in FIELD_SCORES.items():
        pillar = field_config["pillar"]
        if pillar not in weights:
            continue

        value = get_api_value(field_key, trestle_data, batchdata_data, trustedform_data)

        # Track whether we got real (non-null) data for this pillar
        if value is not None:
            pillar_has_data[pillar] = True

        # Handle vertical-specific overrides
        if field_key == "batchdata.owner_occupied" and value == "confirmed_renter":
            if config["hard_kill_renter"]:
                points = -30  # Score it as strong negative instead of skipping
            else:
                points = -20  # Not a hard kill for financial verticals
        elif field_key == "batchdata.property_type" and value == "Mobile/Manufactured":
            if config["hard_kill_mobile"]:
                points = -40  # Score it as strong negative instead of skipping
            else:
                points = -10
        else:
            points = evaluate_field(value, field_config)

        # HARD_KILL from evaluate_field — still score the field as a strong negative
        if points == "HARD_KILL":
            points = -1 * field_config["max_points"]  # Max negative = negative of max_points

        pillar_raw[pillar] += points
        # Only count max_points for fields where we have real data.
        # Null fields (missing API source) shouldn't inflate the denominator —
        # e.g. missing TrustedForm shouldn't drag Behavioral from 100% to 28%.
        if value is not None:
            pillar_max[pillar] += field_config["max_points"]

        # Build reason codes for significant signals
        if abs(points) >= 15:
            label_info = REASON_LABELS.get(field_key, (field_key, {}))
            display_val = label_info[1].get(value, str(value) if value is not None else "N/A")
            if field_key == "batchdata.estimated_value" and value:
                display_val = f"${int(value):,}"
            elif field_key == "batchdata.estimated_equity" and value:
                display_val = f"${int(value):,}"
            reasons.append({
                "label": f"{label_info[0]}: {display_val}",
                "positive": points > 0,
                "impact": abs(points),
            })

    # Normalize pillars to 0-100, apply weights
    # Floor logic: no data = 50% (neutral), bad data = min 5% (never shows empty)
    pillar_breakdown = {}
    weighted_total = 0
    for pillar, weight in weights.items():
        raw = pillar_raw[pillar]
        max_possible = pillar_max[pillar]
        if not pillar_has_data[pillar]:
            # No real data for this pillar — show neutral 50%
            pct = 50
        elif max_possible > 0:
            pct = max(5, min(100, (raw / max_possible) * 100))  # Floor of 5%
        else:
            pct = 50
        pillar_breakdown[pillar] = {"score": round(pct), "weight": weight}
        weighted_total += pct * weight

    final_score = max(5, min(100, round(weighted_total)))  # Floor of 5 — never show 0

    # Assign tier
    tier = "Reject"
    for tier_name, threshold in TIER_THRESHOLDS:
        if final_score >= threshold:
            tier = tier_name
            break

    # Hard kill override — keep pillar scores but force Reject tier
    if killed:
        tier = "Reject"
        final_score = 0

    # Sort reasons by impact, take top 5
    reasons.sort(key=lambda r: r["impact"], reverse=True)

    # If hard-killed, make sure the kill reason is the first reason shown
    if killed:
        kill_reason_entry = {"label": f"⛔ {kill_reason}", "positive": False}
        reason_list = [kill_reason_entry] + [{"label": r["label"], "positive": r["positive"]} for r in reasons[:4]]
    else:
        reason_list = [{"label": r["label"], "positive": r["positive"]} for r in reasons[:5]]

    return {
        "score": final_score, "tier": tier, "hard_kill": killed,
        "hard_kill_reason": kill_reason if killed else None,
        "pillars": pillar_breakdown,
        "reason_codes": reason_list,
    }


# ============================================================
# DEMO MODE — Realistic simulated scores
# ============================================================

def map_lambda_enrichment(enrichment_data):
    """Map Lambda's nested enrichment_data into flat dicts for the local pillar scorer.

    Lambda returns: enrichment_data.trestle.phone_contact_grade
    Local scorer expects: trestle_data["phone.contact_grade"]
    """
    trestle_raw = enrichment_data.get("trestle", {}) or {}
    batchdata_raw = enrichment_data.get("batchdata", {}) or {}
    trustedform_raw = enrichment_data.get("trustedform", {}) or {}

    # Trestle: Lambda uses underscores (phone_contact_grade), we use dots (phone.contact_grade)
    trestle_data = {}
    trestle_field_map = {
        "phone_is_valid": "phone.is_valid",
        "phone_contact_grade": "phone.contact_grade",
        "phone_activity_score": "phone.activity_score",
        "phone_line_type": "phone.line_type",
        "phone_name_match": "phone.name_match",
        "email_is_valid": "email.is_valid",
        "email_name_match": "email.name_match",
        "address_name_match": "address.name_match",
        "address_is_valid": "address.is_valid",
        "litigator_risk": "litigator_risk",
    }
    for lambda_key, local_key in trestle_field_map.items():
        val = trestle_raw.get(lambda_key)
        # Convert booleans to lowercase strings to match FIELD_SCORES expectations
        if isinstance(val, bool):
            trestle_data[local_key] = str(val).lower()
        else:
            trestle_data[local_key] = val

    # BatchData: keys are already flat and match
    batchdata_data = {}
    for key, val in batchdata_raw.items():
        batchdata_data[key] = val

    # TrustedForm: keys already match
    trustedform_data = {}
    for key, val in trustedform_raw.items():
        trustedform_data[key] = val

    return trestle_data, batchdata_data, trustedform_data


def score_via_lambda(lead, vertical):
    """Score a lead by calling the production Lambda via API Gateway.
    Uses Lambda's LLM score/tier + computes local pillar breakdown from enrichment data."""
    # Map vertical display name to Lambda's lowercase format
    vertical_map = {
        "Solar": "solar", "Roofing": "roofing", "Windows": "windows",
        "HVAC": "hvac", "Siding": "siding", "Gutters": "gutters",
        "Painting": "painting", "Plumbing": "plumbing",
        "Bath Remodel": "bathroom_remodel", "Kitchen Remodel": "kitchen_remodel",
        "Flooring": "flooring", "Insurance": "insurance", "Mortgage": "mortgage",
    }
    lambda_vertical = vertical_map.get(vertical, vertical.lower().replace(" ", "_"))

    payload = json.dumps({
        "lead_id": f"s10l-{uuid.uuid4().hex[:8]}",
        "vertical": lambda_vertical,
        "publisher_id": "score_10_leads",
        "publisher_name": "Score 10 Leads Tool",
        "contact": {
            "first_name": lead.get("first_name", ""),
            "last_name": lead.get("last_name", ""),
            "phone": lead.get("phone", ""),
            "email": lead.get("email", ""),
            "address": lead.get("address", ""),
            "city": lead.get("city", ""),
            "state": lead.get("state", ""),
            "zip": lead.get("zip", ""),
        },
        # NOTE: Do NOT send trustedform_cert_url to Lambda.
        # CSV-uploaded leads have stale certs — the Lambda's LLM would penalize
        # the score for old age_seconds. We call TF directly from the app instead
        # (with age_seconds stripped) just for pillar display.
        "trustedform_cert_url": "",
    }).encode()

    try:
        req = urllib.request.Request(
            LAMBDA_API_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode())

        # Parse API Gateway response (body is JSON string)
        result = json.loads(raw["body"]) if isinstance(raw.get("body"), str) else raw

        # Build reason codes from LLM response
        reason_codes = []
        is_hard_kill = result.get("hard_kill", False)
        kill_reason = result.get("hard_kill_reason")

        if is_hard_kill and kill_reason:
            reason_codes.append({"label": f"⛔ {kill_reason}", "positive": False})

        if result.get("llm_response"):
            for r in (result["llm_response"].get("reasons") or []):
                reason_codes.append({"label": r, "positive": True})
            for c in (result["llm_response"].get("concerns") or []):
                reason_codes.append({"label": c, "positive": False})

        # SCORING ARCHITECTURE:
        # - Headline score/tier = Lambda's Sonnet LLM (Trestle + BatchData, no TF)
        # - Pillar bars = local scorer (Trestle + BatchData from Lambda + TF direct call)
        # TF cert URL is NOT sent to Lambda — stale age_seconds would penalize
        # the Sonnet score. TF is called separately for pillar display only.
        enrichment = result.get("enrichment_data", {})
        trustedform_data = {}
        if enrichment:
            trestle_data, batchdata_data, trustedform_data = map_lambda_enrichment(enrichment)

            # Call TrustedForm directly for pillar bars
            cert_url = lead.get("trustedform_url", "").strip()
            if cert_url and TRUSTEDFORM_API_KEY:
                tf_direct = call_trustedform(cert_url)
                if any(v is not None for v in tf_direct.values()):
                    trustedform_data = tf_direct
                    print(f"    TF direct: form={tf_direct.get('form_input_method')}, owner={tf_direct.get('confirmed_owner')}")

            # Strip age_seconds — CSV leads aren't real-time
            if trustedform_data and "age_seconds" in trustedform_data:
                trustedform_data["age_seconds"] = None

            # Local pillar scorer — drives the 5 pillar bars only
            pillar_result = score_lead(lead, vertical, trestle_data, batchdata_data, trustedform_data)
            pillar_breakdown = pillar_result["pillars"]
        else:
            # No enrichment data — show 50% default on all pillars
            config = VERTICAL_CONFIGS.get(vertical, VERTICAL_CONFIGS["Solar"])
            weights = config["pillar_weights"]
            pillar_breakdown = {p: {"score": 50, "weight": w} for p, w in weights.items()}

        # Track whether TF data was available for the warning banner
        has_tf_data = any(v is not None for v in trustedform_data.values()) if trustedform_data else False

        return {
            "score": result.get("score", 0),       # Lambda Sonnet score
            "tier": result.get("tier", "Reject"),   # Lambda Sonnet tier
            "hard_kill": is_hard_kill,
            "hard_kill_reason": kill_reason,
            "pillars": pillar_breakdown,            # Local scorer (includes TF)
            "reason_codes": reason_codes[:5],
            "has_trustedform": has_tf_data,
        }
    except Exception as e:
        print(f"  Lambda API error: {e}")
        # Fall back to demo scores on error
        return generate_demo_scores(lead, vertical)


def generate_demo_scores(lead, vertical):
    """Generate deterministic fake scores seeded by lead data. Shows all 5 pillars."""
    seed_str = f"{lead.get('first_name','')}{lead.get('last_name','')}{lead.get('address','')}{lead.get('zip','')}"
    seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    import random as rng
    rng.seed(seed)

    config = VERTICAL_CONFIGS[vertical]
    weights = config["pillar_weights"]

    # ~18% chance of hard kill
    if rng.random() < 0.18:
        kill_reasons = ["Phone Grade F", "Phone Activity Score Below 30", "Commercial Property"]
        if config["hard_kill_renter"]:
            kill_reasons.append("Confirmed Renter")
        if config["hard_kill_mobile"]:
            kill_reasons.append("Mobile/Manufactured Home")
        kill = rng.choice(kill_reasons)
        return {
            "score": 0, "tier": "Reject", "hard_kill": True,
            "hard_kill_reason": kill,
            "pillars": {p: {"score": rng.randint(5, 30), "weight": w} for p, w in weights.items()},
            "reason_codes": [{"label": kill, "positive": False}],
        }

    # Generate all 5 pillar scores with realistic distribution
    contact = max(0, min(100, round(rng.gauss(62, 18))))
    identity = max(0, min(100, round(rng.gauss(58, 20))))
    fraud = max(0, min(100, round(rng.gauss(70, 16))))
    behav = max(0, min(100, round(rng.gauss(65, 18))))
    prop_fin = max(0, min(100, round(rng.gauss(55, 22))))

    pillar_breakdown = {
        "contactability": {"score": contact, "weight": weights["contactability"]},
        "identity": {"score": identity, "weight": weights["identity"]},
        "fraud_legal": {"score": fraud, "weight": weights["fraud_legal"]},
        "behavioral": {"score": behav, "weight": weights["behavioral"]},
        "property_financial": {"score": prop_fin, "weight": weights["property_financial"]},
    }

    final = round(
        contact * weights["contactability"] +
        identity * weights["identity"] +
        fraud * weights["fraud_legal"] +
        behav * weights["behavioral"] +
        prop_fin * weights["property_financial"]
    )
    final = max(0, min(100, final))

    tier = "Reject"
    for tier_name, threshold in TIER_THRESHOLDS:
        if final >= threshold:
            tier = tier_name
            break

    # Generate plausible reason codes — use rng.sample() to avoid duplicates
    positive_reasons = [
        "Phone Grade: A (Excellent)", "Phone Grade: B (Good)",
        "Ownership: Owner Confirmed", "Property Value: $385,000",
        "Equity: $142,000", "Line Type: Mobile", "Email Valid: Yes",
        "Phone Activity: 82", "Year Built: 1998",
        "TrustedForm: Verified", "TCPA: Clear", "Form Time: 42s",
    ]
    negative_reasons = [
        "Phone Grade: D (Poor)", "Ownership: Probable Renter",
        "Property Value: $78,000", "Line Type: NonFixedVOIP",
        "Email Valid: No", "Phone Activity: 34", "LTV: 94%",
        "Lead Age: 3 days", "Bot Score: Elevated",
    ]
    n_pos = rng.randint(1, 3) if final >= 45 else rng.randint(0, 1)
    n_neg = rng.randint(0, 2) if final >= 45 else rng.randint(1, 3)
    pos_picks = rng.sample(positive_reasons, min(n_pos, len(positive_reasons)))
    neg_picks = rng.sample(negative_reasons, min(n_neg, len(negative_reasons)))

    reasons = [{"label": r, "positive": True} for r in pos_picks]
    reasons += [{"label": r, "positive": False} for r in neg_picks]

    return {
        "score": final, "tier": tier, "hard_kill": False,
        "hard_kill_reason": None, "pillars": pillar_breakdown,
        "reason_codes": reasons[:5],
    }


# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/")
def index():
    return render_template("index.html", demo_mode=DEMO_MODE)


@app.route("/api/submit-prospect", methods=["POST"])
def submit_prospect():
    """Gate form submission. Stores prospect info, returns session token."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    required = ["name", "company", "email", "phone", "vertical"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Missing required field: {field}"}), 400

    if data["vertical"] not in VERTICAL_CONFIGS:
        return jsonify({"error": f"Invalid vertical: {data['vertical']}"}), 400

    token = str(uuid.uuid4())
    PROSPECTS[token] = {
        "name": data["name"],
        "company": data["company"],
        "email": data["email"],
        "phone": data["phone"],
        "vertical": data["vertical"],
        "submitted_at": datetime.utcnow().isoformat(),
    }
    print(f"\n[PROSPECT] {data['name']} / {data['company']} / {data['email']} / {data['vertical']}")

    return jsonify({"token": token, "vertical": data["vertical"]})


@app.route("/api/parse-csv", methods=["POST"])
def parse_csv():
    """Parse uploaded CSV, auto-detect field mappings, return first 10 rows."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    token = request.form.get("token")
    if not token or token not in PROSPECTS:
        return jsonify({"error": "Invalid session"}), 401

    file = request.files["file"]
    content = file.read().decode("utf-8-sig")  # Handle BOM

    # Auto-detect dialect
    try:
        sample = content[:4096]
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    columns = reader.fieldnames or []

    # Read rows (cap at MAX_LEADS)
    rows = []
    for i, row in enumerate(reader):
        if i >= MAX_LEADS:
            break
        rows.append(dict(row))

    total_in_file = sum(1 for _ in csv.DictReader(io.StringIO(content), dialect=dialect))

    # Auto-detect mappings
    mappings = {}
    normalized_cols = {}
    for col in columns:
        norm = col.strip().lower().replace(" ", "_").replace("-", "_")
        normalized_cols[norm] = col

    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in normalized_cols:
                mappings[field] = normalized_cols[alias]
                break

    return jsonify({
        "columns": columns,
        "mappings": mappings,
        "rows": rows,
        "row_count": len(rows),
        "total_in_file": total_in_file,
        "truncated": total_in_file > MAX_LEADS,
    })


@app.route("/api/score-leads", methods=["POST"])
def score_leads():
    """Score up to 10 leads using Trestle + BatchData (or demo mode)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    token = data.get("token")
    if not token or token not in PROSPECTS:
        return jsonify({"error": "Invalid session"}), 401

    vertical = data.get("vertical") or PROSPECTS[token].get("vertical")
    mappings = data.get("mappings", {})
    rows = data.get("rows", [])[:MAX_LEADS]  # Server-side cap

    if not rows:
        return jsonify({"error": "No leads to score"}), 400

    results = []
    for i, row in enumerate(rows):
        # Map CSV columns to standard fields
        lead = {}
        for std_field, csv_col in mappings.items():
            lead[std_field] = row.get(csv_col, "").strip() if row.get(csv_col) else ""

        display_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip() or f"Lead {i+1}"
        print(f"  Scoring lead {i+1}/{len(rows)}: {display_name}")

        if SCORING_MODE == "lambda":
            result = score_via_lambda(lead, vertical)
            time.sleep(0.3)  # Lambda rate spacing
        elif SCORING_MODE == "direct":
            trestle_data = call_trestle(lead)
            batchdata_data = call_batchdata(lead)
            tf_data = call_trustedform(lead.get("trustedform_url"))
            # Disregard TF cert age — CSV leads aren't real-time
            if tf_data and "age_seconds" in tf_data:
                tf_data["age_seconds"] = None
            result = score_lead(lead, vertical, trestle_data, batchdata_data, tf_data)
            result["has_trustedform"] = any(v is not None for v in tf_data.values()) if tf_data else False
            time.sleep(0.2)  # Rate limit spacing
        else:
            result = generate_demo_scores(lead, vertical)
            result["has_trustedform"] = True  # Demo always simulates TF

        result["lead_number"] = i + 1
        result["name"] = display_name
        results.append(result)

    # Summary stats
    tier_counts = {"Gold": 0, "Silver": 0, "Bronze": 0, "Reject": 0}
    for r in results:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1

    # Check if any leads are missing TrustedForm data
    any_missing_tf = any(not r.get("has_trustedform", False) for r in results)

    print(f"\n[SCORED] {len(results)} leads for {PROSPECTS[token]['company']}: " +
          f"Gold={tier_counts['Gold']} Silver={tier_counts['Silver']} " +
          f"Bronze={tier_counts['Bronze']} Reject={tier_counts['Reject']}")
    if any_missing_tf:
        print(f"  ⚠ WARNING: Some leads missing TrustedForm data — Behavioral & Fraud scores affected")

    return jsonify({
        "results": results,
        "summary": tier_counts,
        "total_scored": len(results),
        "demo_mode": DEMO_MODE,
        "missing_trustedform": any_missing_tf,
    })


# ============================================================
# ENTRY POINT
# ============================================================

# ============================================================
# HEALTH CHECK — for load balancers / uptime monitors
# ============================================================

@app.route("/health")
def health():
    return jsonify({"status": "ok", "mode": SCORING_MODE}), 200


# ============================================================
# ENTRY POINT
# ============================================================

PORT = int(os.environ.get("PORT", 5050))

def print_banner():
    mode_labels = {"lambda": "LAMBDA (production scoring)", "direct": "DIRECT (Trestle + BatchData)", "demo": "DEMO (simulated scores)"}
    print(f"\n{'='*50}")
    print(f"  GreenWatt — Score 10 Leads")
    print(f"  Mode: {mode_labels[SCORING_MODE]}")
    if SCORING_MODE == "lambda":
        print(f"  Lambda URL: {LAMBDA_API_URL}")
    print(f"  Trestle API: {'SET' if TRESTLE_API_KEY else 'NOT SET'}")
    print(f"  BatchData API: {'SET' if BATCHDATA_API_KEY else 'NOT SET'}")
    print(f"  TrustedForm API: {'SET' if TRUSTEDFORM_API_KEY else 'NOT SET (optional)'}")
    print(f"  Port: {PORT}")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    print_banner()
    # Use debug=False in production. For local dev, set FLASK_DEBUG=1.
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=PORT, debug=debug)
