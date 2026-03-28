#!/usr/bin/env python3
"""
DST Verifier — Reads every declaration page to verify data accuracy.

Three verification layers:
  Layer 1: FEMA API cross-reference (incidentEndDate comparison)
  Layer 2: Declaration page content verification (HTML + PDF)
  Layer 3: State EO archive staleness check

Outputs a verification report with corrections needed, broken URLs,
and stale ongoing records.

Usage:
  python3 dst_verifier.py                  # Full verification
  python3 dst_verifier.py --fema-only      # Layer 1 only (fast)
  python3 dst_verifier.py --pages-only     # Layer 2 only
  python3 dst_verifier.py --staleness-only # Layer 3 only
"""

import json
import re
import sys
import time
import hashlib
import argparse
import calendar
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    print("WARNING: pdfplumber not installed. PDF verification will be skipped.")

# --- Configuration ---
CURATED_FILE = Path(__file__).parent / "curated_disasters.json"
HASHES_FILE = Path(__file__).parent / "verification_hashes.json"
FEMA_API = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
REQUEST_TIMEOUT = 20
USER_AGENT = "DST-Verifier/1.0 (CPC Medicare Compliance Tool)"

# Domains known to block bots
BOT_BLOCKED_DOMAINS = {"fmcsa.dot.gov", "flgov.com"}

# State emergency duration limits (imported concept from fetcher)
STATE_EMERGENCY_DURATION = {
    "KS": 15, "NV": 15, "ME": 14, "IN": 30, "KY": 30, "MD": 30,
    "NY": 30, "LA": 30, "TX": 30, "FL": 60, "WI": 60, "PA": 90, "AZ": 120,
}

# Status keywords that indicate a declaration has ended or been extended
ENDED_KEYWORDS = [
    "terminated", "rescinded", "expired", "lifted", "revoked",
    "ended", "concluded", "no longer in effect",
    "100% contained", "fully contained", "100 percent contained",
]
EXTENDED_KEYWORDS = [
    "extended", "renewed", "continuation", "amended to extend",
    "remains in effect", "further extended",
]

# Date patterns for extraction
DATE_PATTERNS = [
    r"(\w+ \d{1,2},?\s*\d{4})",          # January 15, 2026
    r"(\d{1,2}/\d{1,2}/\d{4})",           # 1/15/2026
    r"(\d{4}-\d{2}-\d{2})",               # 2026-01-15
    r"(\w+ \d{1,2},?\s*\d{2}(?!\d))",     # January 15, 26
]


def load_records() -> List[Dict]:
    """Load curated disaster records."""
    with open(CURATED_FILE) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("disasters", data.get("records", []))


def load_hashes() -> Dict[str, str]:
    """Load previous content hashes."""
    if HASHES_FILE.exists():
        with open(HASHES_FILE) as f:
            return json.load(f)
    return {}


def save_hashes(hashes: Dict[str, str]):
    """Save content hashes for next run."""
    with open(HASHES_FILE, "w") as f:
        json.dump(hashes, f, indent=2)


def sep_end_for(incident_end_str: str) -> date:
    """Calculate SEP window end per 42 CFR 422.62(b)(18)."""
    d = date.fromisoformat(incident_end_str[:10])
    month = d.month + 2
    year = d.year
    if month > 12:
        month -= 12
        year += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def normalize_title(title: str) -> str:
    """Normalize a disaster title for fuzzy matching."""
    t = title.lower()
    t = re.sub(r"\(.*?\)", "", t)
    t = re.sub(r"(dr|em|fm|eo|oe)[-\s]?\d+[-\s]?", "", t)
    t = re.sub(r"governor\s+\w+\s+(emergency|disaster|proclamation|declaration)", "", t)
    return t.strip()


def fetch_page(url: str) -> Tuple[Optional[str], str, Optional[bytes]]:
    """Fetch a URL. Returns (text_content, content_type, raw_bytes).

    For HTML: returns (extracted_text, 'html', None)
    For PDF: returns (None, 'pdf', raw_bytes)
    For errors: returns (None, 'error:...', None)
    """
    headers = {"User-Agent": USER_AGENT}

    # Check for bot-blocked domains
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower()
    for blocked in BOT_BLOCKED_DOMAINS:
        if blocked in domain:
            return None, f"blocked:{blocked}", None

    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT,
                            allow_redirects=True)
        if resp.status_code >= 400:
            return None, f"error:{resp.status_code}", None

        content_type = resp.headers.get("Content-Type", "").lower()

        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return None, "pdf", resp.content

        # HTML — extract text
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove script/style
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return text, "html", None

    except requests.exceptions.SSLError:
        return None, "error:ssl", None
    except requests.exceptions.Timeout:
        return None, "error:timeout", None
    except requests.exceptions.ConnectionError:
        return None, "error:connection", None
    except Exception as e:
        return None, f"error:{type(e).__name__}", None


