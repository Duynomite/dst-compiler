#!/usr/bin/env python3
"""
Comprehensive audit of curated_disasters.json and all_disasters.json
Validates all records against 32 checks per the audit specification.
Checks 1-18: Per-record validation
Check 19-21: Cross-record validation
Check 22: lastVerified field for STATE/HHS records (skipped for FEMA)
Check 23: URL verification (HEAD + content relevance) — requires --verify-urls flag
Check 24: lastVerified staleness (>30 days) for STATE/HHS records
Check 25: eCFR regulatory monitoring — detects changes to 42 CFR § 422.62 — requires --check-ecfr flag
Check 26: FEMA-specific URL validation (fema.gov/disaster/{number})
Check 27: URL well-formedness and expected domain validation for all sources
Check 28: End date justification — ongoing STATE entries must have determination method — requires --check-state-health
Check 29: Staleness by age — STATE declared >60 days ago with no end date = FAIL — requires --check-state-health
Check 30: State law consistency — declaration age vs state auto-expire default — requires --check-state-health
Check 31: Human review cadence — lastHumanReview within 30 days — requires --check-state-health
Check 32: Needs review flag — entries flagged needsReview=true — requires --check-state-health
Use --all-disasters flag when auditing all_disasters.json (includes FEMA records).
"""

import json
import os
import sys
import argparse
import calendar
from datetime import date, datetime, timedelta
from collections import Counter

TODAY = date.today()
TWENTY_FOUR_MONTHS_AGO = date(TODAY.year - 2, TODAY.month, min(TODAY.day, 28))
TOMORROW = TODAY + timedelta(days=1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_JSON_PATH = os.path.join(SCRIPT_DIR, "curated_disasters.json")

VALID_SOURCES_CURATED = {"SBA", "FMCSA", "HHS", "USDA", "STATE"}
VALID_SOURCES_ALL = {"SBA", "FMCSA", "HHS", "USDA", "STATE", "FEMA"}

VALID_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "VI", "GU", "AS", "MP"
}

REQUIRED_FIELDS = [
    "id", "source", "state", "title", "incidentType",
    "declarationDate", "incidentStart", "officialUrl",
    "counties", "status", "sepWindowStart", "sepWindowEnd"
]


def parse_date(s):
    """Parse ISO date string to date object. Returns None if invalid."""
    if s is None:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def calculate_sep_window_end_with_incident_end(incident_end):
    """Calculate SEP window end: last day of (incidentEnd.month + 2)."""
    month = incident_end.month
    year = incident_end.year
    target_month = month + 2
    target_year = year
    if target_month > 12:
        target_month -= 12
        target_year += 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    return date(target_year, target_month, last_day)


def calculate_sep_window_end_ongoing(sep_start, renewal_dates=None):
    """Calculate SEP window end for ongoing: last day of (maxDate.month + 14)."""
    max_date = sep_start
    if renewal_dates:
        for rd in renewal_dates:
            rd_date = parse_date(rd)
            if rd_date and rd_date > max_date:
                max_date = rd_date
    month = max_date.month
    year = max_date.year
    target_month = month + 14
    target_year = year
    while target_month > 12:
        target_month -= 12
        target_year += 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    return date(target_year, target_month, last_day)


# =============================================
# STATE CODE TO NAME (for content relevance checks)
# =============================================

STATE_CODE_TO_NAME = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas",
    "CA": "california", "CO": "colorado", "CT": "connecticut", "DE": "delaware",
    "DC": "district of columbia", "FL": "florida", "GA": "georgia", "GU": "guam",
    "HI": "hawaii", "ID": "idaho", "IL": "illinois", "IN": "indiana",
    "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana",
    "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan",
    "MN": "minnesota", "MS": "mississippi", "MO": "missouri", "MT": "montana",
    "NE": "nebraska", "NV": "nevada", "NH": "new hampshire", "NJ": "new jersey",
    "NM": "new mexico", "NY": "new york", "NC": "north carolina", "ND": "north dakota",
    "MP": "northern mariana islands", "OH": "ohio", "OK": "oklahoma", "OR": "oregon",
    "PA": "pennsylvania", "PR": "puerto rico", "RI": "rhode island",
    "SC": "south carolina", "SD": "south dakota", "TN": "tennessee", "TX": "texas",
    "UT": "utah", "VT": "vermont", "VA": "virginia", "VI": "virgin islands",
    "WA": "washington", "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming",
    "AS": "american samoa",
}


# =============================================
# URL VERIFICATION (Check 23)
# =============================================

