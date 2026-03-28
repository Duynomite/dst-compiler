#!/usr/bin/env python3
"""
Four-carrier cross-reference: Humana PDF + Wellcare page + Aetna Excel + Healthspring Excel
vs our all_disasters.json (226 records).

Identifies MISSING records, DATE_DISCREPANCY, and EXPIRED gaps.
Humana and Wellcare data manually cataloged from carrier documents (Mar 2026).
Aetna/Healthspring analysis already done in carrier_data_parser.py.
"""
import json
import re
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path
import calendar

def sep_end_for(incident_end_str):
    """Calculate SEP end per 42 CFR 422.62(b)(18)."""
    if not incident_end_str:
        return None
    if isinstance(incident_end_str, date):
        d = incident_end_str
    else:
        d = date.fromisoformat(str(incident_end_str)[:10])
    month = d.month + 2
    year = d.year
    if month > 12:
        month -= 12
        year += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)

# =========================================================================
# HUMANA DATA — Cataloged from March 1, 2026 PDF (22 pages)
# Status: "active" = green/orange in PDF, "expired" = red in PDF
# =========================================================================
HUMANA = [
    # --- EXPIRED (red in PDF) ---
    {"state": "AK", "title": "West Coast Storm", "type": "Severe Storm", "authority": "Governor", "incident_start": "2025-10-08", "incident_end": "2025-12-08", "sep_end": "2026-02-28", "counties": ["Bethel", "Kusilvak", "Nome", "North Slope", "Northwest Arctic"], "statewide": False, "status": "expired", "carrier": "humana"},
    {"state": "AK", "title": "Federal Government Shutdown", "type": "Other", "authority": "Governor", "incident_start": "2025-10-01", "incident_end": "2025-12-03", "sep_end": "2026-02-28", "counties": ["Statewide"], "statewide": True, "status": "expired", "carrier": "humana"},
    {"state": "FL", "title": "May North Florida Tornadoes EO 24-94", "type": "Tornado", "authority": "Governor", "incident_start": "2024-05-10", "incident_end": "2025-12-23", "sep_end": "2026-02-28", "counties": ["Baker", "Columbia", "Escambia", "Gadsden", "Hamilton", "Jefferson", "Lafayette", "Leon", "Liberty", "Madison", "Okaloosa", "Santa Rosa", "Suwannee", "Taylor", "Wakulla"], "statewide": False, "status": "expired", "carrier": "humana"},
    {"state": "FL", "title": "Lake County Flooding EO 25-213", "type": "Flood", "authority": "Governor", "incident_start": "2025-10-26", "incident_end": "2025-12-28", "sep_end": "2026-02-28", "counties": ["Lake"], "statewide": False, "status": "expired", "carrier": "humana"},
    {"state": "KY", "title": "Catastrophic Plane Crash EO 2025-758", "type": "Plane Crash", "authority": "Governor", "incident_start": "2025-11-05", "incident_end": "2025-12-05", "sep_end": "2026-02-28", "counties": ["Statewide"], "statewide": True, "status": "expired", "carrier": "humana"},
    {"state": "LA", "title": "Smitty's Supply Fire EO JML-25-141", "type": "Wildfire", "authority": "Governor", "incident_start": "2025-08-24", "incident_end": "2026-01-04", "sep_end": "2026-02-28", "counties": ["Tangipahoa"], "statewide": False, "status": "expired", "carrier": "humana"},
    {"state": "MO", "title": "Tornadoes and Flooding EO 25-19", "type": "Tornado", "authority": "Governor", "incident_start": "2025-03-14", "incident_end": "2025-12-31", "sep_end": "2026-02-28", "counties": ["Statewide"], "statewide": True, "status": "expired", "carrier": "humana"},
    {"state": "NJ", "title": "Winter Storm EO 406", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2025-12-02", "incident_end": "2025-12-02", "sep_end": "2026-02-28", "counties": ["Hunterdon", "Morris", "Passaic", "Sussex", "Warren"], "statewide": False, "status": "expired", "carrier": "humana"},
    {"state": "TX", "title": "Border Security", "type": "Other", "authority": "Governor", "incident_start": "2022-05-31", "incident_end": "2025-12-18", "sep_end": "2026-02-28", "counties": ["Multiple"], "statewide": False, "status": "expired", "carrier": "humana"},
    {"state": "TX", "title": "Drought", "type": "Drought", "authority": "Governor", "incident_start": "2022-07-08", "incident_end": "2025-12-18", "sep_end": "2026-02-28", "counties": ["Multiple"], "statewide": False, "status": "expired", "carrier": "humana"},
    {"state": "TX", "title": "Heavy Rainfall and Flooding", "type": "Flood", "authority": "Governor", "incident_start": "2025-07-02", "incident_end": "2025-12-18", "sep_end": "2026-02-28", "counties": ["Multiple"], "statewide": False, "status": "expired", "carrier": "humana"},
    {"state": "TX", "title": "Increased Fire Weather Conditions", "type": "Wildfire", "authority": "Governor", "incident_start": "2025-08-10", "incident_end": "2025-12-09", "sep_end": "2026-02-28", "counties": ["Multiple"], "statewide": False, "status": "expired", "carrier": "humana"},
    {"state": "WA", "title": "Olympic Pipeline Shutdown EO 25-06", "type": "Infrastructure Emergency", "authority": "Governor", "incident_start": "2025-11-11", "incident_end": "2025-12-19", "sep_end": "2026-02-28", "counties": ["Statewide"], "statewide": True, "status": "expired", "carrier": "humana"},
    {"state": "WA", "title": "Atmospheric River EO 25-07", "type": "Severe Storm", "authority": "Governor", "incident_start": "2025-12-02", "incident_end": "2025-12-24", "sep_end": "2026-02-28", "counties": ["Statewide"], "statewide": True, "status": "expired", "carrier": "humana"},

    # --- ACTIVE (green/orange in PDF) ---
    {"state": "AL", "title": "Severe Weather", "type": "Severe Storm", "authority": "Governor", "incident_start": "2026-01-23", "incident_end": "2026-03-24", "sep_end": "2026-05-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "AR", "title": "Winter Storm EO 2026-03", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-23", "incident_end": "2026-02-22", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "CA", "title": "Canyon Fire FM-5605", "type": "Wildfire", "authority": "FEMA", "incident_start": "2025-08-07", "incident_end": "2026-08-08", "sep_end": "2026-10-31", "counties": ["Los Angeles"], "statewide": False, "status": "active", "carrier": "humana"},
    {"state": "CA", "title": "Pack County Fire Mono CAG4600001", "type": "Wildfire", "authority": "Governor", "incident_start": "2025-11-13", "incident_end": "2025-02-07", "sep_end": "2026-04-30", "counties": ["Mono"], "statewide": False, "status": "active", "carrier": "humana", "eo": "CAG4600001", "declaration_date": "2025-12-09"},
    {"state": "CA", "title": "Tsunami Risk CAG4601401", "type": "Severe Storm", "authority": "Governor", "incident_start": "2025-07-29", "incident_end": "2026-02-21", "sep_end": "2026-04-30", "counties": ["Del Norte"], "statewide": False, "status": "active", "carrier": "humana", "eo": "CAG4601401", "declaration_date": "2025-12-23"},
    {"state": "CA", "title": "August Storms and Mudslides CAG4601401", "type": "Severe Storm", "authority": "Governor", "incident_start": "2025-08-23", "incident_end": "2026-02-21", "sep_end": "2026-04-30", "counties": ["Sierra"], "statewide": False, "status": "active", "carrier": "humana", "eo": "CAG4601401", "declaration_date": "2025-12-23"},
    {"state": "CA", "title": "August Monsoons CAG4601401", "type": "Severe Storm", "authority": "Governor", "incident_start": "2025-08-24", "incident_end": "2026-02-21", "sep_end": "2026-04-30", "counties": ["Imperial"], "statewide": False, "status": "active", "carrier": "humana", "eo": "CAG4601401", "declaration_date": "2025-12-23"},
    {"state": "CA", "title": "Gifford Fire CAG4601401", "type": "Wildfire", "authority": "Governor", "incident_start": "2025-08-01", "incident_end": "2026-02-21", "sep_end": "2026-04-30", "counties": ["San Luis Obispo", "Santa Barbara"], "statewide": False, "status": "active", "carrier": "humana", "eo": "CAG4601401", "declaration_date": "2025-12-23"},
    {"state": "CA", "title": "January Windstorm CAG4601401", "type": "Severe Storm", "authority": "Governor", "incident_start": "2025-01-07", "incident_end": "2026-02-21", "sep_end": "2026-04-30", "counties": ["San Bernardino"], "statewide": False, "status": "active", "carrier": "humana", "eo": "CAG4601401", "declaration_date": "2025-12-23"},
    {"state": "CA", "title": "Late December Storms CAG4601501", "type": "Severe Storm", "authority": "Governor", "incident_start": "2025-12-23", "incident_end": "2026-02-22", "sep_end": "2026-04-30", "counties": ["Los Angeles", "Orange", "Riverside", "San Bernardino", "San Diego", "Shasta"], "statewide": False, "status": "active", "carrier": "humana", "eo": "CAG4601501", "declaration_date": "2025-12-24"},
    {"state": "DE", "title": "Winter Storm", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-25", "incident_end": "2026-02-24", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "DC", "title": "Winter Storm MO2026-005", "type": "Severe Winter Storm", "authority": "Mayor", "incident_start": "2026-01-24", "incident_end": "2026-02-11", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "FL", "title": "Hurricane Debby EO chain", "type": "Hurricane", "authority": "Governor", "incident_start": "2024-08-01", "incident_end": "2026-01-06", "sep_end": "2026-03-31", "counties": ["Multiple"], "statewide": False, "status": "active", "carrier": "humana"},
    {"state": "FL", "title": "Hurricane Helene EO chain", "type": "Hurricane", "authority": "Governor", "incident_start": "2024-09-23", "incident_end": "2026-01-06", "sep_end": "2026-03-31", "counties": ["Multiple"], "statewide": False, "status": "active", "carrier": "humana"},
    {"state": "FL", "title": "Hurricane Milton EO chain", "type": "Hurricane", "authority": "Governor", "incident_start": "2024-10-05", "incident_end": "2026-01-24", "sep_end": "2026-03-31", "counties": ["Multiple"], "statewide": False, "status": "active", "carrier": "humana"},
    {"state": "FL", "title": "NW Florida May Tornadoes EO 25-101", "type": "Tornado", "authority": "Governor", "incident_start": "2025-05-10", "incident_end": "2026-01-06", "sep_end": "2026-03-31", "counties": ["Holmes"], "statewide": False, "status": "active", "carrier": "humana"},
    {"state": "FL", "title": "Winter Weather EO 26-33", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-31", "incident_end": "2026-04-10", "sep_end": "2026-06-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana", "declaration_date": "2026-02-09"},
    {"state": "GA", "title": "Winter Weather", "type": "Severe Storm", "authority": "Governor", "incident_start": "2026-01-23", "incident_end": "2026-01-29", "sep_end": "2026-03-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "HI", "title": "Wildfires 27th Proclamation", "type": "Wildfire", "authority": "Governor", "incident_start": "2023-11-06", "incident_end": "2026-01-06", "sep_end": "2026-03-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "HI", "title": "Severe Weather Event", "type": "Severe Storm", "authority": "Governor", "incident_start": "2026-02-07", "incident_end": "2026-02-11", "sep_end": "2026-03-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "IN", "title": "Winter Storm EO 26-03", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-23", "incident_end": "2026-03-22", "sep_end": "2026-05-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "KY", "title": "Severe Winter Storm E2026-047", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-24", "incident_end": "2026-02-23", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "LA", "title": "Winter Weather", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-22", "incident_end": "2026-02-22", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "MD", "title": "Winter Storm EO 01.01.2026.02", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-24", "incident_end": "2026-02-23", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "MD", "title": "Winter Storm EO 01.01.2026.05", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-02-22", "incident_end": "2026-02-23", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana", "declaration_date": "2026-02-22"},
    {"state": "MA", "title": "Severe Winter Storm Feb 2026", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-02-22", "incident_end": "2026-03-24", "sep_end": "2026-05-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "MS", "title": "Winter Storms", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-23", "incident_end": "2026-01-27", "sep_end": "2026-03-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "MO", "title": "Winter Storm EO-26-05", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-22", "incident_end": "2026-02-22", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "MT", "title": "Statewide Flooding EO 09-2025", "type": "Flood", "authority": "Governor", "incident_start": "2025-12-08", "incident_end": "2026-06-06", "sep_end": "2026-08-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana", "declaration_date": "2025-12-08"},
    {"state": "MT", "title": "Severe Weather EO 11-2025", "type": "Severe Storm", "authority": "Governor", "incident_start": "2025-12-17", "incident_end": "2026-01-31", "sep_end": "2026-03-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "NJ", "title": "Severe Winter Storm EO 409", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2025-12-26", "incident_end": "2026-06-24", "sep_end": "2026-08-31", "counties": ["Multiple"], "statewide": False, "status": "active", "carrier": "humana", "declaration_date": "2025-12-26"},
    {"state": "NJ", "title": "Severe Winter Storm EO 8", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-24", "incident_end": "2026-01-26", "sep_end": "2026-03-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "NJ", "title": "Severe Winter Storm EO 14", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-02-22", "incident_end": "2026-08-21", "sep_end": "2026-10-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana", "declaration_date": "2026-02-21"},
    {"state": "NM", "title": "Winter Storm E2026-005", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-23", "incident_end": None, "sep_end": None, "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "NM", "title": "Flooding EO 2025-286", "type": "Flood", "authority": "Governor", "incident_start": "2025-06-22", "incident_end": None, "sep_end": "2026-09-30", "counties": ["Chaves", "Lincoln", "Otero", "Valencia"], "statewide": False, "status": "active", "carrier": "humana"},
    {"state": "NM", "title": "Flooding EO 2025-333", "type": "Flood", "authority": "Governor", "incident_start": "2025-07-22", "incident_end": None, "sep_end": "2026-09-30", "counties": ["Dona Ana"], "statewide": False, "status": "active", "carrier": "humana", "declaration_date": "2025-07-25"},
    {"state": "NM", "title": "Crime EO 2025-358/366", "type": "Other", "authority": "Governor", "incident_start": "2025-08-12", "incident_end": None, "sep_end": "2026-11-30", "counties": ["Jicarilla Apache Reservation", "Pueblos of Pojoaque", "Ohkay Owingeh", "Santa Clara", "San Ildefonso", "Tesque", "Rio Arriba", "Santa Fe"], "statewide": False, "status": "active", "carrier": "humana"},
    {"state": "NM", "title": "Flooding EO 2025-362", "type": "Flood", "authority": "Governor", "incident_start": "2025-08-27", "incident_end": None, "sep_end": "2026-10-31", "counties": ["Mora"], "statewide": False, "status": "active", "carrier": "humana", "declaration_date": "2025-08-29"},
    {"state": "NM", "title": "Crime in Albuquerque EO 2025-080/368", "type": "Other", "authority": "Governor", "incident_start": "2025-04-07", "incident_end": None, "sep_end": "2026-11-30", "counties": ["Bernalillo"], "statewide": False, "status": "active", "carrier": "humana"},
    {"state": "NY", "title": "Winter Storm EO 55", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2025-12-26", "incident_end": "2026-01-25", "sep_end": "2026-03-31", "counties": ["Multiple"], "statewide": False, "status": "active", "carrier": "humana", "declaration_date": "2025-12-26"},
    {"state": "NY", "title": "Healthcare Staff Shortage EO 56.1", "type": "Other", "authority": "Governor", "incident_start": "2026-01-09", "incident_end": "2026-01-26", "sep_end": "2026-03-31", "counties": ["Bronx", "Nassau", "New York"], "statewide": False, "status": "active", "carrier": "humana", "declaration_date": "2026-01-09"},
    {"state": "NY", "title": "Winter Storm EO 57", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-23", "incident_end": "2026-02-22", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana", "declaration_date": "2026-01-23"},
    {"state": "NY", "title": "Winter Storm EO 58", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-02-22", "incident_end": "2026-03-24", "sep_end": "2026-05-31", "counties": ["Albany", "Bronx", "Columbia", "Delaware", "Dutchess", "Greene", "Kings", "Nassau", "New York", "Orange", "Otsego", "Putnam", "Queens", "Richmond", "Rensselaer", "Rockland", "Schoharie", "Schenectady", "Suffolk", "Sullivan", "Ulster", "Westchester"], "statewide": False, "status": "active", "carrier": "humana", "declaration_date": "2026-02-21"},
    {"state": "NC", "title": "Winter Storm EO 31", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-24", "incident_end": "2026-02-23", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "OH", "title": "Winter Storm", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-24", "incident_end": "2026-04-26", "sep_end": "2026-06-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "OR", "title": "Rowena Fire EO 25-06", "type": "Wildfire", "authority": "Governor", "incident_start": "2025-06-11", "incident_end": "2026-06-12", "sep_end": "2026-08-31", "counties": ["Wasco"], "statewide": False, "status": "active", "carrier": "humana"},
    {"state": "OR", "title": "Alder Springs Fire EO 25-07", "type": "Wildfire", "authority": "Governor", "incident_start": "2025-06-16", "incident_end": "2026-06-17", "sep_end": "2026-08-31", "counties": ["Deschutes", "Jefferson"], "statewide": False, "status": "active", "carrier": "humana"},
    {"state": "OR", "title": "Rowena Wildfire EO 25-28", "type": "Wildfire", "authority": "Governor", "incident_start": "2025-06-18", "incident_end": "2026-10-21", "sep_end": "2026-12-31", "counties": ["Wasco"], "statewide": False, "status": "active", "carrier": "humana", "declaration_date": "2025-10-31"},
    {"state": "PA", "title": "Winter Storm Jan 2026", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-23", "incident_end": "2026-02-13", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "PA", "title": "Complex Winter Storm Feb 2026", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-02-22", "incident_end": "2026-03-15", "sep_end": "2026-05-31", "counties": ["Multiple (40+)"], "statewide": False, "status": "active", "carrier": "humana", "declaration_date": "2026-02-22"},
    {"state": "PR", "title": "Landslides OE 2024-004", "type": "Landslide", "authority": "Governor", "incident_start": "2025-01-02", "incident_end": "2026-01-02", "sep_end": "2026-03-31", "counties": ["Entire Territory"], "statewide": True, "status": "active", "carrier": "humana", "declaration_date": "2025-01-02"},
    {"state": "PR", "title": "Severe Weather OE 2025-022 (May)", "type": "Severe Storm", "authority": "Governor", "incident_start": "2025-04-19", "incident_end": "2026-05-01", "sep_end": "2026-07-31", "counties": ["Aguas Buenas", "Corozal", "Naranjito", "Orocovis"], "statewide": False, "status": "active", "carrier": "humana", "declaration_date": "2025-05-01"},
    {"state": "PR", "title": "Severe Weather OE 2025-022 (Jul)", "type": "Severe Storm", "authority": "Governor", "incident_start": "2025-07-30", "incident_end": "2026-07-30", "sep_end": "2026-09-30", "counties": ["Entire Territory"], "statewide": True, "status": "active", "carrier": "humana", "declaration_date": "2025-07-30"},
    {"state": "RI", "title": "Blizzard EO 26-02", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-02-22", "incident_end": "2026-03-24", "sep_end": "2026-05-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "SC", "title": "Winter Storm EO 2026-02", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-24", "incident_end": "2026-02-08", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "TN", "title": "Winter Storms EO-110", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-23", "incident_end": "2026-02-05", "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "TX", "title": "Severe Winter Storm Jan 2026", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-22", "incident_end": "2026-02-21", "sep_end": "2026-04-30", "counties": ["Multiple (219+)"], "statewide": False, "status": "active", "carrier": "humana"},
    {"state": "VA", "title": "Winter Storm EO 11", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-22", "incident_end": None, "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "WV", "title": "Winter Storm", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-22", "incident_end": None, "sep_end": "2026-04-30", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "WI", "title": "Flooding and Severe Weather EO 272", "type": "Flood", "authority": "Governor", "incident_start": "2025-08-09", "incident_end": "2026-10-10", "sep_end": "2026-12-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana", "declaration_date": "2025-08-11"},
    {"state": "WY", "title": "Ranch Fires EO 2025-05", "type": "Wildfire", "authority": "Governor", "incident_start": "2025-08-13", "incident_end": "2026-08-17", "sep_end": "2026-10-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana"},
    {"state": "WY", "title": "Federal Government Shutdown EO 2025-08", "type": "Other", "authority": "Governor", "incident_start": "2025-10-31", "incident_end": "2026-10-31", "sep_end": "2026-12-31", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "humana", "declaration_date": "2025-10-31"},
]

# =========================================================================
# WELLCARE DATA — Scraped from live page (Mar 27, 2026)
# =========================================================================
WELLCARE = [
    {"state": "AR", "title": "FEMA EM-3636 Severe Winter Storm", "type": "Severe Winter Storm", "authority": "FEMA", "incident_start": "2026-01-23", "incident_end": None, "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "CA", "title": "Forest Management / Wildfire Prevention", "type": "Wildfire", "authority": "Governor", "incident_start": "2025-03-01", "incident_end": None, "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "CA", "title": "January 2025 Fires & Windstorm", "type": "Wildfire", "authority": "Governor", "incident_start": "2025-01-07", "incident_end": None, "counties": ["Los Angeles", "Ventura"], "statewide": False, "status": "active", "carrier": "wellcare"},
    {"state": "CA", "title": "Board Resolution for Emergency", "type": "Other", "authority": "Local", "incident_start": "2025-10-07", "incident_end": None, "counties": ["Los Angeles"], "statewide": False, "status": "active", "carrier": "wellcare"},
    {"state": "CT", "title": "February 2026 Nor'easter", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-02-22", "incident_end": None, "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "DE", "title": "Winter Storm Fern", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-24", "incident_end": "2026-01-26", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "DE", "title": "February 2026 Nor'easter", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-02-22", "incident_end": "2026-02-24", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "FL", "title": "EO 26-33 Winter Weather", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-31", "incident_end": "2026-02-03", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "FL", "title": "Hurricane Milton Extension", "type": "Hurricane", "authority": "Governor", "incident_start": "2024-10-05", "incident_end": "2026-03-24", "counties": ["Multiple (50)"], "statewide": False, "status": "active", "carrier": "wellcare"},
    {"state": "FL", "title": "Hurricane Debby Extension EO 26-03", "type": "Hurricane", "authority": "Governor", "incident_start": "2024-08-01", "incident_end": "2026-03-06", "counties": ["Multiple (34)"], "statewide": False, "status": "active", "carrier": "wellcare"},
    {"state": "MA", "title": "February 2026 Nor'easter", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-02-22", "incident_end": None, "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "MS", "title": "FEMA DR-4899 Severe Winter Storm", "type": "Severe Winter Storm", "authority": "FEMA", "incident_start": "2026-01-23", "incident_end": "2026-01-27", "counties": ["Multiple"], "statewide": False, "status": "active", "carrier": "wellcare"},
    {"state": "NJ", "title": "Winter Storm EO 8", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-24", "incident_end": "2026-01-26", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "NJ", "title": "Severe Storm Jul 2025", "type": "Severe Storm", "authority": "Governor", "incident_start": "2025-07-14", "incident_end": None, "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "NJ", "title": "February 2026 Nor'easter EO 14", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-02-22", "incident_end": None, "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "NY", "title": "Healthcare Staffing EO 56", "type": "Other", "authority": "Governor", "incident_start": "2026-01-09", "incident_end": "2026-02-08", "counties": ["Bronx", "Nassau", "New York"], "statewide": False, "status": "active", "carrier": "wellcare"},
    {"state": "NY", "title": "Winter Storm EO 57", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-23", "incident_end": "2026-02-22", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "NY", "title": "February 2026 Nor'easter EO 58", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-02-22", "incident_end": "2026-03-24", "counties": ["Multiple (23+)"], "statewide": False, "status": "active", "carrier": "wellcare"},
    {"state": "OH", "title": "January 2026 Winter Storm", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-24", "incident_end": "2026-04-24", "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "OR", "title": "Homelessness Extension", "type": "Other", "authority": "Governor", "incident_start": "2023-01-10", "incident_end": "2027-01-10", "counties": ["Multiple metro regions"], "statewide": False, "status": "active", "carrier": "wellcare"},
    {"state": "TN", "title": "FEMA DR-4898 Severe Winter Storm", "type": "Severe Winter Storm", "authority": "FEMA", "incident_start": "2026-01-22", "incident_end": "2026-01-27", "counties": ["Multiple (15)"], "statewide": False, "status": "active", "carrier": "wellcare"},
    {"state": "TN", "title": "FEMA EM Severe Storms Apr 2025", "type": "Severe Storm", "authority": "FEMA", "incident_start": "2025-04-02", "incident_end": None, "counties": ["Statewide"], "statewide": True, "status": "active", "carrier": "wellcare"},
    {"state": "TX", "title": "Winter Storm Jan 2026", "type": "Severe Winter Storm", "authority": "Governor", "incident_start": "2026-01-21", "incident_end": None, "counties": ["Multiple (219)"], "statewide": False, "status": "active", "carrier": "wellcare"},
    {"state": "WA", "title": "FEMA EM Severe Storms Dec 2025", "type": "Severe Storm", "authority": "FEMA", "incident_start": "2025-12-12", "incident_end": None, "counties": ["Multiple (16+)"], "statewide": False, "status": "active", "carrier": "wellcare"},
]


def normalize_title(title):
    """Normalize for matching."""
    t = title.upper().strip()
    t = re.sub(r'\bEO\s*\d+[-.]?\d*\b', '', t)
    t = re.sub(r'\bCAG\d+\b', '', t)
    t = re.sub(r'\bFM[-]?\d+\b', '', t)
    t = re.sub(r'\bEM[-]?\d+\b', '', t)
    t = re.sub(r'\bDR[-]?\d+\b', '', t)
    t = re.sub(r'\bOE\s*\d+[-]?\d*\b', '', t)
    t = re.sub(r'\bFEMA\b', '', t)
    t = re.sub(r'\(.*?\)', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def match_carrier_to_ours(carrier_rec, our_records_by_state):
    """Try to match a carrier record to our records."""
    state = carrier_rec["state"]
    our_recs = our_records_by_state.get(state, [])
    carrier_norm = normalize_title(carrier_rec["title"])

    best_match = None
    best_score = 0.0

    for our_rec in our_recs:
        our_norm = normalize_title(our_rec.get("title", ""))
        # Name similarity
        sim = SequenceMatcher(None, carrier_norm, our_norm).ratio()
        # Word overlap
        c_words = set(carrier_norm.split()) - {"", "THE", "OF", "AND", "IN", "STATE", "EMERGENCY", "DECLARATION", "GOVERNOR"}
        o_words = set(our_norm.split()) - {"", "THE", "OF", "AND", "IN", "STATE", "EMERGENCY", "DECLARATION", "GOVERNOR"}
        if c_words and o_words:
            overlap = len(c_words & o_words) / max(len(c_words), len(o_words))
            sim = max(sim, overlap)

        if sim > best_score:
            best_score = sim
            best_match = our_rec

    return best_match, best_score


def main():
    base = Path(__file__).parent
    with open(base / "all_disasters.json") as f:
        our_data = json.load(f)

    our_records = our_data["disasters"]
    by_state = {}
    for r in our_records:
        st = r.get("state", "")
        by_state.setdefault(st, []).append(r)

    today = date.today()
    all_carrier = HUMANA + WELLCARE
    # Deduplicate carrier records by state+normalized title
    seen = set()
    unique_carrier = []
    for c in all_carrier:
        key = (c["state"], normalize_title(c["title"]))
        if key not in seen:
            seen.add(key)
            unique_carrier.append(c)

    matched = []
    missing = []
    expired_ours = []

    for c in unique_carrier:
        # Skip expired per carrier
        if c.get("status") == "expired":
            continue

        best, score = match_carrier_to_ours(c, by_state)

        if score >= 0.55:
            matched.append({"carrier": c, "our_record": best["id"], "our_title": best["title"], "score": round(score, 2)})
        else:
            # Check if it's expired per our SEP calculation
            ie = c.get("incident_end")
            if ie:
                try:
                    calc_end = sep_end_for(ie)
                    if calc_end and calc_end < today:
                        expired_ours.append({"carrier": c, "our_sep_end": str(calc_end), "reason": "Expired per 2-month calc"})
                        continue
                except:
                    pass
            missing.append({"carrier": c, "best_candidate": best["id"] if best else None, "best_title": best["title"] if best else None, "best_score": round(score, 2)})

    # Print report
    print("=" * 80)
    print("FOUR-CARRIER CROSS-REFERENCE REPORT")
    print(f"Date: {today}")
    print(f"Our records: {len(our_records)}")
    print(f"Carrier records (unique, active): {sum(1 for c in unique_carrier if c.get('status') != 'expired')}")
    print("=" * 80)

    print(f"\nMATCHED: {len(matched)}")
    print(f"MISSING (need to add): {len(missing)}")
    print(f"EXPIRED per our calc: {len(expired_ours)}")

    if missing:
        print(f"\n{'─' * 80}")
        print("MISSING — Carrier has it, we don't")
        print(f"{'─' * 80}")
        for m in sorted(missing, key=lambda x: x["carrier"]["state"]):
            c = m["carrier"]
            print(f"\n  [{c['state']}] {c['title']}")
            print(f"    Type: {c['type']} | Authority: {c['authority']} | Carrier: {c['carrier']}")
            print(f"    Incident: {c.get('incident_start', '?')} → {c.get('incident_end', 'ongoing')}")
            print(f"    SEP End: {c.get('sep_end', '?')}")
            print(f"    Counties: {', '.join(c.get('counties', [])[:5])}{'...' if len(c.get('counties', [])) > 5 else ''}")
            if m["best_candidate"]:
                print(f"    Closest match: {m['best_candidate']}: {m['best_title']} (score: {m['best_score']})")

    if expired_ours:
        print(f"\n{'─' * 80}")
        print("EXPIRED per our 2-month calculation (carrier tracks longer)")
        print(f"{'─' * 80}")
        for e in expired_ours:
            c = e["carrier"]
            print(f"  [{c['state']}] {c['title']} — our SEP ended {e['our_sep_end']}")

    # Save results
    results = {
        "run_date": str(today),
        "our_record_count": len(our_records),
        "carrier_active_count": sum(1 for c in unique_carrier if c.get("status") != "expired"),
        "matched": len(matched),
        "missing": len(missing),
        "expired_per_our_calc": len(expired_ours),
        "missing_details": [
            {
                "state": m["carrier"]["state"],
                "title": m["carrier"]["title"],
                "type": m["carrier"]["type"],
                "authority": m["carrier"]["authority"],
                "carrier": m["carrier"]["carrier"],
                "incident_start": m["carrier"].get("incident_start"),
                "incident_end": m["carrier"].get("incident_end"),
                "sep_end": m["carrier"].get("sep_end"),
                "eo": m["carrier"].get("eo", ""),
                "declaration_date": m["carrier"].get("declaration_date", ""),
                "counties": m["carrier"].get("counties", []),
                "statewide": m["carrier"].get("statewide", False),
            }
            for m in missing
        ],
    }
    with open(base / "four_carrier_analysis.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n\nResults saved to four_carrier_analysis.json")


if __name__ == "__main__":
    main()