def extract_pdf_text(pdf_bytes: bytes) -> Optional[str]:
    """Extract text from PDF bytes using pdfplumber."""
    if not HAS_PDFPLUMBER:
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(pdf_bytes)
            tmp.flush()
            with pdfplumber.open(tmp.name) as pdf:
                texts = []
                for page in pdf.pages[:10]:  # max 10 pages
                    t = page.extract_text()
                    if t:
                        texts.append(t)
                return " ".join(texts) if texts else None
    except Exception:
        return None


def scan_for_keywords(text: str, keywords: List[str]) -> List[str]:
    """Scan text for keywords. Returns list of found keywords."""
    text_lower = text.lower()
    found = []
    for kw in keywords:
        if kw in text_lower:
            found.append(kw)
    return found


def check_content_relevance(text: str, record: Dict) -> bool:
    """Check if page content is relevant to the disaster record."""
    text_lower = text.lower()
    title = record.get("title", "").lower()
    state = record.get("state", "").lower()
    incident_type = record.get("incidentType", "").lower()

    # Extract keywords from title
    title_words = [w for w in normalize_title(title).split() if len(w) > 3]

    # Check: does the page mention the state AND at least 2 title keywords?
    state_found = state in text_lower
    keyword_hits = sum(1 for w in title_words if w in text_lower)

    # Also check incident type
    type_found = incident_type in text_lower if incident_type else False

    return state_found and (keyword_hits >= 2 or type_found)


def extract_dates_from_text(text: str) -> List[str]:
    """Extract date-like strings from text."""
    dates = []
    for pattern in DATE_PATTERNS:
        matches = re.findall(pattern, text)
        dates.extend(matches)
    return dates[:20]  # cap at 20 to avoid noise


# ============================================================
# Layer 1: FEMA API Cross-Reference
# ============================================================