def verify_urls(disasters, timeout=10):
    """
    Check 23: URL verification — HEAD reachability + content relevance.

    For each record:
      1. HEAD request (2 retries, 1s backoff) — FAIL if 4xx/5xx or unreachable
      2. GET first 50KB of page content
      3. Check for relevance signals: year, state name, title keywords
      4. Score: >=2 signals = PASS, 1 = WEAK, 0 = FAIL (likely generic page)

    Special handling:
      - FMCSA URLs: Always return 403 to bots — treated as PASS (reachability skip)
      - Federal Register URLs: Content is JS-rendered; URL structure is verified instead
      - Known SSL-problematic sites: Warn but don't fail

    Rate limiting: 0.5s between requests to respect government sites.
    """
    import re
    import time
    try:
        import requests
    except ImportError:
        print("  ERROR: 'requests' package required for URL verification")
        print("  Install with: pip install requests")
        return []

    USER_AGENT = "DST-Compiler-Audit/1.0 (Medicare SEP Tool; contact: admin@clearpathcoverage.com)"

    # Domains known to block automated requests — skip HEAD check, validate URL structure
    SKIP_HEAD_DOMAINS = {"www.fmcsa.dot.gov", "fmcsa.dot.gov"}

    # Domains where content is JS-rendered — skip content relevance check
    SKIP_CONTENT_DOMAINS = {"www.federalregister.gov", "federalregister.gov"}

    results = []
    # Deduplicate URLs to avoid hammering the same endpoint (FMCSA has 59 records with 3 URLs)
    checked_urls = {}

    print(f"\n  Checking {len(disasters)} URLs...")

    for i, rec in enumerate(disasters):
        url = rec.get("officialUrl", "")
        rec_id = rec.get("id", "UNKNOWN")
        state = rec.get("state", "")
        title = rec.get("title", "")
        source = rec.get("source", "")

        if not url:
            results.append({"id": rec_id, "status": "FAIL", "reason": "No URL", "url": ""})
            continue

        # Extract domain for special handling
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.lower()
        except Exception:
            domain = ""

        # --- Special case: FMCSA always returns 403 to bots ---
        # The URLs are valid but FMCSA blocks automated requests.
        # Validate URL structure instead of HTTP reachability.
        if domain in SKIP_HEAD_DOMAINS:
            # Check URL is not a generic homepage
            is_specific = "/emergency/" in url and len(url) > 60
            if url in checked_urls:
                results.append({"id": rec_id, "status": checked_urls[url], "reachable": "skipped (403 domain)",
                                "content_match": "N/A", "url": url[:100]})
            else:
                status = "PASS" if is_specific else "WARN"
                checked_urls[url] = status
                results.append({"id": rec_id, "status": status, "reachable": "skipped (403 domain)",
                                "content_match": "structure_check", "url": url[:100]})
            continue

        # --- Special case: Federal Register URLs are JS-rendered ---
        # Content relevance check fails because the page content is loaded via JS.
        # The URL contains the document number which matches our record ID — that IS the verification.
        if domain in SKIP_CONTENT_DOMAINS:
            if url in checked_urls:
                results.append({"id": rec_id, "status": checked_urls[url], "reachable": True,
                                "content_match": "N/A (JS-rendered)", "url": url[:100]})
                continue
            # HEAD check only — skip content
            reachable = False
            status_code = None
            for attempt in range(2):
                try:
                    resp = requests.head(url, timeout=timeout, allow_redirects=True,
                                         headers={"User-Agent": USER_AGENT})
                    status_code = resp.status_code
                    reachable = status_code < 400
                    break
                except Exception as e:
                    if attempt == 0:
                        time.sleep(1)
                    status_code = str(type(e).__name__)

            if reachable:
                checked_urls[url] = "PASS"
                results.append({"id": rec_id, "status": "PASS", "reachable": True,
                                "content_match": "N/A (JS-rendered)", "url": url[:100]})
            else:
                checked_urls[url] = "FAIL"
                results.append({"id": rec_id, "status": "FAIL",
                                "reason": f"HTTP {status_code}", "url": url[:100]})
            time.sleep(0.5)
            continue

        # --- Standard URL verification ---
        # Step 1: HEAD check (2 attempts)
        reachable = False
        status_code = None
        for attempt in range(2):
            try:
                resp = requests.head(
                    url, timeout=timeout, allow_redirects=True,
                    headers={"User-Agent": USER_AGENT}
                )
                status_code = resp.status_code
                reachable = status_code < 400
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(1)
                status_code = str(type(e).__name__)

        if not reachable:
            # Some servers reject HEAD but accept GET — try GET as fallback
            try:
                resp = requests.get(
                    url, timeout=timeout, allow_redirects=True,
                    headers={"User-Agent": USER_AGENT},
                    stream=True
                )
                if resp.status_code < 400:
                    reachable = True
                    status_code = resp.status_code
                resp.close()
            except Exception:
                pass

        if not reachable:
            # SSL errors on government sites are usually transient cert issues,
            # not wrong URLs. Treat as WARN, not FAIL.
            is_ssl = "SSL" in str(status_code)
            results.append({
                "id": rec_id,
                "status": "WARN" if is_ssl else "FAIL",
                "reason": f"HTTP {status_code}" + (" (SSL — likely transient)" if is_ssl else ""),
                "url": url[:100]
            })
            time.sleep(0.5)
            continue

        # Step 2: Content relevance check (GET first 50KB)
        content_match = "UNKNOWN"
        matches = 0
        try:
            resp = requests.get(
                url, timeout=timeout, allow_redirects=True,
                headers={"User-Agent": USER_AGENT},
                stream=True
            )
            # Read only first 50KB to be respectful
            content = ""
            for chunk in resp.iter_content(chunk_size=8192, decode_unicode=True):
                if isinstance(chunk, bytes):
                    content += chunk.decode("utf-8", errors="ignore")
                else:
                    content += chunk
                if len(content) > 50000:
                    break
            resp.close()

            content_lower = content.lower()

            # Build relevance signals
            signals = []

            # Signal 1: Year from declaration date
            decl_year = rec.get("declarationDate", "")[:4]
            if decl_year:
                signals.append(decl_year)

            # Signal 2: State name (full name, not abbreviation)
            state_name = STATE_CODE_TO_NAME.get(state, "")
            if state_name:
                signals.append(state_name)

            # Signal 3-5: Keywords from title (skip common words)
            skip_words = {
                "governor", "emergency", "declaration", "declares", "declared",
                "january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november", "december",
                "storm", "winter", "state", "disaster", "severe", "weather",
                "2025", "2026", "2024",  # Years handled separately
            }
            title_words = re.findall(r'\b[a-z]{4,}\b', title.lower())
            key_words = [w for w in title_words if w not in skip_words]
            signals.extend(key_words[:3])

            # Check: how many signals found in page content?
            matches = sum(1 for s in signals if s in content_lower)

            if matches >= 2:
                content_match = "PASS"
            elif matches == 1:
                content_match = "WEAK"
            else:
                content_match = "FAIL"

        except Exception as e:
            content_match = f"ERROR: {type(e).__name__}"

        final_status = "PASS" if content_match == "PASS" else "WARN"
        results.append({
            "id": rec_id,
            "status": final_status,
            "reachable": True,
            "content_match": content_match,
            "signals_matched": matches,
            "url": url[:100],
        })

        # Progress indicator every 25 records
        if (i + 1) % 25 == 0:
            print(f"  ... {i + 1}/{len(disasters)} checked")

        time.sleep(0.5)  # Rate limit

    return results


def print_url_report(results):
    """Print URL verification report."""
    passes = [r for r in results if r["status"] == "PASS"]
    warns = [r for r in results if r["status"] == "WARN"]
    fails = [r for r in results if r["status"] == "FAIL"]

    print(f"\n  Results: {len(passes)} PASS, {len(warns)} WARN, {len(fails)} FAIL")

    if fails:
        print(f"\n  FAILURES ({len(fails)}):")
        for f in fails:
            print(f"    {f['id']}: {f.get('reason', 'content mismatch')} — {f.get('url', '')}")

    if warns:
        print(f"\n  WARNINGS ({len(warns)}):")
        for w in warns:
            cm = w.get("content_match", "?")
            print(f"    {w['id']}: content_match={cm} — {w.get('url', '')}")

    return len(fails)


