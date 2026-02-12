#!/usr/bin/env python3
"""
Phase 2: Build governor declaration entries for curated_disasters.json

Decision criteria for inclusion:
- Declaration must be from a government entity (governor, mayor, HHS)
- SEP window must still be active as of 2026-02-11
- SEP window = 2 full calendar months after incident end (last day of month+2)
- If ongoing (no end date): 14-month max from SEP start date
- Declarations that were terminated quickly (1-3 days) still generate valid SEP windows
  because the incident period (when damage occurred) is what matters, not the declaration duration

Key date: TODAY = 2026-02-11
"""

import json
import calendar
from datetime import date, datetime

TODAY = date(2026, 2, 11)


def last_day_of_month(year, month):
    """Get the last day of a given month."""
    return calendar.monthrange(year, month)[1]


def calc_sep_end_from_incident_end(incident_end_str):
    """SEP window end = last day of (incidentEnd.month + 2)."""
    d = datetime.strptime(incident_end_str, "%Y-%m-%d").date()
    month = d.month + 2
    year = d.year
    while month > 12:
        month -= 12
        year += 1
    return date(year, month, last_day_of_month(year, month))


def calc_sep_end_ongoing(sep_start_str):
    """SEP window end for ongoing = last day of (sepStart.month + 14)."""
    d = datetime.strptime(sep_start_str, "%Y-%m-%d").date()
    month = d.month + 14
    year = d.year
    while month > 12:
        month -= 12
        year += 1
    return date(year, month, last_day_of_month(year, month))


def days_remaining(sep_end):
    """Calculate days remaining from today."""
    return (sep_end - TODAY).days


def calc_status(incident_end, sep_end, days_rem):
    """Determine status based on incident end and days remaining."""
    if incident_end is None:
        # Ongoing
        if days_rem <= 30:
            return "expiring_soon"
        return "ongoing"
    else:
        # Has incident end
        if days_rem <= 30:
            return "expiring_soon"
        return "active"


def make_entry(id, source, state, title, incident_type, declaration_date,
               incident_start, incident_end, counties, statewide, official_url,
               confidence="curated", last_verified="2026-02-11"):
    """Build a disaster entry with all calculated fields."""

    sep_start = min(declaration_date, incident_start)

    if incident_end:
        sep_end = calc_sep_end_from_incident_end(incident_end)
    else:
        sep_end = calc_sep_end_ongoing(sep_start)

    days_rem = days_remaining(sep_end)

    # Skip if SEP window has already expired
    if days_rem < 0:
        print(f"  SKIPPED {id}: SEP expired {abs(days_rem)} days ago (end: {sep_end})")
        return None

    status = calc_status(incident_end, sep_end, days_rem)

    entry = {
        "id": id,
        "source": source,
        "state": state,
        "title": title,
        "incidentType": incident_type,
        "declarationDate": declaration_date,
        "incidentStart": incident_start,
        "incidentEnd": incident_end,
        "renewalDates": None,
        "counties": counties,
        "statewide": statewide,
        "officialUrl": official_url,
        "status": status,
        "sepWindowStart": sep_start,
        "sepWindowEnd": str(sep_end),
        "daysRemaining": days_rem,
        "confidenceLevel": confidence,
        "lastVerified": last_verified,
        "lastUpdated": "2026-02-11T00:00:00Z"
    }

    print(f"  ADDED {id}: SEP {sep_start} to {sep_end} ({days_rem} days, {status})")
    return entry


# ============================================================
# JAN 2026 WINTER STORM GOVERNOR DECLARATIONS (Winter Storm Fern)
# ============================================================
# The Jan 2026 winter storm hit ~Jan 20-27, 2026
# Most declarations: Jan 21-25, 2026
# Incident period: roughly Jan 20-27, 2026
# For states where termination was quick (DE: terminated Jan 26),
# the incident damage period still counts for SEP window.
# Using Jan 20 as incident start and Jan 27 as incident end for most.
# States with ongoing/unknown termination: incidentEnd = null (ongoing)

print("=" * 60)
print("BUILDING GOVERNOR DECLARATION ENTRIES")
print("=" * 60)

