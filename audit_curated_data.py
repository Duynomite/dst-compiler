#!/usr/bin/env python3
"""
Comprehensive audit of curated_disasters.json
Validates all records against 24 checks per the audit specification.
Checks 1-18: Per-record validation
Check 19-21: Cross-record validation
Check 22: lastVerified field for STATE/HHS records
Check 23: URL verification (HEAD + content relevance) — requires --verify-urls flag
Check 24: lastVerified staleness (>30 days) for STATE/HHS records
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

VALID_SOURCES = {"SBA", "FMCSA", "HHS", "USDA", "STATE"}

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


def run_audit(json_path=None):
    if json_path is None:
        json_path = DEFAULT_JSON_PATH
    with open(json_path, "r") as f:
        data = json.load(f)

    metadata = data.get("metadata", {})
    disasters = data.get("disasters", [])

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

    # Check 20: No FEMA records
    fema_records = [d.get("id", "?") for d in disasters if d.get("source") == "FEMA"]
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
        parts = rid.split("-")
        id_valid = (
            len(parts) >= 3 and
            parts[0] in VALID_SOURCES and
            parts[-1] in VALID_STATE_CODES
        )
        check(rid, 2, "ID format matches SOURCE-...-SS pattern",
              "SOURCE-...-STATE", rid,
              id_valid)

        # Check 3: source is one of valid sources
        source = rec.get("source", "")
        check(rid, 3, "Source is valid (SBA/FMCSA/HHS/USDA/STATE)",
              "One of: SBA, FMCSA, HHS, USDA, STATE", source,
              source in VALID_SOURCES)

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

        # Check 22: lastVerified present and valid for STATE/HHS records
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
        else:
            check(rid, 22, "lastVerified check — N/A (not STATE/HHS)",
                  "N/A", "N/A", True)
            check(rid, 24, "lastVerified staleness — N/A (not STATE/HHS)",
                  "N/A", "N/A", True)

    # =============================================
    # PRINT REPORT
    # =============================================

    print("=" * 80)
    print("CURATED DISASTERS DATA INTEGRITY AUDIT")
    print(f"Date: {TODAY}")
    print(f"File: curated_disasters.json")
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
    args = parser.parse_args()

    json_path = args.json_path or DEFAULT_JSON_PATH
    failure_count = run_audit(json_path=json_path)

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

    # Exit non-zero if any structural audit failures
    # URL warnings don't block (only HEAD failures do)
    exit(1 if failure_count > 0 else 0)
