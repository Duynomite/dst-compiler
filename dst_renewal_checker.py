#!/usr/bin/env python3
"""
DST Renewal Checker — Auto-detect extensions, terminations, and new declarations.

Scans governor EO archive pages using state-specific strategies:
  Strategy 1: Predicted URL check (TX — monthly, predictable URL slugs)
  Strategy 2: Sequential EO check (NY, FL — numbered EOs)
  Strategy 3: Archive page keyword scan (all other states)
  Strategy 4: New declaration discovery (scan for disasters we don't have)

Auto-applies findings to curated_disasters.json when --auto-apply is set.

Usage:
  python3 dst_renewal_checker.py                # Report only
  python3 dst_renewal_checker.py --auto-apply   # Find + apply changes
  python3 dst_renewal_checker.py --state TX     # Check one state only
"""

import json
import re
import sys
import time
import argparse
import calendar
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

CURATED_FILE = Path(__file__).parent / "curated_disasters.json"
USER_AGENT = "DST-RenewalChecker/1.0 (CPC Medicare Compliance Tool)"
REQUEST_TIMEOUT = 20

MONTH_NAMES = {
    1: "january", 2: "february", 3: "march", 4: "april",
    5: "may", 6: "june", 7: "july", 8: "august",
    9: "september", 10: "october", 11: "november", 12: "december",
}

# ==========================================================================
# Governor EO Archive URLs
# ==========================================================================
STATE_EO_ARCHIVES = {
    "TX": "https://gov.texas.gov/news/category/proclamation",
    "FL": "https://www.flgov.com/eog/news/executive-orders",
    "NY": "https://www.governor.ny.gov/executive-order",
    "LA": "https://www.doa.la.gov/doa/osr/executive-orders/",
    "CA": "https://www.caloes.ca.gov/office-of-the-director/policy-administration/legal-affairs/emergency-proclamations/",
    "HI": "https://governor.hawaii.gov/emergency-proclamations/",
    "OR": "https://apps.oregon.gov/oregon-newsroom/OR/GOV",
    "NM": "https://www.governor.state.nm.us/about-the-governor/executive-orders/",
    "AZ": "https://azgovernor.gov/executive-orders",
    "MI": "https://www.michigan.gov/whitmer/news/state-orders-and-directives",
    "MO": "https://governor.mo.gov/press-releases",
    "NC": "https://governor.nc.gov/news/executive-orders",
    "SC": "https://governor.sc.gov/executive-orders",
    "WA": "https://governor.wa.gov/office-governor/official-actions/proclamations",
}

# TX predicted URL slugs (Strategy 1)
TX_RECORD_SLUGS = {
    "STATE-2021-001-TX": ("renews", "border-security-disaster-proclamation"),
    "STATE-2024-001-TX": ("amends-renews", "drought-disaster-proclamation"),
    "STATE-2025-001-TX": ("amends-renews", "flooding-disaster-proclamation"),
    "STATE-2025-002-TX": ("amends-renews", "fire-weather-conditions-disaster-proclamation"),
}

# Keywords for finding new declarations
EMERGENCY_KEYWORDS = [
    "state of emergency", "disaster declaration", "emergency proclamation",
    "executive order", "disaster emergency", "emergency declaration",
    "declares emergency", "declares disaster",
]

TERMINATION_KEYWORDS = [
    "terminated", "rescinded", "expired", "lifted", "revoked",
    "ended", "no longer in effect",
]

RENEWAL_KEYWORDS = [
    "extended", "renewed", "renews", "continuation", "amends",
    "remains in effect", "further extended",
]


def load_records() -> List[Dict]:
    with open(CURATED_FILE) as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("disasters", data.get("records", []))


def save_records(records: List[Dict]):
    with open(CURATED_FILE, "w") as f:
        json.dump(records, f, indent=2)


def fetch_page_text(url: str) -> Optional[str]:
    """Fetch a page and return extracted text. Returns None on failure."""
    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code >= 400:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)
    except Exception:
        return None


def head_check(url: str) -> bool:
    """HEAD check — returns True if URL returns 200-399."""
    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
        return resp.status_code < 400
    except Exception:
        return False