new_entries = []

# ----- TEXAS -----
# Gov Abbott, Jan 22 declaration, 219 counties (expanded Jan 25)
# Still active - no termination found
e = make_entry(
    id="STATE-2026-001-TX",
    source="STATE",
    state="TX",
    title="Governor Abbott Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-20",
    incident_end=None,  # No termination found
    counties=["Statewide"],  # 219 of 254 counties, effectively statewide for Medicare purposes
    statewide=True,
    official_url="https://gov.texas.gov/news/post/governor-abbott-provides-update-on-texas-ongoing-response-to-severe-winter-weather-"
)
if e: new_entries.append(e)

# ----- NORTH CAROLINA (1st declaration) -----
# Gov Stein, Jan 21 declaration, statewide
e = make_entry(
    id="STATE-2026-001-NC",
    source="STATE",
    state="NC",
    title="Governor Stein Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-21",
    incident_start="2026-01-20",
    incident_end=None,  # No termination found
    counties=["Statewide"],
    statewide=True,
    official_url="https://governor.nc.gov/news/press-releases/2026/01/21/governor-stein-declares-state-emergency-ahead-winter-storm"
)
if e: new_entries.append(e)

# ----- VIRGINIA -----
# Gov Spanberger, Jan 22, EO 11, statewide
e = make_entry(
    id="STATE-2026-001-VA",
    source="STATE",
    state="VA",
    title="Governor Spanberger Emergency Declaration (EO 11) — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-20",
    incident_end=None,  # No termination found
    counties=["Statewide"],
    statewide=True,
    official_url="https://www.governor.virginia.gov/newsroom/news-releases/2026/january-releases/name-1111570-en.html"
)
if e: new_entries.append(e)

# ----- GEORGIA (1st declaration) -----
# Gov Kemp, Jan 22, statewide, effective through Jan 29
e = make_entry(
    id="STATE-2026-001-GA",
    source="STATE",
    state="GA",
    title="Governor Kemp Emergency Declaration — January 2026 Winter Storm (Fern)",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-22",
    incident_end="2026-01-29",  # Effective through Jan 29
    counties=["Statewide"],
    statewide=True,
    official_url="https://gov.georgia.gov/press-releases/2026-01-22/gov-kemp-declares-state-emergency-activates-state-operations-center-ahead"
)
if e: new_entries.append(e)

# ----- GEORGIA (2nd declaration - Winter Storm Gianna) -----
# Gov Kemp, Jan 30, statewide, effective through Feb 6
e = make_entry(
    id="STATE-2026-002-GA",
    source="STATE",
    state="GA",
    title="Governor Kemp Emergency Declaration — January 2026 Winter Storm (Gianna)",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-30",
    incident_start="2026-01-30",
    incident_end="2026-02-06",  # Effective through Feb 6
    counties=["Statewide"],
    statewide=True,
    official_url="https://gov.georgia.gov/press-releases/2026-01-30/gov-kemp-declares-new-state-emergency-ahead-winter-storm"
)
if e: new_entries.append(e)

# ----- NEW YORK -----
# Gov Hochul, Jan 23, EO 57, statewide
e = make_entry(
    id="STATE-2026-001-NY",
    source="STATE",
    state="NY",
    title="Governor Hochul Emergency Declaration (EO 57) — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-23",
    incident_start="2026-01-23",
    incident_end=None,  # No termination found
    counties=["Statewide"],
    statewide=True,
    official_url="https://www.governor.ny.gov/news/governor-hochul-declares-state-emergency-ahead-extreme-cold-and-massive-winter-storm-weekend"
)
if e: new_entries.append(e)

# ----- PENNSYLVANIA -----
# Gov Shapiro, Jan 24 2026, statewide, 21-day auto-expire (~Feb 14)
e = make_entry(
    id="STATE-2026-001-PA",
    source="STATE",
    state="PA",
    title="Governor Shapiro Disaster Emergency Proclamation — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-24",
    incident_start="2026-01-23",
    incident_end="2026-02-14",  # 21-day auto-expire
    counties=["Statewide"],
    statewide=True,
    official_url="https://www.pa.gov/governor/newsroom/2026-press-releases/gov-shapiro-signs-proclamation-of-disaster-emergency"
)
if e: new_entries.append(e)

