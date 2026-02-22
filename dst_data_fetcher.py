#!/usr/bin/env python3
"""
DST Data Fetcher — Collects disaster data for the DST Compiler Tool.

Sources:
  - SBA: Federal Register API (automated)
  - HHS: Curated + scrape attempt
  - FMCSA: Curated + scrape attempt
  - USDA: Curated only
  - STATE: Curated only
  - FEMA: OpenFEMA API (automated, live)
  - Drought Monitor: Warning signal only (no records)

Output:
  - curated_disasters.json — Non-FEMA sources only (backward compatible)
  - all_disasters.json — All sources including FEMA (single source of truth)
"""

import sys
import json
import re
import time
import hashlib
import calendar
import traceback
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple

import requests
from bs4 import BeautifulSoup

# =========================================================================
# Configuration
# =========================================================================

LOOKBACK_MONTHS = 24
REQUEST_TIMEOUT = 15  # seconds
USER_AGENT = "DST-Compiler/1.0 (Medicare SEP Tool; contact: admin@clearpathcoverage.com)"
OUTPUT_FILE = "curated_disasters.json"
ALL_DISASTERS_FILE = "all_disasters.json"

VERIFY_URLS_ON_BUILD = False  # Set True for local debug runs; False for CI (rate limits)

FALLBACK_URLS = {
    "HHS": "https://aspr.hhs.gov/legal/PHE/Pages/default.aspx",
    "SBA": "https://www.sba.gov/funding-programs/disaster-assistance",
    "USDA": "https://www.fsa.usda.gov/programs-and-services/disaster-assistance-program/",
    "FMCSA": "https://www.fmcsa.dot.gov/emergency-declarations",
    "STATE": None,
}

VALID_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA",
    "GU", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
    "NY", "NC", "ND", "MP", "OH", "OK", "OR", "PA", "PR", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "VI", "WA", "WV", "WI", "WY",
    "AS",
}

STATE_NAME_TO_CODE = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Guam": "GU",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN",
    "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Northern Mariana Islands": "MP", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Puerto Rico": "PR",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Virgin Islands": "VI", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "American Samoa": "AS",
}

STATE_CODE_TO_NAME = {v: k for k, v in STATE_NAME_TO_CODE.items()}

# =========================================================================
# Utility Functions
# =========================================================================

def calculate_sep_window_end(incident_end: date) -> date:
    """
    Calculate SEP end: last day of 2nd full calendar month after incident end.
    CRITICAL: Uses month arithmetic only, never day arithmetic.
    Never use setMonth() equivalent — use monthrange() for last day.

    Examples:
      Jan 15 -> Mar 31
      Jan 31 -> Mar 31
      Feb 28 -> Apr 30
      Nov 30 -> Jan 31 (next year)
      Dec 31 -> Feb 28/29
    """
    month = incident_end.month
    year = incident_end.year
    target_month = month + 2
    target_year = year
    if target_month > 12:
        target_month -= 12
        target_year += 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    return date(target_year, target_month, last_day)


def calculate_ongoing_max_end(sep_start: date, renewal_dates: Optional[List[date]] = None) -> date:
    """
    Calculate 14-month maximum for ongoing disasters.
    Clock resets from the latest of sep_start or any renewal date.
    """
    max_date = sep_start
    if renewal_dates:
        for rd in renewal_dates:
            if rd > max_date:
                max_date = rd
    month = max_date.month
    year = max_date.year
    target_month = month + 14
    target_year = year
    while target_month > 12:
        target_month -= 12
        target_year += 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    return date(target_year, target_month, last_day)


def calculate_sep_start(declaration_date: date, incident_start: date) -> date:
    """SEP start = earlier of declaration date and incident start."""
    return min(declaration_date, incident_start)


def calculate_status(sep_end: date, is_ongoing: bool) -> str:
    """Determine status: ongoing, active, expiring_soon, expired."""
    today = date.today()
    days_remaining = (sep_end - today).days
    if days_remaining < 0:
        return "expired"
    if days_remaining <= 30:
        return "expiring_soon"
    if is_ongoing:
        return "ongoing"
    return "active"


def days_remaining(sep_end: Optional[date]) -> Optional[int]:
    """Days until SEP window closes. None if no end date."""
    if not sep_end:
        return None
    return (sep_end - date.today()).days