def extract_links(url: str) -> List[Tuple[str, str]]:
    """Fetch a page and extract all links as (href, text) tuples."""
    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code >= 400:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if href.startswith("/"):
                # Make absolute
                parsed = urlparse(url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            links.append((href, text))
        return links
    except Exception:
        return []


# ==========================================================================
# Strategy 1: TX Predicted URL Check
# ==========================================================================

def strategy1_tx_predicted(records: List[Dict]) -> List[Dict]:
    """Check TX records using predicted monthly URL patterns."""
    findings = []
    today = date.today()

    tx_ongoing = [r for r in records if r.get("state") == "TX"
                  and r.get("status") == "ongoing" and r.get("source") == "STATE"
                  and r.get("id") in TX_RECORD_SLUGS]

    for rec in tx_ongoing:
        rid = rec["id"]
        verb, slug = TX_RECORD_SLUGS[rid]

        # Determine expected renewal months (from latest renewal forward)
        renewals = rec.get("renewalDates", [])
        latest = date.fromisoformat(renewals[-1]) if renewals else date.fromisoformat(rec["declarationDate"])

        # Check current month and next month
        for offset in range(0, 3):
            check_month = latest.month + 1 + offset
            check_year = latest.year
            while check_month > 12:
                check_month -= 12
                check_year += 1

            if date(check_year, check_month, 1) > today:
                continue  # future month, skip

            month_name = MONTH_NAMES[check_month]
            predicted_url = f"https://gov.texas.gov/news/post/governor-abbott-{verb}-{slug}-in-{month_name}-{check_year}"

            if head_check(predicted_url):
                # Renewal found!
                renewal_date_str = f"{check_year}-{check_month:02d}-01"
                if renewal_date_str not in (renewals or []):
                    findings.append({
                        "type": "RENEWAL",
                        "strategy": "predicted_url",
                        "record_id": rid,
                        "record_title": rec["title"][:60],
                        "renewal_date": renewal_date_str,
                        "url": predicted_url,
                        "confidence": "HIGH",
                        "message": f"TX renewal found for {month_name} {check_year}",
                    })

        time.sleep(0.3)

    return findings


# ==========================================================================
# Strategy 2: Sequential EO Check (NY, FL)
# ==========================================================================

def strategy2_sequential_eo(records: List[Dict]) -> List[Dict]:
    """Check NY/FL for sequential EO extensions."""
    findings = []

    # --- NY: Check for next sequential EO ---
    ny_ongoing = [r for r in records if r.get("state") == "NY"
                  and r.get("status") == "ongoing" and r.get("source") == "STATE"]

    for rec in ny_ongoing:
        title = rec.get("title", "")
        # Extract EO number from title
        eo_match = re.search(r"EO (\d+)", title)
        if not eo_match:
            continue
        eo_num = int(eo_match.group(1))

        # Check for extensions (EO N.1, N.2) and next EO (N+1)
        for suffix in [".1", ".2", ".3"]:
            ext_url = f"https://www.governor.ny.gov/executive-order/no-{eo_num}{suffix.replace('.', '')}"
            # NY uses "no-521" for EO 52.1 — check this pattern
            # Actually NY uses "no-571" for EO 57.1
            ext_num = f"{eo_num}{suffix.replace('.', '')}"
            ext_url = f"https://www.governor.ny.gov/executive-order/no-{ext_num}"

            text = fetch_page_text(ext_url)
            if text and len(text) > 200:
                # Found an extension
                terminated = any(kw in text.lower() for kw in TERMINATION_KEYWORDS)
                findings.append({
                    "type": "TERMINATION" if terminated else "EXTENSION_FOUND",
                    "strategy": "sequential_eo",
                    "record_id": rec["id"],
                    "record_title": rec["title"][:60],
                    "url": ext_url,
                    "eo_extension": f"EO {eo_num}{suffix}",
                    "confidence": "HIGH",
                    "message": f"Found EO {eo_num}{suffix} — {'terminated' if terminated else 'extension'}",
                })
                break  # found the latest extension
            time.sleep(0.3)

    # --- FL: Check EO listing page for new disaster-related EOs ---
    fl_ongoing = [r for r in records if r.get("state") == "FL"
                  and r.get("status") == "ongoing" and r.get("source") == "STATE"]

    if fl_ongoing:
        fl_links = extract_links("https://www.flgov.com/eog/news/executive-orders")
        for rec in fl_ongoing:
            # Extract disaster keywords from title
            title_lower = rec["title"].lower()
            disaster_keywords = []
            for kw in ["debby", "helene", "milton", "immigration", "wildfire", "drought", "cold front"]:
                if kw in title_lower:
                    disaster_keywords.append(kw)

            if not disaster_keywords:
                continue

            # Check FL EO links for references to this disaster
            for href, link_text in fl_links:
                link_lower = link_text.lower()
                if any(kw in link_lower for kw in disaster_keywords):
                    # Check if this is a NEW EO we don't know about
                    eo_match = re.search(r"(\d{2,4})-(\d+)", href)
                    if eo_match:
                        findings.append({
                            "type": "EXTENSION_FOUND",
                            "strategy": "sequential_eo",
                            "record_id": rec["id"],
                            "record_title": rec["title"][:60],
                            "url": href,
                            "confidence": "MEDIUM",
                            "message": f"FL EO reference found: {link_text[:60]}",
                        })

    return findings


# ==========================================================================
# Strategy 3: Archive Page Keyword Scan
# ==========================================================================

def strategy3_keyword_scan(records: List[Dict]) -> List[Dict]:
    """Scan governor EO archive pages for extension/termination keywords."""
    findings = []

    # Group ongoing STATE records by state
    by_state: Dict[str, List[Dict]] = {}
    for rec in records:
        if rec.get("status") == "ongoing" and rec.get("source") == "STATE":
            st = rec.get("state", "")
            if st not in by_state:
                by_state[st] = []
            by_state[st].append(rec)

    # Skip states already handled by Strategy 1/2
    skip_states = set(TX_RECORD_SLUGS.values())  # TX handled by Strategy 1
    skip_strategy2 = {"NY", "FL"}  # Handled by Strategy 2

    for state, state_recs in sorted(by_state.items()):
        if state in skip_strategy2:
            continue
        if state == "TX":
            continue  # handled by Strategy 1

        archive_url = STATE_EO_ARCHIVES.get(state)
        if not archive_url:
            continue

        text = fetch_page_text(archive_url)
        if not text:
            continue

        text_lower = text.lower()

        for rec in state_recs:
            title = rec.get("title", "")
            # Extract EO number or disaster name keywords
            eo_match = re.search(r"(?:EO|OE|JML|JBE)\s*[-\s]?\d+[-\d]*", title)
            eo_ref = eo_match.group(0) if eo_match else ""

            # Extract disaster name keywords
            name_keywords = []
            for word in ["hurricane", "wildfire", "fire", "flood", "tornado", "drought",
                         "storm", "blizzard", "immigration", "crime", "sewer", "water",
                         "lahaina", "ida", "debby", "helene", "milton"]:
                if word in title.lower():
                    name_keywords.append(word)

            # Search archive page for this disaster
            found_renewal = False
            found_termination = False

            if eo_ref and eo_ref.lower() in text_lower:
                # EO number mentioned on archive page
                # Check surrounding context for renewal/termination
                idx = text_lower.find(eo_ref.lower())
                context = text_lower[max(0, idx - 200):idx + 200]

                if any(kw in context for kw in TERMINATION_KEYWORDS):
                    found_termination = True
                elif any(kw in context for kw in RENEWAL_KEYWORDS):
                    found_renewal = True

            if found_termination:
                findings.append({
                    "type": "TERMINATION",
                    "strategy": "keyword_scan",
                    "record_id": rec["id"],
                    "record_title": rec["title"][:60],
                    "url": archive_url,
                    "confidence": "MEDIUM",
                    "message": f"Archive page mentions {eo_ref} with termination language",
                })
            elif found_renewal:
                findings.append({
                    "type": "EXTENSION_FOUND",
                    "strategy": "keyword_scan",
                    "record_id": rec["id"],
                    "record_title": rec["title"][:60],
                    "url": archive_url,
                    "confidence": "MEDIUM",
                    "message": f"Archive page mentions {eo_ref} with renewal language",
                })

        time.sleep(0.5)

    return findings


# ==========================================================================
# Strategy 4: New Declaration Discovery
# ==========================================================================

def strategy4_new_declarations(records: List[Dict]) -> List[Dict]:
    """Scan governor EO archives for NEW declarations we don't have."""
    findings = []
    today = date.today()
    cutoff = today - timedelta(days=60)

    # Get existing record IDs by state
    existing_by_state: Dict[str, set] = {}
    for rec in records:
        st = rec.get("state", "")
        if st not in existing_by_state:
            existing_by_state[st] = set()
        existing_by_state[st].add(rec.get("title", "").lower())

    # Scan key states' archive pages
    for state, archive_url in STATE_EO_ARCHIVES.items():
        links = extract_links(archive_url)
        if not links:
            continue

        for href, link_text in links:
            link_lower = link_text.lower()

            # Must have DISASTER-specific keywords (not just "executive order")
            DISASTER_KEYWORDS = [
                "state of emergency", "disaster declaration", "emergency proclamation",
                "disaster emergency", "emergency declaration", "declares emergency",
                "declares disaster", "hurricane", "wildfire", "fire", "flood",
                "tornado", "storm", "drought", "earthquake", "tsunami",
                "blizzard", "severe weather", "winter weather",
            ]
            is_disaster = any(kw in link_lower for kw in DISASTER_KEYWORDS)
            # Filter out non-disaster EOs
            is_noise = any(kw in link_lower for kw in [
                "extends executive order", "suspension", "assignment",
                "re:", "judicial", "appointment", "personnel", "clemency",
                "pardon", "commut", "extradition", "rural area",
                "opportunity", "budget", "redistricting", "election",
            ])
            if not is_disaster or is_noise:
                continue

            # Skip links with very short text (just EO numbers, no context)
            if len(link_text) < 20:
                continue

            # Check if it's recent (has a 2026 or late 2025 date reference)
            has_recent_date = "2026" in link_text or "2025" in link_text
            if not has_recent_date:
                continue

            # Check if we already have this
            existing_titles = existing_by_state.get(state, set())
            already_known = any(
                len(set(link_lower.split()) & set(t.split())) >= 3
                for t in existing_titles
            )
            if already_known:
                continue

            # Verify URL works
            if not head_check(href):
                continue

            findings.append({
                "type": "NEW_DECLARATION",
                "strategy": "discovery",
                "state": state,
                "title": link_text[:80],
                "url": href,
                "confidence": "MEDIUM",
                "message": f"Potential new {state} declaration: {link_text[:60]}",
            })

        time.sleep(0.5)

    # --- FEMA cross-check: new federal disasters without STATE records ---
    try:
        cutoff_str = cutoff.isoformat()
        params = {
            "$filter": f"declarationDate ge '{cutoff_str}' and (declarationType eq 'DR' or declarationType eq 'EM')",
            "$select": "femaDeclarationString,declarationTitle,state,declarationDate",
            "$top": 50,
            "$orderby": "declarationDate desc",
        }
        resp = requests.get("https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries",
                            params=params, timeout=15)
        if resp.status_code == 200:
            fema_data = resp.json().get("DisasterDeclarationsSummaries", [])
            # Deduplicate by declaration string
            seen = set()
            for d in fema_data:
                key = d.get("femaDeclarationString", "")
                if key in seen:
                    continue
                seen.add(key)

                state = d.get("state", "")
                # Check if we have a STATE record for this state
                state_records = [r for r in records if r.get("state") == state and r.get("source") == "STATE"]
                fema_title = d.get("declarationTitle", "").lower()

                # Check if any STATE record matches this FEMA disaster
                has_match = False
                for sr in state_records:
                    sr_title = sr.get("title", "").lower()
                    # Check for keyword overlap
                    fema_words = set(w for w in fema_title.split() if len(w) > 3)
                    sr_words = set(w for w in sr_title.split() if len(w) > 3)
                    if len(fema_words & sr_words) >= 2:
                        has_match = True
                        break

                if not has_match and state_records:
                    # FEMA has a disaster but we might not have the matching STATE record
                    pass  # Don't flag if state has other records — may be different event
                elif not has_match and not state_records:
                    findings.append({
                        "type": "FEMA_GAP",
                        "strategy": "fema_crosscheck",
                        "state": state,
                        "fema_id": key,
                        "title": d.get("declarationTitle", ""),
                        "url": f"https://www.fema.gov/disaster/{key.split('-')[1] if '-' in key else key}",
                        "confidence": "MEDIUM",
                        "message": f"FEMA {key} in {state} but no STATE record found",
                    })
    except Exception:
        pass

    return findings


# ==========================================================================
# Auto-Apply Logic
# ==========================================================================

def auto_apply(records: List[Dict], findings: List[Dict]) -> int:
    """Apply verified findings to curated_disasters.json. Returns count of changes."""
    changes = 0
    today_str = date.today().isoformat()

    for finding in findings:
        if finding.get("confidence") not in ("HIGH", "MEDIUM"):
            continue

        rid = finding.get("record_id")
        ftype = finding.get("type")

        if ftype == "RENEWAL" and rid:
            # Find the record and add renewal date
            for rec in records:
                if rec.get("id") == rid:
                    renewal_date = finding.get("renewal_date")
                    url = finding.get("url")

                    if not rec.get("renewalDates"):
                        rec["renewalDates"] = []
                    if renewal_date and renewal_date not in rec["renewalDates"]:
                        rec["renewalDates"].append(renewal_date)
                        rec["renewalDates"].sort()

                        # Update URL to latest renewal
                        if url and head_check(url):
                            rec["officialUrl"] = url

                        rec["lastVerified"] = today_str
                        changes += 1
                        print(f"  AUTO-RENEWED: {rid} — {finding.get('message')}")
                    break

        # Note: TERMINATION and NEW_DECLARATION findings are flagged but not auto-applied
        # to curated_disasters.json directly — they need fetcher CORRECTIONS table entries
        # or new build_record() calls, which require human review.

    return changes


# ==========================================================================
# Report
# ==========================================================================

def print_report(findings: List[Dict]):
    print(f"\n{'='*60}")
    print(f"DST RENEWAL CHECK — {date.today().isoformat()}")
    print(f"{'='*60}")

    renewals = [f for f in findings if f["type"] == "RENEWAL"]
    extensions = [f for f in findings if f["type"] == "EXTENSION_FOUND"]
    terminations = [f for f in findings if f["type"] == "TERMINATION"]
    new_decls = [f for f in findings if f["type"] == "NEW_DECLARATION"]
    fema_gaps = [f for f in findings if f["type"] == "FEMA_GAP"]

    print(f"\nRenewals found: {len(renewals)}")
    for f in renewals:
        print(f"  {f.get('record_id', '?')}: {f['message']}")
        print(f"    URL: {f.get('url', '?')}")

    print(f"\nExtensions found: {len(extensions)}")
    for f in extensions:
        print(f"  {f.get('record_id', '?')}: {f['message']}")

    print(f"\nTerminations found: {len(terminations)}")
    for f in terminations:
        print(f"  {f.get('record_id', '?')}: {f['message']}")

    print(f"\nNew declarations discovered: {len(new_decls)}")
    for f in new_decls:
        print(f"  {f.get('state', '?')}: {f.get('title', '?')}")
        print(f"    URL: {f.get('url', '?')}")

    if fema_gaps:
        print(f"\nFEMA gaps (federal disaster, no STATE record): {len(fema_gaps)}")
        for f in fema_gaps:
            print(f"  {f.get('state', '?')}: {f.get('fema_id', '?')} — {f.get('title', '?')}")

    if not findings:
        print("\n  No changes detected.")

    print(f"\n{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="DST Renewal Checker")
    parser.add_argument("--auto-apply", action="store_true", help="Auto-apply verified findings")
    parser.add_argument("--state", type=str, help="Check one state only")
    parser.add_argument("--json-output", type=str, help="Write findings to JSON file")
    args = parser.parse_args()

    print(f"DST Renewal Checker — {date.today().isoformat()}")

    records = load_records()
    print(f"Loaded {len(records)} curated records")

    ongoing_state = [r for r in records if r.get("status") == "ongoing" and r.get("source") == "STATE"]
    print(f"Ongoing STATE records: {len(ongoing_state)}")

    if args.state:
        records = [r for r in records if r.get("state") == args.state]
        print(f"Filtered to state: {args.state}")

    all_findings = []

    # Strategy 1: TX predicted URLs
    print("\n--- Strategy 1: TX Predicted URL Check ---")
    findings = strategy1_tx_predicted(records)
    all_findings.extend(findings)
    print(f"  Found: {len(findings)}")

    # Strategy 2: Sequential EO check (NY, FL)
    print("\n--- Strategy 2: Sequential EO Check (NY, FL) ---")
    findings = strategy2_sequential_eo(records)
    all_findings.extend(findings)
    print(f"  Found: {len(findings)}")

    # Strategy 3: Archive page keyword scan
    print("\n--- Strategy 3: Archive Page Keyword Scan ---")
    findings = strategy3_keyword_scan(records)
    all_findings.extend(findings)
    print(f"  Found: {len(findings)}")

    # Strategy 4: New declaration discovery
    print("\n--- Strategy 4: New Declaration Discovery ---")
    findings = strategy4_new_declarations(records)
    all_findings.extend(findings)
    print(f"  Found: {len(findings)}")

    # Report
    print_report(all_findings)

    # Auto-apply
    if args.auto_apply and all_findings:
        records_full = load_records()  # reload full dataset
        changes = auto_apply(records_full, all_findings)
        if changes > 0:
            save_records(records_full)
            print(f"\nAUTO-APPLIED: {changes} changes to curated_disasters.json")
        else:
            print("\nNo auto-applicable changes.")

    # JSON output
    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump(all_findings, f, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