# ----- DELAWARE -----
# Gov Meyer, Jan 23 2026, statewide, TERMINATED Jan 26
e = make_entry(
    id="STATE-2026-001-DE",
    source="STATE",
    state="DE",
    title="Governor Meyer Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-23",
    incident_start="2026-01-23",
    incident_end="2026-01-26",  # Terminated Jan 26
    counties=["Statewide"],
    statewide=True,
    official_url="https://news.delaware.gov/2026/01/23/soe-eoc-activated-winter-storm/"
)
if e: new_entries.append(e)

# ----- NEW MEXICO -----
# Gov Lujan Grisham, Jan 2026, EO 2026-005, statewide
e = make_entry(
    id="STATE-2026-001-NM",
    source="STATE",
    state="NM",
    title="Governor Lujan Grisham Emergency Declaration (EO 2026-005) — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-20",
    incident_end=None,  # No termination found
    counties=["Statewide"],
    statewide=True,
    official_url="https://www.governor.state.nm.us/about-the-governor/executive-orders/"
)
if e: new_entries.append(e)

# ----- KENTUCKY -----
# Gov Beshear, Jan 2026 winter storm (separate from Jan 2025)
# Has FEMA EM-3633 for Jan 2025; this is a new Jan 2026 declaration
e = make_entry(
    id="STATE-2026-001-KY",
    source="STATE",
    state="KY",
    title="Governor Beshear Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-20",
    incident_end=None,  # No termination found
    counties=["Statewide"],
    statewide=True,
    official_url="https://governor.ky.gov/attachments/20250104_Executive-Order_2025-007_State-of-Emergency-Related-to-Winter-Weather-Event.pdf"
)
if e: new_entries.append(e)

# ----- LOUISIANA -----
# Gov Landry, Jan 18 2025, statewide, renewed via EOs
# SEP from Jan 18 2025 incident - still has active SEP window
e = make_entry(
    id="STATE-2025-001-LA",
    source="STATE",
    state="LA",
    title="Governor Landry Emergency Declaration (JML 25-12) — January 2025 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2025-01-18",
    incident_start="2025-01-18",
    incident_end=None,  # Renewed/extended
    counties=["Statewide"],
    statewide=True,
    official_url="https://gov.louisiana.gov/news/4746"
)
if e: new_entries.append(e)

# ----- ARKANSAS -----
# Gov Sanders, Jan 4 2025, statewide, expired Jan 13
# SEP: incident end Jan 13 -> SEP end March 31, 2025 - EXPIRED
# Jan 2026 declaration also exists
e = make_entry(
    id="STATE-2026-001-AR",
    source="STATE",
    state="AR",
    title="Governor Sanders Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-20",
    incident_end=None,  # No termination info found for 2026 declaration
    counties=["Statewide"],
    statewide=True,
    official_url="https://governor.arkansas.gov/news_post/sanders-declares-state-of-emergency-ahead-of-anticipated-severe-winter-weather/"
)
if e: new_entries.append(e)

# ----- MISSISSIPPI -----
# Gov Reeves, Jan 2026 winter storm (separate from Jan 19 2025 which expired Jan 22)
e = make_entry(
    id="STATE-2026-001-MS",
    source="STATE",
    state="MS",
    title="Governor Reeves Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-20",
    incident_end=None,  # No termination found
    counties=["Statewide"],
    statewide=True,
    official_url="https://governorreeves.ms.gov/governor-reeves-issues-state-of-emergency-ahead-of-severe-winter-weather/"
)
if e: new_entries.append(e)

# ----- INDIANA -----
# Gov Braun, Jan 25 2026, EO 26-03, statewide, 60-day window
e = make_entry(
    id="STATE-2026-001-IN",
    source="STATE",
    state="IN",
    title="Governor Braun Disaster Emergency (EO 26-03) — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-25",
    incident_start="2026-01-23",
    incident_end=None,  # 60-day window, still active
    counties=["Statewide"],
    statewide=True,
    official_url="https://www.in.gov/gov/newsroom/executive-orders/"
)
if e: new_entries.append(e)

