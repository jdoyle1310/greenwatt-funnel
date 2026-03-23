"""
Pillar Scoring Fix — Run this to patch app.py with correct field mappings.

Usage: python patch_pillars.py
This will rewrite the FIELD_SCORES, VERTICAL_CONFIGS, TIER_THRESHOLDS, REASON_LABELS,
get_api_value(), call_trestle(), call_batchdata(), and score_lead() in app.py.

What it fixes:
- Missing fields: address.name_match, owner_name, free_and_clear, high_equity, tax_lien, sale_propensity
- Phantom fields removed: trestle.phone.prepaid, trustedform.seconds_on_page, activity_score_behavioral
- Fixed field names: trestle.is_litigator → trestle.litigator_risk
- Cross-API pillar assignments: BatchData feeds identity + fraud, not just property
- Pillar weights corrected from backtest data (contactability is #1, not fraud)
- Added TrustedForm data flow through scoring engine
- Updated tier thresholds to 75/53/25
"""

import re

with open("app.py", "r") as f:
    code = f.read()

# ============================================================
# 1. Replace FIELD_SCORES
# ============================================================
old_field_scores_start = "FIELD_SCORES = {"
old_field_scores_end = "\n}\n\n# Per-vertical"  # ends before VERTICAL_CONFIGS comment

new_field_scores = '''FIELD_SCORES = {
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
    "batchdata.owner_occupied": {
        "pillar": "identity",
        "values": {
            "confirmed_owner": 40, "probable_owner": 20,
            "probable_renter": -15, "confirmed_renter": -30,
        },
        "null_penalty": -10,
        "max_points": 40,
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
    # D. BEHAVIORAL — Does lead behavior look legitimate?
    # Sources: TrustedForm timing + owner verification
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

    # ═══════════════════════════════════════════════════
    # E. PROPERTY & FINANCIAL — Qualified property?
    # Sources: BatchData property + valuation + quickLists
    # ═══════════════════════════════════════════════════
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
    "batchdata.sale_propensity": {
        "pillar": "property_financial",
        "ranges": [
            (0, 30, 15), (30, 60, 5), (60, 80, -5), (80, 100, -15),
        ],
        "null_penalty": 0,
        "max_points": 15,
    },
}'''

# Find and replace FIELD_SCORES block
pattern = r'FIELD_SCORES = \{.*?\n\}\n'
code = re.sub(pattern, new_field_scores + '\n', code, count=1, flags=re.DOTALL)

# ============================================================
# 2. Replace VERTICAL_CONFIGS
# ============================================================
new_vertical_configs = '''
# Per-vertical configs — weights from backtest dispo data (contactability is #1 predictor)
VERTICAL_CONFIGS = {
    # Validated verticals
    "Solar":           {"pillar_weights": {"contactability": 0.30, "identity": 0.20, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": False, "hard_kill_mobile": True},
    "Roofing":         {"pillar_weights": {"contactability": 0.30, "identity": 0.25, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.20}, "hard_kill_renter": True,  "hard_kill_mobile": True},
    "Windows":         {"pillar_weights": {"contactability": 0.30, "identity": 0.20, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    # Financial verticals — identity weighs more
    "Insurance":       {"pillar_weights": {"contactability": 0.25, "identity": 0.30, "fraud_legal": 0.15, "behavioral": 0.15, "property_financial": 0.15}, "hard_kill_renter": False, "hard_kill_mobile": False},
    "Mortgage":        {"pillar_weights": {"contactability": 0.20, "identity": 0.35, "fraud_legal": 0.15, "behavioral": 0.15, "property_financial": 0.15}, "hard_kill_renter": False, "hard_kill_mobile": False},
    # Unvalidated — nearest validated vertical
    "HVAC":            {"pillar_weights": {"contactability": 0.30, "identity": 0.20, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Siding":          {"pillar_weights": {"contactability": 0.30, "identity": 0.25, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.20}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Gutters":         {"pillar_weights": {"contactability": 0.35, "identity": 0.15, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Painting":        {"pillar_weights": {"contactability": 0.35, "identity": 0.15, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Plumbing":        {"pillar_weights": {"contactability": 0.35, "identity": 0.15, "fraud_legal": 0.10, "behavioral": 0.20, "property_financial": 0.20}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Flooring":        {"pillar_weights": {"contactability": 0.30, "identity": 0.20, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Bath Remodel":    {"pillar_weights": {"contactability": 0.25, "identity": 0.25, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
    "Kitchen Remodel": {"pillar_weights": {"contactability": 0.25, "identity": 0.25, "fraud_legal": 0.10, "behavioral": 0.15, "property_financial": 0.25}, "hard_kill_renter": True,  "hard_kill_mobile": False},
}'''

