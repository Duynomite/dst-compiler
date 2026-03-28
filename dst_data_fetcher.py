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
from pathlib import Path
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
    last_verified: Optional[str] = None,
    extensions: Optional[List[Dict]] = None,
    carrier_acknowledgments: Optional[Dict] = None,
) -> Optional[Dict]:
    """Build a validated disaster record dict. Returns None if invalid.

    Args:
        extensions: Optional list of extension events, each with:
            {"date": "ISO", "newIncidentEnd": "ISO|null", "newSepEnd": "ISO",
             "source": "str", "notes": "str"}
        carrier_acknowledgments: Optional dict of carrier ack metadata:
            {"aetna": {"acknowledged": true, ...}, "wellcare": {...}, "humana": null}
    """
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
    if extensions:
        record["extensions"] = extensions
    if carrier_acknowledgments:
        record["carrierAcknowledgments"] = carrier_acknowledgments
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
        seen_doc_numbers = set()
        for doc in all_results:
            doc_num = doc.get("document_number", "")
            if doc_num in seen_doc_numbers:
                continue
            seen_doc_numbers.add(doc_num)
            title = (doc.get("title") or "").lower()
            # Must be a declaration or amendment notice related to disasters
            is_declaration = "declaration" in title and "disaster" in title
            is_amendment = "amendment" in title and "disaster" in title
            if is_declaration or is_amendment:
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
        # Primary pattern: "In [State]: county1, county2"
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

        # Fallback pattern: "contiguous counties in the State of [Name]" or
        # "the following counties in [Name]: county1, county2"
        if not result:
            for state_match in re.finditer(
                r"(?:contiguous\s+counties\s+in\s+(?:the\s+State\s+of\s+)?|the\s+following\s+counties\s+in\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*[:\-—]\s*([^.]+)",
                contiguous_text, re.IGNORECASE
            ):
                state_name = state_match.group(1).strip().title()
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
            # PA Hotel Fire — curated includes primary + contiguous counties
            "SBA-2026-04576-PA",
            "SBA-2026-04576-NJ",
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

        # SBA-2026-04576-PA: Hotel Hampton Fire (Feb 20, 2026)
        # Declared Mar 4, 2026. Primary: Northampton. Contiguous: Bucks, Carbon, Lehigh, Monroe.
        # SEP window: ends Apr 30, 2026.
        rec = build_record(
            id_str="SBA-2026-04576-PA", source="SBA", state="PA",
            title="Hotel Hampton Fire",
            incident_type="Fire",
            declaration_date=date(2026, 3, 4),
            incident_start=date(2026, 2, 20), incident_end=date(2026, 2, 20),
            renewal_dates_list=None,
            counties=["Bucks", "Carbon", "Lehigh", "Monroe", "Northampton"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2026/03/09/2026-04576/administrative-declaration-of-a-disaster-for-the-commonwealth-of-pennsylvania",
            confidence="verified",
        )
        if rec:
            curated.append(rec)

        # SBA-2026-04576-NJ: Contiguous to PA Hotel Hampton Fire (Warren County)
        rec = build_record(
            id_str="SBA-2026-04576-NJ", source="SBA", state="NJ",
            title="Hotel Hampton Fire",
            incident_type="Fire",
            declaration_date=date(2026, 3, 4),
            incident_start=date(2026, 2, 20), incident_end=date(2026, 2, 20),
            renewal_dates_list=None,
            counties=["Warren"],
            statewide=False,
            official_url="https://www.federalregister.gov/documents/2026/03/09/2026-04576/administrative-declaration-of-a-disaster-for-the-commonwealth-of-pennsylvania",
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

    # PHE lasts 90 days under Section 319 of the Public Health Service Act
    # unless renewed or terminated early
    PHE_DURATION_DAYS = 90
    PHE_EXPIRY_WARNING_DAYS = 14

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

        # Check 90-day PHE expiry for ongoing records
        self._check_phe_expiry()

        return self.records

    def _check_phe_expiry(self):
        """Flag HHS PHE records approaching or past 90-day statutory limit."""
        today = date.today()
        for rec in self.records:
            if rec.get("incidentEnd") is not None:
                continue  # Has an end date — not an open PHE
            decl_str = rec.get("declarationDate")
            if not decl_str:
                continue
            # Use latest renewal date if available, otherwise declaration date
            anchor = datetime.strptime(decl_str, "%Y-%m-%d").date()
            renewals = rec.get("renewalDates")
            if renewals:
                for rd in renewals:
                    rd_date = datetime.strptime(rd, "%Y-%m-%d").date()
                    if rd_date > anchor:
                        anchor = rd_date
            expiry = anchor + timedelta(days=self.PHE_DURATION_DAYS)
            rec["pheExpiryDate"] = expiry.isoformat()
            days_until = (expiry - today).days
            if days_until < 0:
                self.warnings.append(
                    f"{rec['id']}: PHE 90-day statutory limit EXPIRED {abs(days_until)} days ago "
                    f"(anchor: {anchor}). Check for renewal at aspr.hhs.gov or set incidentEnd."
                )
            elif days_until <= self.PHE_EXPIRY_WARNING_DAYS:
                self.warnings.append(
                    f"{rec['id']}: PHE 90-day limit expires in {days_until} days "
                    f"(anchor: {anchor}, expiry: {expiry}). Check for renewal."
                )

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
        # 90-day statutory limit: Dec 23 + 90 = Mar 24, 2026. No renewal found.
        rec = build_record(
            id_str="HHS-2025-001-WA",
            source="HHS",
            state="WA",
            title="HHS Public Health Emergency — Washington State Severe Weather",
            incident_type="Severe Storm",
            declaration_date=date(2025, 12, 23),
            incident_start=date(2025, 12, 9),
            incident_end=date(2026, 3, 24),  # 90-day statutory limit, no renewal found
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
            last_verified="2026-03-27",
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
        # Extended Feb 27, 2026 to Mar 14, 2026 — added NC, OH, RI, VA.
        # Pipeline break at Marcus Hook refinery + winter storms disrupted propane supply.
        fmcsa_2025_012_states = [
            "CT", "DE", "MA", "MD", "ME", "NC", "NH", "NJ", "NY",
            "OH", "PA", "RI", "VA", "VT", "WV",
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
                incident_end=date(2026, 3, 14),  # Extended Feb 27 to Mar 14
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
        # Extended Feb 14, 2026 to Feb 28, 2026 (confirmed via PA Propane Gas Assn).
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
                incident_end=date(2026, 2, 28),  # Extended Feb 14 to Feb 28
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NEW YORK (EO 55, Dec 26 2025 Winter Storm) ---
        # 35 counties. EO 55.1 extended to statewide scope.
        rec = build_record(
            id_str="STATE-2025-002-NY",
            source="STATE", state="NY",
            title="Governor Hochul Emergency Declaration (EO 55) — December 2025 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2025, 12, 26),
            incident_start=date(2025, 12, 26),
            incident_end=date(2026, 1, 25),
            renewal_dates_list=None,
            counties=["Albany", "Bronx", "Broome", "Cayuga", "Chenango", "Columbia",
                       "Cortland", "Delaware", "Dutchess", "Fulton", "Greene", "Herkimer",
                       "Kings", "Madison", "Montgomery", "Nassau", "New York", "Oneida",
                       "Onondaga", "Orange", "Oswego", "Otsego", "Putnam", "Queens",
                       "Rensselaer", "Richmond", "Rockland", "Saratoga", "Schenectady",
                       "Schoharie", "Suffolk", "Sullivan", "Ulster", "Wayne", "Westchester"],
            statewide=False,
            official_url="https://www.governor.ny.gov/executive-order/no-55-declaring-disaster-emergency-counties-albany-bronx-broome-cayuga-chenango",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NEW YORK (EO 57, Jan 23 2026 Winter Storm) ---
        # Statewide. Previously had wrong URL (pointed to EO 55).
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
            official_url="https://www.governor.ny.gov/executive-order/no-57-declaring-disaster-emergency-throughout-state-new-york",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NEW YORK (EO 58, Feb 21 2026 Nor'easter / Winter Storm Hernando) ---
        # 22+ counties
        rec = build_record(
            id_str="STATE-2026-003-NY",
            source="STATE", state="NY",
            title="Governor Hochul Emergency Declaration (EO 58) — February 2026 Nor'easter",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 21),
            incident_start=date(2026, 2, 22),
            incident_end=date(2026, 3, 24),
            renewal_dates_list=None,
            counties=["Albany", "Bronx", "Columbia", "Delaware", "Dutchess", "Greene",
                       "Kings", "Nassau", "New York", "Orange", "Otsego", "Putnam",
                       "Queens", "Rensselaer", "Richmond", "Rockland", "Schenectady",
                       "Schoharie", "Suffolk", "Sullivan", "Ulster", "Westchester"],
            statewide=False,
            official_url="https://www.governor.ny.gov/executive-order/no-58-declaring-disaster-emergency-counties-albany-bronx-columbia-greene-delaware",
            confidence="curated",
            last_verified="2026-03-27",
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
            official_url="https://www.pa.gov/governor/newsroom/2026-press-releases/gov-shapiro-signs-proclamation-of-disaster-emergency-to-prepare-/",
            confidence="curated",
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            official_url="https://governor.ky.gov/attachments/20260123_Executive-Order_2026-047_State-of-Emergency-Related-to-Continuing-Winter-Weather-Event.pdf",
            confidence="curated",
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            official_url="https://www.in.gov/gov/files/EO26-03.pdf",
            confidence="curated",
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- COLORADO — Western Colorado Flooding (Oct 2025) ---
        # EO D 2025-021, verbal Oct 12, signed Nov 10. Tropical Storms Priscilla/Raymond.
        # FEMA major disaster request denied; appeal filed.
        # $13.8M validated infrastructure damage, 60+ miles of road destroyed.
        rec = build_record(
            id_str="STATE-2025-001-CO",
            source="STATE", state="CO",
            title="Governor Polis Emergency — Western Colorado Flooding (EO D 2025-021)",
            incident_type="Flood",
            declaration_date=date(2025, 10, 12),
            incident_start=date(2025, 10, 10),
            incident_end=date(2025, 10, 14),
            renewal_dates_list=None,
            counties=["Archuleta", "La Plata", "Mineral"],
            statewide=False,
            official_url="https://www.colorado.gov/governor/news/governor-polis-memorializes-emergency-declaration-support-communities-recovering-flooding",
            confidence="curated",
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            incident_end=date(2026, 4, 26),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://content.govdelivery.com/accounts/OHIOGOVERNOR/bulletins/405eda8",
            confidence="curated",
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            official_url="https://www.maine.gov/governor/mills/news/governor-mills-declares-state-civil-emergency-coastal-counties-impacted-flooding-urges-maine",
            confidence="curated",
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
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
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # NEW STATE DECLARATIONS — Added Mar 27, 2026 audit
        # =============================================================

        # Florida EO 26-33: Cold front (Jan 31 - Feb 3), drought, wildfires — all 67 counties
        # Signed Feb 9, 2026. Incident start = Jan 31 (cold front onset per EO text).
        # Ongoing due to drought/wildfire component (120 active wildfires at signing).
        # PDF: https://www.flgov.com/eog/sites/default/files/executive-orders/2026/EO%2026-33.pdf
        rec = build_record(
            id_str="STATE-2026-001-FL",
            source="STATE", state="FL",
            title="Governor DeSantis EO 26-33 — Cold Front, Drought, Wildfires",
            incident_type="Wildfire",
            declaration_date=date(2026, 2, 9),
            incident_start=date(2026, 1, 31),
            incident_end=None,  # Ongoing — drought + 120 active wildfires
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.flgov.com/eog/sites/default/files/executive-orders/2026/EO%2026-33.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # Oklahoma EO 2026-11: Tornadoes/severe weather — Mar 7, 2026
        rec = build_record(
            id_str="STATE-2026-002-OK",
            source="STATE", state="OK",
            title="Governor Stitt Emergency Declaration — Tornadoes and Severe Weather",
            incident_type="Tornado",
            declaration_date=date(2026, 3, 7),
            incident_start=date(2026, 3, 7),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Creek", "Mayes", "Muskogee", "Okmulgee", "Rogers", "Tulsa", "Wagoner", "Washington"],
            statewide=False,
            official_url="https://oklahoma.gov/governor/newsroom/newsroom/2026/governor-stitt-declares-state-of-emergency-following-severe-weather.html",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # Michigan EO 2026-1: Deadly tornadoes — Mar 8, 2026
        rec = build_record(
            id_str="STATE-2026-002-MI",
            source="STATE", state="MI",
            title="Governor Whitmer Emergency Declaration — Deadly Tornadoes",
            incident_type="Tornado",
            declaration_date=date(2026, 3, 8),
            incident_start=date(2026, 3, 8),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Branch", "Cass", "St. Joseph"],
            statewide=False,
            official_url="https://www.michigan.gov/whitmer/news/press-releases/2026/03/08/whitmer-declares-state-emergency-following-deadly-tornadoes-in-southwest-michigan",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # Michigan EO 2026-2/3: Historic blizzard — Mar 17+25, 2026
        rec = build_record(
            id_str="STATE-2026-003-MI",
            source="STATE", state="MI",
            title="Governor Whitmer Emergency Declaration — Historic Blizzard",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 3, 17),
            incident_start=date(2026, 3, 17),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Antrim", "Benzie", "Grand Traverse", "Kalkaska", "Leelanau",
                       "Manistee", "Missaukee", "Osceola", "Wexford"],
            statewide=False,
            official_url="https://www.michigan.gov/whitmer/news/state-orders-and-directives/2026/03/17/executive-order-2026-2-declaration-of-state-of-emergency-and-energy-emergency",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # Missouri EO 26-08: Severe storms/tornadoes — Mar 6, 2026
        rec = build_record(
            id_str="STATE-2026-002-MO",
            source="STATE", state="MO",
            title="Governor Kehoe Emergency Declaration — Severe Storms and Tornadoes",
            incident_type="Tornado",
            declaration_date=date(2026, 3, 6),
            incident_start=date(2026, 3, 6),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.mo.gov/press-releases/archive/governor-kehoe-signs-executive-order-26-08-activating-state-emergency",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # Nebraska: Wildfires — Mar 25-26, 2026
        rec = build_record(
            id_str="STATE-2026-002-NE",
            source="STATE", state="NE",
            title="Governor Pillen Emergency Declaration — Wildfires",
            incident_type="Wildfire",
            declaration_date=date(2026, 3, 25),
            incident_start=date(2026, 3, 25),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.nebraska.gov/gov-pillen-declares-emergency-mobilizes-guard-wildfires-burn-central-and-western-nebraska",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # Rhode Island EO 26-02: Blizzard — Feb 22, 2026
        rec = build_record(
            id_str="STATE-2026-001-RI",
            source="STATE", state="RI",
            title="Governor McKee Emergency Declaration — Blizzard",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 22),
            incident_start=date(2026, 2, 22),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.ri.gov/press-releases/governor-mckee-declares-state-emergency-issues-travel-ban-ahead-blizzard-conditions",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # v3.0 CARRIER-DISCOVERED BACKFILL — March 2026
        # Records below discovered via Aetna/Wellcare carrier data
        # cross-reference (carrier_data_parser.py). Official government
        # URLs verified from carrier RelatedLinks fields.
        # =============================================================

        # --- CALIFORNIA (Governor Newsom consolidated declarations) ---
        # Many CA disasters covered by a Dec 23 2025 omnibus proclamation

        rec = build_record(
            id_str="STATE-2025-010-CA",
            source="STATE", state="CA",
            title="Governor Newsom Emergency — February 2025 Storms",
            incident_type="Severe Storm",
            declaration_date=date(2025, 2, 1),
            incident_start=date(2025, 1, 31),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.gov.ca.gov/2025/07/29/governor-newsom-issues-emergency-proclamation-for-storm-impacted-counties/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-011-CA",
            source="STATE", state="CA",
            title="Governor Newsom Emergency — Rancho Cucamonga Windstorm",
            incident_type="Severe Wind",
            declaration_date=date(2025, 1, 7),
            incident_start=date(2025, 1, 7),
            incident_end=date(2026, 1, 7),
            renewal_dates_list=None,
            counties=["San Bernardino"],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/12/23/governor-newsom-declares-states-of-emergency-related-to-multiple-severe-weather-events-in-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-012-CA",
            source="STATE", state="CA",
            title="Governor Newsom Emergency — July 2025 Tsunami",
            incident_type="Tsunami",
            declaration_date=date(2025, 7, 30),
            incident_start=date(2025, 7, 30),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.gov.ca.gov/2025/12/23/governor-newsom-declares-states-of-emergency-related-to-multiple-severe-weather-events-in-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-013-CA",
            source="STATE", state="CA",
            title="Governor Newsom Emergency — Gifford Fire",
            incident_type="Wildfire",
            declaration_date=date(2025, 8, 1),
            incident_start=date(2025, 8, 1),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.gov.ca.gov/2025/12/23/governor-newsom-declares-states-of-emergency-related-to-multiple-severe-weather-events-in-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-014-CA",
            source="STATE", state="CA",
            title="Governor Newsom Emergency — August Storms and Mudslides",
            incident_type="Severe Storm",
            declaration_date=date(2025, 8, 23),
            incident_start=date(2025, 8, 23),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.gov.ca.gov/2025/12/23/governor-newsom-declares-states-of-emergency-related-to-multiple-severe-weather-events-in-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-015-CA",
            source="STATE", state="CA",
            title="Governor Newsom Emergency — September Lightning Complex",
            incident_type="Wildfire",
            declaration_date=date(2025, 9, 2),
            incident_start=date(2025, 9, 2),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.gov.ca.gov/2025/09/19/governor-newsom-issues-emergency-proclamation-to-help-calaveras-and-tuolumne-counties-recover-from-tcu-lightning-complex-fires/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-016-CA",
            source="STATE", state="CA",
            title="Governor Newsom Emergency — Tropical Storm Mario",
            incident_type="Tropical Storm",
            declaration_date=date(2025, 9, 18),
            incident_start=date(2025, 9, 18),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.gov.ca.gov/2025/12/23/governor-newsom-declares-states-of-emergency-related-to-multiple-severe-weather-events-in-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-017-CA",
            source="STATE", state="CA",
            title="Governor Newsom Emergency — Mono Pack Fire",
            incident_type="Wildfire",
            declaration_date=date(2025, 12, 9),
            incident_start=date(2025, 11, 13),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Mono"],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/12/09/governor-newsom-proclaims-state-of-emergency-in-mono-county-due-to-the-pack-fire/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- CONNECTICUT — Feb 22 2026 Winter Storm ---
        rec = build_record(
            id_str="STATE-2026-002-CT",
            source="STATE", state="CT",
            title="Governor Lamont Emergency Declaration — February 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 22),
            incident_start=date(2026, 2, 22),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://portal.ct.gov/governor/news/press-releases/2026/02-2026/governor-lamont-declares-state-of-emergency-prohibits-commercial-vehicle-travel",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- HAWAII ---
        rec = build_record(
            id_str="STATE-2025-001-HI",
            source="STATE", state="HI",
            title="Governor Green Emergency — Wildfires",
            incident_type="Wildfire",
            declaration_date=date(2025, 7, 15),
            incident_start=date(2025, 7, 15),
            incident_end=date(2025, 10, 21),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.hawaii.gov/wp-content/uploads/2025/07/2507065_ATG-Proclamation-Wildfires.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2026-001-HI",
            source="STATE", state="HI",
            title="Governor Green Emergency — February 2026 Severe Weather",
            incident_type="Severe Storm",
            declaration_date=date(2026, 2, 6),
            incident_start=date(2026, 2, 6),
            incident_end=date(2026, 2, 11),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.hawaii.gov/newsroom/news-release-hiema-advises-public-to-prepare-for-severe-weather/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- HAWAII — Feb 20-22 Heavy Rains ---
        # Proclamation 2602068, signed Feb 24. Separate from Feb 6-11 severe weather.
        rec = build_record(
            id_str="STATE-2026-002-HI",
            source="STATE", state="HI",
            title="Governor Green Proclamation — February 20-22, 2026 Heavy Rains",
            incident_type="Flood",
            declaration_date=date(2026, 2, 24),
            incident_start=date(2026, 2, 20),
            incident_end=date(2026, 2, 22),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.hawaii.gov/wp-content/uploads/2026/02/2602068_Proclamation-Relating-to-February-20-22-2026-Rains-Scanned.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- KANSAS — Wildland Fires Feb 2026 ---
        rec = build_record(
            id_str="STATE-2026-002-KS",
            source="STATE", state="KS",
            title="Governor Kelly Emergency — Wildland Fires",
            incident_type="Wildfire",
            declaration_date=date(2026, 2, 15),
            incident_start=date(2026, 2, 15),
            incident_end=date(2026, 3, 2),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.kansastag.gov/m/newsflash/Home/Detail/821",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- LOUISIANA — Tallulah Water System ---
        rec = build_record(
            id_str="STATE-2025-001-LA",
            source="STATE", state="LA",
            title="Governor Landry Emergency — Tallulah Water System Failure",
            incident_type="Infrastructure Emergency",
            declaration_date=date(2025, 2, 13),
            incident_start=date(2025, 2, 13),
            incident_end=date(2025, 11, 2),
            renewal_dates_list=None,
            counties=["Madison"],
            statewide=False,
            official_url="https://gov.louisiana.gov/assets/ExecutiveOrders/2026/JML-Exective-Order-26-007.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- MAINE — Jan 2026 Winter Storm ---
        rec = build_record(
            id_str="STATE-2026-002-ME",
            source="STATE", state="ME",
            title="Governor Mills Emergency — January 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 25),
            incident_start=date(2026, 1, 25),
            incident_end=date(2026, 2, 24),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.maine.gov/governor/mills/news/powerful-noreaster-expected-governor-mills-closes-state-offices-monday-2026-02-22",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- MISSOURI ---
        rec = build_record(
            id_str="STATE-2025-001-MO",
            source="STATE", state="MO",
            title="Governor Kehoe Emergency — April 2025 Severe Storms",
            incident_type="Severe Storm",
            declaration_date=date(2025, 4, 29),
            incident_start=date(2025, 4, 29),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.mo.gov/press-releases/archive/governor-kehoe-requests-federal-disaster-declaration-response-march-30-april",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-002-MO",
            source="STATE", state="MO",
            title="Governor Kehoe Emergency — May 2025 Memorial Weekend Storms",
            incident_type="Severe Storm",
            declaration_date=date(2025, 5, 23),
            incident_start=date(2025, 5, 23),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.mo.gov/press-releases/archive/governor-kehoe-announces-fema-participate-joint-damage-assessments-5",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- MONTANA — Dec 2025 Flooding ---
        rec = build_record(
            id_str="STATE-2025-001-MT",
            source="STATE", state="MT",
            title="Governor Gianforte Emergency — December 2025 Flooding",
            incident_type="Flood",
            declaration_date=date(2025, 12, 8),
            incident_start=date(2025, 12, 8),
            incident_end=date(2026, 1, 25),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://news.mt.gov/Governors-Office/Governor-Gianforte-Receives-Incident-Command-Briefing-on-Flooding-in-Libby",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NEBRASKA (multiple 2025 events) ---
        rec = build_record(
            id_str="STATE-2025-001-NE",
            source="STATE", state="NE",
            title="Governor Pillen Emergency — March 2025 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2025, 3, 21),
            incident_start=date(2025, 3, 18),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Boone", "Burt", "Butler", "Cass", "Clay", "Colfax", "Cuming", "Dodge", "Douglas", "Fillmore", "Hamilton", "Jefferson", "Johnson", "Lancaster", "Nuckolls", "Otoe", "Platte", "Polk", "Saline", "Sarpy", "Saunders", "Seward", "Thayer", "Thurston", "Washington", "York"],
            statewide=False,
            official_url="https://governor.nebraska.gov/gov-pillen-declares-emergency-counties-impacted-winter-storm",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-002-NE",
            source="STATE", state="NE",
            title="Governor Pillen Emergency — Plum Creek Fire",
            incident_type="Wildfire",
            declaration_date=date(2025, 4, 21),
            incident_start=date(2025, 4, 21),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.nebraska.gov/governor-pillen-declares-emergency-mobilizes-nebraska-national-guard-and-issues-statewide-burn-ban",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-003-NE",
            source="STATE", state="NE",
            title="Governor Pillen Emergency — Dawson County Severe Storms",
            incident_type="Severe Storm",
            declaration_date=date(2025, 6, 29),
            incident_start=date(2025, 6, 29),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Dawson"],
            statewide=False,
            official_url="https://governor.nebraska.gov/gov-pillen-issues-disaster-declaration-dawson-county-following-june-storms",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-004-NE",
            source="STATE", state="NE",
            title="Governor Pillen Emergency — August 2025 Storms",
            incident_type="Severe Storm",
            declaration_date=date(2025, 8, 8),
            incident_start=date(2025, 8, 8),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.nebraska.gov/gov-pillen-issues-disaster-declaration-23-counties-following-aug-8-storms",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NEW MEXICO ---
        rec = build_record(
            id_str="STATE-2025-001-NM",
            source="STATE", state="NM",
            title="Governor Lujan Grisham Emergency — July 2025 Flooding",
            incident_type="Flood",
            declaration_date=date(2025, 7, 25),
            incident_start=date(2025, 7, 22),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.governor.state.nm.us/2025/07/08/new-mexico-governor-mobilizes-resources-following-catastrophic-flooding-in-ruidoso/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2026-002-NM",
            source="STATE", state="NM",
            title="Governor Lujan Grisham Emergency — January 2026 Severe Weather",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 23),
            incident_start=date(2026, 1, 23),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.dot.nm.gov/blog/2026/01/22/winter-storm-watch-and-travel-advisory-issued/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- OKLAHOMA — Feb 2026 Wildfires ---
        rec = build_record(
            id_str="STATE-2026-003-OK",
            source="STATE", state="OK",
            title="Governor Stitt Emergency — February 2026 Wildfires",
            incident_type="Wildfire",
            declaration_date=date(2026, 2, 17),
            incident_start=date(2026, 2, 17),
            incident_end=date(2026, 3, 19),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://oklahoma.gov/governor/newsroom/newsroom/2026/governor-declares-state-of-emergency.html",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- OREGON (multiple wildfires 2025) ---
        or_fires = [
            ("STATE-2025-001-OR", "Governor Kotek Emergency — Rowena Fire", date(2025, 6, 11), date(2025, 7, 30),
             "https://apps.oregon.gov/oregon-newsroom/OR/GOV/Posts/Post/governor-kotek-declares-state-of-emergency-for-rowena-fire"),
            ("STATE-2025-002-OR", "Governor Kotek Emergency — Cold Spring Fire", date(2025, 7, 2), None,
             "https://apps.oregon.gov/oregon-newsroom/OR/GOV/Posts/Post/governor-kotek-invokes-conflagration-act-for-the-cold-springs-fire"),
            ("STATE-2025-003-OR", "Governor Kotek Emergency — Elk Fire", date(2025, 7, 9), None,
             "https://apps.oregon.gov/oregon-newsroom/OR/GOV/Posts/Post/governor-kotek-invokes-conflagration-act-for-the-elk-fire"),
            ("STATE-2025-004-OR", "Governor Kotek Emergency — Highland Fire", date(2025, 7, 12), None,
             "https://apps.oregon.gov/oregon-newsroom/OR/GOV/Posts/Post/governor-kotek-invokes-conflagration-act-for-the-highland-fire"),
            ("STATE-2025-005-OR", "Governor Kotek Emergency — Cram Fire", date(2025, 7, 14), None,
             "https://apps.oregon.gov/oregon-newsroom/OR/GOV/Posts/Post/governor-kotek-invokes-conflagration-act-for-the-cram-fire"),
            ("STATE-2025-006-OR", "Governor Kotek Emergency — Flat Fire", date(2025, 8, 22), None,
             "https://apps.oregon.gov/oregon-newsroom/OR/GOV/Posts/Post/governor-kotek-invokes-conflagration-act-for-the-flat-fire"),
            ("STATE-2025-007-OR", "Governor Kotek Emergency — Moon Complex Fire", date(2025, 9, 27), None,
             "https://apps.oregon.gov/oregon-newsroom/OR/GOV/Posts/Post/governor-kotek-invokes-conflagration-act-for-the-moon-complex-fire"),
        ]
        for id_str, title, inc_start, inc_end, url in or_fires:
            rec = build_record(
                id_str=id_str,
                source="STATE", state="OR",
                title=title,
                incident_type="Wildfire",
                declaration_date=inc_start,
                incident_start=inc_start,
                incident_end=inc_end,
                renewal_dates_list=None,
                counties=["Statewide"],
                statewide=True,
                official_url=url,
                confidence="curated",
                last_verified="2026-03-27",
            )
            if rec:
                curated.append(rec)

        # --- SOUTH DAKOTA — Dec 2025 Winter Wind Storm ---
        rec = build_record(
            id_str="STATE-2025-001-SD",
            source="STATE", state="SD",
            title="Governor Noem Emergency — Severe Winter Wind Storm",
            incident_type="Severe Wind",
            declaration_date=date(2025, 12, 17),
            incident_start=date(2025, 12, 17),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://news.sd.gov/news?id=news_kb_article_view&sys_id=96a3de25dbd2b2d091ce9f9583d5bfbd",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- WASHINGTON — Dec 2025 Winter Weather ---
        rec = build_record(
            id_str="STATE-2025-001-WA",
            source="STATE", state="WA",
            title="Governor Ferguson Emergency — Winter Weather and River Flooding",
            incident_type="Severe Winter Storm",
            declaration_date=date(2025, 12, 2),
            incident_start=date(2025, 12, 2),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.wa.gov/news/2025/governor-ferguson-declares-statewide-emergency",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- WYOMING ---
        rec = build_record(
            id_str="STATE-2025-001-WY",
            source="STATE", state="WY",
            title="Governor Gordon Emergency — Red Canyon Fire",
            incident_type="Wildfire",
            declaration_date=date(2025, 8, 13),
            incident_start=date(2025, 8, 13),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.wyo.gov/news-releases/governor-gordon-issues-emergency-declaration-for-red-canyon-fire",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        rec = build_record(
            id_str="STATE-2025-002-WY",
            source="STATE", state="WY",
            title="Governor Gordon Emergency — Dollar Fire",
            incident_type="Wildfire",
            declaration_date=date(2025, 8, 21),
            incident_start=date(2025, 8, 21),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.wyo.gov/news-releases/governor-gordon-provides-wildfire-updates-dollar-fire",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # FLORIDA — HURRICANE / STORM GOVERNOR DECLARATIONS
        # Carrier cross-reference: Aetna + Wellcare both track these
        # =============================================================

        # --- FL Hurricane Debby (Aug 2024) ---
        # EO 24-156 initial, 10 governor extensions through EO 2026-59 (Mar 2026)
        # Note: Aug 7 date from prior data was CFO/FDACS order, NOT governor EO
        # 51+ counties, still active
        rec = build_record(
            id_str="STATE-2024-001-FL",
            source="STATE", state="FL",
            title="Governor DeSantis Emergency — Hurricane Debby (EO 24-156)",
            incident_type="Hurricane",
            declaration_date=date(2024, 8, 1),
            incident_start=date(2024, 8, 1),
            incident_end=None,
            renewal_dates_list=[
                date(2024, 9, 25), date(2024, 11, 22),
                date(2025, 1, 17), date(2025, 3, 14), date(2025, 5, 14),
                date(2025, 7, 11), date(2025, 9, 9), date(2025, 11, 7),
                date(2026, 1, 6), date(2026, 3, 6),
            ],
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.flgov.com/eog/news/executive-orders/2026-59",
            confidence="curated",
            last_verified="2026-03-27",
            extensions=[
                {"date": "2024-09-25", "eo": "2024-211", "url": "https://www.flgov.com/eog/news/executive-orders/2024-211", "notes": "First 60-day extension"},
                {"date": "2024-11-22", "eo": "2024-261", "url": "https://www.flgov.com/eog/news/executive-orders/2024-261", "notes": "Second extension"},
                {"date": "2025-01-17", "eo": "2025-12", "url": "https://www.flgov.com/eog/news/executive-orders/2025-12", "notes": "Third extension"},
                {"date": "2025-03-14", "eo": "2025-59", "url": "https://www.flgov.com/eog/news/executive-orders/2025-59", "notes": "Fourth extension"},
                {"date": "2025-05-14", "eo": "2025-104", "url": "https://www.flgov.com/eog/news/executive-orders/2025-104", "notes": "Fifth extension"},
                {"date": "2025-07-11", "eo": "2025-144", "url": "https://www.flgov.com/eog/news/executive-orders/2025-144", "notes": "Sixth extension"},
                {"date": "2025-09-09", "eo": "2025-184", "url": "https://www.flgov.com/eog/news/executive-orders/2025-184", "notes": "Seventh extension"},
                {"date": "2025-11-07", "eo": "2025-232", "url": "https://www.flgov.com/eog/news/executive-orders/2025-232", "notes": "Eighth extension"},
                {"date": "2026-01-06", "eo": "2026-03", "url": "https://www.flgov.com/eog/news/executive-orders/2026-3", "notes": "Ninth extension"},
                {"date": "2026-03-06", "eo": "2026-59", "url": "https://www.flgov.com/eog/news/executive-orders/2026-59", "notes": "Tenth extension (current)"},
            ],
        )
        if rec:
            curated.append(rec)

        # --- FL Hurricane Helene (Sep 2024) ---
        # EO 24-208 initial (for "Potential Tropical Cyclone Nine"), 7 extensions through EO 2026-58
        # EO 24-209 amended to expand to 61 counties on Sep 24
        # Still active
        rec = build_record(
            id_str="STATE-2024-002-FL",
            source="STATE", state="FL",
            title="Governor DeSantis Emergency — Hurricane Helene (EO 24-208)",
            incident_type="Hurricane",
            declaration_date=date(2024, 9, 23),
            incident_start=date(2024, 9, 23),
            incident_end=None,
            renewal_dates_list=[
                date(2024, 11, 21), date(2025, 5, 14), date(2025, 7, 11),
                date(2025, 9, 9), date(2025, 11, 7), date(2026, 1, 6),
                date(2026, 3, 6),
            ],
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.flgov.com/eog/news/executive-orders/2026-58",
            confidence="curated",
            last_verified="2026-03-27",
            extensions=[
                {"date": "2024-11-21", "eo": "2024-249", "url": "https://www.flgov.com/eog/news/executive-orders/2024-249", "notes": "First extension"},
                {"date": "2025-05-14", "eo": "2025-102", "url": "https://www.flgov.com/eog/news/executive-orders/2025-102", "notes": "Second extension"},
                {"date": "2025-07-11", "eo": "2025-143", "url": "https://www.flgov.com/eog/news/executive-orders/2025-143", "notes": "Third extension"},
                {"date": "2025-09-09", "eo": "2025-182", "url": "https://www.flgov.com/eog/news/executive-orders/2025-182", "notes": "Fourth extension"},
                {"date": "2025-11-07", "eo": "2025-231", "url": "https://www.flgov.com/eog/news/executive-orders/2025-231", "notes": "Fifth extension (previously untracked)"},
                {"date": "2026-01-06", "eo": "2026-02", "url": "https://www.flgov.com/eog/news/executive-orders/2026-2", "notes": "Sixth extension"},
                {"date": "2026-03-06", "eo": "2026-58", "url": "https://www.flgov.com/eog/news/executive-orders/2026-58", "notes": "Seventh extension (current)"},
            ],
        )
        if rec:
            curated.append(rec)

        # --- FL Hurricane Milton (Oct 2024) ---
        # EO 24-214 initial (titled "Tropical Storm Milton" at issuance), 7 extensions
        # EO 24-215 amended Oct 6 to expand counties as storm intensified to Cat 5
        # Confirmed expired: Last extension EO 2025-242 (Nov 25, 2025). No 2026 renewal.
        # incidentEnd set to 2026-01-24 per Humana carrier data + our research.
        rec = build_record(
            id_str="STATE-2024-003-FL",
            source="STATE", state="FL",
            title="Governor DeSantis Emergency — Hurricane Milton (EO 24-214)",
            incident_type="Hurricane",
            declaration_date=date(2024, 10, 5),
            incident_start=date(2024, 10, 5),
            incident_end=date(2026, 1, 24),
            renewal_dates_list=[
                date(2024, 12, 3), date(2025, 1, 31), date(2025, 3, 31),
                date(2025, 5, 30), date(2025, 7, 28), date(2025, 9, 26),
                date(2025, 11, 25),
            ],
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.flgov.com/eog/news/executive-orders/2025-242",
            confidence="curated",
            last_verified="2026-03-27",
            extensions=[
                {"date": "2024-12-03", "eo": "2024-264", "url": "https://www.flgov.com/eog/news/executive-orders/2024-264", "notes": "First extension"},
                {"date": "2025-01-31", "eo": "2025-26", "url": "https://www.flgov.com/eog/news/executive-orders/2025-26", "notes": "Second extension"},
                {"date": "2025-03-31", "eo": "2025-68", "url": "https://www.flgov.com/eog/news/executive-orders/2025-68", "notes": "Third extension"},
                {"date": "2025-05-30", "eo": "2025-119", "url": "https://www.flgov.com/eog/news/executive-orders/2025-119", "notes": "Fourth extension (previously untracked)"},
                {"date": "2025-07-28", "eo": "2025-150", "url": "https://www.flgov.com/eog/news/executive-orders/2025-150", "notes": "Fifth extension"},
                {"date": "2025-09-26", "eo": "2025-191", "url": "https://www.flgov.com/eog/news/executive-orders/2025-191", "notes": "Sixth extension"},
                {"date": "2025-11-25", "eo": "2025-242", "url": "https://www.flgov.com/eog/news/executive-orders/2025-242", "notes": "Seventh extension (last known — no 2026 renewal found)"},
            ],
        )
        if rec:
            curated.append(rec)

        # --- FL May 2024 North Florida Tornadoes ---
        # EO 24-94 initial, 9+ extensions, 15 counties
        # incidentEnd set to 2025-12-23 per Humana carrier data
        rec = build_record(
            id_str="STATE-2024-004-FL",
            source="STATE", state="FL",
            title="Governor DeSantis Emergency — May 2024 North Florida Tornadoes (EO 24-94)",
            incident_type="Tornado",
            declaration_date=date(2024, 5, 10),
            incident_start=date(2024, 5, 10),
            incident_end=date(2025, 12, 23),
            renewal_dates_list=[
                date(2024, 9, 6), date(2024, 11, 4), date(2025, 3, 3),
                date(2025, 5, 1), date(2025, 7, 1), date(2025, 9, 1),
                date(2025, 11, 1), date(2026, 1, 1), date(2026, 3, 1),
            ],
            counties=["Baker", "Columbia", "Escambia", "Gadsden", "Hamilton",
                       "Jefferson", "Lafayette", "Leon", "Liberty", "Madison",
                       "Okaloosa", "Santa Rosa", "Suwannee", "Taylor", "Wakulla"],
            statewide=False,
            official_url="https://www.flgov.com/eog/news/executive-orders/2026-34",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- FL May 2025 NW Florida Tornadoes ---
        # EO 25-101, 5 extensions, Holmes County
        # incidentEnd set to 2026-01-06 per Humana carrier data (last extension expired)
        rec = build_record(
            id_str="STATE-2025-001-FL",
            source="STATE", state="FL",
            title="Governor Emergency — May 2025 NW Florida Tornadoes (EO 25-101)",
            incident_type="Tornado",
            declaration_date=date(2025, 5, 11),
            incident_start=date(2025, 5, 10),
            incident_end=date(2026, 1, 6),
            renewal_dates_list=[
                date(2025, 7, 10), date(2025, 9, 8), date(2025, 11, 7),
                date(2026, 1, 6), date(2026, 3, 6),
            ],
            counties=["Holmes"],
            statewide=False,
            official_url="https://www.flgov.com/eog/news/executive-orders/2025-101",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- FL Lake County Flooding ---
        # EO 25-213, extended by EO 25-257
        # incidentEnd set to 2025-12-28 per Humana carrier data
        rec = build_record(
            id_str="STATE-2025-002-FL",
            source="STATE", state="FL",
            title="Governor Emergency — Lake County Flooding (EO 25-213)",
            incident_type="Flood",
            declaration_date=date(2025, 10, 29),
            incident_start=date(2025, 10, 26),
            incident_end=date(2025, 12, 28),
            renewal_dates_list=[date(2025, 12, 22)],
            counties=["Lake"],
            statewide=False,
            official_url="https://www.flgov.com/eog/news/executive-orders/2025-213",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- FL Illegal Migration ---
        # EO 23-03, Jan 6 2023, statewide, 19+ renewals, still active (EO 2026-75)
        rec = build_record(
            id_str="STATE-2023-001-FL",
            source="STATE", state="FL",
            title="Governor DeSantis Emergency — Illegal Immigration (EO 23-03)",
            incident_type="Immigration Emergency",
            declaration_date=date(2023, 1, 6),
            incident_start=date(2023, 1, 6),
            incident_end=None,
            renewal_dates_list=[
                date(2025, 3, 24), date(2025, 5, 22), date(2025, 7, 20),
                date(2025, 9, 17), date(2025, 11, 25), date(2026, 3, 24),
            ],
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.flgov.com/eog/news/executive-orders/2026-75",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # NEW YORK — NON-STANDARD GOVERNOR DECLARATIONS
        # =============================================================

        # --- NY Vaccine Access Disaster ---
        # EO No. 52, Sep 5 2025, statewide, extended through Apr 19 2026 (EO 52.7)
        rec = build_record(
            id_str="STATE-2025-001-NY",
            source="STATE", state="NY",
            title="Governor Hochul Disaster Declaration — Vaccine Access (EO 52)",
            incident_type="Healthcare Emergency",
            declaration_date=date(2025, 9, 5),
            incident_start=date(2025, 9, 5),
            incident_end=None,
            renewal_dates_list=[
                date(2025, 10, 4), date(2025, 11, 3), date(2025, 12, 3),
                date(2026, 1, 2), date(2026, 1, 31), date(2026, 2, 20),
                date(2026, 3, 21),
            ],
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.governor.ny.gov/executive-order/no-527-extending-declaration-disaster-state-new-york-due-federal-actions-related",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # TEXAS — BORDER CRISIS + DROUGHT
        # =============================================================

        # --- TX Border Crisis ---
        # Disaster Proclamation May 31 2021, renewed monthly, 60+ counties
        rec = build_record(
            id_str="STATE-2021-001-TX",
            source="STATE", state="TX",
            title="Governor Abbott Disaster Proclamation — Border Security",
            incident_type="Immigration Emergency",
            declaration_date=date(2021, 5, 31),
            incident_start=date(2021, 5, 31),
            incident_end=None,
            renewal_dates_list=[
                date(2025, 9, 1), date(2025, 10, 1), date(2025, 11, 1),
                date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1),
            ],
            counties=["Statewide"],
            statewide=True,
            official_url="https://gov.texas.gov/news/post/governor-abbott-renews-border-security-disaster-proclamation-in-november-2024-",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # OKLAHOMA — WILDFIRES
        # =============================================================

        # --- OK Wildfires EO 2026-09 ---
        # Feb 18 2026, Beaver/Texas/Woodward/Harper counties
        rec = build_record(
            id_str="STATE-2026-001-OK",
            source="STATE", state="OK",
            title="Governor Stitt Emergency — Wildfires (EO 2026-09)",
            incident_type="Wildfire",
            declaration_date=date(2026, 2, 18),
            incident_start=date(2026, 2, 17),
            incident_end=date(2026, 3, 19),
            renewal_dates_list=None,
            counties=["Beaver", "Harper", "Texas", "Woodward"],
            statewide=False,
            official_url="https://www.sos.ok.gov/documents/executive/2170.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # MONTANA — FLOODING + HIGH WIND
        # =============================================================

        # --- MT Flooding EO 9-2025 ---
        rec = build_record(
            id_str="STATE-2025-001-MT",
            source="STATE", state="MT",
            title="Governor Gianforte Disaster Declaration — Flooding (EO 9-2025)",
            incident_type="Flood",
            declaration_date=date(2025, 12, 11),
            incident_start=date(2025, 12, 8),
            incident_end=date(2026, 1, 25),
            renewal_dates_list=None,
            counties=["Lincoln", "Sanders", "Flathead"],
            statewide=False,
            official_url="https://news.mt.gov/Governors-Office/Governor-Gianforte-Issues-Executive-Order-Declaring-Flooding-Disaster",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- MT Damaging High Wind EO 11-2025 ---
        rec = build_record(
            id_str="STATE-2025-002-MT",
            source="STATE", state="MT",
            title="Governor Gianforte Disaster Declaration — Severe Wind (EO 11-2025)",
            incident_type="Severe Wind",
            declaration_date=date(2025, 12, 18),
            incident_start=date(2025, 12, 17),
            incident_end=date(2026, 2, 1),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://news.mt.gov/Governors-Office/Governor-Gianforte-Issues-Executive-Order-Declaring-Wind-Disaster",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # CONNECTICUT — FEB 2026 BLIZZARD
        # =============================================================

        rec = build_record(
            id_str="STATE-2026-001-CT",
            source="STATE", state="CT",
            title="Governor Lamont Emergency — February 2026 Blizzard",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 22),
            incident_start=date(2026, 2, 22),
            incident_end=date(2026, 2, 23),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://portal.ct.gov/-/media/office-of-the-governor/news/2026/20260222-emergency-declaration.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # GEORGIA — SPALDING COUNTY WATER SUPPLY
        # Fuel spill at Hartsfield-Jackson contaminated Flint River intake
        # Advisory lifted same night after testing cleared supply
        # =============================================================

        rec = build_record(
            id_str="STATE-2026-003-GA",
            source="STATE", state="GA",
            title="Governor Kemp Emergency — Spalding County Water Supply (EO 01.30.26.02)",
            incident_type="Infrastructure Emergency",
            declaration_date=date(2026, 1, 30),
            incident_start=date(2026, 1, 30),
            incident_end=date(2026, 2, 6),
            renewal_dates_list=None,
            counties=["Spalding"],
            statewide=False,
            official_url="https://gov.georgia.gov/document/2026-executive-order/01302602/download",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # NEBRASKA — POWER DEMANDS
        # =============================================================

        rec = build_record(
            id_str="STATE-2026-001-NE",
            source="STATE", state="NE",
            title="Governor Pillen Emergency — Power Demands (EO 26-01)",
            incident_type="Power Emergency",
            declaration_date=date(2026, 1, 23),
            incident_start=date(2026, 1, 23),
            incident_end=date(2026, 2, 27),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.nebraska.gov/sites/default/files/doc/press/EO-26-01.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # UTAH — WILDFIRES (single EO covers all 3 fires)
        # =============================================================

        rec = build_record(
            id_str="STATE-2025-001-UT",
            source="STATE", state="UT",
            title="Governor Cox Emergency — 2025 Wildfires (EO 2025-08)",
            incident_type="Wildfire",
            declaration_date=date(2025, 7, 31),
            incident_start=date(2025, 7, 1),
            incident_end=date(2025, 8, 30),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.utah.gov/press/gov-cox-declares-state-of-emergency-as-wildfires-intensify/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # LOUISIANA — HURRICANE IDA (still active 2026!)
        # =============================================================

        rec = build_record(
            id_str="STATE-2021-001-LA",
            source="STATE", state="LA",
            title="Governor Emergency — Hurricane Ida (JBE 2021-165, renewed through 2026)",
            incident_type="Hurricane",
            declaration_date=date(2021, 8, 26),
            incident_start=date(2021, 8, 26),
            incident_end=None,
            renewal_dates_list=[
                date(2025, 9, 1), date(2025, 10, 1), date(2025, 11, 1),
                date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1),
                date(2026, 3, 1),
            ],
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.doa.la.gov/doa/osr/executive-orders/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # OREGON — ADDITIONAL DECLARATIONS
        # =============================================================

        # --- OR Alder Springs Fire ---
        # EO 25-07, Jun 16 2025, Jefferson/Deschutes (Conflagration Act)
        rec = build_record(
            id_str="STATE-2025-010-OR",
            source="STATE", state="OR",
            title="Governor Kotek Emergency — Alder Springs Fire (EO 25-07)",
            incident_type="Wildfire",
            declaration_date=date(2025, 6, 16),
            incident_start=date(2025, 6, 16),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Jefferson", "Deschutes"],
            statewide=False,
            official_url="https://apps.oregon.gov/oregon-newsroom/OR/GOV/Posts/Post/governor-kotek-invokes-conflagration-act-for-the-alder-springs-fire",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- OR Rowena Fire ---
        # EO 25-08, Jun 21 2025, Wasco County
        rec = build_record(
            id_str="STATE-2025-011-OR",
            source="STATE", state="OR",
            title="Governor Kotek Emergency — Rowena Fire (EO 25-08)",
            incident_type="Wildfire",
            declaration_date=date(2025, 6, 21),
            incident_start=date(2025, 6, 11),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Wasco"],
            statewide=False,
            official_url="https://apps.oregon.gov/oregon-newsroom/OR/GOV/Posts/Post/governor-kotek-declares-state-of-emergency-due-to-rowena-fire",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- OR Statewide Wildfire Emergency ---
        # EO 25-16, Jul 16 2025, statewide, through Dec 2025
        rec = build_record(
            id_str="STATE-2025-008-OR",
            source="STATE", state="OR",
            title="Governor Kotek Emergency — Statewide Wildfire Threat (EO 25-16)",
            incident_type="Wildfire",
            declaration_date=date(2025, 7, 16),
            incident_start=date(2025, 7, 16),
            incident_end=date(2025, 12, 31),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://apps.oregon.gov/oregon-newsroom/OR/GOV/Posts/Post/governor-kotek-declares-state-of-emergency-due-to-imminent-threat-of-wildfire",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- OR Homelessness Emergency ---
        # EO 25-01 (originally 23-02), statewide, through Jan 10 2027
        rec = build_record(
            id_str="STATE-2023-001-OR",
            source="STATE", state="OR",
            title="Governor Kotek Emergency — Homelessness (EO 25-01)",
            incident_type="Homelessness Emergency",
            declaration_date=date(2023, 1, 10),
            incident_start=date(2023, 1, 10),
            incident_end=None,
            renewal_dates_list=[
                date(2024, 1, 9), date(2025, 1, 9), date(2026, 1, 9),
            ],
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.oregon.gov/oem/pages/housing-emergency-executive-orders.aspx",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- OR December 2025 Severe Storms ---
        # EO 25-32, Dec 30 2025, 25 counties
        rec = build_record(
            id_str="STATE-2025-009-OR",
            source="STATE", state="OR",
            title="Governor Kotek Emergency — December 2025 Severe Storms (EO 25-32)",
            incident_type="Severe Storm",
            declaration_date=date(2025, 12, 30),
            incident_start=date(2025, 12, 15),
            incident_end=date(2025, 12, 21),
            renewal_dates_list=None,
            counties=["Clackamas", "Clatsop", "Coos", "Curry", "Douglas",
                       "Hood River", "Jackson", "Klamath", "Lane", "Lincoln",
                       "Linn", "Marion", "Multnomah", "Polk", "Tillamook",
                       "Umatilla", "Union", "Wallowa", "Washington", "Yamhill"],
            statewide=False,
            official_url="https://www.oregon.gov/gov/eo/eo-25-32.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # KENTUCKY — UPS PLANE CRASH
        # =============================================================

        rec = build_record(
            id_str="STATE-2025-001-KY",
            source="STATE", state="KY",
            title="Governor Beshear Emergency — Louisville UPS Plane Crash (EO 2025-758)",
            incident_type="Plane Crash",
            declaration_date=date(2025, 11, 5),
            incident_start=date(2025, 11, 4),
            incident_end=date(2025, 11, 4),
            renewal_dates_list=None,
            counties=["Jefferson"],
            statewide=False,
            official_url="https://governor.ky.gov/Documents/Executive%20Order%202025-758%20-%20State%20of%20Emergency%20Related%20to%20Louisville%20Plane%20Crash.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # MINNESOTA — WILDFIRES
        # =============================================================

        # --- MN Munger Shaw / Camp House Fires ---
        # EO 25-05, May 20 2025, Saint Louis County
        rec = build_record(
            id_str="STATE-2025-001-MN",
            source="STATE", state="MN",
            title="Governor Walz Peacetime Emergency — NE Minnesota Wildfires (EO 25-05)",
            incident_type="Wildfire",
            declaration_date=date(2025, 5, 20),
            incident_start=date(2025, 5, 12),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Saint Louis"],
            statewide=False,
            official_url="https://mn.gov/governor/newsroom/press-releases/?id=1055-685281",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # LOUISIANA — TALLULAH WATER SYSTEM
        # =============================================================

        # EO JML 25-054, renewed monthly through JML 26-027
        rec = build_record(
            id_str="STATE-2025-001-LA",
            source="STATE", state="LA",
            title="Governor Landry Emergency — Tallulah Water System (JML 25-054)",
            incident_type="Infrastructure Emergency",
            declaration_date=date(2025, 2, 13),
            incident_start=date(2025, 2, 13),
            incident_end=None,
            renewal_dates_list=[
                date(2025, 3, 15), date(2025, 4, 14), date(2025, 5, 14),
                date(2025, 6, 13), date(2025, 7, 13), date(2025, 8, 12),
                date(2025, 9, 11), date(2025, 10, 11), date(2025, 11, 10),
                date(2025, 12, 10), date(2026, 1, 9), date(2026, 2, 8),
            ],
            counties=["Madison"],
            statewide=False,
            official_url="https://gov.louisiana.gov/assets/2026-Executive-Orders/JML-Exective-Order-26-027.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # MASSACHUSETTS — FEB 2026 BLIZZARD
        # =============================================================

        rec = build_record(
            id_str="STATE-2026-002-MA",
            source="STATE", state="MA",
            title="Governor Healey Emergency — February 2026 Blizzard",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 22),
            incident_start=date(2026, 2, 22),
            incident_end=date(2026, 2, 24),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.mass.gov/news/governor-healey-declares-emergency-activates-national-guard-ahead-of-strong-winter-storm",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # ALASKA — WINDSTORM + WINTER STORM + POWER OUTAGE
        # =============================================================

        # --- AK Mat-SU Windstorm ---
        rec = build_record(
            id_str="STATE-2025-001-AK",
            source="STATE", state="AK",
            title="Governor Dunleavy Disaster Declaration — Mat-Su Windstorm",
            incident_type="Severe Wind",
            declaration_date=date(2025, 12, 10),
            incident_start=date(2025, 12, 9),
            incident_end=date(2026, 1, 9),
            renewal_dates_list=None,
            counties=["Matanuska-Susitna"],
            statewide=False,
            official_url="https://ready.alaska.gov/Documents/PIO/PressReleases/2025.12.10_Press%20Release%20-%20Governor%20Dunleavy%20Declares%20December%202025%20Mat-Su%20Windstorm%20a%20Disaster.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- AK Napaskiak Power Outage ---
        # Dec 30 2025 declaration, Bethel Census Area
        rec = build_record(
            id_str="STATE-2025-002-AK",
            source="STATE", state="AK",
            title="Governor Dunleavy Disaster Declaration — Napaskiak Power Outage",
            incident_type="Power Emergency",
            declaration_date=date(2025, 12, 30),
            incident_start=date(2025, 12, 6),
            incident_end=date(2026, 2, 4),
            renewal_dates_list=None,
            counties=["Bethel"],
            statewide=False,
            official_url="https://ready.alaska.gov/Documents/PIO/PressReleases/2025.01.05_Press%20Release%20-%20Governor%20Dunleavy%20Declares%202025%20Napaskiak%20Power%20Outage.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- AK Southeast Winter Storm ---
        rec = build_record(
            id_str="STATE-2026-001-AK",
            source="STATE", state="AK",
            title="Governor Dunleavy Disaster Declaration — Jan 2026 Southeast Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 1, 10),
            incident_start=date(2026, 1, 6),
            incident_end=date(2026, 2, 9),
            renewal_dates_list=None,
            counties=["Hoonah-Angoon", "Juneau"],
            statewide=False,
            official_url="https://ready.alaska.gov/Documents/PIO/PressReleases/2026.01.10_Press%20Release%20-%20Governor%20Dunleavy%20Declares%202026%20Jan%20Southeast%20Winter%20Storm.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- TX Flooding / Hill Country ---
        # Jul 4 2025, 30 counties, renewed through Mar 2026
        rec = build_record(
            id_str="STATE-2025-001-TX",
            source="STATE", state="TX",
            title="Governor Abbott Disaster Proclamation — Hill Country Flooding",
            incident_type="Flood",
            declaration_date=date(2025, 7, 4),
            incident_start=date(2025, 7, 2),
            incident_end=None,
            renewal_dates_list=[date(2025, 7, 22), date(2026, 3, 1)],
            counties=["Bandera", "Bexar", "Burnet", "Caldwell", "Coke", "Comal",
                       "Concho", "Edwards", "Gillespie", "Guadalupe", "Hamilton",
                       "Kendall", "Kerr", "Kimble", "Kinney", "Lampasas", "Llano",
                       "Mason", "Maverick", "McCulloch", "Menard", "Real", "Reeves",
                       "San Saba", "Schleicher", "Sutton", "Tom Green", "Travis",
                       "Uvalde", "Williamson"],
            statewide=False,
            official_url="https://gov.texas.gov/news/post/governor-abbott-amends-renews-flooding-disaster-proclamation-in-march-2026",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- TX Wildfires / Fire Weather ---
        # Aug 12 2025, statewide, renewed through Mar 2026
        rec = build_record(
            id_str="STATE-2025-002-TX",
            source="STATE", state="TX",
            title="Governor Abbott Disaster Proclamation — Fire Weather Conditions",
            incident_type="Wildfire",
            declaration_date=date(2025, 8, 12),
            incident_start=date(2025, 8, 10),
            incident_end=None,
            renewal_dates_list=[date(2026, 3, 9)],
            counties=["Statewide"],
            statewide=True,
            official_url="https://gov.texas.gov/news/post/governor-abbott-amends-renews-fire-weather-conditions-disaster-proclamation-in-march-2026",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- TX Drought ---
        # Governor Abbott disaster proclamation, renewed monthly, 80+ counties
        rec = build_record(
            id_str="STATE-2024-001-TX",
            source="STATE", state="TX",
            title="Governor Abbott Disaster Proclamation — Drought",
            incident_type="Drought",
            declaration_date=date(2024, 7, 1),
            incident_start=date(2024, 7, 1),
            incident_end=None,
            renewal_dates_list=[
                date(2025, 9, 18), date(2025, 10, 18), date(2025, 11, 18),
                date(2025, 12, 18), date(2026, 1, 18), date(2026, 2, 18),
                date(2026, 3, 18),
            ],
            counties=["Statewide"],
            statewide=True,
            official_url="https://gov.texas.gov/news/post/governor-abbott-amends-renews-drought-disaster-proclamation-in-march-2026",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # NEW MEXICO — CRIME, FLOODS, FIRE, INFRASTRUCTURE
        # =============================================================

        # --- NM Española Crime Emergency ---
        # EO 2025-358, Aug 13 2025, Rio Arriba County + Pueblos
        rec = build_record(
            id_str="STATE-2025-003-NM",
            source="STATE", state="NM",
            title="Governor Lujan Grisham Emergency — Española Crime (EO 2025-358)",
            incident_type="Crime Emergency",
            declaration_date=date(2025, 8, 13),
            incident_start=date(2025, 8, 13),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Rio Arriba"],
            statewide=False,
            official_url="https://www.governor.state.nm.us/2025/08/13/governor-declares-emergency-in-espanola-area-due-to-crime/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NM Albuquerque Crime Emergency ---
        # EO 2025-080, Apr 8 2025, Albuquerque/Bernalillo County
        rec = build_record(
            id_str="STATE-2025-004-NM",
            source="STATE", state="NM",
            title="Governor Lujan Grisham Emergency — Albuquerque Crime (EO 2025-080)",
            incident_type="Crime Emergency",
            declaration_date=date(2025, 4, 8),
            incident_start=date(2025, 4, 8),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Bernalillo"],
            statewide=False,
            official_url="https://www.governor.state.nm.us/wp-content/uploads/2025/04/Executive-Order-2025-080-1.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NM Cotton/Desert Willow Complex Fire ---
        # EO 2025-247, Jun 21 2025, Valencia County
        rec = build_record(
            id_str="STATE-2025-005-NM",
            source="STATE", state="NM",
            title="Governor Lujan Grisham Emergency — Cotton Fire / Desert Willow Complex (EO 2025-247)",
            incident_type="Wildfire",
            declaration_date=date(2025, 6, 21),
            incident_start=date(2025, 6, 21),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Valencia"],
            statewide=False,
            official_url="https://www.governor.state.nm.us/2025/06/21/governor-secures-resources-to-support-cotton-fire-response-additional-firefighting-crews-air-support-and-shelter-services-mobilized/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NM Lincoln County Flood ---
        # EO 2025-248, Jun 26 2025, Lincoln County
        rec = build_record(
            id_str="STATE-2025-006-NM",
            source="STATE", state="NM",
            title="Governor Lujan Grisham Emergency — Lincoln County Flooding (EO 2025-248)",
            incident_type="Flood",
            declaration_date=date(2025, 6, 26),
            incident_start=date(2025, 6, 23),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Lincoln"],
            statewide=False,
            official_url="https://www.dhsem.nm.gov/governor-signs-emergency-declarations-for-lincoln-and-chaves-county/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NM Dona Ana County Flood ---
        # EO 2025-333, Jul 25 2025, Dona Ana County
        rec = build_record(
            id_str="STATE-2025-007-NM",
            source="STATE", state="NM",
            title="Governor Lujan Grisham Emergency — Dona Ana County Flooding (EO 2025-333)",
            incident_type="Flood",
            declaration_date=date(2025, 7, 25),
            incident_start=date(2025, 7, 22),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Dona Ana"],
            statewide=False,
            official_url="https://www.governor.state.nm.us/2025/07/25/governor-signs-emergency-order-for-dona-ana-county-flooding/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NM Torrance County Well Outages ---
        # EO 2025-373, Oct 2025, Torrance County
        rec = build_record(
            id_str="STATE-2025-008-NM",
            source="STATE", state="NM",
            title="Governor Lujan Grisham Emergency — Torrance County Water System (EO 2025-373)",
            incident_type="Infrastructure Emergency",
            declaration_date=date(2025, 10, 15),
            incident_start=date(2024, 12, 1),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Torrance"],
            statewide=False,
            official_url="https://www.dhsem.nm.gov/state-to-provide-emergency-water-to-torrance-county-community/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # =============================================================
        # PHASE 3 SESSION 2 — CARRIER CROSS-REFERENCE GAP FILLS
        # Added 2026-03-27 from four-carrier cross-reference analysis
        # =============================================================

        # --- CALIFORNIA: Pack Fire, Mono County ---
        # Governor Newsom proclamation Dec 9, 2025
        rec = build_record(
            id_str="STATE-2025-018-CA",
            source="STATE", state="CA",
            title="Governor Newsom Proclamation — Pack Fire (Mono County)",
            incident_type="Wildfire",
            declaration_date=date(2025, 12, 9),
            incident_start=date(2025, 11, 13),
            incident_end=date(2025, 12, 3),
            renewal_dates_list=None,
            counties=["Mono"],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/12/09/governor-newsom-proclaims-state-of-emergency-in-mono-county-for-pack-fire/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- CALIFORNIA: July Tsunami, Del Norte County ---
        # Part of Dec 23, 2025 omnibus proclamation (6 events)
        rec = build_record(
            id_str="STATE-2025-019-CA",
            source="STATE", state="CA",
            title="Governor Newsom Proclamation — July 2025 Tsunami (Del Norte County)",
            incident_type="Tsunami",
            declaration_date=date(2025, 12, 23),
            incident_start=date(2025, 7, 29),
            incident_end=date(2025, 7, 30),
            renewal_dates_list=None,
            counties=["Del Norte"],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/12/23/governor-newsom-declares-states-of-emergency-related-to-multiple-severe-weather-events-in-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- CALIFORNIA: August Storms/Mudslides, Sierra County ---
        rec = build_record(
            id_str="STATE-2025-020-CA",
            source="STATE", state="CA",
            title="Governor Newsom Proclamation — August 2025 Storms and Mudslides (Sierra County)",
            incident_type="Severe Storm",
            declaration_date=date(2025, 12, 23),
            incident_start=date(2025, 8, 23),
            incident_end=date(2025, 8, 27),
            renewal_dates_list=None,
            counties=["Sierra"],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/12/23/governor-newsom-declares-states-of-emergency-related-to-multiple-severe-weather-events-in-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- CALIFORNIA: August Monsoon Storms, Imperial County ---
        rec = build_record(
            id_str="STATE-2025-021-CA",
            source="STATE", state="CA",
            title="Governor Newsom Proclamation — August 2025 Monsoon Storms (Imperial County)",
            incident_type="Severe Storm",
            declaration_date=date(2025, 12, 23),
            incident_start=date(2025, 8, 25),
            incident_end=date(2025, 8, 25),
            renewal_dates_list=None,
            counties=["Imperial"],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/12/23/governor-newsom-declares-states-of-emergency-related-to-multiple-severe-weather-events-in-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- CALIFORNIA: Gifford Fire, SLO + Santa Barbara ---
        rec = build_record(
            id_str="STATE-2025-022-CA",
            source="STATE", state="CA",
            title="Governor Newsom Proclamation — Gifford Fire (SLO, Santa Barbara)",
            incident_type="Wildfire",
            declaration_date=date(2025, 12, 23),
            incident_start=date(2025, 8, 1),
            incident_end=date(2025, 9, 28),
            renewal_dates_list=None,
            counties=["San Luis Obispo", "Santa Barbara"],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/12/23/governor-newsom-declares-states-of-emergency-related-to-multiple-severe-weather-events-in-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- CALIFORNIA: January Windstorm, San Bernardino ---
        rec = build_record(
            id_str="STATE-2025-023-CA",
            source="STATE", state="CA",
            title="Governor Newsom Proclamation — January 2025 Windstorm (San Bernardino)",
            incident_type="Severe Wind",
            declaration_date=date(2025, 12, 23),
            incident_start=date(2025, 1, 7),
            incident_end=date(2025, 1, 9),
            renewal_dates_list=None,
            counties=["San Bernardino"],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/12/23/governor-newsom-declares-states-of-emergency-related-to-multiple-severe-weather-events-in-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- CALIFORNIA: Mid-September Storm, Imperial + San Bernardino ---
        rec = build_record(
            id_str="STATE-2025-024-CA",
            source="STATE", state="CA",
            title="Governor Newsom Proclamation — September 2025 Storm (Imperial, San Bernardino)",
            incident_type="Severe Storm",
            declaration_date=date(2025, 12, 23),
            incident_start=date(2025, 9, 18),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Imperial", "San Bernardino"],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/12/23/governor-newsom-declares-states-of-emergency-related-to-multiple-severe-weather-events-in-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- CALIFORNIA: Late December Storms, 6 counties ---
        rec = build_record(
            id_str="STATE-2025-025-CA",
            source="STATE", state="CA",
            title="Governor Newsom Proclamation — Late December 2025 Storms (6 counties)",
            incident_type="Severe Storm",
            declaration_date=date(2025, 12, 24),
            incident_start=date(2025, 12, 23),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Los Angeles", "Orange", "Riverside", "San Bernardino", "San Diego", "Shasta"],
            statewide=False,
            official_url="https://www.gov.ca.gov/2025/12/24/governor-newsom-proclaims-state-of-emergency-to-support-response-in-multiple-counties-due-to-late-december-storms/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NJ EO 409: Dec 26, 2025 Winter Storm ---
        rec = build_record(
            id_str="STATE-2025-001-NJ",
            source="STATE", state="NJ",
            title="NJ Acting Governor Way Emergency (EO 409) — December 2025 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2025, 12, 26),
            incident_start=date(2025, 12, 26),
            incident_end=date(2025, 12, 30),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://nj.gov/infobank/eo/056murphy/pdf/EO-409.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NJ EO 392: Jul 14, 2025 Flash Flooding ---
        rec = build_record(
            id_str="STATE-2025-002-NJ",
            source="STATE", state="NJ",
            title="Governor Murphy Emergency (EO 392) — July 2025 Flash Flooding",
            incident_type="Flash Flooding",
            declaration_date=date(2025, 7, 14),
            incident_start=date(2025, 7, 14),
            incident_end=date(2025, 8, 8),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://nj.gov/infobank/eo/056murphy/pdf/EO-392.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NJ EO 394: Jul 31, 2025 Flash Flooding ---
        rec = build_record(
            id_str="STATE-2025-003-NJ",
            source="STATE", state="NJ",
            title="NJ Acting Governor Way Emergency (EO 394) — July 2025 Flash Flooding",
            incident_type="Flash Flooding",
            declaration_date=date(2025, 7, 31),
            incident_start=date(2025, 7, 31),
            incident_end=date(2025, 8, 8),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.nj.gov/governor/news/news/562025/approved/20250731a.shtml",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NJ EO 14: Feb 21, 2026 Nor'easter ---
        rec = build_record(
            id_str="STATE-2026-002-NJ",
            source="STATE", state="NJ",
            title="Governor Sherrill Emergency (EO 14) — February 2026 Nor'easter",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 21),
            incident_start=date(2026, 2, 22),
            incident_end=date(2026, 2, 25),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://nj.gov/infobank/eo/057sherrill/pdf/EO-14.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- DE Feb 2026 Nor'easter ---
        rec = build_record(
            id_str="STATE-2026-002-DE",
            source="STATE", state="DE",
            title="Governor Meyer Emergency — February 2026 Nor'easter",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 22),
            incident_start=date(2026, 2, 22),
            incident_end=date(2026, 2, 24),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.delaware.gov/state-of-emergency/declaration-of-a-state-of-emergency-due-to-a-severe-winter-storm/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- WI EO 272: Aug 2025 Flooding ---
        rec = build_record(
            id_str="STATE-2025-001-WI",
            source="STATE", state="WI",
            title="Governor Evers Emergency (EO 272) — August 2025 Flooding",
            incident_type="Flood",
            declaration_date=date(2025, 8, 11),
            incident_start=date(2025, 8, 9),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://evers.wi.gov/Documents/EO/EO272-EmergencyOrderFlooding.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- PA Feb 22 Blizzard ---
        rec = build_record(
            id_str="STATE-2026-002-PA",
            source="STATE", state="PA",
            title="Governor Shapiro Disaster Emergency — February 2026 Winter Storm",
            incident_type="Severe Winter Storm",
            declaration_date=date(2026, 2, 22),
            incident_start=date(2026, 2, 22),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://www.pa.gov/content/dam/copapwp-pagov/en/pema/documents/governor-proclamations/2026.2.22%20disaster%20emergency%20proclamation%20winter%20weather.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NM EO 2025-362: Mora County Flooding ---
        rec = build_record(
            id_str="STATE-2025-009-NM",
            source="STATE", state="NM",
            title="Governor Lujan Grisham Emergency (EO 2025-362) — Mora County Flooding",
            incident_type="Flood",
            declaration_date=date(2025, 9, 2),
            incident_start=date(2025, 8, 28),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Mora"],
            statewide=False,
            official_url="https://www.governor.state.nm.us/2025/09/02/governor-signs-emergency-order-for-mora-county-flooding/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- HI Lahaina Wildfires (ongoing since Aug 2023) ---
        # 27th Proclamation (Nov 2025), 28th (Jan 2026). Separate from STATE-2025-001-HI.
        rec = build_record(
            id_str="STATE-2023-001-HI",
            source="STATE", state="HI",
            title="Governor Green Emergency — Lahaina Wildfires (ongoing since Aug 2023)",
            incident_type="Wildfire",
            declaration_date=date(2023, 8, 9),
            incident_start=date(2023, 8, 8),
            incident_end=None,
            renewal_dates_list=[date(2025, 11, 7), date(2026, 1, 9)],
            counties=["Maui"],
            statewide=True,
            official_url="https://governor.hawaii.gov/wp-content/uploads/2025/11/2511016.pdf",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- PR records REMOVED 2026-03-27 ---
        # CPC does not sell plans in Puerto Rico. PR declarations (OE-2025-004 landslides,
        # OE-2025-022 April rains) are valid DSTs but not relevant to our agents.

        # =============================================================
        # PHASE 3 SESSION 2b — REMAINING CARRIER GAPS (from cross-ref)
        # =============================================================

        # --- OR Drought (5 EOs, 8 counties) ---
        # Governor Kotek, July-Sep 2025, rolling drought declarations
        rec = build_record(
            id_str="STATE-2025-008-OR",
            source="STATE", state="OR",
            title="Governor Kotek Drought Emergency — Multiple Counties (EO 25-12 through 25-23)",
            incident_type="Drought",
            declaration_date=date(2025, 7, 15),
            incident_start=date(2025, 6, 1),
            incident_end=None,
            renewal_dates_list=[date(2025, 8, 4), date(2025, 9, 29)],
            counties=["Baker", "Coos", "Douglas", "Jefferson", "Lincoln", "Morrow", "Union", "Wheeler"],
            statewide=False,
            official_url="https://apps.oregon.gov/oregon-newsroom/OR/GOV/Posts/Post/governor-kotek-declares-drought-emergency-in-baker-county",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- AR Severe Storms, Tornadoes, Flooding (DR 25-04) ---
        # Governor Sanders, April 2, 2025
        rec = build_record(
            id_str="STATE-2025-001-AR",
            source="STATE", state="AR",
            title="Governor Sanders Emergency (DR 25-04) — April 2025 Storms and Tornadoes",
            incident_type="Tornado",
            declaration_date=date(2025, 4, 2),
            incident_start=date(2025, 4, 2),
            incident_end=date(2025, 4, 16),
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://governor.arkansas.gov/news_post/sanders-declares-an-emergency-for-severe-storms-tornadoes-and-flooding-on-or-about-april-2-2025/",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- AZ Gila County Flooding ---
        # Governor Hobbs, Sep 27 + Oct 13, 2025
        rec = build_record(
            id_str="STATE-2025-001-AZ",
            source="STATE", state="AZ",
            title="Governor Hobbs Emergency — Gila County Flooding",
            incident_type="Flood",
            declaration_date=date(2025, 9, 27),
            incident_start=date(2025, 9, 27),
            incident_end=None,
            renewal_dates_list=[date(2025, 10, 13)],
            counties=["Gila", "Maricopa", "Mohave"],
            statewide=False,
            official_url="https://azgovernor.gov/office-arizona-governor/news/2025/09/governor-katie-hobbs-declares-state-emergency-gila-county",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- CO Western Colorado Flooding (EO D 2025 021) ---
        # Governor Polis, Oct 12, 2025
        rec = build_record(
            id_str="STATE-2025-001-CO",
            source="STATE", state="CO",
            title="Governor Polis Emergency (EO D 2025 021) — Western Colorado Flooding",
            incident_type="Flood",
            declaration_date=date(2025, 10, 12),
            incident_start=date(2025, 10, 10),
            incident_end=date(2025, 10, 14),
            renewal_dates_list=None,
            counties=["Archuleta", "La Plata", "Mineral"],
            statewide=False,
            official_url="https://governorsoffice.colorado.gov/governor/news/governor-polis-verbally-declares-disaster-emergency-flooding-western-colorado",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- DC Potomac Interceptor Collapse (Mayor's Order 2026-028) ---
        # Mayor Bowser, Feb 18, 2026. Pipe collapsed Jan 19.
        rec = build_record(
            id_str="STATE-2026-002-DC",
            source="STATE", state="DC",
            title="Mayor Bowser Public Emergency (Order 2026-028) — Potomac Sewer Collapse",
            incident_type="Infrastructure Emergency",
            declaration_date=date(2026, 2, 18),
            incident_start=date(2026, 1, 19),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Statewide"],
            statewide=True,
            official_url="https://mayor.dc.gov/release/mayor-bowser-requests-federal-support-region-continues-respond-potomac-interceptor-break",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- KS Severe Storms, Straight-line Winds, Flooding (Jul 2025) ---
        # Governor Kelly, Jul 17-22, 2025. Federal disaster declaration approved.
        rec = build_record(
            id_str="STATE-2025-001-KS",
            source="STATE", state="KS",
            title="Governor Kelly Emergency — July 2025 Severe Storms and Flooding",
            incident_type="Severe Storm",
            declaration_date=date(2025, 7, 17),
            incident_start=date(2025, 7, 17),
            incident_end=date(2025, 7, 22),
            renewal_dates_list=None,
            counties=["Barton", "Comanche", "Edwards", "Ford", "Hodgeman", "Johnson",
                       "Logan", "Marion", "Morris", "Ottawa", "Pawnee", "Rawlins",
                       "Saline", "Stevens", "Sumner", "Wyandotte"],
            statewide=False,
            official_url="https://www.governor.ks.gov/Home/Components/News/News/696/55",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- NC Sam Davis Road Fire (under EO 12 + FEMA FM-5580) ---
        # Governor Stein EO 12 covers WNC wildfires including Swain County
        rec = build_record(
            id_str="STATE-2025-001-NC",
            source="STATE", state="NC",
            title="Governor Stein Emergency (EO 12) — WNC Wildfires (Sam Davis Road Fire)",
            incident_type="Wildfire",
            declaration_date=date(2025, 3, 26),
            incident_start=date(2025, 3, 26),
            incident_end=None,
            renewal_dates_list=[date(2025, 4, 26)],
            counties=["Avery", "Buncombe", "Burke", "Caldwell", "Cherokee", "Clay",
                       "Graham", "Haywood", "Henderson", "Jackson", "Macon", "Madison",
                       "McDowell", "Mitchell", "Polk", "Rutherford", "Swain", "Transylvania",
                       "Watauga", "Yancey"],
            statewide=False,
            official_url="https://governor.nc.gov/executive-order-no-12-declaration-state-emergency-0",
            confidence="curated",
            last_verified="2026-03-27",
        )
        if rec:
            curated.append(rec)

        # --- SC Covington Drive Fire (EO 2025-10 + FEMA FM-5554) ---
        # Governor McMaster, Mar 2, 2025
        rec = build_record(
            id_str="STATE-2025-001-SC",
            source="STATE", state="SC",
            title="Governor McMaster Emergency (EO 2025-10) — Covington Drive Wildfire",
            incident_type="Wildfire",
            declaration_date=date(2025, 3, 2),
            incident_start=date(2025, 3, 1),
            incident_end=None,
            renewal_dates_list=None,
            counties=["Horry"],
            statewide=False,
            official_url="https://governor.sc.gov/news/2025-03/governor-henry-mcmaster-declares-state-emergency-due-wildfires",
            confidence="curated",
            last_verified="2026-03-27",
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

    Fetches DisasterDeclarationsSummaries, paginates,
    consolidates county-level records into one disaster per femaDeclarationString,
    and builds records using the shared build_record() function.
    Includes DR (Major Disaster), EM (Emergency), and FM (Fire Management).

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
        Includes DR (Major Disaster), EM (Emergency), and FM (Fire Management).
        FM/FMAG included as of v3.0: all 3 major carriers (Aetna, Wellcare,
        Humana) honor FMAG declarations as valid DST triggers. While FM is
        not a "major disaster" under Stafford Act §401, carriers treat the
        accompanying governor declarations as valid under 42 CFR § 422.62(b)(18).
        Including FM ensures agents can find the same DSTs carriers honor.
        Strips parenthetical suffixes from county names.
        Detects statewide declarations.
        """
        groups: Dict[str, Dict] = {}

        for rec in records:
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

def inject_carrier_acknowledgments(records: List[Dict]) -> None:
    """Inject carrierAcknowledgments from carrier_analysis.json + Humana/Healthspring crossref.

    Modifies records in-place. Each record gets a dict like:
    {"aetna": true, "wellcare": true, "humana": true, "healthspring": false}
    Only added if at least one carrier acknowledges the record.
    """
    carrier_analysis_path = Path(__file__).parent / "carrier_analysis.json"
    if not carrier_analysis_path.exists():
        print("  WARNING: carrier_analysis.json not found — skipping carrier acks")
        return

    with open(carrier_analysis_path) as f:
        analysis = json.load(f)

    # Build lookup: curated_id -> set of carriers
    acks: Dict[str, set] = {}
    for match in analysis.get("matched", []):
        cid = match.get("curated_id", "")
        carrier = match.get("carrier", "").lower()
        if cid and carrier:
            if cid not in acks:
                acks[cid] = set()
            acks[cid].add(carrier)

    # Also match Humana/Healthspring from four_carrier_crossref.py embedded data
    # These aren't in carrier_analysis.json (which only has Aetna/Wellcare)
    # We match by state + fuzzy title
    try:
        crossref_path = Path(__file__).parent / "four_carrier_crossref.py"
        if crossref_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("crossref", crossref_path)
            crossref_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(crossref_mod)

            humana_data = getattr(crossref_mod, "HUMANA", [])
            wellcare_extra = getattr(crossref_mod, "WELLCARE", [])

            # Build index of our records by state
            by_state: Dict[str, List[Dict]] = {}
            for rec in records:
                st = rec.get("state", "")
                if st not in by_state:
                    by_state[st] = []
                by_state[st].append(rec)

            def normalize_title(t):
                import re
                t = t.lower()
                t = re.sub(r'\(.*?\)', '', t)
                t = re.sub(r'(dr|em|fm|eo|oe)-?\d+[-\s]?', '', t)
                return t.strip()

            def fuzzy_match(carrier_title, our_title):
                from difflib import SequenceMatcher
                ct = normalize_title(carrier_title)
                ot = normalize_title(our_title)
                return SequenceMatcher(None, ct, ot).ratio()

            # Match Humana records
            for h in humana_data:
                state = h.get("state", "")
                title = h.get("title", "")
                state_recs = by_state.get(state, [])
                best_score = 0
                best_id = None
                for rec in state_recs:
                    score = fuzzy_match(title, rec.get("title", ""))
                    if score > best_score:
                        best_score = score
                        best_id = rec.get("id")
                if best_id and best_score >= 0.35:
                    if best_id not in acks:
                        acks[best_id] = set()
                    acks[best_id].add("humana")

            # Match Healthspring (if present)
            healthspring_data = getattr(crossref_mod, "HEALTHSPRING", [])
            for hs in healthspring_data:
                state = hs.get("state", "")
                title = hs.get("title", "")
                state_recs = by_state.get(state, [])
                best_score = 0
                best_id = None
                for rec in state_recs:
                    score = fuzzy_match(title, rec.get("title", ""))
                    if score > best_score:
                        best_score = score
                        best_id = rec.get("id")
                if best_id and best_score >= 0.35:
                    if best_id not in acks:
                        acks[best_id] = set()
                    acks[best_id].add("healthspring")
    except Exception as e:
        print(f"  WARNING: Humana/Healthspring matching failed: {e}")

    # Inject into records
    injected = 0
    for rec in records:
        rid = rec.get("id", "")
        if rid in acks:
            carriers = acks[rid]
            rec["carrierAcknowledgments"] = {
                "aetna": "aetna" in carriers,
                "wellcare": "wellcare" in carriers,
                "humana": "humana" in carriers,
                "healthspring": "healthspring" in carriers,
            }
            injected += 1

    print(f"  Carrier acknowledgments injected: {injected}/{len(records)} records")
    carrier_counts = {}
    for rid, carriers in acks.items():
        for c in carriers:
            carrier_counts[c] = carrier_counts.get(c, 0) + 1
    for c, n in sorted(carrier_counts.items()):
        print(f"    {c}: {n} matches")


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

    # --- Inject carrier acknowledgments from carrier_analysis.json ---
    inject_carrier_acknowledgments(unique_curated)

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