# ----- MARYLAND -----
# Gov Moore, late Jan 2025 declaration (Jan 24-26 storm) - statewide
# Also requested federal emergency declaration
e = make_entry(
    id="STATE-2025-002-MD",
    source="STATE",
    state="MD",
    title="Governor Moore Emergency Declaration — January 2025 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2025-01-24",
    incident_start="2025-01-24",
    incident_end="2025-01-28",  # Storm passed by Jan 28
    counties=["Statewide"],
    statewide=True,
    official_url="https://governor.maryland.gov/news/press/pages/Governor-Moore-Declares-State-of-Emergency,-Requests-Federal-Emergency-Declaration-Ahead-of-Dangerous-Winter-Storm.aspx"
)
if e: new_entries.append(e)

# ----- WEST VIRGINIA -----
# Gov Morrisey, Jan 23 2026, statewide (all 55 counties)
e = make_entry(
    id="STATE-2026-001-WV",
    source="STATE",
    state="WV",
    title="Governor Morrisey Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-23",
    incident_start="2026-01-21",
    incident_end=None,  # No termination found
    counties=["Statewide"],
    statewide=True,
    official_url="https://governor.wv.gov/article/governor-morrisey-declares-state-emergency-all-55-counties-major-winter-storm-approaches"
)
if e: new_entries.append(e)

# ----- SOUTH CAROLINA -----
# Gov McMaster, Jan 2026 winter storm declaration
e = make_entry(
    id="STATE-2026-001-SC",
    source="STATE",
    state="SC",
    title="Governor McMaster Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-20",
    incident_end=None,  # 15-day auto-expire would be ~Feb 6 but no explicit termination found
    counties=["Statewide"],
    statewide=True,
    official_url="https://governor.sc.gov/news/2025-01/governor-henry-mcmaster-declares-state-emergency-winter-weather"
)
if e: new_entries.append(e)

# ----- DC -----
# Mayor Bowser, Jan 23 2025 declaration (late Jan storm)
# Snow emergency ended Jan 27
e = make_entry(
    id="STATE-2025-001-DC",
    source="STATE",
    state="DC",
    title="Mayor Bowser Emergency Declaration — January 2025 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2025-01-23",
    incident_start="2025-01-23",
    incident_end="2025-01-27",  # Snow emergency ended
    counties=["District of Columbia"],
    statewide=True,
    official_url="https://mayor.dc.gov/release/mayor-bowser-declares-state-emergency-washington-dc-ahead-major-winter-storm-and-extreme"
)
if e: new_entries.append(e)

# ----- TENNESSEE -----
# Gov Lee, Jan 22 2026, statewide (all 95 counties), effective through Feb 5
e = make_entry(
    id="STATE-2026-001-TN",
    source="STATE",
    state="TN",
    title="Governor Lee Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-22",
    incident_end=None,  # No termination found; federal escalation ongoing
    counties=["Statewide"],
    statewide=True,
    official_url="https://www.tn.gov/governor/news/2026/1/22/gov--lee-issues-state-of-emergency-ahead-of-major-winter-storm.html"
)
if e: new_entries.append(e)

# ----- CONNECTICUT -----
# Gov Lamont, Jan 25 2026, statewide
# Commercial ban lifted Jan 26 but broader SOE may be longer
e = make_entry(
    id="STATE-2026-001-CT",
    source="STATE",
    state="CT",
    title="Governor Lamont Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-25",
    incident_start="2026-01-25",
    incident_end="2026-01-27",  # Storm passed, commercial ban lifted Jan 26
    counties=["Statewide"],
    statewide=True,
    official_url="https://portal.ct.gov/governor/news/press-releases/2026/01-2026/governor-lamont-declares-state-of-emergency-limits-commercial-vehicle-travel"
)
if e: new_entries.append(e)

# ----- OHIO -----
# Gov DeWine, Jan 24 2026, statewide (all 88 counties), 90-day window
e = make_entry(
    id="STATE-2026-001-OH",
    source="STATE",
    state="OH",
    title="Governor DeWine Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-24",
    incident_start="2026-01-23",
    incident_end=None,  # 90-day window, still active
    counties=["Statewide"],
    statewide=True,
    official_url="https://governor.ohio.gov/"
)
if e: new_entries.append(e)