pattern = r'# Per-vertical configs.*?VERTICAL_CONFIGS = \{.*?\n\}\n'
code = re.sub(pattern, new_vertical_configs + '\n', code, count=1, flags=re.DOTALL)

# ============================================================
# 3. Replace TIER_THRESHOLDS
# ============================================================
code = code.replace(
    'TIER_THRESHOLDS = [("Gold", 70), ("Silver", 45), ("Bronze", 20)]',
    'TIER_THRESHOLDS = [("Gold", 75), ("Silver", 53), ("Bronze", 25)]'
)

# ============================================================
# 4. Replace REASON_LABELS
# ============================================================
new_reason_labels = '''REASON_LABELS = {
    "trestle.phone.is_valid": ("Phone Valid", {"true": "Yes", "false": "No"}),
    "trestle.phone.contact_grade": ("Phone Grade", {"A": "A (Excellent)", "B": "B (Good)", "C": "C (Fair)", "D": "D (Poor)", "F": "F (Very Poor)"}),
    "trestle.phone.activity_score": ("Phone Activity", {}),
    "trestle.phone.line_type": ("Line Type", {}),
    "trestle.phone.name_match": ("Phone Name Match", {"true": "Yes", "false": "No"}),
    "trestle.email.is_valid": ("Email Valid", {"true": "Yes", "false": "No"}),
    "trestle.email.name_match": ("Email Name Match", {"true": "Yes", "false": "No"}),
    "trestle.address.name_match": ("Address Name Match", {"true": "Yes", "false": "No"}),
    "trestle.litigator_risk": ("Litigator Risk", {"true": "Yes ⚠️", "false": "No"}),
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
}'''

pattern = r'REASON_LABELS = \{.*?\n\}\n'
code = re.sub(pattern, new_reason_labels + '\n', code, count=1, flags=re.DOTALL)

# ============================================================
# 5. Replace get_api_value to support TrustedForm
# ============================================================
old_get_api = '''def get_api_value(field_key, trestle_data, batchdata_data):
    """Extract a value from API results by field key."""
    if field_key.startswith("trestle."):
        key = field_key.replace("trestle.", "")
        return trestle_data.get(key)
    elif field_key.startswith("batchdata."):
        key = field_key.replace("batchdata.", "")
        return batchdata_data.get(key)
    return None'''

new_get_api = '''def get_api_value(field_key, trestle_data, batchdata_data, trustedform_data=None):
    """Extract a value from API results by field key."""
    if field_key.startswith("trestle."):
        key = field_key.replace("trestle.", "")
        return trestle_data.get(key)
    elif field_key.startswith("batchdata."):
        key = field_key.replace("batchdata.", "")
        return batchdata_data.get(key)
    elif field_key.startswith("trustedform."):
        if trustedform_data is None:
            return None
        key = field_key.replace("trustedform.", "")
        return trustedform_data.get(key)
    return None'''

code = code.replace(old_get_api, new_get_api)

# ============================================================
# 6. Update score_lead — signature, hard-kill display fix, TF passthrough
# ============================================================

# 6a. Update signature to accept trustedform_data
code = code.replace(
    'def score_lead(lead_data, vertical, trestle_data, batchdata_data):',
    'def score_lead(lead_data, vertical, trestle_data, batchdata_data, trustedform_data=None):'
)

# 6b. Remove hard-kill early return — always score all pillars, override tier at end
#     This ensures the UI shows real pillar scores even on Reject leads
old_hardkill_block = '''    # Check hard kills first
    killed, kill_reason = check_hard_kills(trestle_data, batchdata_data, vertical)
    if killed:
        return {
            "score": 0, "tier": "Reject", "hard_kill": True,
            "hard_kill_reason": kill_reason,
            "pillars": {p: {"score": 0, "weight": w} for p, w in weights.items()},
            "reason_codes": [{"label": kill_reason, "positive": False}],
        }'''

new_hardkill_block = '''    # Check hard kills (but don't return early — still score all pillars)
    killed, kill_reason = check_hard_kills(trestle_data, batchdata_data, vertical)'''

code = code.replace(old_hardkill_block, new_hardkill_block)