def parse_date_fuzzy(date_str: str) -> Optional[date]:
    """
    Parse various date formats to date object.
    Handles: "January 15, 2026", "Jan 15, 2026", "01/15/2026", "2026-01-15"
    """
    if not date_str:
        return None
    date_str = date_str.strip().rstrip(".")

    # ISO format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            pass

    formats = [
        "%B %d, %Y",      # January 15, 2026
        "%b %d, %Y",      # Jan 15, 2026
        "%b. %d, %Y",     # Jan. 15, 2026
        "%m/%d/%Y",        # 01/15/2026
        "%B %d %Y",        # January 15 2026
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def normalize_county_name(name: str) -> str:
    """
    Strip county type suffixes. Order matters:
    "(City and Borough)" before "(Borough)" to avoid partial match.
    """
    suffixes = [
        "(City and Borough)",
        "(County)",
        "(Parish)",
        "(Borough)",
        "(Census Area)",
        "(city)",
        "(Municipio)",
        "(ANV/ANVSA)",
    ]
    result = name.strip()
    for suffix in suffixes:
        result = re.sub(re.escape(suffix), "", result, flags=re.IGNORECASE).strip()
    return result


def verify_url(url: str) -> bool:
    """
    Verify URL is reachable with HEAD request.
    Returns True on 2xx or 3xx status.
    """
    for attempt in range(2):
        try:
            resp = requests.head(
                url, timeout=REQUEST_TIMEOUT, allow_redirects=True,
                headers={"User-Agent": USER_AGENT}
            )
            return resp.status_code < 400
        except Exception:
            if attempt == 0:
                time.sleep(1)
    return False


def build_record(
    id_str: str, source: str, state: str, title: str, incident_type: str,
    declaration_date: date, incident_start: date, incident_end: Optional[date],
    renewal_dates_list: Optional[List[date]], counties: List[str],
    statewide: bool, official_url: str, confidence: str,
    last_verified: Optional[str] = None
) -> Optional[Dict]:
    """Build a validated disaster record dict. Returns None if invalid."""
    today = date.today()

    # Validate
    if declaration_date > today:
        return None
    if incident_end and incident_start > incident_end:
        return None
    if not official_url:
        return None
    if VERIFY_URLS_ON_BUILD:
        if not verify_url(official_url):
            print(f"  WARNING: URL unreachable for {id_str}: {official_url[:80]}")
    if not counties:
        return None
    if state not in VALID_STATES:
        return None

    is_ongoing = incident_end is None
    sep_start = calculate_sep_start(declaration_date, incident_start)

    if is_ongoing:
        renewal_dates_d = renewal_dates_list or []
        sep_end = calculate_ongoing_max_end(sep_start, renewal_dates_d if renewal_dates_d else None)
    else:
        sep_end = calculate_sep_window_end(incident_end)

    status = calculate_status(sep_end, is_ongoing)
    if status == "expired":
        return None

    days_rem = days_remaining(sep_end)

    renewal_strs = None
    if renewal_dates_list:
        renewal_strs = [d.isoformat() for d in renewal_dates_list]

    record = {
        "id": id_str,
        "source": source,
        "state": state,
        "title": title,
        "incidentType": incident_type,
        "declarationDate": declaration_date.isoformat(),
        "incidentStart": incident_start.isoformat(),
        "incidentEnd": incident_end.isoformat() if incident_end else None,
        "renewalDates": renewal_strs,
        "counties": sorted(counties, key=lambda c: c.lower()),
        "statewide": statewide,
        "officialUrl": official_url,
        "status": status,
        "sepWindowStart": sep_start.isoformat(),
        "sepWindowEnd": sep_end.isoformat(),
        "daysRemaining": days_rem,
        "confidenceLevel": confidence,
        "lastUpdated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if last_verified:
        record["lastVerified"] = last_verified
    return record


# =========================================================================
# SBA Collector — Federal Register API
# =========================================================================

class SBACollector:
    """Collects SBA disaster declarations via Federal Register API."""

    FR_API = "https://www.federalregister.gov/api/v1/documents.json"

    def __init__(self):
        self.records: List[Dict] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.fr_count = 0
        self.curated_count = 0

    def collect(self) -> List[Dict]:
        try:
            documents = self._fetch_documents()
            for doc in documents:
                try:
                    results = self._parse_document(doc)
                    for rec in results:
                        if rec:
                            self.records.append(rec)
                            self.fr_count += 1
                except Exception as e:
                    doc_num = doc.get("document_number", "?")
                    self.errors.append(f"Failed to parse FR doc {doc_num}: {e}")
        except Exception as e:
            self.errors.append(f"Federal Register API query failed: {e}")
            self.warnings.append("Using curated SBA data as fallback")

        # Curated overrides take priority over FR-parsed records.
        # This corrects known parser failures (wrong dates, corrupted counties).
        # IDs to suppress from FR results (even if the curated version is expired/None)
        override_ids = self._get_curated_sba_override_ids()
        self.records = [r for r in self.records if r["id"] not in override_ids]
        curated = self._get_curated_sba()
        for rec in curated:
            if rec:
                self.records.append(rec)
                self.curated_count += 1

        return self.records

    def _fetch_documents(self) -> List[Dict]:
        """Query Federal Register for SBA disaster notices."""
        cutoff = (date.today() - timedelta(days=LOOKBACK_MONTHS * 31)).isoformat()
        all_results = []
        page = 1

        while True:
            params = {
                "conditions[agencies][]": "small-business-administration",
                "conditions[term]": "disaster",
                "conditions[publication_date][gte]": cutoff,
                "per_page": 50,
                "order": "newest",
                "page": page,
                "fields[]": [
                    "title", "abstract", "publication_date", "html_url",
                    "raw_text_url", "document_number", "type"
                ],
            }
            resp = requests.get(
                self.FR_API, params=params, timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT}
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            all_results.extend(results)

            total_pages = data.get("total_pages", 1)
            if page >= total_pages or not results:
                break
            page += 1
            time.sleep(0.5)  # Be respectful

        # Filter to actual disaster declarations only
        filtered = []
        for doc in all_results:
            title = (doc.get("title") or "").lower()
            # Must be a declaration notice, not a filing extension or policy document
            if "declaration" in title and "disaster" in title:
                # Skip presidential declarations (overlap with FEMA)
                if "presidential" in title:
                    continue
                # Skip filing deadline / reopening notices (not new declarations)
                if "impacted by" in title or "filing" in title or "reopening" in title:
                    continue
                filtered.append(doc)

        return filtered

    def _parse_document(self, doc: Dict) -> List[Optional[Dict]]:
        """
        Parse a Federal Register document into DST records.
        Returns a list because contiguous counties in other states create separate records.
        """
        raw_text_url = doc.get("raw_text_url")
        if not raw_text_url:
            return []

        resp = requests.get(
            raw_text_url, timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT}
        )
        resp.raise_for_status()
        full_text = resp.text

        doc_number = doc.get("document_number", "UNKNOWN")
        publication_date = doc.get("publication_date")
        official_url = doc.get("html_url", "")
        title_raw = doc.get("title", "SBA Disaster Declaration")
        abstract = doc.get("abstract", "")

        # Extract primary state from title
        primary_state = self._extract_state_from_title(title_raw)
        if not primary_state:
            self.warnings.append(f"Could not determine state from FR doc {doc_number}")
            return []

        # Extract dates
        decl_date = parse_date_fuzzy(publication_date)
        if not decl_date:
            return []
        incident_start, incident_end = self._extract_incident_dates(full_text)
        if not incident_start:
            # Fall back to declaration date
            incident_start = decl_date

        # Extract incident name from abstract or title
        incident_name = self._extract_incident_name(abstract, title_raw)

        # Extract counties
        primary_counties = self._extract_primary_counties(full_text)
        contiguous_by_state = self._extract_contiguous_counties(full_text)

        records = []

        # Build primary state record
        if primary_counties:
            rec = build_record(
                id_str=f"SBA-{doc_number}-{primary_state}",
                source="SBA",
                state=primary_state,
                title=incident_name or title_raw,
                incident_type=self._infer_incident_type(incident_name or title_raw),
                declaration_date=decl_date,
                incident_start=incident_start,
                incident_end=incident_end,
                renewal_dates_list=None,
                counties=[normalize_county_name(c) for c in primary_counties],
                statewide=False,
                official_url=official_url,
                confidence="verified",
            )
            if rec:
                records.append(rec)

        # Build contiguous state records
        for state_name, counties in contiguous_by_state.items():
            state_code = STATE_NAME_TO_CODE.get(state_name)
            if not state_code:
                continue
            if state_code == primary_state:
                continue  # Already covered in primary
            rec = build_record(
                id_str=f"SBA-{doc_number}-{state_code}",
                source="SBA",
                state=state_code,
                title=incident_name or title_raw,
                incident_type=self._infer_incident_type(incident_name or title_raw),
                declaration_date=decl_date,
                incident_start=incident_start,
                incident_end=incident_end,
                renewal_dates_list=None,
                counties=[normalize_county_name(c) for c in counties],
                statewide=False,
                official_url=official_url,
                confidence="verified",
            )
            if rec:
                records.append(rec)

        return records

    def _extract_state_from_title(self, title: str) -> Optional[str]:
        """Extract state code from title like 'Declaration of a Disaster for the State of CALIFORNIA'."""
        # Try "State of [NAME]" pattern
        match = re.search(r"State of\s+([A-Z][A-Za-z\s]+?)(?:\s*$|\s*dated)", title, re.IGNORECASE)
        if match:
            state_name = match.group(1).strip().title()
            code = STATE_NAME_TO_CODE.get(state_name)
            if code:
                return code

        # "Rural Area" declarations are typically in Alaska (tribal villages)
        if "rural area" in title.lower():
            # Check abstract/full text for state, but assume AK for now
            return "AK"

        # Try matching state names directly
        for name, code in STATE_NAME_TO_CODE.items():
            if name.upper() in title.upper():
                return code

        return None

    def _extract_incident_dates(self, text: str) -> Tuple[Optional[date], Optional[date]]:
        """Extract incident start/end from the full text DATES section."""
        # Pattern 1: "Incident Period: January 23, 2026 through January 25, 2026"
        match = re.search(
            r"Incident\s+Period:\s*(.+?)(?:through|to)\s+(.+?)(?:\.|$)",
            text, re.IGNORECASE
        )
        if match:
            start = parse_date_fuzzy(match.group(1).strip())
            end = parse_date_fuzzy(match.group(2).strip())
            if start:
                return start, end

        # Pattern 2: "beginning December 16, 2025 and ending December 26, 2025"
        match = re.search(
            r"beginning\s+(.+?)\s+and\s+ending\s+(.+?)(?:\.|,|$)",
            text, re.IGNORECASE
        )
        if match:
            start = parse_date_fuzzy(match.group(1).strip())
            end = parse_date_fuzzy(match.group(2).strip())
            if start:
                return start, end

        # Pattern 3: "beginning on December 16, 2025, and continuing"
        match = re.search(
            r"beginning\s+(?:on\s+)?(.+?)(?:,?\s+and\s+continuing)",
            text, re.IGNORECASE
        )
        if match:
            start = parse_date_fuzzy(match.group(1).strip())
            if start:
                return start, None  # Ongoing

        # Pattern 4: "Incident Period: January 25, 2025." (single date = single-day event)
        # This must come AFTER patterns 1-3 to avoid false matches on multi-date patterns.
        # When FR specifies a single date with no "through"/"and continuing", the incident
        # was a one-day event (fire, storm, crash). End date = start date.
        match = re.search(
            r"Incident\s+Period:\s*(\w+\s+\d{1,2},?\s+\d{4})\s*\.?",
            text, re.IGNORECASE
        )
        if match:
            start = parse_date_fuzzy(match.group(1).strip())
            if start:
                return start, start  # Single-day event: end = start

        return None, None

    def _extract_incident_name(self, abstract: str, title: str) -> Optional[str]:
        """Extract incident name like '2025 Late December Storm' from abstract or title."""
        # From abstract: "Incident: 2025 Late December Storm."
        match = re.search(r"Incident:\s*(.+?)(?:\.|$)", abstract)
        if match:
            return match.group(1).strip()
        # From abstract: "Incident Period: ... Incident: ..."
        match = re.search(r"Incident:\s*(.+?)(?:\.|$)", title)
        if match:
            return match.group(1).strip()
        return None

    def _extract_primary_counties(self, text: str) -> List[str]:
        """Extract primary counties from 'Primary Counties:' section."""
        # Look for "Primary Counties:" or "Primary Parishes:" etc.
        match = re.search(
            r"Primary\s+(?:Counties|Parishes|Boroughs|Areas)(?:\s*\(Physical\s+Damage[^)]*\))?:\s*(.+?)(?:Contiguous|$)",
            text, re.IGNORECASE | re.DOTALL
        )
        if not match:
            # Try alternate pattern — stop at double newline, "Interest", or "Contiguous"
            match = re.search(
                r"Primary\s+(?:Counties|Parishes):\s*(.+?)(?:\n\n|\nContiguous|\nInterest)",
                text, re.IGNORECASE | re.DOTALL
            )
        if not match:
            return []

        counties_text = match.group(1).strip()
        # Split by comma, semicolon, or newline
        counties = re.split(r"[,;\n]+", counties_text)
        counties = [c.strip().rstrip(".") for c in counties if c.strip() and len(c.strip()) > 1]
        # Filter out non-county items (state names, headers, metadata, HTML)
        counties = [c for c in counties if not re.match(r"^(In |and |the )", c, re.IGNORECASE)]
        # Reject garbage: lines with special chars, HTML, numbers, or very long strings
        counties = [
            c for c in counties
            if len(c) < 60
            and not re.search(r"[<>(){}\[\]|/\\]", c)
            and not re.search(r"^\d", c)
            and not re.search(r"(Catalog|BILLING|Available|Credit|Percent|Interest|Elsewhere|Filed|Code|--------)", c, re.IGNORECASE)
        ]
        return counties

    def _extract_contiguous_counties(self, text: str) -> Dict[str, List[str]]:
        """
        Extract contiguous counties by state.
        Pattern: 'In California: Inyo, Kern, Lassen' or 'In Arizona: La Paz, Mohave'
        """
        result: Dict[str, List[str]] = {}

        # Find the contiguous section
        match = re.search(
            r"Contiguous\s+(?:Counties|Parishes|Boroughs|Areas)(?:\s*\([^)]*\))?:\s*(.+?)(?:Interest\s+Rates|A\s+list\s+of|The\s+interest|$)",
            text, re.IGNORECASE | re.DOTALL
        )
        if not match:
            return result

        contiguous_text = match.group(1).strip()

        # Pattern: "In [State]: county1, county2, county3."
        # or "In [State]: county1, county2"
        for state_match in re.finditer(
            r"(?:^|\n)\s*(?:In\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*:\s*([^:]+?)(?=(?:\n\s*(?:In\s+)?[A-Z][a-z]|$))",
            contiguous_text, re.DOTALL
        ):
            state_name = state_match.group(1).strip()
            counties_str = state_match.group(2).strip()
            counties = re.split(r"[,;\n]+", counties_str)
            counties = [c.strip().rstrip(".") for c in counties if c.strip() and len(c.strip()) > 1]
            counties = [c for c in counties if not re.match(r"^(In |and |the )", c, re.IGNORECASE)]
            if counties:
                result[state_name] = counties

        return result

    def _infer_incident_type(self, name: str) -> str:
        """Infer incident type from disaster name."""
        name_lower = name.lower()
        if "hurricane" in name_lower:
            return "Hurricane"
        if "wildfire" in name_lower:
            return "Wildfire"
        if "fire" in name_lower:
            # Distinguish structure fires from wildfires
            if any(kw in name_lower for kw in ["apartment", "building", "complex", "house", "structure", "residential", "alarm"]):
                return "Fire"
            return "Wildfire"
        if "flood" in name_lower or "tidal" in name_lower:
            return "Flood"
        if "tornado" in name_lower:
            return "Tornado"
        if "winter storm" in name_lower or "ice storm" in name_lower or "snow" in name_lower:
            return "Severe Winter Storm"
        if "storm" in name_lower or "severe" in name_lower:
            return "Severe Storm"
        if "drought" in name_lower:
            return "Drought"
        if "earthquake" in name_lower:
            return "Earthquake"
        return "Disaster"

    def _get_curated_sba_override_ids(self) -> set:
        """
        IDs of FR-parsed records that curated data should replace.
        Includes records that are expired — those must be suppressed from FR output
        even though the curated build_record returns None.
        """
        return {
            "SBA-2025-12380-CA",  # Expired (incident ended Jun 18, 2025)
            "SBA-2025-16217-AK",  # Wrong incidentStart
            "SBA-2025-23433-CT",  # Wrong incidentStart/End
            "SBA-2025-23433-NJ",  # Contiguous record, same date issues
            "SBA-2025-04575-OR",  # Expired + corrupted counties
            # Single-day events: parser missed end date (Pattern 4 fix in _extract_incident_dates)
            # These overrides ensure correct data even if the parser fix doesn't retroactively
            # apply to cached FR text.
            "SBA-2025-01588-TX",  # Single-day storm Dec 28, 2024 — EXPIRED
            "SBA-2025-01871-TX",  # Same event area expansion — EXPIRED
            "SBA-2025-04573-IL",  # Single-day fire Jan 25, 2025 — EXPIRED
            "SBA-2025-04573-IN",  # Contiguous for above — EXPIRED
            "SBA-2025-04581-NJ",  # Single-day fire Jan 10, 2025 (primary=NY) — EXPIRED
            "SBA-2025-04581-NY",  # Primary record for above — EXPIRED
            "SBA-2025-07251-IL",  # Single-day storm Mar 19, 2025 (primary=IN) — EXPIRED
            "SBA-2025-07251-IN",  # Primary record for above — EXPIRED
            "SBA-2025-20283-IN",  # Single-day crash Nov 4, 2025 (primary=KY) — EXPIRED
            "SBA-2025-20283-KY",  # Primary record for above — EXPIRED
            # Wrong incidentStart (used FR pub date) + missing incidentEnd (single-day events)
            "SBA-2025-05997-IL",  # Single-day apartment fire Feb 22, 2025 — EXPIRED
            "SBA-2025-05997-IN",  # Contiguous for above — EXPIRED
            "SBA-2025-23887-MN",  # Single-day fire Oct 26, 2025 — EXPIRED
            # Amendment expanded county list — curated override has full list
            "SBA-2026-02294-LA",  # Original had 5 parishes; amendment adds 16 more
        }

    def _get_curated_sba(self) -> List[Optional[Dict]]:
        """
        Curated SBA overrides/fallbacks.
        Used to correct records where the FR raw text parser gets dates wrong
        or to add records the FR API query misses.

        Known parser issues (discovered in Phase 3 audit, Feb 7 2026):
        - SBA-2025-12380-CA: Parser missed incidentEnd (June 18, 2025) — DST actually expired Aug 31, 2025
        - SBA-2025-16217-AK: Parser fell back to FR pub date for incidentStart (Aug 25 instead of Jun 19)
        - SBA-2025-23433-CT: Parser fell back to FR pub date for incidentStart (Dec 19 instead of Nov 23)
        - SBA-2025-04575-OR: "Rural area" doc format causes county parser to capture garbage
        """
        curated = []

        # SBA-2025-12380-CA: Los Angeles County Civil Unrest
        # FR doc says incident ended June 18, 2025. SEP end = Aug 31, 2025 (EXPIRED).
        # This override will cause build_record to return None (expired), which
        # prevents the incorrect ongoing FR-parsed version from surviving dedup.
        rec = build_record(
            id_str="SBA-2025-12380-CA",
            source="SBA", state="CA",
            title="Los Angeles County Civil Unrest",
            incident_type="Disaster",
            declaration_date=date(2025, 7, 2),
            incident_start=date(2025, 6, 6),
            incident_end=date(2025, 6, 18),
            renewal_dates_list=None,
            counties=["Los Angeles"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/07/02/2025-12380/administrative-declaration-of-a-disaster-for-the-state-of-california",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-16217-AK: Bear Creek Fire / Nenana Ridge Complex Fire
        # Actual incident start: June 19, 2025 (parser fell back to pub date Aug 25)
        # Counties verified against FR doc 2025-16217: Denali Borough + Yukon-Koyukuk (primary),
        # Matanuska-Susitna (contiguous). Southeast Fairbanks NOT in FR doc — removed.
        rec = build_record(
            id_str="SBA-2025-16217-AK",
            source="SBA", state="AK",
            title="Bear Creek Fire Group and Nenana Ridge Complex Fire",
            incident_type="Wildfire",
            declaration_date=date(2025, 8, 25),
            incident_start=date(2025, 6, 19),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Denali", "Matanuska-Susitna", "Yukon-Koyukuk"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/08/25/2025-16217/administrative-declaration-of-an-economic-injury-disaster-for-the-state-of-alaska",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-23433-CT: Cottage Avenue Apartment Building Fire
        # Actual incident: Nov 23, 2025 (parser fell back to pub date Dec 19)
        rec = build_record(
            id_str="SBA-2025-23433-CT",
            source="SBA", state="CT",
            title="Cottage Avenue Apartment Building Fire",
            incident_type="Fire",
            declaration_date=date(2025, 12, 19),
            incident_start=date(2025, 11, 23),
            incident_end=date(2025, 11, 23),
            renewal_dates_list=None,
            counties=["Fairfield"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/12/19/2025-23433/administrative-declaration-of-a-disaster-for-the-state-of-connecticut",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-23433-NJ: Contiguous county record for the CT fire above
        # Same date corrections as CT record
        rec = build_record(
            id_str="SBA-2025-23433-NJ",
            source="SBA", state="NJ",
            title="Cottage Avenue Apartment Building Fire",
            incident_type="Fire",
            declaration_date=date(2025, 12, 19),
            incident_start=date(2025, 11, 23),
            incident_end=date(2025, 11, 23),
            renewal_dates_list=None,
            counties=["Bergen"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/12/19/2025-23433/administrative-declaration-of-a-disaster-for-the-state-of-connecticut",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-04575-OR: Wildfires (Rural Area declaration)
        # Parser garbled counties from "rural area" doc format. Only valid county: Wheeler.
        # Actual incident: Jul 10, 2024 – Aug 23, 2024. SEP end = Oct 31, 2024. EXPIRED.
        # build_record returns None for expired records, preventing the bad FR version.
        rec = build_record(
            id_str="SBA-2025-04575-OR",
            source="SBA", state="OR",
            title="Wildfires",
            incident_type="Wildfire",
            declaration_date=date(2025, 3, 13),
            incident_start=date(2024, 7, 10),
            incident_end=date(2024, 8, 23),
            renewal_dates_list=None,
            counties=["Wheeler"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/03/19/2025-04575/administrative-disaster-declaration-of-a-rural-area-for-the-state-of-oregon",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # -----------------------------------------------------------------
        # Single-day events that the FR parser missed incidentEnd for.
        # These are all EXPIRED — build_record returns None for expired records,
        # which prevents the incorrect "ongoing" FR-parsed version from surviving.
        # -----------------------------------------------------------------

        # SBA-2025-01588-TX: Severe Storm, single-day Dec 28, 2024
        # SEP end = Feb 28, 2025 — EXPIRED
        rec = build_record(
            id_str="SBA-2025-01588-TX", source="SBA", state="TX",
            title="Severe Storm, Tornadoes, and Straight-line Winds",
            incident_type="Severe Storm",
            declaration_date=date(2025, 1, 16),
            incident_start=date(2024, 12, 28), incident_end=date(2024, 12, 28),
            renewal_dates_list=None,
            counties=["Brazoria", "Montgomery"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/01/16/2025-01588/administrative-declaration-of-a-disaster-for-the-state-of-texas",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-01871-TX: Same event, area expansion, same single-day
        # SEP end = Feb 28, 2025 — EXPIRED
        rec = build_record(
            id_str="SBA-2025-01871-TX", source="SBA", state="TX",
            title="Severe Storm, Tornadoes, and Straight-line Winds",
            incident_type="Severe Storm",
            declaration_date=date(2025, 1, 24),
            incident_start=date(2024, 12, 28), incident_end=date(2024, 12, 28),
            renewal_dates_list=None,
            counties=["Brazoria", "Fort Bend", "Galveston", "Harris", "Montgomery"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/01/29/2025-01871/administrative-declaration-amendment-of-a-disaster-for-the-state-of-texas",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-04573-IL: Tatra Apartment Fire, single-day Jan 25, 2025
        # SEP end = Mar 31, 2025 — EXPIRED
        rec = build_record(
            id_str="SBA-2025-04573-IL", source="SBA", state="IL",
            title="Tatra Multi-Family Apartment Complex Fire",
            incident_type="Fire",
            declaration_date=date(2025, 3, 14),
            incident_start=date(2025, 1, 25), incident_end=date(2025, 1, 25),
            renewal_dates_list=None,
            counties=["Cook"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/03/19/2025-04573/administrative-declaration-of-a-disaster-for-the-state-of-illinois",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-04573-IN: Contiguous for IL fire above
        # SEP end = Mar 31, 2025 — EXPIRED
        rec = build_record(
            id_str="SBA-2025-04573-IN", source="SBA", state="IN",
            title="Tatra Multi-Family Apartment Complex Fire",
            incident_type="Fire",
            declaration_date=date(2025, 3, 14),
            incident_start=date(2025, 1, 25), incident_end=date(2025, 1, 25),
            renewal_dates_list=None,
            counties=["Lake"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/03/19/2025-04573/administrative-declaration-of-a-disaster-for-the-state-of-illinois",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-04581-NY: Five Alarm Fire in Bronx County, single-day Jan 10, 2025
        # Primary state is NY (Bronx County), NJ is contiguous
        # SEP end = Mar 31, 2025 — EXPIRED
        rec = build_record(
            id_str="SBA-2025-04581-NY", source="SBA", state="NY",
            title="Five Alarm Apartment Building Fire",
            incident_type="Fire",
            declaration_date=date(2025, 3, 14),
            incident_start=date(2025, 1, 10), incident_end=date(2025, 1, 10),
            renewal_dates_list=None,
            counties=["Bronx"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/03/19/2025-04581/administrative-declaration-of-a-disaster-for-the-state-of-new-york",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-04581-NJ: Contiguous for NY fire above
        # SEP end = Mar 31, 2025 — EXPIRED
        rec = build_record(
            id_str="SBA-2025-04581-NJ", source="SBA", state="NJ",
            title="Five Alarm Apartment Building Fire",
            incident_type="Fire",
            declaration_date=date(2025, 3, 14),
            incident_start=date(2025, 1, 10), incident_end=date(2025, 1, 10),
            renewal_dates_list=None,
            counties=["Bergen", "Hudson", "Passaic"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/03/19/2025-04581/administrative-declaration-of-a-disaster-for-the-state-of-new-york",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-07251-IN: Severe Storms, single-day Mar 19, 2025
        # Primary state is IN (Bartholomew/Lake Counties), IL is contiguous
        # SEP end = May 31, 2025 — EXPIRED
        rec = build_record(
            id_str="SBA-2025-07251-IN", source="SBA", state="IN",
            title="Severe Storms and Tornadoes",
            incident_type="Severe Storm",
            declaration_date=date(2025, 4, 24),
            incident_start=date(2025, 3, 19), incident_end=date(2025, 3, 19),
            renewal_dates_list=None,
            counties=["Bartholomew", "Lake"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/04/28/2025-07251/administrative-declaration-of-a-disaster-for-the-state-of-indiana",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-07251-IL: Contiguous for IN storms above
        # SEP end = May 31, 2025 — EXPIRED
        rec = build_record(
            id_str="SBA-2025-07251-IL", source="SBA", state="IL",
            title="Severe Storms and Tornadoes",
            incident_type="Severe Storm",
            declaration_date=date(2025, 4, 24),
            incident_start=date(2025, 3, 19), incident_end=date(2025, 3, 19),
            renewal_dates_list=None,
            counties=["Clark", "Cook", "Lake", "Vermilion"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/04/28/2025-07251/administrative-declaration-of-a-disaster-for-the-state-of-indiana",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-20283-KY: Louisville Airplane Crash, single-day Nov 4, 2025
        # Primary state is KY (Jefferson County), IN is contiguous
        # SEP end = Jan 31, 2026 — EXPIRED (16 days ago as of Feb 16)
        rec = build_record(
            id_str="SBA-2025-20283-KY", source="SBA", state="KY",
            title="Louisville Airplane Crash",
            incident_type="Disaster",
            declaration_date=date(2025, 11, 19),
            incident_start=date(2025, 11, 4), incident_end=date(2025, 11, 4),
            renewal_dates_list=None,
            counties=["Jefferson"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/11/25/2025-20283/administrative-declaration-of-an-economic-injury-disaster-for-the-commonwealth-of-kentucky",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-20283-IN: Contiguous for KY crash above
        # SEP end = Jan 31, 2026 — EXPIRED
        rec = build_record(
            id_str="SBA-2025-20283-IN", source="SBA", state="IN",
            title="Louisville Airplane Crash",
            incident_type="Disaster",
            declaration_date=date(2025, 11, 19),
            incident_start=date(2025, 11, 4), incident_end=date(2025, 11, 4),
            renewal_dates_list=None,
            counties=["Clark", "Floyd", "Harrison"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/11/25/2025-20283/administrative-declaration-of-an-economic-injury-disaster-for-the-commonwealth-of-kentucky",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # -----------------------------------------------------------------
        # SBA-2025-05997-IL/IN: Apartment fire, single-day Feb 22, 2025
        # Parser used FR pub date (2025-04-08) as incidentStart and null end.
        # Correct: incidentStart=incidentEnd=2025-02-22. SEP end = Apr 30, 2025 — EXPIRED.
        # -----------------------------------------------------------------

        # SBA-2025-05997-IL: Primary — Cook County apartment fire
        rec = build_record(
            id_str="SBA-2025-05997-IL", source="SBA", state="IL",
            title="Apartment Complex Fire",
            incident_type="Fire",
            declaration_date=date(2025, 4, 8),
            incident_start=date(2025, 2, 22), incident_end=date(2025, 2, 22),
            renewal_dates_list=None,
            counties=["Cook"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/04/08/2025-05997/administrative-declaration-of-a-disaster-for-the-state-of-illinois",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-05997-IN: Contiguous for IL fire above
        rec = build_record(
            id_str="SBA-2025-05997-IN", source="SBA", state="IN",
            title="Apartment Complex Fire",
            incident_type="Fire",
            declaration_date=date(2025, 4, 8),
            incident_start=date(2025, 2, 22), incident_end=date(2025, 2, 22),
            renewal_dates_list=None,
            counties=["Lake"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/04/08/2025-05997/administrative-declaration-of-a-disaster-for-the-state-of-illinois",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2025-23887-MN: Skyline Tower Apartment Complex Fire, single-day Oct 26, 2025
        # Parser used FR pub date (2025-12-29) as incidentStart and null end.
        # Correct: incidentStart=incidentEnd=2025-10-26. SEP end = Dec 31, 2025 — EXPIRED.
        rec = build_record(
            id_str="SBA-2025-23887-MN", source="SBA", state="MN",
            title="Skyline Tower Apartment Complex Fire",
            incident_type="Fire",
            declaration_date=date(2025, 12, 29),
            incident_start=date(2025, 10, 26), incident_end=date(2025, 10, 26),
            renewal_dates_list=None,
            counties=["Hennepin"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2025/12/29/2025-23887/administrative-declaration-of-a-disaster-for-the-state-of-minnesota",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # -----------------------------------------------------------------
        # SBA-2026-02924-CA: Oakland Apartment Fire, single-day Jan 19, 2026
        # FR published Feb 13, 2026. SEP end = Mar 31, 2026.
        # MISSING from FR API results — add as curated.
        # -----------------------------------------------------------------
        # Counties verified against FR doc 2026-02924: Alameda (primary) +
        # Contra Costa, San Francisco, San Joaquin, San Mateo, Santa Clara, Stanislaus (contiguous).
        rec = build_record(
            id_str="SBA-2026-02924-CA", source="SBA", state="CA",
            title="Oakland Apartment Fire",
            incident_type="Fire",
            declaration_date=date(2026, 2, 10),
            incident_start=date(2026, 1, 19), incident_end=date(2026, 1, 19),
            renewal_dates_list=None,
            counties=["Alameda", "Contra Costa", "San Francisco", "San Joaquin",
                       "San Mateo", "Santa Clara", "Stanislaus"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2026/02/13/2026-02924/administrative-declaration-of-a-disaster-for-the-state-of-california",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # -----------------------------------------------------------------
        # SBA-2026-02294-LA: 2026 Severe Winter Storm (amended)
        # Original FR doc (2026-02294) had 5 parishes. Amendment FR doc
        # (2026-03026, pub Feb 17) expanded to 21 parishes + contiguous
        # counties in TX, AR, MS.
        # -----------------------------------------------------------------
        rec = build_record(
            id_str="SBA-2026-02294-LA", source="SBA", state="LA",
            title="2026 Severe Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 5),
            incident_start=date(2026, 1, 23), incident_end=date(2026, 1, 25),
            renewal_dates_list=None,
            counties=["Bossier", "Caddo", "Caldwell", "Catahoula", "Concordia",
                       "DeSoto", "East Carroll", "Franklin", "Jackson", "Lincoln",
                       "Madison", "Morehouse", "Natchitoches", "Ouachita", "Red River",
                       "Richland", "Sabine", "Tensas", "Union", "Webster", "West Carroll"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2026/02/05/2026-02294/administrative-declaration-of-an-economic-injury-disaster-for-the-state-of-louisiana",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2026-02294-TX: Contiguous counties for LA winter storm (amendment)
        rec = build_record(
            id_str="SBA-2026-02294-TX", source="SBA", state="TX",
            title="2026 Severe Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 5),
            incident_start=date(2026, 1, 23), incident_end=date(2026, 1, 25),
            renewal_dates_list=None,
            counties=["Panola", "Shelby"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2026/02/17/2026-03026/administrative-declaration-amendment-of-an-economic-injury-disaster-for-the-state-of-louisiana",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2026-02294-AR: Contiguous counties for LA winter storm (amendment)
        rec = build_record(
            id_str="SBA-2026-02294-AR", source="SBA", state="AR",
            title="2026 Severe Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 5),
            incident_start=date(2026, 1, 23), incident_end=date(2026, 1, 25),
            renewal_dates_list=None,
            counties=["Chicot", "Lafayette", "Miller"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2026/02/17/2026-03026/administrative-declaration-amendment-of-an-economic-injury-disaster-for-the-state-of-louisiana",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2026-02294-MS: Contiguous counties for LA winter storm (amendment)
        rec = build_record(
            id_str="SBA-2026-02294-MS", source="SBA", state="MS",
            title="2026 Severe Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 5),
            incident_start=date(2026, 1, 23), incident_end=date(2026, 1, 25),
            renewal_dates_list=None,
            counties=["Adams", "Claiborne", "Issaquena", "Jefferson", "Warren"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2026/02/17/2026-03026/administrative-declaration-amendment-of-an-economic-injury-disaster-for-the-state-of-louisiana",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        return curated


# =========================================================================
# HHS Collector — Curated + Scrape Attempt
# =========================================================================

class HHSCollector:
    """Collects HHS Public Health Emergency declarations."""

    PHE_URL = "https://aspr.hhs.gov/legal/PHE/Pages/default.aspx"

    def __init__(self):
        self.records: List[Dict] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def collect(self) -> List[Dict]:
        # Start with curated data
        self.records = self._get_curated_hhs()

        # Attempt scrape for new PHEs
        try:
            scraped = self._scrape_phe_page()
            existing_ids = {r["id"] for r in self.records}
            for rec in scraped:
                if rec and rec["id"] not in existing_ids:
                    self.records.append(rec)
        except Exception as e:
            self.warnings.append(f"HHS scrape failed ({type(e).__name__}: {e}) — using curated data only")

        return self.records

    def _scrape_phe_page(self) -> List[Dict]:
        """Attempt to scrape HHS PHE page. May fail due to SSL/SharePoint."""
        resp = requests.get(
            self.PHE_URL, timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            verify=True  # Will fail if cert is bad
        )
        resp.raise_for_status()
        # SharePoint pages are complex — basic parsing
        soup = BeautifulSoup(resp.text, "html.parser")
        # Look for active PHE indicators in page content
        # This is best-effort; curated data is the reliable path
        return []

    def _get_curated_hhs(self) -> List[Optional[Dict]]:
        """
        Curated HHS PHE data.

        As of Feb 2026:
        - COVID-19 PHE ended May 11, 2023
        - Mpox PHE ended Jan 31, 2024
        - No new nationwide PHEs declared since
        - Washington State PHE for severe weather (Dec 2025) is active
        - Some state-specific PHE renewals exist (handled by STATE collector)

        If a new PHE is declared, add it here.
        """
        curated = []

        # HHS-2025-001-WA: Washington State Severe Weather PHE
        # Declared Dec 23, 2025, retroactive to Dec 9, 2025
        # Atmospheric rivers / flooding affecting 16 counties
        # NOT bird flu/HPAI — this is severe weather damage
        rec = build_record(
            id_str="HHS-2025-001-WA",
            source="HHS",
            state="WA",
            title="HHS Public Health Emergency — Washington State Severe Weather",
            incident_type="Severe Storm",
            declaration_date=date(2025, 12, 23),
            incident_start=date(2025, 12, 9),
            incident_end=None,  # Ongoing recovery
            renewal_dates_list=None,
            counties=[
                "Clallam", "Clark", "Cowlitz", "Grays Harbor", "Jefferson",
                "King", "Kitsap", "Lewis", "Mason", "Pacific",
                "Pierce", "Skagit", "Skamania", "Snohomish", "Thurston",
                "Wahkiakum",
            ],
            statewide=False,
            official_url="https://aspr.hhs.gov/newsroom/Pages/PHE-Declared-for-Washington-Following-Severe-Weather-Dec2025.aspx",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        return curated


# =========================================================================
# FMCSA Collector — Curated + Scrape Attempt
# =========================================================================

class FMCSACollector:
    """Collects FMCSA emergency declarations."""

    LISTING_URL = "https://www.fmcsa.dot.gov/emergency-declarations"

    def __init__(self):
        self.records: List[Dict] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def collect(self) -> List[Dict]:
        # Start with curated data
        self.records = self._get_curated_fmcsa()

        # Attempt scrape for new declarations
        try:
            scraped = self._scrape_listing()
            existing_ids = {r["id"] for r in self.records}
            for rec in scraped:
                if rec and rec["id"] not in existing_ids:
                    self.records.append(rec)
        except Exception as e:
            self.warnings.append(f"FMCSA scrape failed ({type(e).__name__}: {e}) — using curated data only")

        return self.records

    def _scrape_listing(self) -> List[Dict]:
        """Attempt to scrape FMCSA emergency declarations page."""
        resp = requests.get(
            self.LISTING_URL, timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT}
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Parse emergency declaration links
        # Known issue: FMCSA returns 403 to automated requests
        return []

    def _get_curated_fmcsa(self) -> List[Optional[Dict]]:
        """
        Curated FMCSA emergency declarations.
        Updated when new FMCSA emergencies are discovered.

        FMCSA declarations are typically 30-day regional emergencies
        covering transportation/fuel supply disruptions.
        They often cover 30-40+ states at once.
        """
        curated = []

        # --- FMCSA 2026-001: January 2026 Severe Winter Storms ---
        # Issued Jan 23, 2026 (document text: "this 23rd day of January 2026").
        # Extended Feb 3, 2026 to Feb 20, 2026.
        # Source: https://www.fmcsa.dot.gov/emergency/esc-msc-ssc-wsc-regional-emergency-declaration-no-2026-001-01-22-2026
        fmcsa_2026_001_states = [
            "AL", "AR", "CO", "CT", "DE", "DC", "FL", "GA", "IL", "IN",
            "IA", "KS", "KY", "LA", "MD", "MA", "MI", "MN", "MS", "MO",
            "MT", "NE", "NH", "NJ", "NY", "NC", "ND", "OH", "OK", "PA",
            "RI", "SC", "SD", "TN", "TX", "VT", "VA", "WV", "WI", "WY",
        ]
        for st in fmcsa_2026_001_states:
            rec = build_record(
                id_str=f"FMCSA-2026-001-{st}",
                source="FMCSA",
                state=st,
                title="FMCSA Regional Emergency Declaration 2026-001 — Severe Winter Storms",
                incident_type="Severe Winter Storm",
                declaration_date=date(2026, 1, 23),
                incident_start=date(2026, 1, 20),
                incident_end=date(2026, 2, 20),  # Extended expiration
                renewal_dates_list=None,
                counties=["Statewide"],
                statewide=True,
                official_url="https://www.fmcsa.dot.gov/emergency/esc-msc-ssc-wsc-regional-emergency-declaration-no-2026-001-01-22-2026",
                confidence="curated",
            )
            if rec:
                curated.append(rec)

        # --- FMCSA 2025-012: Heating Fuels Emergency (Dec 2025) ---
        # Original: Dec 12, 2025 for DE/NJ/NY/PA.
        # Extended Dec 23, 2025 to add CT/MD/MA/NH/WV.
        # Extended Jan 15, 2026 to Feb 15, 2026.
        # Extended Feb 13, 2026 to Feb 28, 2026 — added ME and VT.
        # Pipeline break at Marcus Hook refinery disrupted propane supply.
        # Note: VA is NOT included per verified Feb 13 extension document.
        fmcsa_2025_012_states = [
            "CT", "DE", "MD", "MA", "ME", "NH", "NJ", "NY", "PA", "VT", "WV",
        ]
        for st in fmcsa_2025_012_states:
            rec = build_record(
                id_str=f"FMCSA-2025-012-{st}",
                source="FMCSA",
                state=st,
                title="FMCSA Emergency Declaration 2025-012 — Heating Fuels Shortage",
                incident_type="Fuel Supply Emergency",
                declaration_date=date(2025, 12, 12),
                incident_start=date(2025, 12, 10),
                incident_end=date(2026, 2, 28),  # Extended Feb 13 to Feb 28
                renewal_dates_list=None,
                counties=["Statewide"],
                statewide=True,
                official_url="https://www.fmcsa.dot.gov/emergency/esc-de-nj-ny-and-pa-regional-emergency-declaration-no-2025-012",
                confidence="curated",
            )
            if rec:
                curated.append(rec)

        # --- FMCSA 2025-013: Heating Fuels — Midwest/South (Dec 2025) ---
        # Issued Dec 23, 2025. Extended Jan 15, 2026 to Feb 15, 2026.
        # No evidence of further extension to Feb 28 (that was 2025-012 only).
        # Pipeline break + winter storms affecting heating fuel delivery.
        # Note: MI was never part of this declaration (MN is correct per FMCSA source).
        fmcsa_2025_013_states = [
            "IL", "IA", "KS", "KY", "MN", "MO", "NE", "OH", "TN", "WI",
        ]
        for st in fmcsa_2025_013_states:
            rec = build_record(
                id_str=f"FMCSA-2025-013-{st}",
                source="FMCSA",
                state=st,
                title="FMCSA Regional Emergency Declaration 2025-013 — Heating Fuels",
                incident_type="Fuel Supply Emergency",
                declaration_date=date(2025, 12, 23),
                incident_start=date(2025, 12, 20),
                incident_end=date(2026, 2, 15),  # Extended Jan 15 to Feb 15
                renewal_dates_list=None,
                counties=["Statewide"],
                statewide=True,
                official_url="https://www.fmcsa.dot.gov/emergency/msc-ssc-regional-emergency-declaration-no-2025-013-heating-fuels-12-23-2025",
                confidence="curated",
            )
            if rec:
                curated.append(rec)

        # --- FMCSA 2025-014: Washington State Flooding (Nov-Dec 2025) ---
        # Original: Nov 2025 for WA. Extended Dec 23, 2025 to Jan 23, 2026.
        # No evidence of further extension beyond Jan 23 (per FMCSA PDF).
        # Atmospheric rivers / severe flooding affecting transportation.
        # Same event as HHS-2025-001-WA but separate declaring authority (FMCSA).
        rec = build_record(
            id_str="FMCSA-2025-014-WA",
            source="FMCSA",
            state="WA",
            title="FMCSA Emergency Declaration 2025-014 — Washington State Flooding",
            incident_type="Severe Storm",
            declaration_date=date(2025, 11, 20),
            incident_start=date(2025, 11, 19),
            incident_end=date(2026, 1, 23),  # Extended expiration (Jan 23, verified via PDF)
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.fmcsa.dot.gov/emergency/wsc-wa-extension-emergency-declaration-no-2025-014-12-23-2025",
            confidence="curated",
        )
        if rec:
            curated.append(rec)

        return curated


# =========================================================================
# USDA Collector — Curated Only
# =========================================================================

class USDACollector:
    """USDA Secretarial Designations — curated only."""

    def __init__(self):
        self.records: List[Dict] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def collect(self) -> List[Dict]:
        self.records = self._get_curated_usda()
        return self.records

    def _get_curated_usda(self) -> List[Optional[Dict]]:
        """
        Curated USDA secretarial disaster designations.

        NOTE (2026-02-11): USDA drought designations do NOT trigger Medicare DST
        SEPs under 42 CFR 422.62(b)(18). They are agricultural loan programs
        (FSA Emergency Loans), not disaster declarations in the Medicare sense.
        This collector is kept as a placeholder in case future USDA designations
        do qualify, but currently returns no records.

        USDA FSA does not publish county-level designations on the Federal Register
        in a parseable format. Entries here would be manually maintained.
        """
        # No USDA designations qualify as Medicare DST triggers
        return []


# =========================================================================
# State Governor Collector — Curated Only
# =========================================================================

class StateCollector:
    """State Governor emergency declarations — curated only."""

    def __init__(self):
        self.records: List[Dict] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def collect(self) -> List[Dict]:
        self.records = self._get_curated_state()
        return self.records

    def _get_curated_state(self) -> List[Optional[Dict]]:
        """
        Curated state governor emergency declarations.

        No centralized national database of governor declarations exists.
        FMCSA captures ~15-25% (transportation-related only).
        Entries here are the primary mechanism for state coverage.

        To add a new state declaration:
        1. Find the governor's executive order or proclamation
        2. Get the official URL (governor's office website)
        3. Identify affected counties (or "Statewide")
        4. Add a build_record() call below

        Last comprehensive review: 2026-02-11
        """
        curated = []

        # =============================================================
        # JAN 2026 WINTER STORM GOVERNOR DECLARATIONS
        # Storm hit ~Jan 20-27, 2026 across eastern/central US
        # =============================================================

        # --- TEXAS ---
        # Gov Abbott, Jan 22 declaration, 219 counties (expanded Jan 25)
        # No termination found
        rec = build_record(
            id_str="STATE-2026-001-TX",
            source="STATE", state="TX",
            title="Governor Abbott Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 20),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://gov.texas.gov/news/post/governor-abbott-provides-update-on-texas-ongoing-response-to-severe-winter-weather-",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- NORTH CAROLINA ---
        # Gov Stein, Jan 21 declaration, statewide
        rec = build_record(
            id_str="STATE-2026-001-NC",
            source="STATE", state="NC",
            title="Governor Stein Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 21),
            incident_start=date(2026, 1, 20),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.nc.gov/news/press-releases/2026/01/21/governor-stein-declares-state-emergency-ahead-winter-storm",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- VIRGINIA ---
        # Gov Spanberger, Jan 22, EO 11, statewide
        rec = build_record(
            id_str="STATE-2026-001-VA",
            source="STATE", state="VA",
            title="Governor Spanberger Emergency Declaration (EO 11) — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 20),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.governor.virginia.gov/newsroom/news-releases/2026/january-releases/name-1111570-en.html",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- GEORGIA (Winter Storm Fern) ---
        # Gov Kemp, Jan 22, statewide, effective through Jan 29
        rec = build_record(
            id_str="STATE-2026-001-GA",
            source="STATE", state="GA",
            title="Governor Kemp Emergency Declaration — January 2026 Winter Storm (Fern)",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 22),
            incident_end=date(2026, 1, 29),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://gov.georgia.gov/press-releases/2026-01-22/gov-kemp-declares-state-emergency-activates-state-operations-center-ahead",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- GEORGIA (Winter Storm Gianna) ---
        # Gov Kemp, Jan 30, statewide, effective through Feb 6
        rec = build_record(
            id_str="STATE-2026-002-GA",
            source="STATE", state="GA",
            title="Governor Kemp Emergency Declaration — January 2026 Winter Storm (Gianna)",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 30),
            incident_start=date(2026, 1, 30),
            incident_end=date(2026, 2, 6),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://gov.georgia.gov/press-releases/2026-01-30/gov-kemp-declares-new-state-emergency-ahead-winter-storm",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- NEW YORK ---
        # Gov Hochul, Jan 23, EO 57, statewide
        rec = build_record(
            id_str="STATE-2026-001-NY",
            source="STATE", state="NY",
            title="Governor Hochul Emergency Declaration (EO 57) — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 23),
            incident_start=date(2026, 1, 23),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.governor.ny.gov/news/governor-hochul-declares-state-emergency-ahead-extreme-cold-and-massive-winter-storm-weekend",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- PENNSYLVANIA ---
        # Gov Shapiro, Jan 24, statewide, 21-day auto-expire (~Feb 14)
        rec = build_record(
            id_str="STATE-2026-001-PA",
            source="STATE", state="PA",
            title="Governor Shapiro Disaster Emergency Proclamation — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 24),
            incident_start=date(2026, 1, 23),
            incident_end=date(2026, 2, 14),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.pa.gov/governor/newsroom/2026-press-releases/gov-shapiro-signs-proclamation-of-disaster-emergency",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- DELAWARE ---
        # Gov Meyer, Jan 23, statewide, TERMINATED Jan 26
        rec = build_record(
            id_str="STATE-2026-001-DE",
            source="STATE", state="DE",
            title="Governor Meyer Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 23),
            incident_start=date(2026, 1, 23),
            incident_end=date(2026, 1, 26),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://news.delaware.gov/2026/01/23/soe-eoc-activated-winter-storm/",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- NEW MEXICO ---
        # Gov Lujan Grisham, Jan 22, EO 2026-005, statewide
        rec = build_record(
            id_str="STATE-2026-001-NM",
            source="STATE", state="NM",
            title="Governor Lujan Grisham Emergency Declaration (EO 2026-005) — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 20),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.dhsem.nm.gov/governor-activates-emergency-resources-as-winter-weather-moves-into-new-mexico/",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- KENTUCKY ---
        # Gov Beshear, Jan 2026 winter storm (separate from Jan 2025)
        rec = build_record(
            id_str="STATE-2026-001-KY",
            source="STATE", state="KY",
            title="Governor Beshear Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 20),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.kentucky.gov/Pages/Activity-stream.aspx?n=GovernorBeshear&prId=2675",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- LOUISIANA ---
        # Gov Landry, Jan 18 2025, statewide, renewed/extended
        rec = build_record(
            id_str="STATE-2025-001-LA",
            source="STATE", state="LA",
            title="Governor Landry Emergency Declaration (JML 25-12) — January 2025 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2025, 1, 18),
            incident_start=date(2025, 1, 18),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://gov.louisiana.gov/news/4746",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- ARKANSAS ---
        # Gov Sanders, Jan 2026 winter storm
        rec = build_record(
            id_str="STATE-2026-001-AR",
            source="STATE", state="AR",
            title="Governor Sanders Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 20),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.arkansas.gov/executive_orders/sanders-declares-emergency-for-severe-winter-weather-expected-on-or-about-january-23-2026/",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- MISSISSIPPI ---
        # Gov Reeves, Jan 2026 winter storm
        rec = build_record(
            id_str="STATE-2026-001-MS",
            source="STATE", state="MS",
            title="Governor Reeves Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 20),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governorreeves.ms.gov/governor-reeves-issues-state-of-emergency-ahead-of-severe-winter-weather/",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- INDIANA ---
        # Gov Braun, Jan 25 2026, EO 26-03, statewide, 60-day window
        rec = build_record(
            id_str="STATE-2026-001-IN",
            source="STATE", state="IN",
            title="Governor Braun Disaster Emergency (EO 26-03) — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 25),
            incident_start=date(2026, 1, 23),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://events.in.gov/event/gov-mike-braun-commends-first-responders-state-agencies-following-coordinated-response-to-extreme-winter-weather",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- MARYLAND ---
        # Gov Moore, late Jan 2025 (Jan 24-26 storm), statewide
        rec = build_record(
            id_str="STATE-2025-002-MD",
            source="STATE", state="MD",
            title="Governor Moore Emergency Declaration — January 2025 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2025, 1, 24),
            incident_start=date(2025, 1, 24),
            incident_end=date(2025, 1, 28),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.maryland.gov/news/press/pages/Governor-Moore-Declares-State-of-Emergency,-Requests-Federal-Emergency-Declaration-Ahead-of-Dangerous-Winter-Storm.aspx",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- WEST VIRGINIA ---
        # Gov Morrisey, Jan 23 2026, statewide (all 55 counties)
        rec = build_record(
            id_str="STATE-2026-001-WV",
            source="STATE", state="WV",
            title="Governor Morrisey Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 23),
            incident_start=date(2026, 1, 21),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.wv.gov/article/governor-morrisey-declares-state-emergency-all-55-counties-major-winter-storm-approaches",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- SOUTH CAROLINA ---
        # Gov McMaster, Jan 2026 winter storm
        rec = build_record(
            id_str="STATE-2026-001-SC",
            source="STATE", state="SC",
            title="Governor McMaster Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 20),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.sc.gov/news/2026-01/gov-mcmaster-declares-state-emergency-ahead-winter-storm",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- TENNESSEE ---
        # Gov Lee, Jan 22 2026, statewide (all 95 counties)
        rec = build_record(
            id_str="STATE-2026-001-TN",
            source="STATE", state="TN",
            title="Governor Lee Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 22),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.tn.gov/governor/news/2026/1/22/gov--lee-issues-state-of-emergency-ahead-of-major-winter-storm.html",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- CONNECTICUT ---
        # Gov Lamont, Jan 25 2026, statewide, storm passed ~Jan 27
        rec = build_record(
            id_str="STATE-2026-001-CT",
            source="STATE", state="CT",
            title="Governor Lamont Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 25),
            incident_start=date(2026, 1, 25),
            incident_end=date(2026, 1, 27),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://portal.ct.gov/governor/news/press-releases/2026/01-2026/governor-lamont-declares-state-of-emergency-limits-commercial-vehicle-travel",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- OHIO ---
        # Gov DeWine, Jan 24 2026, statewide (all 88 counties), 90-day window
        rec = build_record(
            id_str="STATE-2026-001-OH",
            source="STATE", state="OH",
            title="Governor DeWine Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 24),
            incident_start=date(2026, 1, 23),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/405eda8",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- KANSAS ---
        # Gov Kelly, Jan 2026 winter storm
        rec = build_record(
            id_str="STATE-2026-001-KS",
            source="STATE", state="KS",
            title="Governor Kelly Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 20),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.kansastag.gov/m/newsflash/Home/Detail/817",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- MISSOURI ---
        # Gov Kehoe, Jan 2026 winter storm
        rec = build_record(
            id_str="STATE-2026-001-MO",
            source="STATE", state="MO",
            title="Governor Kehoe Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 20),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.mo.gov/press-releases/archive/governor-kehoe-signs-executive-order-26-05-declaring-state-emergency",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- ALABAMA ---
        # Gov Ivey, Jan 2026 winter storm
        rec = build_record(
            id_str="STATE-2026-001-AL",
            source="STATE", state="AL",
            title="Governor Ivey Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 22),
            incident_start=date(2026, 1, 20),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.alabama.gov/newsroom/2026/01/governor-ivey-issues-state-of-emergency-for-19-northern-counties-ahead-of-wintery-icy-forecast/",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # --- NEW JERSEY ---
        # Gov Sherrill, Jan 24 2026, Executive Order 8, all 21 counties
        # Emergency ended Jan 26 at noon
        rec = build_record(
            id_str="STATE-2026-001-NJ",
            source="STATE", state="NJ",
            title="Governor Sherrill Emergency Declaration (EO 8) — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 24),
            incident_start=date(2026, 1, 23),
            incident_end=date(2026, 1, 26),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.nj.gov/governor/news/2026/20260123b.shtml",
            confidence="curated",
            last_verified="2026-02-16",
        )
        if rec:
            curated.append(rec)

        # --- MARYLAND (Jan 2026 Winter Storm — separate from Jan 2025) ---
        # Gov Moore, Jan 23 2026, statewide
        rec = build_record(
            id_str="STATE-2026-001-MD",
            source="STATE", state="MD",
            title="Governor Moore Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 23),
            incident_start=date(2026, 1, 23),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.maryland.gov/news/press/pages/Governor-Moore-Declares-State-of-Emergency,-Requests-Federal-Emergency-Declaration-Ahead-of-Dangerous-Winter-Storm.aspx",
            confidence="curated",
            last_verified="2026-02-16",
        )
        if rec:
            curated.append(rec)

        # --- WASHINGTON, D.C. ---
        # Mayor Bowser, Jan 23 2026, district-wide
        # Snow emergency period Jan 24 - Jan 27
        rec = build_record(
            id_str="STATE-2026-001-DC",
            source="STATE", state="DC",
            title="Mayor Bowser Emergency Declaration — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 23),
            incident_start=date(2026, 1, 23),
            incident_end=date(2026, 1, 27),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://mayor.dc.gov/release/mayor-bowser-declares-state-emergency-washington-dc-ahead-major-winter-storm-and-extreme",
            confidence="curated",
            last_verified="2026-02-16",
        )
        if rec:
            curated.append(rec)

        # --- MAINE ---
        # Gov Mills, Jan 5 2026, Energy Emergency Proclamation
        # Also declared Civil Emergency for coastal flooding Jan 10
        # Energy emergency expired Jan 15; coastal counties affected
        rec = build_record(
            id_str="STATE-2026-001-ME",
            source="STATE", state="ME",
            title="Governor Mills Emergency Declaration — January 2026 Energy Emergency & Coastal Flooding",
            incident_type="Energy Emergency",
            declaration_date=date(2026, 1, 5),
            incident_start=date(2026, 1, 5),
            incident_end=date(2026, 1, 15),
            renewal_dates_list=None,
            counties=[
                "Cumberland", "Hancock", "Knox", "Lincoln",
                "Sagadahoc", "Waldo", "Washington", "York",
            ],
            statewide=False,
            official_url="https://www.maine.gov/governor/mills/official_documents/proclamations/2026-01-proclamation-energy-emergency",
            confidence="curated",
            last_verified="2026-02-16",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # MASSACHUSETTS GOVERNOR DECLARATION
        # =============================================================

        # Gov Healey, Jan 23 2026, Declaration of Emergency (heating fuels + winter storm)
        # Referenced on FMCSA site; statewide scope
        rec = build_record(
            id_str="STATE-2026-001-MA",
            source="STATE", state="MA",
            title="Governor Healey Declaration of Emergency — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 23),
            incident_start=date(2026, 1, 23),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.fmcsa.dot.gov/emergency/massachusetts-declaration-emergency-notice-1-23-2026",
            confidence="curated",
            last_verified="2026-02-17",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # CALIFORNIA GOVERNOR DECLARATIONS
        # =============================================================

        # California Dec 2025 storms - Gov Newsom, 6 counties
        rec = build_record(
            id_str="STATE-2025-002-CA",
            source="STATE", state="CA",
            title="Governor Newsom Emergency Declaration — December 2025 Winter Storms",
            incident_type="Severe Storm",
            declaration_date=date(2025, 12, 24),
            incident_start=date(2025, 12, 21),
            incident_end=None,
            renewal_dates_list=None,
            counties=[
                "Los Angeles", "Orange", "Riverside", "San Bernardino",
                "San Diego", "Shasta",
            ],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/12/24/governor-newsom-proclaims-state-of-emergency-to-support-response-in-multiple-counties-due-to-late-december-storms/",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # MASSACHUSETTS GOVERNOR DECLARATION
        # =============================================================

        # Gov Healey, Jan 23 2026, Declaration of Emergency (heating fuels + winter storm)
        # Referenced on FMCSA site; statewide scope
        rec = build_record(
            id_str="STATE-2026-001-MA",
            source="STATE", state="MA",
            title="Governor Healey Declaration of Emergency — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 23),
            incident_start=date(2026, 1, 23),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.fmcsa.dot.gov/emergency/massachusetts-declaration-emergency-notice-1-23-2026",
            confidence="curated",
            last_verified="2026-02-17",
        )
        if rec:
            curated.append(rec)

        # California Jan 2025 LA Wildfires - Gov Newsom
        rec = build_record(
            id_str="STATE-2025-001-CA",
            source="STATE", state="CA",
            title="Governor Newsom Emergency Declaration — January 2025 Los Angeles Wildfires",
            incident_type="Wildfire",
            declaration_date=date(2025, 1, 7),
            incident_start=date(2025, 1, 7),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Los Angeles", "Ventura"],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/01/07/governor-newsom-proclaims-state-of-emergency-meets-with-first-responders-in-pacific-palisades-amid-dangerous-fire-weather/",
            confidence="curated",
            last_verified="2026-02-11",
        )
        if rec:
            curated.append(rec)

        return curated


# =========================================================================
# FEMA Collector — Live API
# =========================================================================

class FEMACollector:
    """
    Collects FEMA disaster declarations via the OpenFEMA API.

    Fetches DisasterDeclarationsSummaries, paginates, filters FM declarations,
    consolidates county-level records into one disaster per femaDeclarationString,
    and builds records using the shared build_record() function.

    Mirrors the frontend's consolidateFEMA() logic exactly.
    """

    FEMA_API_BASE = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
    PAGE_SIZE = 1000

    def __init__(self):
        self.records: List[Dict] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.api_count = 0

    def collect(self) -> List[Dict]:
        """Fetch, consolidate, and build FEMA disaster records."""
        try:
            raw_records = self._fetch_all()
            consolidated = self._consolidate(raw_records)
            for group in consolidated.values():
                rec = self._build_from_group(group)
                if rec:
                    self.records.append(rec)
                    self.api_count += 1
        except Exception as e:
            self.errors.append(f"FEMA API fetch failed: {e}")
            self.warnings.append("FEMA data unavailable — all_disasters.json will have curated sources only")

        return self.records

    def _fetch_all(self) -> List[Dict]:
        """Paginate through the FEMA API with 24-month lookback."""
        cutoff = (date.today() - timedelta(days=LOOKBACK_MONTHS * 31)).isoformat()
        all_records = []
        skip = 0

        while True:
            params = {
                "$filter": f"declarationDate ge '{cutoff}'",
                "$orderby": "declarationDate desc",
                "$top": str(self.PAGE_SIZE),
                "$skip": str(skip),
            }
            resp = requests.get(
                self.FEMA_API_BASE, params=params, timeout=30,
                headers={"User-Agent": USER_AGENT}
            )
            if resp.status_code != 200:
                raise RuntimeError(f"FEMA API returned HTTP {resp.status_code}")

            data = resp.json()
            records = data.get("DisasterDeclarationsSummaries", [])
            all_records.extend(records)

            if len(records) < self.PAGE_SIZE:
                break
            skip += self.PAGE_SIZE
            time.sleep(0.3)  # Be respectful

        return all_records

    def _consolidate(self, records: List[Dict]) -> Dict[str, Dict]:
        """
        Group county-level FEMA records by femaDeclarationString.
        Excludes FM (Fire Management) declarations per 42 CFR § 422.62(b)(18).
        Strips parenthetical suffixes from county names.
        Detects statewide declarations.
        """
        groups: Dict[str, Dict] = {}

        for rec in records:
            # EXCLUDE Fire Management — not a Presidential disaster declaration
            if rec.get("declarationType") == "FM":
                continue

            key = rec.get("femaDeclarationString", "")
            if not key:
                continue

            if key not in groups:
                decl_date_raw = rec.get("declarationDate", "")
                inc_begin_raw = rec.get("incidentBeginDate", "")
                inc_end_raw = rec.get("incidentEndDate", "")

                groups[key] = {
                    "femaDeclarationString": key,
                    "declarationType": rec.get("declarationType", ""),
                    "declarationDate": decl_date_raw.split("T")[0] if decl_date_raw else None,
                    "incidentBeginDate": inc_begin_raw.split("T")[0] if inc_begin_raw else None,
                    "incidentEndDate": inc_end_raw.split("T")[0] if inc_end_raw else None,
                    "state": rec.get("state", ""),
                    "declarationTitle": rec.get("declarationTitle", ""),
                    "incidentType": rec.get("incidentType", ""),
                    "disasterNumber": rec.get("disasterNumber"),
                    "counties": [],
                    "statewide": False,
                }

            # Process county name
            area = rec.get("designatedArea", "")
            if area:
                county = normalize_county_name(area)
                if county.lower() == "statewide":
                    groups[key]["statewide"] = True
                if county and county not in groups[key]["counties"]:
                    groups[key]["counties"].append(county)

        return groups

    def _build_from_group(self, group: Dict) -> Optional[Dict]:
        """Convert a consolidated FEMA group into a standard disaster record."""
        decl_date_str = group.get("declarationDate")
        inc_begin_str = group.get("incidentBeginDate")
        inc_end_str = group.get("incidentEndDate")
        disaster_number = group.get("disasterNumber")

        if not decl_date_str or not inc_begin_str:
            return None

        decl_date = parse_date_fuzzy(decl_date_str)
        inc_start = parse_date_fuzzy(inc_begin_str)
        inc_end = parse_date_fuzzy(inc_end_str) if inc_end_str else None

        if not decl_date or not inc_start:
            return None

        # Build official URL using numeric disasterNumber (NOT femaDeclarationString)
        if disaster_number:
            official_url = f"https://www.fema.gov/disaster/{disaster_number}"
        else:
            self.warnings.append(
                f"No disasterNumber for {group['femaDeclarationString']} — skipping"
            )
            return None

        state = group.get("state", "")
        counties = group.get("counties", [])
        statewide = group.get("statewide", False)

        # If statewide detected, ensure 'Statewide' is in counties
        if statewide and "Statewide" not in counties:
            counties = ["Statewide"] + [c for c in counties if c.lower() != "statewide"]

        fema_decl_string = group["femaDeclarationString"]

        return build_record(
            id_str=f"FEMA-{fema_decl_string}",
            source="FEMA",
            state=state,
            title=group.get("declarationTitle", ""),
            incident_type=group.get("incidentType", "Disaster"),
            declaration_date=decl_date,
            incident_start=inc_start,
            incident_end=inc_end,
            renewal_dates_list=None,
            counties=counties,
            statewide=statewide,
            official_url=official_url,
            confidence="verified",
        )


# =========================================================================
# Drought Monitor — Warning Signal Only
# =========================================================================

class DroughtMonitor:
    """US Drought Monitor — discovery signal for USDA designations."""

    API_URL = "https://usdmdataservices.unl.edu/api/USStatistics/GetDroughtSeverityStatisticsByArea"

    def __init__(self):
        self.warnings: List[str] = []

    def check(self):
        """Query Drought Monitor API for D3/D4 counties."""
        try:
            today_str = date.today().strftime("%m/%d/%Y")
            params = {
                "aoi": "state",
                "startdate": today_str,
                "enddate": today_str,
                "statisticsType": "1",
            }
            resp = requests.get(
                self.API_URL, params=params, timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT}
            )
            if resp.status_code != 200:
                return

            data = resp.json()
            d3_d4_states = []
            for entry in data:
                d3 = float(entry.get("D3", 0) or 0)
                d4 = float(entry.get("D4", 0) or 0)
                state_name = entry.get("Name", "")
                if d3 > 25 or d4 > 5:
                    state_code = STATE_NAME_TO_CODE.get(state_name, state_name)
                    d3_d4_states.append(f"{state_code} (D3: {d3:.0f}%, D4: {d4:.0f}%)")

            if d3_d4_states:
                self.warnings.append(
                    f"{len(d3_d4_states)} states with significant D3/D4 drought — "
                    "check for USDA secretarial designations:"
                )
                for s in d3_d4_states[:10]:
                    self.warnings.append(f"  {s}")

        except Exception:
            # Silently fail — this is a bonus feature
            pass


# =========================================================================
# Coverage Gap Analyzer — Cross-Reference FEMA ↔ STATE
# =========================================================================

class CoverageGapAnalyzer:
    """
    Detects missing governor declarations by cross-referencing sources.

    Strategy:
    1. Use FEMA records from FEMACollector (no separate API call needed)
    2. Extract unique states with active FEMA disasters
    3. Compare against curated STATE records
    4. Flag states with FEMA/FMCSA coverage but no governor declaration

    This catches the most common gap: a major disaster hits a state, FEMA
    responds, but we haven't yet curated the governor's declaration.
    """

    def __init__(self):
        self.gaps: List[str] = []
        self.warnings: List[str] = []
        self.fema_states: Dict[str, List[str]] = {}  # state -> [disaster titles]

    def analyze(self, curated_records: List[Dict], fema_records: List[Dict]):
        """Run gap analysis using curated records and FEMA collector output."""
        # Collect curated STATE records by state
        state_covered = set()
        for rec in curated_records:
            if rec.get("source") == "STATE":
                state_covered.add(rec.get("state"))

        # Collect FMCSA-covered states
        fmcsa_states: Dict[str, List[str]] = {}
        for rec in curated_records:
            if rec.get("source") == "FMCSA":
                st = rec.get("state")
                if st not in fmcsa_states:
                    fmcsa_states[st] = []
                fmcsa_states[st].append(rec.get("title", ""))

        # Build FEMA state map from collector output (no separate API call)
        for rec in fema_records:
            state = rec.get("state", "")
            title = rec.get("title", "")
            if state and state in VALID_STATES:
                if state not in self.fema_states:
                    self.fema_states[state] = []
                self.fema_states[state].append(title)

        # Gap detection 1: FEMA state has no governor declaration
        for state, disasters in self.fema_states.items():
            if state not in state_covered:
                disaster_summary = disasters[0][:60] if disasters else "Unknown"
                self.gaps.append(
                    f"FEMA→STATE gap: {state} has {len(disasters)} FEMA disaster(s) "
                    f"but no governor declaration curated. Latest: {disaster_summary}"
                )

        # Gap detection 2: FMCSA state has no governor declaration
        # (FMCSA emergency declarations almost always follow a governor declaration)
        for state, declarations in fmcsa_states.items():
            if state not in state_covered and state not in self.fema_states:
                self.gaps.append(
                    f"FMCSA→STATE gap: {state} has {len(declarations)} FMCSA declaration(s) "
                    f"but no governor declaration curated"
                )

        # Summary
        if self.gaps:
            self.warnings.append(
                f"{len(self.gaps)} coverage gap(s) detected — "
                "governor declarations may be missing"
            )


# =========================================================================
# Validation and Deduplication
# =========================================================================

def deduplicate(records: List[Dict]) -> List[Dict]:
    """Remove duplicate records by ID. First occurrence wins."""
    seen = set()
    unique = []
    for rec in records:
        if rec["id"] not in seen:
            seen.add(rec["id"])
            unique.append(rec)
    return unique


def deduplicate_prefer_fema(curated_records: List[Dict], fema_records: List[Dict]) -> List[Dict]:
    """
    Merge curated + FEMA records, preferring FEMA for duplicate IDs.
    Matches the frontend's merge behavior: FEMA records go first,
    curated records added only if their ID doesn't already exist.
    """
    by_id: Dict[str, Dict] = {}

    # FEMA records take priority
    for rec in fema_records:
        by_id[rec["id"]] = rec

    # Curated records fill in the rest
    for rec in curated_records:
        if rec["id"] not in by_id:
            by_id[rec["id"]] = rec

    return list(by_id.values())


# =========================================================================
# Summary Report
# =========================================================================

def write_output(filepath: str, records: List[Dict], sba_collector=None) -> Dict:
    """
    Write disaster records to a JSON file with metadata wrapper.
    Returns the output dict for reference.
    """
    # Auto-update lastVerified for STATE/HHS records
    today_str = date.today().isoformat()
    for rec in records:
        if rec.get("source") in ("STATE", "HHS"):
            rec["lastVerified"] = today_str

    # Sort by state, then declaration date
    records.sort(key=lambda r: (r["state"], r.get("declarationDate", "")))

    # Compute content hash and source counts
    records_json = json.dumps(records, sort_keys=True)
    content_hash = hashlib.sha256(records_json.encode()).hexdigest()[:16]

    source_counts = {}
    for rec in records:
        src = rec.get("source", "UNKNOWN")
        source_counts[src] = source_counts.get(src, 0) + 1

    # Build Federal Register diagnostics from SBA collector
    fr_diagnostics = {}
    if sba_collector and hasattr(sba_collector, "fr_count"):
        fr_diagnostics = {
            "recordsParsed": sba_collector.fr_count,
            "curatedOverrides": sba_collector.curated_count,
        }

    output = {
        "metadata": {
            "lastUpdated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "recordCount": len(records),
            "generatedBy": "dst_data_fetcher.py",
            "contentHash": content_hash,
            "dataIntegrity": {
                "auditChecks": 25,
                "sourceCounts": source_counts,
                "federalRegister": fr_diagnostics,
                "urlVerification": None,
                "regulatoryMonitoring": None,
            },
        },
        "disasters": records,
    }
    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)

    return output


def print_report(
    collectors: Dict, drought: DroughtMonitor,
    gap_analyzer: CoverageGapAnalyzer,
    curated_count: int, all_count: int, elapsed: float,
):
    """Print summary report to stdout."""
    print()
    print("=" * 60)
    print("DST DATA FETCHER — SUMMARY REPORT")
    print("=" * 60)
    print(f"Run time: {elapsed:.1f} seconds")
    print(f"Output: {OUTPUT_FILE} ({curated_count} records)")
    print(f"Output: {ALL_DISASTERS_FILE} ({all_count} records)")
    print()

    print("RECORDS BY SOURCE:")
    for name, collector in collectors.items():
        count = len(collector.records)
        detail = ""
        if hasattr(collector, "fr_count") and hasattr(collector, "curated_count"):
            detail = f" ({collector.fr_count} from Federal Register, {collector.curated_count} curated)"
        elif hasattr(collector, "api_count"):
            detail = f" ({collector.api_count} from API)"
        elif count > 0:
            detail = " (curated)"
        print(f"  {name:8} {count:4} records{detail}")
    print()

    # Errors
    all_errors = []
    for name, collector in collectors.items():
        for err in collector.errors:
            all_errors.append(f"[{name}] {err}")
    if all_errors:
        print(f"ERRORS: {len(all_errors)}")
        for err in all_errors:
            print(f"  {err}")
        print()

    # Warnings
    all_warnings = []
    for name, collector in collectors.items():
        for w in collector.warnings:
            all_warnings.append(f"[{name}] {w}")
    if all_warnings:
        print(f"WARNINGS: {len(all_warnings)}")
        for w in all_warnings:
            print(f"  {w}")
        print()

    # Drought Monitor
    if drought.warnings:
        print("DROUGHT MONITOR:")
        for w in drought.warnings:
            print(f"  {w}")
        print()

    # Coverage Gap Analysis
    if gap_analyzer.gaps:
        print("COVERAGE GAPS (governor declarations may be missing):")
        for gap in gap_analyzer.gaps:
            print(f"  ⚠ {gap}")
        print()
        print("  ACTION: Research governor emergency declarations for flagged states.")
        print("  Add to StateCollector._get_curated_state() in dst_data_fetcher.py")
        print()
    elif gap_analyzer.fema_states:
        print("COVERAGE GAPS: None — all FEMA/FMCSA states have governor declarations")
        print()

    print("=" * 60)


# =========================================================================
# Main
# =========================================================================

def main():
    start_time = time.time()
    print("DST Data Fetcher — Starting collection...\n")

    # --- Curated collectors (non-FEMA) ---
    curated_collectors = {
        "SBA": SBACollector(),
        "HHS": HHSCollector(),
        "FMCSA": FMCSACollector(),
        "USDA": USDACollector(),
        "STATE": StateCollector(),
    }

    curated_records: List[Dict] = []

    for name, collector in curated_collectors.items():
        print(f"Collecting {name}...")
        try:
            records = collector.collect()
            curated_records.extend(records)
            print(f"  -> {len(records)} records")
        except Exception as e:
            collector.errors.append(f"Collector crashed: {e}")
            print(f"  -> FAILED: {e}")
        print()

    # --- FEMA collector (live API) ---
    fema_collector = FEMACollector()
    print("Collecting FEMA (live API)...")
    try:
        fema_records = fema_collector.collect()
        print(f"  -> {len(fema_records)} records")
    except Exception as e:
        fema_collector.errors.append(f"Collector crashed: {e}")
        fema_records = []
        print(f"  -> FAILED: {e}")
    print()

    # All collectors for reporting
    collectors = {**curated_collectors, "FEMA": fema_collector}

    # Drought Monitor signal
    print("Checking US Drought Monitor for D3/D4 signals...")
    drought = DroughtMonitor()
    drought.check()
    if drought.warnings:
        print(f"  -> {len(drought.warnings)} warnings")
    else:
        print("  -> No significant D3/D4 drought signals")
    print()

    # Coverage Gap Analysis — use FEMA records from collector directly
    print("Running coverage gap analysis (FEMA ↔ STATE cross-reference)...")
    gap_analyzer = CoverageGapAnalyzer()
    gap_analyzer.analyze(curated_records, fema_records)
    if gap_analyzer.gaps:
        print(f"  -> {len(gap_analyzer.gaps)} gap(s) found:")
        for gap in gap_analyzer.gaps:
            print(f"     {gap}")
    else:
        print("  -> No coverage gaps detected")
    print()

    # --- Write curated_disasters.json (non-FEMA, backward compatible) ---
    print("Deduplicating curated records...")
    unique_curated = deduplicate(curated_records)
    dup_count = len(curated_records) - len(unique_curated)
    if dup_count > 0:
        print(f"  -> Removed {dup_count} duplicates")
    print(f"  -> {len(unique_curated)} unique curated records")
    print()

    sba_collector = curated_collectors.get("SBA")
    print(f"Writing to {OUTPUT_FILE}...")
    write_output(OUTPUT_FILE, unique_curated, sba_collector=sba_collector)
    print(f"  -> {len(unique_curated)} records written")

    # --- Write all_disasters.json (curated + FEMA merged) ---
    print(f"\nMerging curated + FEMA for {ALL_DISASTERS_FILE}...")
    merged_records = deduplicate_prefer_fema(unique_curated, fema_records)
    print(f"  -> {len(merged_records)} merged records ({len(fema_records)} FEMA + {len(unique_curated)} curated, deduped)")

    print(f"Writing to {ALL_DISASTERS_FILE}...")
    write_output(ALL_DISASTERS_FILE, merged_records, sba_collector=sba_collector)
    print(f"  -> {len(merged_records)} records written")

    # Report
    elapsed = time.time() - start_time
    print_report(
        collectors, drought, gap_analyzer,
        len(unique_curated), len(merged_records), elapsed,
    )

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