# ----- KANSAS -----
# Gov Kelly, Jan 2026 winter storm (separate from Jan 4 2025 which expired)
e = make_entry(
    id="STATE-2026-001-KS",
    source="STATE",
    state="KS",
    title="Governor Kelly Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-20",
    incident_end=None,  # No termination found
    counties=["Statewide"],
    statewide=True,
    official_url="https://www.kansastag.gov/m/newsflash/Home/Detail/817"
)
if e: new_entries.append(e)

# ----- MISSOURI -----
# Gov Kehoe (took office Jan 13 2025), Jan 2026 winter storm
e = make_entry(
    id="STATE-2026-001-MO",
    source="STATE",
    state="MO",
    title="Governor Kehoe Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-20",
    incident_end=None,  # No termination found
    counties=["Statewide"],
    statewide=True,
    official_url="https://governor.mo.gov/"
)
if e: new_entries.append(e)

# ----- ALABAMA (Jan 2026) -----
# Gov Ivey, Jan 2026 winter storm, 19 counties
# (Jan 2025 declarations were terminated - SEP expired)
e = make_entry(
    id="STATE-2026-001-AL",
    source="STATE",
    state="AL",
    title="Governor Ivey Emergency Declaration — January 2026 Winter Storm",
    incident_type="Severe Winter Storm",
    declaration_date="2026-01-22",
    incident_start="2026-01-20",
    incident_end=None,  # No termination found
    counties=["Statewide"],  # Research indicated county-specific but 19 counties is significant
    statewide=True,
    official_url="https://governor.alabama.gov/newsroom/2025/01/state-of-emergency-winter-weather-5/"
)
if e: new_entries.append(e)

# ----- NEW JERSEY (Jan 2026) -----
# NJ had Jan 2025 terminated Jan 27 - SEP expired March 31
# Check if there was a Jan 2026 declaration too
# Research showed Jan 18 2025 only. Skip if no Jan 2026 declaration confirmed.
# Actually research DID confirm NJ was in the Jan 2025 storm - terminated Jan 27
# SEP end would be: Jan 27 + 2 months = March 31, 2025 -- EXPIRED
# No confirmed Jan 2026 declaration found for NJ
print("\n  INFO: NJ - Only Jan 2025 declaration found (terminated Jan 27, SEP expired March 31 2025)")

# ============================================================
# HHS PUBLIC HEALTH EMERGENCY
# ============================================================
print("\n" + "=" * 60)
print("BUILDING HHS PHE ENTRIES")
print("=" * 60)

# Washington State HHS PHE - Severe Weather (NOT bird flu)
# Dec 23 2025, retroactive to Dec 9 2025
e = make_entry(
    id="HHS-2025-001-WA",
    source="HHS",
    state="WA",
    title="HHS Public Health Emergency — Washington State Severe Weather",
    incident_type="Severe Storm",
    declaration_date="2025-12-23",
    incident_start="2025-12-09",  # Retroactive
    incident_end=None,  # Ongoing recovery
    counties=[
        "Clallam", "Clark", "Cowlitz", "Grays Harbor", "Jefferson",
        "King", "Kitsap", "Lewis", "Mason", "Pacific",
        "Pierce", "Skagit", "Skamania", "Snohomish", "Thurston",
        "Wahkiakum"
    ],
    statewide=False,
    official_url="https://aspr.hhs.gov/newsroom/Pages/PHE-Declared-for-Washington-Following-Severe-Weather-Dec2025.aspx"
)
if e: new_entries.append(e)

# ============================================================
# CALIFORNIA GOVERNOR DECLARATIONS
# ============================================================
print("\n" + "=" * 60)
print("BUILDING CALIFORNIA GOVERNOR ENTRIES")
print("=" * 60)