# 6c. Change vertical-specific override skips to score as strong negatives
code = code.replace(
    '''        if field_key == "batchdata.owner_occupied" and value == "confirmed_renter":
            if config["hard_kill_renter"]:
                continue  # Already handled in hard_kills''',
    '''        if field_key == "batchdata.owner_occupied" and value == "confirmed_renter":
            if config["hard_kill_renter"]:
                points = -30  # Score as strong negative instead of skipping'''
)
code = code.replace(
    '''        elif field_key == "batchdata.property_type" and value == "Mobile/Manufactured":
            if config["hard_kill_mobile"]:
                continue''',
    '''        elif field_key == "batchdata.property_type" and value == "Mobile/Manufactured":
            if config["hard_kill_mobile"]:
                points = -40  # Score as strong negative instead of skipping'''
)

# 6d. Change HARD_KILL field results from skip to max negative
code = code.replace(
    '''        if points == "HARD_KILL":
            continue  # Already handled''',
    '''        # HARD_KILL from evaluate_field — score as max negative instead of skipping
        if points == "HARD_KILL":
            points = -1 * field_config["max_points"]'''
)

# 6e. Add hard-kill override AFTER pillar scoring, before final return
code = code.replace(
    '''    # Sort reasons by impact, take top 5
    reasons.sort(key=lambda r: r["impact"], reverse=True)

    return {
        "score": final_score, "tier": tier, "hard_kill": False,
        "hard_kill_reason": None, "pillars": pillar_breakdown,
        "reason_codes": [{"label": r["label"], "positive": r["positive"]} for r in reasons[:5]],
    }''',
    '''    # Hard kill override — keep pillar scores but force Reject tier
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
    }'''
)

# 6f. Update get_api_value calls inside score_lead to pass trustedform_data
code = code.replace(
    'value = get_api_value(field_key, trestle_data, batchdata_data)',
    'value = get_api_value(field_key, trestle_data, batchdata_data, trustedform_data)'
)

# ============================================================
# 7. Update call_trestle to extract missing fields
# ============================================================
# Add address.name_match, address.is_valid, litigator_risk to trestle extraction
old_trestle_return = '''        result["phone.contact_grade"] = data.get("phone.contact_grade")
        result["phone.activity_score"] = data.get("phone.activity_score")
        result["phone.line_type"] = data.get("phone.linetype")
        result["phone.name_match"] = data.get("phone.name_match")
        result["email.is_valid"] = data.get("email.is_valid")
        result["email.name_match"] = data.get("email.name_match")'''

new_trestle_return = '''        result["phone.is_valid"] = str(data.get("phone.is_valid")) if data.get("phone.is_valid") is not None else None
        result["phone.contact_grade"] = data.get("phone.contact_grade")
        result["phone.activity_score"] = data.get("phone.activity_score")
        result["phone.line_type"] = data.get("phone.linetype")  # NOTE: API returns "linetype" not "line_type"
        result["phone.name_match"] = str(data.get("phone.name_match")) if data.get("phone.name_match") is not None else None
        result["email.is_valid"] = str(data.get("email.is_valid")) if data.get("email.is_valid") is not None else None
        result["email.name_match"] = str(data.get("email.name_match")) if data.get("email.name_match") is not None else None
        result["address.is_valid"] = str(data.get("address.is_valid")) if data.get("address.is_valid") is not None else None
        result["address.name_match"] = str(data.get("address.name_match")) if data.get("address.name_match") is not None else None
        # Litigator risk from add_ons
        add_ons = data.get("add_ons", {}) or {}
        litigator = add_ons.get("litigator_checks", {}) or {}
        result["litigator_risk"] = str(litigator.get("phone.is_litigator_risk")) if litigator.get("phone.is_litigator_risk") is not None else None'''

code = code.replace(old_trestle_return, new_trestle_return)

# ============================================================
# 8. Update call_batchdata to extract missing fields
# ============================================================
# Add after year_built extraction (find the line and append)
old_batchdata_end = '''        result["year_built"] = building.get("yearBuilt")

    except Exception as e:
        print(f"  BatchData API error: {e}")

    return result'''

new_batchdata_end = '''        result["year_built"] = building.get("yearBuilt")

        # QuickLists flags
        quick = props.get("quickLists", {}) or {}
        result["free_and_clear"] = quick.get("freeAndClear")
        result["high_equity"] = quick.get("highEquity")
        result["tax_lien"] = quick.get("taxDefault")
        result["corporate_owned"] = quick.get("corporateOwned")
        result["inherited"] = quick.get("inherited")
        result["senior_owner"] = quick.get("seniorOwner")
        result["absentee_owner"] = quick.get("absenteeOwner")

        # Owner name (for display in identity pillar)
        owner_names = []
        for o in (owner.get("owners") or owner.get("names") or []):
            n = o.get("fullName") or o.get("name", "")
            if n: owner_names.append(n)
        if not owner_names and owner.get("fullName"):
            owner_names = [owner["fullName"]]
        result["owner_name"] = "; ".join(owner_names) if owner_names else None

        # Intel
        intel = props.get("intel", {}) or {}
        result["sale_propensity"] = intel.get("salePropensity")

        # Demographics
        demo = props.get("demographics", {}) or {}
        result["bd_age"] = demo.get("age")

    except Exception as e:
        print(f"  BatchData API error: {e}")

    return result'''