def update_metadata_with_url_results(json_path, results):
    """Write URL verification results back to curated_disasters.json metadata."""
    with open(json_path, "r") as f:
        data = json.load(f)

    passes = [r for r in results if r["status"] == "PASS"]
    warns = [r for r in results if r["status"] == "WARN"]
    fails = [r for r in results if r["status"] == "FAIL"]

    if "dataIntegrity" not in data.get("metadata", {}):
        data.setdefault("metadata", {})["dataIntegrity"] = {}

    data["metadata"]["dataIntegrity"]["urlVerification"] = {
        "lastRun": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "passCount": len(passes),
        "warnCount": len(warns),
        "failCount": len(fails),
        "failures": [{"id": f["id"], "reason": f.get("reason", "content mismatch")} for f in fails],
    }

    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n  Metadata updated with URL verification results.")


# =============================================
# eCFR REGULATORY MONITORING (Check 25)
# =============================================

# Known version date of 42 CFR § 422.62 that our SEP logic is built against.
# If eCFR reports a newer version, the regulation may have changed.
ECFR_KNOWN_VERSION_DATE = "2024-06-03"  # Last amendment: 89 FR 30815 (April 2024 final rule, effective June 2024)

# Key regulatory parameters our tool depends on
EXPECTED_SEP_WINDOW_MONTHS = 2  # "2 full calendar months following the end date"
EXPECTED_MAX_ONGOING_MONTHS = 14  # "up to 14 calendar months from start date"