def layer1_fema_crossref(records: List[Dict]) -> List[Dict]:
    """Cross-reference STATE records against FEMA API for incidentEndDate."""
    print("\n--- Layer 1: FEMA API Cross-Reference ---")

    state_records = [r for r in records if r.get("source") == "STATE"]
    print(f"  STATE records to check: {len(state_records)}")

    # Get unique states
    states = set(r.get("state", "") for r in state_records)

    # Fetch FEMA data for each state (batched)
    fema_by_state: Dict[str, List[Dict]] = {}
    cutoff = (date.today() - timedelta(days=730)).isoformat()  # 2 years back

    for st in sorted(states):
        try:
            params = {
                "$filter": f"state eq '{st}' and declarationDate ge '{cutoff}'",
                "$select": "femaDeclarationString,declarationTitle,declarationType,"
                           "incidentBeginDate,incidentEndDate,state,declarationDate",
                "$top": 100,
                "$orderby": "declarationDate desc",
            }
            resp = requests.get(FEMA_API, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json().get("DisasterDeclarationsSummaries", [])
                # Deduplicate by declaration string
                seen = set()
                unique = []
                for d in data:
                    key = d.get("femaDeclarationString", "")
                    if key not in seen:
                        seen.add(key)
                        unique.append(d)
                fema_by_state[st] = unique
        except Exception:
            pass
        time.sleep(0.2)  # rate limit

    findings = []
    matched = 0
    discrepancies = 0

    for rec in state_records:
        st = rec.get("state", "")
        fema_records = fema_by_state.get(st, [])
        if not fema_records:
            continue

        rec_start = rec.get("incidentStart", "")
        rec_title = normalize_title(rec.get("title", ""))
        rec_end = rec.get("incidentEnd")
        rec_status = rec.get("status", "")

        # Try to match against FEMA records
        best_match = None
        best_score = 0

        for fema in fema_records:
            fema_title = normalize_title(fema.get("declarationTitle", ""))
            fema_start = (fema.get("incidentBeginDate") or "")[:10]

            # Score: title similarity + date proximity
            title_score = SequenceMatcher(None, rec_title, fema_title).ratio()

            date_score = 0
            if rec_start and fema_start:
                try:
                    diff = abs((date.fromisoformat(rec_start) -
                                date.fromisoformat(fema_start)).days)
                    if diff <= 7:
                        date_score = 1.0
                    elif diff <= 30:
                        date_score = 0.5
                    elif diff <= 90:
                        date_score = 0.2
                except ValueError:
                    pass

            combined = title_score * 0.6 + date_score * 0.4
            if combined > best_score:
                best_score = combined
                best_match = fema

        if best_match and best_score >= 0.45:
            matched += 1
            fema_end = (best_match.get("incidentEndDate") or "")[:10]

            # Skip false positives: if FEMA declaration year differs by >1 from ours
            fema_decl = (best_match.get("declarationDate") or "")[:10]
            if fema_decl and rec_start:
                try:
                    year_diff = abs(date.fromisoformat(fema_decl).year -
                                    date.fromisoformat(rec_start).year)
                    if year_diff > 1:
                        continue  # wrong disaster match
                except ValueError:
                    pass

            # Note: FEMA incidentEndDate = when the INCIDENT ended (storm passed,
            # fire contained). Governor declarations often persist longer for recovery.
            # Only flag if the governor has NO renewals past the FEMA end date.
            has_renewals_past_fema = False
            if fema_end and rec.get("renewalDates"):
                for rd in rec["renewalDates"]:
                    try:
                        if date.fromisoformat(rd) > date.fromisoformat(fema_end):
                            has_renewals_past_fema = True
                            break
                    except ValueError:
                        pass

            # Check for discrepancy
            if fema_end and rec_status == "ongoing" and not rec_end and not has_renewals_past_fema:
                findings.append({
                    "type": "FEMA_END_DATE",
                    "severity": "HIGH",
                    "record_id": rec["id"],
                    "record_title": rec["title"][:60],
                    "fema_id": best_match.get("femaDeclarationString", ""),
                    "fema_end": fema_end,
                    "our_end": "ongoing",
                    "message": f"FEMA says incident ended {fema_end}, we have ongoing",
                    "match_score": round(best_score, 2),
                })
                discrepancies += 1
            elif fema_end and rec_end and fema_end != rec_end:
                # Date mismatch (both have end dates but they differ)
                try:
                    diff = abs((date.fromisoformat(fema_end) -
                                date.fromisoformat(rec_end)).days)
                    if diff > 7:
                        findings.append({
                            "type": "FEMA_DATE_MISMATCH",
                            "severity": "MEDIUM",
                            "record_id": rec["id"],
                            "record_title": rec["title"][:60],
                            "fema_id": best_match.get("femaDeclarationString", ""),
                            "fema_end": fema_end,
                            "our_end": rec_end,
                            "diff_days": diff,
                            "message": f"End date differs by {diff} days (FEMA: {fema_end}, ours: {rec_end})",
                            "match_score": round(best_score, 2),
                        })
                        discrepancies += 1
                except ValueError:
                    pass

    print(f"  FEMA matches found: {matched}")
    print(f"  Discrepancies: {discrepancies}")
    return findings


# ============================================================
# Layer 2: Declaration Page Content Verification
# ============================================================

def layer2_page_verification(records: List[Dict], prev_hashes: Dict[str, str]) -> Tuple[List[Dict], Dict[str, str]]:
    """Fetch and verify every declaration page."""
    print("\n--- Layer 2: Declaration Page Content Verification ---")

    new_hashes: Dict[str, str] = {}
    findings = []

    # Group by unique URL to avoid duplicate fetches
    url_to_records: Dict[str, List[Dict]] = {}
    for rec in records:
        url = rec.get("officialUrl", "")
        if url:
            if url not in url_to_records:
                url_to_records[url] = []
            url_to_records[url].append(rec)

    total = len(url_to_records)
    print(f"  Unique URLs to check: {total}")

    checked = 0
    passed = 0
    failed = 0
    blocked = 0
    pdf_checked = 0
    content_changed = 0

    for i, (url, recs) in enumerate(url_to_records.items()):
        if i % 20 == 0 and i > 0:
            print(f"  Progress: {i}/{total} URLs checked...")

        rec = recs[0]  # use first record for context
        rid = rec.get("id", "?")

        # Fetch the page
        text, content_type, pdf_bytes = fetch_page(url)

        if content_type.startswith("blocked:"):
            blocked += 1
            # For FMCSA: validate URL structure
            if "fmcsa.dot.gov" in url:
                if "/emergency/" in url or "/emergency-declarations/" in url:
                    passed += 1  # structure valid
                else:
                    findings.append({
                        "type": "URL_STRUCTURE",
                        "severity": "LOW",
                        "record_id": rid,
                        "message": f"FMCSA URL doesn't match expected pattern: {url[:80]}",
                    })
            continue

        if content_type.startswith("error:"):
            failed += 1
            findings.append({
                "type": "URL_BROKEN",
                "severity": "HIGH",
                "record_id": rid,
                "record_title": rec.get("title", "")[:60],
                "url": url[:100],
                "error": content_type,
                "message": f"URL returned {content_type}: {url[:80]}",
            })
            continue

        # Handle PDF
        if content_type == "pdf" and pdf_bytes:
            pdf_checked += 1
            text = extract_pdf_text(pdf_bytes)
            if not text:
                # Can't extract text (scanned image PDF)
                checked += 1
                passed += 1  # URL works, just can't read content
                new_hashes[url] = hashlib.md5(pdf_bytes).hexdigest()
                continue

        if not text:
            checked += 1
            continue

        checked += 1

        # --- Content hash tracking ---
        content_hash = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()
        new_hashes[url] = content_hash
        if url in prev_hashes and prev_hashes[url] != content_hash:
            content_changed += 1
            findings.append({
                "type": "CONTENT_CHANGED",
                "severity": "INFO",
                "record_id": rid,
                "record_title": rec.get("title", "")[:60],
                "message": f"Page content changed since last verification",
            })

        # --- Content relevance check ---
        if len(text) > 100:
            relevant = check_content_relevance(text, rec)
            if not relevant:
                findings.append({
                    "type": "WRONG_CONTENT",
                    "severity": "MEDIUM",
                    "record_id": rid,
                    "record_title": rec.get("title", "")[:60],
                    "url": url[:100],
                    "message": "Page content doesn't match disaster record (wrong page?)",
                })

        # --- Status keyword scan ---
        if rec.get("status") == "ongoing":
            ended = scan_for_keywords(text, ENDED_KEYWORDS)
            if ended:
                findings.append({
                    "type": "ENDED_KEYWORD",
                    "severity": "HIGH",
                    "record_id": rid,
                    "record_title": rec.get("title", "")[:60],
                    "keywords_found": ended,
                    "message": f"Page contains termination language ({', '.join(ended)}) but record is ongoing",
                })

        extended = scan_for_keywords(text, EXTENDED_KEYWORDS)
        if extended and rec.get("status") == "ongoing":
            # Check if we have the extension tracked
            if not rec.get("renewalDates"):
                findings.append({
                    "type": "EXTENSION_FOUND",
                    "severity": "MEDIUM",
                    "record_id": rid,
                    "record_title": rec.get("title", "")[:60],
                    "keywords_found": extended,
                    "message": f"Page mentions extension/renewal but we have no renewalDates",
                })

        passed += 1
        time.sleep(0.3)  # rate limit

    print(f"  Checked: {checked} (HTML: {checked - pdf_checked}, PDF: {pdf_checked})")
    print(f"  Passed: {passed}, Failed: {failed}, Blocked: {blocked}")
    print(f"  Content changed since last run: {content_changed}")

    return findings, new_hashes


# ============================================================
# Layer 3: State EO Archive Staleness Check
# ============================================================

def layer3_staleness_check(records: List[Dict]) -> List[Dict]:
    """Flag ongoing STATE records past their state's auto-expire limit."""
    print("\n--- Layer 3: State EO Archive Staleness Check ---")

    findings = []
    today = date.today()

    ongoing_state = [r for r in records
                     if r.get("status") == "ongoing" and r.get("source") == "STATE"]

    for rec in ongoing_state:
        state = rec.get("state", "")
        duration_limit = STATE_EMERGENCY_DURATION.get(state)
        if not duration_limit:
            # State has no auto-expire — check if >180 days with no renewals
            decl_date = date.fromisoformat(rec["declarationDate"])
            renewals = rec.get("renewalDates", [])
            latest = date.fromisoformat(renewals[-1]) if renewals else decl_date
            days_since = (today - latest).days
            if days_since > 180 and not renewals:
                findings.append({
                    "type": "NO_EXPIRE_STALE",
                    "severity": "LOW",
                    "record_id": rec["id"],
                    "record_title": rec["title"][:60],
                    "state": state,
                    "days_since_activity": days_since,
                    "message": f"No auto-expire state, {days_since}d since declaration, no renewals. Monitor.",
                })
            continue

        # State HAS auto-expire limit
        decl_date = date.fromisoformat(rec["declarationDate"])
        renewals = rec.get("renewalDates", [])
        latest = date.fromisoformat(renewals[-1]) if renewals else decl_date
        days_since = (today - latest).days

        if days_since > duration_limit:
            findings.append({
                "type": "PAST_AUTO_EXPIRE",
                "severity": "HIGH",
                "record_id": rec["id"],
                "record_title": rec["title"][:60],
                "state": state,
                "state_limit_days": duration_limit,
                "days_since_activity": days_since,
                "days_overdue": days_since - duration_limit,
                "message": f"{state} limit={duration_limit}d, last activity {days_since}d ago ({days_since - duration_limit}d overdue). Research extension or termination.",
            })

    stale_count = len([f for f in findings if f["severity"] == "HIGH"])
    monitor_count = len([f for f in findings if f["severity"] == "LOW"])
    print(f"  Past auto-expire (HIGH): {stale_count}")
    print(f"  No-expire stale (monitor): {monitor_count}")

    return findings


# ============================================================
# Report Generation
# ============================================================

def print_report(all_findings: List[Dict], records: List[Dict]):
    """Print the verification report."""
    print("\n" + "=" * 60)
    print("DST VERIFICATION REPORT")
    print(f"Date: {date.today().isoformat()}")
    print(f"Records verified: {len(records)}")
    print("=" * 60)

    # Group by severity
    high = [f for f in all_findings if f.get("severity") == "HIGH"]
    medium = [f for f in all_findings if f.get("severity") == "MEDIUM"]
    low = [f for f in all_findings if f.get("severity") == "LOW"]
    info = [f for f in all_findings if f.get("severity") == "INFO"]

    print(f"\nFindings: {len(high)} HIGH, {len(medium)} MEDIUM, {len(low)} LOW, {len(info)} INFO")

    if high:
        print(f"\n{'='*60}")
        print("HIGH SEVERITY — Action Required")
        print("=" * 60)
        for f in high:
            print(f"\n  [{f['type']}] {f['record_id']}")
            print(f"  {f.get('record_title', '')}")
            print(f"  {f['message']}")
            if f.get("fema_id"):
                print(f"  FEMA: {f['fema_id']} end={f.get('fema_end')}")
            if f.get("keywords_found"):
                print(f"  Keywords: {f['keywords_found']}")

    if medium:
        print(f"\n{'='*60}")
        print("MEDIUM SEVERITY — Review Recommended")
        print("=" * 60)
        for f in medium:
            print(f"\n  [{f['type']}] {f['record_id']}: {f['message']}")

    if low:
        print(f"\n{'='*60}")
        print("LOW SEVERITY — Monitor")
        print("=" * 60)
        for f in low:
            print(f"  [{f['type']}] {f['record_id']}: {f['message']}")

    if info:
        print(f"\n{'='*60}")
        print(f"INFO — {len(info)} content changes detected")
        print("=" * 60)
        for f in info:
            print(f"  {f['record_id']}: {f['message']}")

    if not all_findings:
        print("\n  ALL CLEAR — No issues detected.")

    print(f"\n{'='*60}")
    print("END OF REPORT")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="DST Declaration Page Verifier")
    parser.add_argument("--fema-only", action="store_true", help="Run Layer 1 only")
    parser.add_argument("--pages-only", action="store_true", help="Run Layer 2 only")
    parser.add_argument("--staleness-only", action="store_true", help="Run Layer 3 only")
    parser.add_argument("--json-output", type=str, help="Write findings to JSON file")
    args = parser.parse_args()

    run_all = not (args.fema_only or args.pages_only or args.staleness_only)

    print("DST Verifier — Declaration Page Accuracy Check")
    print(f"Date: {date.today().isoformat()}")

    records = load_records()
    print(f"Loaded {len(records)} curated records")

    all_findings = []

    # Layer 1: FEMA cross-reference
    if run_all or args.fema_only:
        findings = layer1_fema_crossref(records)
        all_findings.extend(findings)

    # Layer 2: Page content verification
    if run_all or args.pages_only:
        prev_hashes = load_hashes()
        findings, new_hashes = layer2_page_verification(records, prev_hashes)
        all_findings.extend(findings)
        save_hashes(new_hashes)

    # Layer 3: Staleness check
    if run_all or args.staleness_only:
        findings = layer3_staleness_check(records)
        all_findings.extend(findings)

    # Report
    print_report(all_findings, records)

    # JSON output
    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump(all_findings, f, indent=2)
        print(f"\nFindings written to {args.json_output}")

    return 1 if any(f.get("severity") == "HIGH" for f in all_findings) else 0


if __name__ == "__main__":
    sys.exit(main())