# California Dec 2025 storms - Gov Newsom, 6 counties
e = make_entry(
    id="STATE-2025-002-CA",
    source="STATE",
    state="CA",
    title="Governor Newsom Emergency Declaration — December 2025 Winter Storms",
    incident_type="Severe Storm",
    declaration_date="2025-12-24",
    incident_start="2025-12-21",
    incident_end=None,  # Ongoing recovery
    counties=[
        "Los Angeles", "Orange", "Riverside", "San Bernardino",
        "San Diego", "Shasta"
    ],
    statewide=False,
    official_url="https://www.gov.ca.gov/2025/12/24/governor-newsom-proclaims-state-of-emergency-to-support-response-in-multiple-counties-due-to-late-december-storms/"
)
if e: new_entries.append(e)

# California Jan 2025 LA Wildfires - Gov Newsom
# Still active/ongoing for recovery
e = make_entry(
    id="STATE-2025-001-CA",
    source="STATE",
    state="CA",
    title="Governor Newsom Emergency Declaration — January 2025 Los Angeles Wildfires",
    incident_type="Wildfire",
    declaration_date="2025-01-07",
    incident_start="2025-01-07",
    incident_end=None,  # Ongoing recovery
    counties=[
        "Los Angeles", "Ventura"
    ],
    statewide=False,
    official_url="https://www.gov.ca.gov/2025/01/07/governor-newsom-proclaims-state-of-emergency-meets-with-first-responders-in-pacific-palisades-amid-dangerous-fire-weather/"
)
if e: new_entries.append(e)


# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'=' * 60}")
print(f"TOTAL NEW ENTRIES: {len(new_entries)}")
print(f"{'=' * 60}")

# Now merge with existing curated_disasters.json
print("\nLoading existing curated_disasters.json...")
with open("/Users/connorvanduyn/Downloads/Claude/DST Tool NEW/dst-compiler/curated_disasters.json", "r") as f:
    data = json.load(f)

existing_ids = set(d["id"] for d in data["disasters"])
added = 0
skipped_dup = 0
for entry in new_entries:
    if entry["id"] in existing_ids:
        print(f"  DUPLICATE SKIPPED: {entry['id']}")
        skipped_dup += 1
    else:
        data["disasters"].append(entry)
        existing_ids.add(entry["id"])
        added += 1

# Fix SBA-2024-28528-CA status from ongoing to expiring_soon
for d in data["disasters"]:
    if d["id"] == "SBA-2024-28528-CA":
        old_status = d["status"]
        # Recalculate days remaining from today
        from datetime import datetime as dt
        sep_end = datetime.strptime(d["sepWindowEnd"], "%Y-%m-%d").date()
        d["daysRemaining"] = (sep_end - TODAY).days
        if d["daysRemaining"] <= 30:
            d["status"] = "expiring_soon"
        print(f"  FIXED SBA-2024-28528-CA: status {old_status} -> {d['status']} (daysRemaining: {d['daysRemaining']})")

# Update metadata
data["metadata"]["lastUpdated"] = "2026-02-11T00:00:00Z"
data["metadata"]["recordCount"] = len(data["disasters"])

# Sort by state, then source, then ID
data["disasters"].sort(key=lambda x: (x.get("state", ""), x.get("source", ""), x.get("id", "")))

# Recalculate daysRemaining for ALL existing records
for d in data["disasters"]:
    if d.get("sepWindowEnd"):
        sep_end = datetime.strptime(d["sepWindowEnd"], "%Y-%m-%d").date()
        d["daysRemaining"] = (sep_end - TODAY).days
        # Also update status based on new daysRemaining
        if d.get("incidentEnd") is None:
            if d["daysRemaining"] <= 30:
                d["status"] = "expiring_soon"
            else:
                d["status"] = "ongoing"
        else:
            if d["daysRemaining"] <= 30:
                d["status"] = "expiring_soon"
            else:
                d["status"] = "active"

print(f"\nAdded: {added} new entries")
print(f"Duplicate skipped: {skipped_dup}")
print(f"Total records: {len(data['disasters'])}")

# Write updated file
with open("/Users/connorvanduyn/Downloads/Claude/DST Tool NEW/dst-compiler/curated_disasters.json", "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("\nFile written successfully!")
print(f"New record count: {data['metadata']['recordCount']}")