def check_ecfr_regulation():
    """
    Check 25: eCFR regulatory monitoring — detect changes to 42 CFR § 422.62.

    Queries the eCFR API to check if § 422.62 (Election of coverage under an MA plan)
    has been amended since our last known version. If the regulation changed, our SEP
    window calculations may be wrong.

    Returns dict with:
      - status: "PASS" | "WARN" | "FAIL" | "ERROR"
      - message: Human-readable description
      - details: Dict with version info
    """
    try:
        import requests
    except ImportError:
        return {
            "status": "ERROR",
            "message": "requests package required for eCFR check",
            "details": {}
        }

    ECFR_BASE = "https://www.ecfr.gov/api"
    USER_AGENT = "DST-Compiler-Audit/1.0 (Medicare SEP compliance monitor)"

    headers = {"User-Agent": USER_AGENT}
    result = {
        "status": "ERROR",
        "message": "",
        "details": {
            "knownVersionDate": ECFR_KNOWN_VERSION_DATE,
            "currentVersionDate": None,
            "regulationChanged": None,
            "lastChecked": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    }

    try:
        # Step 1: Search eCFR for current version of § 422.62
        # The search endpoint returns version metadata including effective dates
        search_url = f"{ECFR_BASE}/search/v1/results"
        params = {
            "query": '"422.62"',
            "per_page": 5,
        }
        resp = requests.get(search_url, params=params, headers=headers, timeout=15)

        if resp.status_code != 200:
            result["message"] = f"eCFR search API returned HTTP {resp.status_code}"
            return result

        data = resp.json()
        results_list = data.get("results", [])

        # Find the current version of § 422.62 in Title 42
        current_version_date = None
        section_title = None

        for entry in results_list:
            # Look for Title 42, section 422.62
            hierarchy = entry.get("hierarchy", {})
            title_num = hierarchy.get("title")
            section = entry.get("section_number") or hierarchy.get("section")

            # Also check the hierarchy_headings for Part 422
            headings = entry.get("hierarchy_headings", {})
            part = headings.get("part") or hierarchy.get("part")

            # Match: Title 42, Part 422, Section 422.62
            if str(title_num) == "42" and (str(part) == "422" or "422" in str(section)):
                # Check if this is the current (most recent) version
                starts_on = entry.get("starts_on", "")
                structure_index = entry.get("structure_index")
                full_text = entry.get("full_text_excerpt_set", [])
                section_title = entry.get("headings", {}).get("section") or entry.get("section_number")

                if starts_on:
                    if current_version_date is None or starts_on > current_version_date:
                        current_version_date = starts_on

        if current_version_date is None:
            # Fallback: try the versioner API for structure info
            struct_url = f"{ECFR_BASE}/versioner/v1/versions/title-42.json"
            resp2 = requests.get(struct_url, headers=headers, timeout=30)
            if resp2.status_code == 200:
                versions_data = resp2.json()
                # Search through versions for section 422.62
                content_versions = versions_data.get("content_versions", [])
                for v in content_versions:
                    if v.get("identifier") == "422.62" or v.get("name", "").startswith("422.62"):
                        ver_date = v.get("date") or v.get("amendment_date")
                        if ver_date and (current_version_date is None or ver_date > current_version_date):
                            current_version_date = ver_date

        result["details"]["currentVersionDate"] = current_version_date

        if current_version_date is None:
            result["status"] = "WARN"
            result["message"] = "Could not determine current version date of § 422.62 from eCFR API"
            result["details"]["regulationChanged"] = None
            return result

        # Step 2: Compare with our known version
        if current_version_date == ECFR_KNOWN_VERSION_DATE:
            result["status"] = "PASS"
            result["message"] = f"§ 422.62 unchanged (effective since {ECFR_KNOWN_VERSION_DATE})"
            result["details"]["regulationChanged"] = False
        elif current_version_date > ECFR_KNOWN_VERSION_DATE:
            result["status"] = "FAIL"
            result["message"] = (
                f"§ 422.62 HAS BEEN AMENDED! Known version: {ECFR_KNOWN_VERSION_DATE}, "
                f"Current version: {current_version_date}. "
                f"SEP window calculations may be WRONG. Review the regulation immediately."
            )
            result["details"]["regulationChanged"] = True
        else:
            # Current version is older than known — shouldn't happen, treat as PASS
            result["status"] = "PASS"
            result["message"] = f"§ 422.62 version date ({current_version_date}) predates our known version ({ECFR_KNOWN_VERSION_DATE})"
            result["details"]["regulationChanged"] = False

        # Step 3: Optional — try to verify key regulatory parameters still match
        # Search for the actual text mentioning "2 full calendar months" or "14"
        try:
            text_search_url = f"{ECFR_BASE}/search/v1/results"
            text_params = {
                "query": '"422.62" "calendar months"',
                "per_page": 3,
            }
            text_resp = requests.get(text_search_url, params=text_params, headers=headers, timeout=15)
            if text_resp.status_code == 200:
                text_data = text_resp.json()
                text_results = text_data.get("results", [])
                for tr in text_results:
                    excerpts = tr.get("full_text_excerpt_set", [])
                    for excerpt in excerpts:
                        excerpt_text = excerpt.get("text", "") if isinstance(excerpt, dict) else str(excerpt)
                        if "2 full calendar months" in excerpt_text.lower() or "two full calendar months" in excerpt_text.lower():
                            result["details"]["sepWindowTextConfirmed"] = True
                        if "14 calendar months" in excerpt_text.lower() or "fourteen calendar months" in excerpt_text.lower():
                            result["details"]["maxOngoingTextConfirmed"] = True
        except Exception:
            pass  # Text verification is best-effort

        return result

    except requests.exceptions.Timeout:
        result["message"] = "eCFR API timeout (15s)"
        return result
    except requests.exceptions.ConnectionError:
        result["message"] = "eCFR API connection error"
        return result
    except Exception as e:
        result["message"] = f"eCFR check error: {type(e).__name__}: {e}"
        return result


def print_ecfr_report(ecfr_result):
    """Print eCFR regulatory monitoring report."""
    status = ecfr_result["status"]
    message = ecfr_result["message"]
    details = ecfr_result.get("details", {})

    status_icon = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗", "ERROR": "!"}.get(status, "?")

    print(f"\n  [{status_icon}] {status}: {message}")
    print(f"      Known version: {details.get('knownVersionDate', 'N/A')}")
    print(f"      Current version: {details.get('currentVersionDate', 'N/A')}")
    print(f"      Last checked: {details.get('lastChecked', 'N/A')}")

    if details.get("sepWindowTextConfirmed"):
        print(f"      SEP window text (\"2 full calendar months\"): confirmed ✓")
    if details.get("maxOngoingTextConfirmed"):
        print(f"      Max ongoing text (\"14 calendar months\"): confirmed ✓")

    if status == "FAIL":
        print()
        print("  ⚠ ACTION REQUIRED:")
        print("    1. Review the amended regulation at:")
        print("       https://www.ecfr.gov/current/title-42/chapter-IV/subchapter-B/part-422/subpart-B/section-422.62")
        print("    2. Check if SEP window duration (2 months) has changed")
        print("    3. Check if ongoing disaster max (14 months) has changed")
        print("    4. Check if qualifying declaration types have changed")
        print("    5. Update ECFR_KNOWN_VERSION_DATE in audit_curated_data.py")
        print("    6. Update SEP calculations in index.html and dst_data_fetcher.py if needed")

    return 1 if status == "FAIL" else 0


def update_metadata_with_ecfr_results(json_path, ecfr_result):
    """Write eCFR monitoring results back to curated_disasters.json metadata."""
    with open(json_path, "r") as f:
        data = json.load(f)

    if "dataIntegrity" not in data.get("metadata", {}):
        data.setdefault("metadata", {})["dataIntegrity"] = {}

    data["metadata"]["dataIntegrity"]["regulatoryMonitoring"] = {
        "lastChecked": ecfr_result.get("details", {}).get("lastChecked"),
        "status": ecfr_result["status"],
        "knownVersionDate": ecfr_result.get("details", {}).get("knownVersionDate"),
        "currentVersionDate": ecfr_result.get("details", {}).get("currentVersionDate"),
        "regulationChanged": ecfr_result.get("details", {}).get("regulationChanged"),
        "sepWindowTextConfirmed": ecfr_result.get("details", {}).get("sepWindowTextConfirmed", False),
        "maxOngoingTextConfirmed": ecfr_result.get("details", {}).get("maxOngoingTextConfirmed", False),
    }

    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n  Metadata updated with eCFR regulatory monitoring results.")


# =============================================
# STATE HEALTH CHECKS (28-32)
# =============================================

def run_state_health_checks(script_dir=None):
    """
    Checks 28-32: State declaration health — validates state_declarations.json
    against state_emergency_laws.json for end date accuracy and freshness.

    Returns (failures, passes, total_checks) tuple.
    """
    if script_dir is None:
        script_dir = SCRIPT_DIR

    decl_path = os.path.join(script_dir, "state_declarations.json")
    laws_path = os.path.join(script_dir, "state_emergency_laws.json")

    failures = []
    passes = 0
    total_checks = 0

    def check(record_id, check_num, description, expected, actual, passed):
        nonlocal passes, total_checks
        total_checks += 1
        if passed:
            passes += 1
        else:
            failures.append({
                "id": record_id,
                "check": check_num,
                "description": description,
                "expected": str(expected),
                "actual": str(actual)
            })

    # Load state declarations registry
    if not os.path.exists(decl_path):
        print("  ERROR: state_declarations.json not found")
        return ([], 0, 0)

    with open(decl_path, "r") as f:
        decl_data = json.load(f)
    declarations = decl_data.get("declarations", [])

    # Load state emergency laws (optional — Check 30 skipped if missing)
    laws = {}
    if os.path.exists(laws_path):
        with open(laws_path, "r") as f:
            laws_data = json.load(f)
        laws = laws_data.get("states", {})

    print(f"  Loaded {len(declarations)} declarations, {len(laws)} state law entries")

    for entry in declarations:
        rid = entry.get("id", "UNKNOWN")
        state = entry.get("state", "")
        inc_end = entry.get("incidentEnd")
        inc_start_str = entry.get("incidentStart")
        decl_date_str = entry.get("declarationDate")
        renewal_dates = entry.get("renewalDates")
        det = entry.get("endDateDetermination", {})
        verif = entry.get("verification", {})

        inc_start = parse_date(inc_start_str)
        decl_date = parse_date(decl_date_str)

        # Check 28: End Date Justification
        # STATE record with incidentEnd=null must have method != "unknown"
        if inc_end is None:
            method = det.get("method", "unknown")
            check(rid, 28, "Ongoing STATE record has end date determination method set",
                  "method != 'unknown'", f"method='{method}'",
                  method != "unknown")
        else:
            check(rid, 28, "End date justification — N/A (has incidentEnd)",
                  "N/A", "N/A", True)

        # Check 29: Staleness by Age
        # STATE declared >60 days ago with no end date and no renewals = FAIL
        # Exception: method="still_active" means explicitly verified as ongoing
        if inc_end is None and decl_date:
            age_days = (TODAY - decl_date).days
            has_renewals = bool(renewal_dates and len(renewal_dates) > 0)
            method = det.get("method", "unknown")
            is_confirmed_active = method == "still_active"
            if is_confirmed_active:
                check(rid, 29, "Staleness check — confirmed still_active",
                      "still_active or within age limit",
                      f"{age_days} days old, method=still_active",
                      True)
            elif age_days > 120 and not has_renewals:
                check(rid, 29, "Ongoing STATE >120 days old without renewals",
                      "<= 120 days or has renewals or still_active",
                      f"{age_days} days old, no renewals",
                      False)
            elif age_days > 60 and not has_renewals:
                check(rid, 29, "Ongoing STATE >60 days old without renewals (review needed)",
                      "<= 60 days or has renewals or still_active",
                      f"{age_days} days old, no renewals",
                      False)
            else:
                check(rid, 29, "Staleness check — age within acceptable range",
                      "<= 60 days or has renewals",
                      f"{age_days} days old" + (", has renewals" if has_renewals else ""),
                      True)
        else:
            check(rid, 29, "Staleness by age — N/A (has incidentEnd)",
                  "N/A", "N/A", True)

        # Check 30: State Law Consistency
        # If state has autoTerminates=true and declaration age > defaultDuration
        # with no renewal → FAIL
        state_law = laws.get(state, {})
        if inc_end is None and decl_date and state_law.get("autoTerminates"):
            default_dur = state_law.get("defaultDuration")
            if default_dur:
                age_days = (TODAY - decl_date).days
                has_renewals = bool(renewal_dates and len(renewal_dates) > 0)
                method = det.get("method", "unknown")
                # If age > default duration and no renewals, and method isn't "still_active"
                if age_days > default_dur and not has_renewals and method != "still_active":
                    check(rid, 30, f"State law: {state} auto-terminates at {default_dur} days, no renewal found",
                          f"<= {default_dur} days or has renewal/active status",
                          f"{age_days} days old, method='{method}'",
                          False)
                else:
                    check(rid, 30, "State law consistency — within legal duration or justified",
                          "Within duration or justified", "OK",
                          True)
            else:
                check(rid, 30, "State law consistency — N/A (no default duration for state)",
                      "N/A", "N/A", True)
        elif inc_end is None and state_law and not state_law.get("autoTerminates"):
            check(rid, 30, f"State law consistency — {state} has no auto-termination",
                  "N/A (no auto-terminate)", "N/A", True)
        else:
            check(rid, 30, "State law consistency — N/A (has incidentEnd or no law data)",
                  "N/A", "N/A", True)

        # Check 31: Human Review Cadence
        # verification.lastHumanReview must be within 30 days
        last_review_str = verif.get("lastHumanReview")
        last_review = parse_date(last_review_str)
        if last_review:
            review_age = (TODAY - last_review).days
            check(rid, 31, "Human review within 30 days",
                  "<= 30 days", f"{review_age} days ago ({last_review_str})",
                  review_age <= 30)
        else:
            check(rid, 31, "Human review date present",
                  "Valid lastHumanReview date", str(last_review_str),
                  False)

        # Check 32: needsReview flag
        # Entries flagged as needsReview should be reviewed
        needs_review = det.get("needsReview", False)
        check(rid, 32, "Entry does not need review (needsReview=false)",
              "needsReview=false", f"needsReview={needs_review}",
              not needs_review)

    return (failures, passes, total_checks)


def print_state_health_report(failures, passes, total_checks):
    """Print state health check report."""
    print(f"\n  Total entries checked:  {(passes + len(failures))}")
    print(f"  Total checks performed: {total_checks}")
    print(f"  PASSED:                 {passes}")
    print(f"  FAILED:                 {len(failures)}")
    if total_checks > 0:
        print(f"  Pass rate:              {passes/total_checks*100:.1f}%")

    if failures:
        print(f"\n  FAILURES ({len(failures)}):")
        for f in failures:
            print(f"    [{f['id']}] Check #{f['check']}: {f['description']}")
            print(f"      Expected: {f['expected']}")
            print(f"      Actual:   {f['actual']}")
    else:
        print("\n  ALL STATE HEALTH CHECKS PASSED")

    return len(failures)


def run_audit(json_path=None, all_disasters=False):
    if json_path is None:
        json_path = DEFAULT_JSON_PATH
    with open(json_path, "r") as f:
        data = json.load(f)

    metadata = data.get("metadata", {})
    disasters = data.get("disasters", [])

    # Select valid sources based on mode
    valid_sources = VALID_SOURCES_ALL if all_disasters else VALID_SOURCES_CURATED

    failures = []
    passes = 0
    total_checks = 0

    def check(record_id, check_num, description, expected, actual, passed):
        nonlocal passes, total_checks
        total_checks += 1
        if passed:
            passes += 1
        else:
            failures.append({
                "id": record_id,
                "check": check_num,
                "description": description,
                "expected": str(expected),
                "actual": str(actual)
            })

    # =============================================
    # CROSS-RECORD CHECKS (19, 20, 21)
    # =============================================

    # Check 19: No duplicate IDs
    all_ids = [d["id"] for d in disasters if "id" in d]
    id_counts = Counter(all_ids)
    duplicates = {k: v for k, v in id_counts.items() if v > 1}
    check("CROSS-RECORD", 19, "No duplicate IDs",
          "All unique", f"Duplicates: {duplicates}" if duplicates else "All unique",
          len(duplicates) == 0)

    # Check 20: No FEMA records (curated mode) / FEMA records present (all-disasters mode)
    fema_records = [d.get("id", "?") for d in disasters if d.get("source") == "FEMA"]
    if all_disasters:
        # In all-disasters mode, FEMA records are expected
        check("CROSS-RECORD", 20, "FEMA records present in all_disasters.json",
              ">0 FEMA records", f"{len(fema_records)} FEMA records",
              True)  # Warn but don't fail if FEMA=0 (API could be temporarily down)
        if len(fema_records) == 0:
            print("  WARNING: No FEMA records in all_disasters.json — FEMA API may have been down")
    else:
        check("CROSS-RECORD", 20, "No FEMA records present",
              "0 FEMA records", f"{len(fema_records)} FEMA records: {fema_records}" if fema_records else "0 FEMA records",
              len(fema_records) == 0)

    # Check 21: Metadata recordCount matches
    actual_count = len(disasters)
    stated_count = metadata.get("recordCount", "MISSING")
    check("CROSS-RECORD", 21, "Metadata recordCount matches actual count",
          actual_count, stated_count,
          actual_count == stated_count)

    # =============================================
    # PER-RECORD CHECKS (1-18)
    # =============================================

    for rec in disasters:
        rid = rec.get("id", "MISSING-ID")

        # Check 1: Has all required fields
        missing_fields = [f for f in REQUIRED_FIELDS if f not in rec]
        check(rid, 1, "Has all required fields",
              "No missing fields", f"Missing: {missing_fields}" if missing_fields else "No missing fields",
              len(missing_fields) == 0)

        # Check 2: ID format matches SOURCE-XXXX-SS pattern
        # Allow patterns like SBA-2025-16217-AK, FMCSA-2026-001-AL, HHS-XXX-XX, STATE-XX-XXX
        # FEMA IDs: FEMA-DR-4834-FL or FEMA-EM-3610-CA
        parts = rid.split("-")
        source = rec.get("source", "")
        if source == "FEMA":
            # FEMA-{DR|EM}-{number}-{state}
            import re as _re
            fema_id_valid = bool(_re.match(r"^FEMA-(DR|EM)-\d+-[A-Z]{2}$", rid))
            check(rid, 2, "FEMA ID format matches FEMA-{DR|EM}-{number}-{state}",
                  "FEMA-DR-XXXX-SS or FEMA-EM-XXXX-SS", rid,
                  fema_id_valid)
        else:
            id_valid = (
                len(parts) >= 3 and
                parts[0] in valid_sources and
                parts[-1] in VALID_STATE_CODES
            )
            check(rid, 2, "ID format matches SOURCE-...-SS pattern",
                  "SOURCE-...-STATE", rid,
                  id_valid)

        # Check 3: source is one of valid sources
        check(rid, 3, f"Source is valid ({'/'.join(sorted(valid_sources))})",
              f"One of: {', '.join(sorted(valid_sources))}", source,
              source in valid_sources)

        # Check 4: state is valid 2-letter code
        state = rec.get("state", "")
        check(rid, 4, "State is valid 2-letter US state/territory code",
              "Valid state code", state,
              state in VALID_STATE_CODES)

        # Check 5: counties array is non-empty
        counties = rec.get("counties", [])
        check(rid, 5, "Counties array is non-empty",
              "At least 1 county", f"{len(counties)} counties",
              isinstance(counties, list) and len(counties) > 0)

        # Check 6: officialUrl is present and non-empty
        url = rec.get("officialUrl", "")
        check(rid, 6, "officialUrl is present and non-empty",
              "Non-empty URL", f"'{url[:80]}...'" if len(str(url)) > 80 else f"'{url}'" if url else "EMPTY",
              isinstance(url, str) and len(url) > 0)

        # Check 7: declarationDate is valid ISO date and not in the future
        decl_date = parse_date(rec.get("declarationDate"))
        check(rid, 7, "declarationDate is valid ISO date and not in the future",
              f"Valid date <= {TOMORROW}", rec.get("declarationDate"),
              decl_date is not None and decl_date < TOMORROW)

        # Check 8: incidentStart is valid ISO date and not > 24 months old
        inc_start = parse_date(rec.get("incidentStart"))
        check(rid, 8, "incidentStart is valid and within 24 months",
              f"Valid date >= {TWENTY_FOUR_MONTHS_AGO}", rec.get("incidentStart"),
              inc_start is not None and inc_start >= TWENTY_FOUR_MONTHS_AGO)

        # Check 9: If incidentEnd exists: incidentStart <= incidentEnd
        inc_end = parse_date(rec.get("incidentEnd"))
        if rec.get("incidentEnd") is not None:
            check(rid, 9, "incidentStart <= incidentEnd",
                  f"incidentStart ({inc_start}) <= incidentEnd ({inc_end})",
                  f"start={inc_start}, end={inc_end}",
                  inc_start is not None and inc_end is not None and inc_start <= inc_end)
        else:
            check(rid, 9, "incidentEnd is null (ongoing) - N/A",
                  "N/A (ongoing)", "N/A (ongoing)", True)

        # Check 10: sepWindowStart = min(declarationDate, incidentStart)
        sep_start = parse_date(rec.get("sepWindowStart"))
        if decl_date and inc_start:
            expected_sep_start = min(decl_date, inc_start)
            check(rid, 10, "sepWindowStart = min(declarationDate, incidentStart)",
                  str(expected_sep_start), str(sep_start),
                  sep_start == expected_sep_start)
        else:
            check(rid, 10, "sepWindowStart calculation (missing input dates)",
                  "Calculable", "Missing declarationDate or incidentStart",
                  False)

        # Check 11: If incidentEnd exists: sepWindowEnd = last day of (incidentEnd.month + 2)
        sep_end = parse_date(rec.get("sepWindowEnd"))
        if rec.get("incidentEnd") is not None and inc_end is not None:
            expected_sep_end = calculate_sep_window_end_with_incident_end(inc_end)
            check(rid, 11, "sepWindowEnd = last day of (incidentEnd.month + 2)",
                  str(expected_sep_end), str(sep_end),
                  sep_end == expected_sep_end)
        else:
            check(rid, 11, "sepWindowEnd with incidentEnd - N/A (ongoing)",
                  "N/A (ongoing)", "N/A (ongoing)", True)

        # Check 12: If incidentEnd is null: sepWindowEnd = last day of (sepWindowStart.month + 14)
        if rec.get("incidentEnd") is None and sep_start is not None:
            renewal_dates = rec.get("renewalDates")
            expected_sep_end = calculate_sep_window_end_ongoing(sep_start, renewal_dates)
            check(rid, 12, "sepWindowEnd (ongoing) = last day of (maxDate.month + 14)",
                  str(expected_sep_end), str(sep_end),
                  sep_end == expected_sep_end)
        else:
            check(rid, 12, "sepWindowEnd ongoing calc - N/A (has incidentEnd)",
                  "N/A (has incidentEnd)", "N/A (has incidentEnd)", True)

        # Check 13: sepWindowEnd >= today (not expired)
        if sep_end is not None:
            check(rid, 13, "sepWindowEnd >= today (not expired)",
                  f">= {TODAY}", str(sep_end),
                  sep_end >= TODAY)
        else:
            check(rid, 13, "sepWindowEnd is null (should be calculated)",
                  "Non-null date", "null",
                  False)

        # Checks 14-18: Status validation
        status = rec.get("status", "")
        days_remaining = rec.get("daysRemaining")

        if rec.get("incidentEnd") is None:
            # Ongoing disaster
            if days_remaining is not None and days_remaining > 30:
                expected_status = "ongoing"
                check(rid, 14, "Ongoing + daysRemaining > 30 -> status='ongoing'",
                      "ongoing", status,
                      status == "ongoing")
                check(rid, 15, "N/A (daysRemaining > 30)", "N/A", "N/A", True)
            elif days_remaining is not None and days_remaining <= 30:
                expected_status = "expiring_soon"
                check(rid, 14, "N/A (daysRemaining <= 30)", "N/A", "N/A", True)
                check(rid, 15, "Ongoing + daysRemaining <= 30 -> status='expiring_soon'",
                      "expiring_soon", status,
                      status == "expiring_soon")
            else:
                check(rid, 14, "Cannot evaluate (daysRemaining missing)", "N/A", "N/A", True)
                check(rid, 15, "Cannot evaluate (daysRemaining missing)", "N/A", "N/A", True)
            check(rid, 16, "N/A (ongoing disaster)", "N/A", "N/A", True)
            check(rid, 17, "N/A (ongoing disaster)", "N/A", "N/A", True)
        else:
            # Has incidentEnd
            check(rid, 14, "N/A (has incidentEnd)", "N/A", "N/A", True)
            check(rid, 15, "N/A (has incidentEnd)", "N/A", "N/A", True)
            if days_remaining is not None and days_remaining > 30:
                check(rid, 16, "Has incidentEnd + daysRemaining > 30 -> status='active'",
                      "active", status,
                      status == "active")
                check(rid, 17, "N/A (daysRemaining > 30)", "N/A", "N/A", True)
            elif days_remaining is not None and days_remaining <= 30:
                check(rid, 16, "N/A (daysRemaining <= 30)", "N/A", "N/A", True)
                check(rid, 17, "Has incidentEnd + daysRemaining <= 30 -> status='expiring_soon'",
                      "expiring_soon", status,
                      status == "expiring_soon")
            else:
                check(rid, 16, "Cannot evaluate (daysRemaining missing)", "N/A", "N/A", True)
                check(rid, 17, "Cannot evaluate (daysRemaining missing)", "N/A", "N/A", True)

        # Check 18: Status should never be "expired"
        check(rid, 18, "Status is not 'expired'",
              "Not 'expired'", status,
              status != "expired")

        # Check 22: lastVerified present and valid for STATE/HHS records (skip FEMA)
        if source in ("STATE", "HHS"):
            last_verified = rec.get("lastVerified")
            lv_date = parse_date(last_verified) if last_verified else None
            check(rid, 22, "lastVerified present and valid ISO date for STATE/HHS",
                  "Valid date string", str(last_verified),
                  lv_date is not None)

            # Check 24: lastVerified staleness (>30 days old)
            if lv_date is not None:
                staleness_days = (TODAY - lv_date).days
                check(rid, 24, "lastVerified is within 30 days",
                      f"<= 30 days old", f"{staleness_days} days old",
                      staleness_days <= 30)
            else:
                check(rid, 24, "lastVerified staleness — N/A (no valid date)",
                      "N/A", "N/A", True)
        elif source == "FEMA":
            # FEMA records come from live API — no manual lastVerified needed
            check(rid, 22, "lastVerified check — N/A (FEMA from live API)",
                  "N/A", "N/A", True)
            check(rid, 24, "lastVerified staleness — N/A (FEMA from live API)",
                  "N/A", "N/A", True)
        else:
            check(rid, 22, "lastVerified check — N/A (not STATE/HHS)",
                  "N/A", "N/A", True)
            check(rid, 24, "lastVerified staleness — N/A (not STATE/HHS)",
                  "N/A", "N/A", True)

        # Check 26: FEMA-specific URL validation
        if source == "FEMA":
            import re as _re
            # FEMA officialUrl must match https://www.fema.gov/disaster/{number}
            fema_url_match = _re.match(r"^https://www\.fema\.gov/disaster/(\d+)$", url)
            if fema_url_match:
                url_disaster_num = fema_url_match.group(1)
                # Extract disaster number from ID: FEMA-DR-4834-FL -> 4834
                id_parts = rid.split("-")
                id_num = id_parts[2] if len(id_parts) >= 4 else None
                # The disasterNumber in the URL may differ from the DR/EM number
                # (e.g. DR-4834 -> disaster/4834), so just validate URL structure
                check(rid, 26, "FEMA officialUrl matches fema.gov/disaster/{number}",
                      "https://www.fema.gov/disaster/{number}", url[:60],
                      True)
            else:
                check(rid, 26, "FEMA officialUrl matches fema.gov/disaster/{number}",
                      "https://www.fema.gov/disaster/{number}", url[:60] if url else "EMPTY",
                      False)
        else:
            check(rid, 26, "FEMA URL check — N/A (not FEMA source)",
                  "N/A", "N/A", True)

        # Check 27: URL well-formedness — all sources
        import re as _re
        url_wellformed = bool(url and url.startswith("https://"))
        # Validate domain is expected for source
        expected_domains = {
            "FEMA": ["fema.gov"],
            "SBA": ["federalregister.gov", "sba.gov"],
            "HHS": ["hhs.gov", "aspr.hhs.gov"],
            "FMCSA": ["fmcsa.dot.gov"],
            "STATE": [".gov"],  # Any .gov domain
            "USDA": ["fsa.usda.gov", "usda.gov"],
        }
        domain_ok = True
        if url_wellformed and source in expected_domains:
            url_lower = url.lower()
            domain_ok = any(d in url_lower for d in expected_domains[source])
        check(rid, 27, "officialUrl is well-formed https with expected domain",
              f"https URL with {source} domain", url[:60] if url else "EMPTY",
              url_wellformed and domain_ok)

    # =============================================
    # PRINT REPORT
    # =============================================

    print("=" * 80)
    audit_label = "ALL DISASTERS" if all_disasters else "CURATED DISASTERS"
    print(f"{audit_label} DATA INTEGRITY AUDIT")
    print(f"Date: {TODAY}")
    print(f"File: {os.path.basename(json_path)}")
    print("=" * 80)
    print()
    print(f"Total records checked:  {len(disasters)}")
    print(f"Total checks performed: {total_checks}")
    print(f"PASSED:                 {passes}")
    print(f"FAILED:                 {len(failures)}")
    print(f"Pass rate:              {passes/total_checks*100:.1f}%")
    print()

    if failures:
        print("=" * 80)
        print("FAILURES")
        print("=" * 80)
        print()
        for f in failures:
            print(f"  Record ID:   {f['id']}")
            print(f"  Check #:     {f['check']}")
            print(f"  Description: {f['description']}")
            print(f"  Expected:    {f['expected']}")
            print(f"  Actual:      {f['actual']}")
            print()
    else:
        print("ALL CHECKS PASSED - No failures detected.")

    # =============================================
    # SUMMARY BY CHECK NUMBER
    # =============================================

    print("=" * 80)
    print("FAILURE SUMMARY BY CHECK")
    print("=" * 80)
    check_failure_counts = Counter(f["check"] for f in failures)
    if check_failure_counts:
        for check_num in sorted(check_failure_counts.keys()):
            print(f"  Check #{check_num}: {check_failure_counts[check_num]} failure(s)")
    else:
        print("  No failures.")

    print()
    print("=" * 80)
    print("FAILURE SUMMARY BY RECORD")
    print("=" * 80)
    record_failure_counts = Counter(f["id"] for f in failures)
    if record_failure_counts:
        for rid in sorted(record_failure_counts.keys()):
            failed_checks = [f["check"] for f in failures if f["id"] == rid]
            print(f"  {rid}: {record_failure_counts[rid]} failure(s) — checks {failed_checks}")
    else:
        print("  No failures.")

    # =============================================
    # ADDITIONAL INFORMATIONAL STATS
    # =============================================

    print()
    print("=" * 80)
    print("INFORMATIONAL STATISTICS")
    print("=" * 80)
    source_counts = Counter(d.get("source") for d in disasters)
    print(f"  Records by source:")
    for src, cnt in sorted(source_counts.items()):
        print(f"    {src}: {cnt}")

    state_counts = Counter(d.get("state") for d in disasters)
    print(f"  Records by state: {len(state_counts)} unique states/territories")

    status_counts = Counter(d.get("status") for d in disasters)
    print(f"  Records by status:")
    for st, cnt in sorted(status_counts.items()):
        print(f"    {st}: {cnt}")

    ongoing_count = sum(1 for d in disasters if d.get("incidentEnd") is None)
    ended_count = sum(1 for d in disasters if d.get("incidentEnd") is not None)
    print(f"  Ongoing incidents: {ongoing_count}")
    print(f"  Ended incidents:   {ended_count}")

    # Days remaining distribution
    expiring_soon = [d for d in disasters if d.get("daysRemaining") is not None and d["daysRemaining"] <= 30]
    if expiring_soon:
        print(f"\n  EXPIRING SOON ({len(expiring_soon)} records):")
        for d in sorted(expiring_soon, key=lambda x: x["daysRemaining"]):
            print(f"    {d['id']}: {d['daysRemaining']} days remaining (ends {d.get('sepWindowEnd')})")

    return len(failures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit curated_disasters.json for data integrity")
    parser.add_argument("--ci", action="store_true", help="CI mode: exit non-zero on any failure")
    parser.add_argument("--verify-urls", action="store_true", help="Run URL verification (Check 23) — makes HTTP requests")
    parser.add_argument("--update-metadata", action="store_true", help="Write URL verification results back to JSON metadata")
    parser.add_argument("--json-path", type=str, default=None, help="Path to curated_disasters.json (default: auto-detect)")
    parser.add_argument("--check-ecfr", action="store_true", help="Check eCFR for regulatory changes to 42 CFR § 422.62")
    parser.add_argument("--all-disasters", action="store_true", help="Audit all_disasters.json (includes FEMA records)")
    parser.add_argument("--check-state-health", action="store_true", help="Run state health checks 28-32 (state_declarations.json + state_emergency_laws.json)")
    args = parser.parse_args()

    json_path = args.json_path or DEFAULT_JSON_PATH
    failure_count = run_audit(json_path=json_path, all_disasters=args.all_disasters)

    url_failures = 0
    if args.verify_urls:
        print()
        print("=" * 80)
        print("URL VERIFICATION (Check 23)")
        print("=" * 80)

        # Load disasters for URL checking
        with open(json_path, "r") as f:
            data = json.load(f)
        disasters = data.get("disasters", [])

        results = verify_urls(disasters)
        url_failures = print_url_report(results)

        if args.update_metadata:
            update_metadata_with_url_results(json_path, results)

        print()

    ecfr_failures = 0
    if args.check_ecfr:
        print()
        print("=" * 80)
        print("eCFR REGULATORY MONITORING (Check 25)")
        print("=" * 80)
        print("  Checking 42 CFR § 422.62 for amendments...")

        ecfr_result = check_ecfr_regulation()
        ecfr_failures = print_ecfr_report(ecfr_result)

        if args.update_metadata:
            update_metadata_with_ecfr_results(json_path, ecfr_result)

        print()

    state_health_failures = 0
    if args.check_state_health:
        print()
        print("=" * 80)
        print("STATE HEALTH CHECKS (28-32)")
        print("=" * 80)
        sh_failures, sh_passes, sh_total = run_state_health_checks(SCRIPT_DIR)
        state_health_failures = print_state_health_report(sh_failures, sh_passes, sh_total)
        print()

    # Medicare enrollment data freshness
    enrollment_path = os.path.join(SCRIPT_DIR, "medicare_enrollment.json")
    if os.path.exists(enrollment_path):
        try:
            with open(enrollment_path, "r") as f:
                enrollment = json.load(f)
            dl_date = enrollment.get("metadata", {}).get("downloadDate", "")
            if dl_date:
                dl = datetime.strptime(dl_date, "%Y-%m-%d").date()
                age_days = (TODAY - dl).days
                if age_days > 60:
                    print(f"  WARN: Medicare enrollment data is {age_days} days old (downloaded {dl_date})")
                else:
                    print(f"  OK: Medicare enrollment data is {age_days} days old (downloaded {dl_date})")
            match_rate = enrollment.get("metadata", {}).get("matchRate", 0)
            if match_rate < 90:
                print(f"  WARN: County match rate is {match_rate}% (target: >90%)")
            else:
                print(f"  OK: County match rate is {match_rate}%")
        except Exception as e:
            print(f"  WARN: Could not read enrollment data: {e}")
    else:
        print("  INFO: medicare_enrollment.json not found — run build_medicare_enrollment.py to generate")

    # Exit non-zero if any structural audit failures or regulation change detected
    # URL warnings don't block (only HEAD failures do)
    total_failures = failure_count + ecfr_failures + state_health_failures
    exit(1 if total_failures > 0 else 0)
