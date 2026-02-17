#!/usr/bin/env python3
"""
Medicare Enrollment Data Builder — Downloads CMS county-level enrollment data
and outputs medicare_enrollment.json for the DST Compiler Tool.

Data Source: CMS Medicare Monthly Enrollment (data.cms.gov)
  - API: https://data.cms.gov/data-api/v1/dataset/d7fabe1e-d19b-4333-9eff-e80e0643f2fd/data
  - Public, no authentication required
  - County-level total Medicare + MA enrollment
  - Updated monthly (~3 month lag)

Output: medicare_enrollment.json
  - Keyed by state abbreviation + county name (matching county_state_map.json format)
  - Used by index.html for reporting (impact summary banner, state headers)

Usage:
  python build_medicare_enrollment.py              # Normal run
  python build_medicare_enrollment.py --dry-run     # Show what would be generated without writing
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Dict, Optional, Tuple

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COUNTY_MAP_PATH = os.path.join(SCRIPT_DIR, 'county_state_map.json')
OUTPUT_PATH = os.path.join(SCRIPT_DIR, 'medicare_enrollment.json')

# CMS data.cms.gov API endpoint for Medicare Monthly Enrollment
CMS_API_BASE = 'https://data.cms.gov/data-api/v1/dataset/d7fabe1e-d19b-4333-9eff-e80e0643f2fd/data'

# Column names from the CMS dataset
COL_GEO_LEVEL = 'BENE_GEO_LVL'
COL_STATE = 'BENE_STATE_ABRVTN'
COL_COUNTY = 'BENE_COUNTY_DESC'
COL_FIPS = 'BENE_FIPS_CD'
COL_YEAR = 'YEAR'
COL_MONTH = 'MONTH'
COL_TOTAL = 'TOT_BENES'
COL_ORIGINAL = 'ORGNL_MDCR_BENES'
COL_MA = 'MA_AND_OTH_BENES'

# Months in order for finding the latest available
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November', 'December']

# Known county name mappings: CMS name -> our county_state_map.json name
# CMS appends " County", " Parish", " Borough", etc. — we strip those.
# This dict handles the remaining edge cases where names differ.
COUNTY_NAME_OVERRIDES = {
    # CMS uses "Doña Ana" or "Dona Ana" — our map uses "Dona Ana"
    'Doña Ana': 'Dona Ana',
    # CMS city-counties
    'Carson City': 'Carson City',
    # Alaska — CMS uses "City And Borough" (capital A)
    'Anchorage Municipality': 'Anchorage',
    'Juneau City And Borough': 'Juneau',
    'Sitka City And Borough': 'Sitka',
    'Wrangell City And Borough': 'Wrangell',
    'Yakutat City And Borough': 'Yakutat',
    # Connecticut — CMS uses planning regions (replaced counties in 2022)
    # Our county_state_map still uses old county names.
    # Map planning regions → approximate old county equivalents.
    'Capitol Planning Region': 'Hartford',
    'Greater Bridgeport Planning Region': 'Fairfield',
    'Lower Connecticut River Valley Planning Region': 'Middlesex',
    'Naugatuck Valley Planning Region': 'New Haven',
    'Northeastern Connecticut Planning Region': 'Windham',
    'Northwest Hills Planning Region': 'Litchfield',
    'South Central Connecticut Planning Region': 'New Haven',
    'Southeastern Connecticut Planning Region': 'New London',
    'Western Connecticut Planning Region': 'Fairfield',
}

# Suffixes to strip from CMS county names to match our format
COUNTY_SUFFIXES = [
    ' County', ' Parish', ' Census Area', ' Borough',
    ' Municipality', ' city', ' City and Borough', ' City And Borough',
]


def normalize_cms_county_name(cms_name: str) -> str:
    """Convert CMS county name to match county_state_map.json format."""
    if not cms_name:
        return ''

    # Check explicit overrides first
    if cms_name in COUNTY_NAME_OVERRIDES:
        return COUNTY_NAME_OVERRIDES[cms_name]

    # Strip suffixes
    name = cms_name
    for suffix in COUNTY_SUFFIXES:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break

    return name.strip()


def safe_int(value: str) -> int:
    """Parse CMS string value to int, handling suppressed values ('*')."""
    if not value or value == '*':
        return 0
    try:
        return int(value.replace(',', ''))
    except (ValueError, TypeError):
        return 0


def load_county_map() -> Dict[str, list]:
    """Load county_state_map.json to validate county name matching."""
    with open(COUNTY_MAP_PATH, 'r') as f:
        return json.load(f)


def discover_latest_period(session: requests.Session) -> Tuple[str, str]:
    """Find the most recent year/month available in the CMS dataset."""
    print('Discovering latest available data period...')

    # Try the most recent years first
    current_year = datetime.now().year
    for year in range(current_year, current_year - 3, -1):
        # Check if this year has any county data
        params = {
            'filter[BENE_GEO_LVL]': 'County',
            'filter[YEAR]': str(year),
            'size': 1,
        }
        try:
            resp = session.get(CMS_API_BASE, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data:
                # Found data for this year — now find latest month
                for month in reversed(MONTHS):
                    params['filter[MONTH]'] = month
                    resp = session.get(CMS_API_BASE, params=params, timeout=30)
                    resp.raise_for_status()
                    if resp.json():
                        print(f'  Latest available: {month} {year}')
                        return str(year), month
        except requests.RequestException as e:
            print(f'  Warning: API error checking {year}: {e}')
            continue

    raise RuntimeError('Could not find any available data period in CMS API')


def fetch_county_enrollment(session: requests.Session, year: str, month: str) -> list:
    """Fetch all county-level enrollment records for a given period."""
    print(f'Fetching county enrollment data for {month} {year}...')

    all_records = []
    page_size = 5000
    offset = 0

    while True:
        params = {
            'filter[BENE_GEO_LVL]': 'County',
            'filter[YEAR]': year,
            'filter[MONTH]': month,
            'size': page_size,
            'offset': offset,
        }

        try:
            resp = session.get(CMS_API_BASE, params=params, timeout=60)
            resp.raise_for_status()
            page = resp.json()
        except requests.RequestException as e:
            print(f'  Error fetching offset {offset}: {e}')
            if all_records:
                print(f'  Using {len(all_records)} records fetched so far')
                break
            raise

        if not page:
            break

        all_records.extend(page)
        print(f'  Fetched {len(all_records)} records...')

        if len(page) < page_size:
            break

        offset += page_size
        time.sleep(0.5)  # Be polite to the API

    print(f'  Total: {len(all_records)} county records')
    return all_records


def build_enrollment_json(records: list, county_map: dict, year: str, month: str) -> dict:
    """Process CMS records into our output format, validated against county_map."""
    states = {}
    matched = 0
    unmatched = []
    skipped_territories = 0

    # Build a lookup set from county_state_map for validation
    county_lookup = {}
    for state, counties in county_map.items():
        county_lookup[state] = {c.lower(): c for c in counties}

    for rec in records:
        state = rec.get(COL_STATE, '')
        cms_county = rec.get(COL_COUNTY, '')
        fips = rec.get(COL_FIPS, '')

        if not state or not cms_county:
            continue

        # Skip "Unknown" county entries
        if cms_county.lower() in ('unknown', 'unknown county'):
            continue

        # Normalize the CMS county name to match our format
        our_county = normalize_cms_county_name(cms_county)

        # Parse enrollment numbers
        total = safe_int(rec.get(COL_TOTAL, '0'))
        original = safe_int(rec.get(COL_ORIGINAL, '0'))
        ma = safe_int(rec.get(COL_MA, '0'))

        if total == 0:
            continue

        # Initialize state entry
        if state not in states:
            states[state] = {
                'total': 0,
                'maEnrollment': 0,
                'counties': {},
            }

        # Add county data (aggregate if multiple CMS entries map to same name, e.g. CT planning regions)
        if our_county in states[state]['counties']:
            states[state]['counties'][our_county]['total'] += total
            states[state]['counties'][our_county]['ma'] += ma
        else:
            states[state]['counties'][our_county] = {
                'total': total,
                'ma': ma,
                'fips': fips,
            }
        states[state]['total'] += total
        states[state]['maEnrollment'] += ma

        # Check if we can match this to our county_state_map
        if state in county_lookup:
            if our_county.lower() in county_lookup[state]:
                matched += 1
            else:
                unmatched.append(f'{our_county}, {state}')
        else:
            skipped_territories += 1

    # Summary
    total_counties = sum(len(s['counties']) for s in states.values())
    total_benes = sum(s['total'] for s in states.values())
    total_ma = sum(s['maEnrollment'] for s in states.values())

    print(f'\nProcessing summary:')
    print(f'  States: {len(states)}')
    print(f'  Counties: {total_counties}')
    print(f'  Total Medicare beneficiaries: {total_benes:,}')
    print(f'  Medicare Advantage: {total_ma:,} ({total_ma/total_benes*100:.1f}%)')
    print(f'  Matched to county_state_map: {matched}')
    print(f'  Unmatched (CMS has, we don\'t): {len(unmatched)}')
    if skipped_territories:
        print(f'  Territory counties (no state match): {skipped_territories}')

    if unmatched and len(unmatched) <= 20:
        print(f'  Unmatched counties: {", ".join(unmatched[:20])}')
    elif unmatched:
        print(f'  First 20 unmatched: {", ".join(unmatched[:20])}...')

    # Calculate match rate against our map
    total_in_map = sum(len(counties) for counties in county_map.values())
    match_rate = matched / total_in_map * 100 if total_in_map else 0
    print(f'  Match rate: {match_rate:.1f}% of our {total_in_map} counties')

    output = {
        'metadata': {
            'source': 'CMS Medicare Monthly Enrollment',
            'sourceUrl': 'https://data.cms.gov/summary-statistics-on-beneficiary-enrollment/medicare-and-medicaid-reports/medicare-monthly-enrollment',
            'period': f'{month} {year}',
            'downloadDate': datetime.now().strftime('%Y-%m-%d'),
            'totalBeneficiaries': total_benes,
            'totalMA': total_ma,
            'counties': total_counties,
            'matchRate': round(match_rate, 1),
        },
        'states': states,
    }

    return output


def main():
    dry_run = '--dry-run' in sys.argv

    # Load our county map for validation
    print('Loading county_state_map.json...')
    county_map = load_county_map()
    total_counties = sum(len(v) for v in county_map.values())
    print(f'  {len(county_map)} states, {total_counties} counties')

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'DST-Compiler-Medicare-Enrollment/1.0 (github.com/Duynomite/dst-compiler)',
        'Accept': 'application/json',
    })

    # Step 1: Find latest available period
    year, month = discover_latest_period(session)

    # Step 2: Fetch county-level enrollment data
    records = fetch_county_enrollment(session, year, month)

    if not records:
        print('ERROR: No records returned from CMS API')
        sys.exit(1)

    # Step 3: Build the output JSON
    output = build_enrollment_json(records, county_map, year, month)

    # Step 4: Write output
    if dry_run:
        print(f'\n[DRY RUN] Would write {len(json.dumps(output)):,} bytes to {OUTPUT_PATH}')
        # Print a sample
        sample_state = list(output['states'].keys())[0] if output['states'] else None
        if sample_state:
            state_data = output['states'][sample_state]
            sample_counties = dict(list(state_data['counties'].items())[:3])
            print(f'\nSample — {sample_state}:')
            print(f'  State total: {state_data["total"]:,}')
            print(f'  State MA: {state_data["maEnrollment"]:,}')
            for county, data in sample_counties.items():
                print(f'  {county}: {data["total"]:,} total, {data["ma"]:,} MA')
    else:
        with open(OUTPUT_PATH, 'w') as f:
            json.dump(output, f, indent=2)
        file_size = os.path.getsize(OUTPUT_PATH)
        print(f'\nWrote {OUTPUT_PATH} ({file_size:,} bytes)')

    print('\nDone.')


if __name__ == '__main__':
    main()