code = code.replace(old_batchdata_end, new_batchdata_end)

# ============================================================
# 9. Add call_trustedform function (if not exists)
# ============================================================
if 'def call_trustedform(' not in code:
    # Add before SCORING ENGINE section
    tf_function = '''

# ============================================================
# TRUSTEDFORM API
# ============================================================

def call_trustedform(cert_url):
    """Call TrustedForm Insights API to get form behavior data."""
    import base64
    result = {"form_input_method": None, "age_seconds": None, "confirmed_owner": None}

    if not cert_url or not TRUSTEDFORM_API_KEY:
        return result

    try:
        # Extract cert ID
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
            if has_prepop and not has_typing: result["form_input_method"] = "pre-populated_only"
            elif has_paste and not has_typing and not has_autofill: result["form_input_method"] = "paste_only"
            elif has_typing and has_paste: result["form_input_method"] = "typing_paste"
            elif has_typing and has_autofill: result["form_input_method"] = "typing_autofill"
            elif has_autofill and not has_typing: result["form_input_method"] = "autofill_only"
            elif has_typing: result["form_input_method"] = "typing_only"
            else: result["form_input_method"] = "empty"
        else:
            result["form_input_method"] = "empty"

        result["age_seconds"] = props.get("age_seconds")

        # Normalize confirmed_owner
        raw_owner = props.get("confirmed_owner", "")
        if isinstance(raw_owner, str):
            lower = raw_owner.lower()
            if "verified owner" in lower: result["confirmed_owner"] = "verified"
            elif "named account" in lower: result["confirmed_owner"] = "named_account"
            elif "no verified" in lower: result["confirmed_owner"] = "no_verified_account"

    except Exception as e:
        print(f"  TrustedForm API error: {e}")

    return result

'''
    code = code.replace(
        '# ============================================================\n# SCORING ENGINE',
        tf_function + '# ============================================================\n# SCORING ENGINE'
    )

# ============================================================
# 10. Add TRUSTEDFORM_API_KEY to config if missing
# ============================================================
if 'TRUSTEDFORM_API_KEY' not in code.split('FIELD_SCORES')[0]:
    code = code.replace(
        'BATCHDATA_API_KEY = os.environ.get("BATCHDATA_API_KEY")',
        'BATCHDATA_API_KEY = os.environ.get("BATCHDATA_API_KEY")\nTRUSTEDFORM_API_KEY = os.environ.get("TRUSTEDFORM_API_KEY")  # Optional — enables Fraud & Behavioral pillars from TF certs'
    )

# ============================================================
# Write patched file
# ============================================================
with open("app.py", "w") as f:
    f.write(code)

print("✅ app.py patched successfully!")
print()
print("Changes applied:")
print("  1. FIELD_SCORES — 22 fields across 5 pillars (was 14 with 3 phantoms)")
print("  2. VERTICAL_CONFIGS — 13 verticals with corrected weights")
print("  3. TIER_THRESHOLDS — 75/53/25 (was 70/45/20)")
print("  4. REASON_LABELS — all 22 fields with display names")
print("  5. get_api_value() — now supports TrustedForm fields")
print("  6. score_lead() — hard-killed leads now show real pillar scores (was all zeros)")
print("     • Hard kill overrides tier → Reject and score → 0, but pillars still calculated")
print("     • HARD_KILL fields scored as max-negative instead of skipped")
print("     • Kill reason shown as first reason code with ⛔ prefix")
print("  7. call_trestle() — extracts address.name_match, address.is_valid, litigator_risk")
print("  8. call_batchdata() — extracts free_and_clear, high_equity, tax_lien, sale_propensity, owner_name, bd_age")
print("  9. call_trustedform() — NEW function for TF Insights API")
print(" 10. TRUSTEDFORM_API_KEY — added to config")
print()
print("⚠️  NOTE: The scoring route also needs to call call_trustedform() and pass")
print("   the result to score_lead(). Search for 'score_lead(' in the scoring route")
print("   and add trustedform_data as the 5th argument.")
print()
print("   Example:")
print("     tf_data = call_trustedform(lead.get('trustedform_url'))")
print("     result = score_lead(lead, vertical, trestle_data, batchdata_data, tf_data)")
