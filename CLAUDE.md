# CLAUDE.md — DST Compiler Tool

## Project Status
- **Version:** v3.0 — Carrier integration + verification framework + auto-monitoring
- **Last Session:** 2026-03-28
- **Live URL:** https://duynomite.github.io/dst-compiler/
- **Audit:** 3,775/3,775 + 4,948/4,948 (100%, zero failures)
- **Records:** 164 curated + 51 FEMA = 215 total
- **Next:** LA JML 26-006 (new declaration found by renewal checker). UI: extension timelines, expiring-soon badges.

## What This Is

DST compiler for Medicare Advantage agents. Collects every valid government-declared disaster that triggers a Medicare DST, shows them in a searchable interface, and lets agents copy declaration details into SunFire.

**Accuracy > features, always.** Wrong dates or missing declarations = compliance violations.

## Your Role

CTO. Before making changes:
1. Read this file + RUNBOOK.md for operational procedures
2. Run `python3 dst_verifier.py --staleness-only` to check system health
3. Check the CORRECTIONS table in `dst_data_fetcher.py` for the T1-T5 verification framework

## Critical Rules

1. **SEP Window = 2 calendar months after incidentEnd** (NOT 60 days). Jan 15 → Mar 31, not Mar 16.
2. **Ongoing disasters = 14-month max** from declaration date or latest renewal.
3. **Every incidentEnd must have T1-T5 evidence.** No estimates. No guesses. See RUNBOOK.md.
4. **Fire containment ≠ declaration termination.** Governor can keep declaration active for recovery.
5. **State auto-expire laws vary wildly.** KS=15d, IN/KY/MD=30d, FL=60d, NM/CA/NE=none. See STATE_EMERGENCY_DURATION in fetcher.
6. **AZ 120-day limit is PUBLIC HEALTH ONLY.** Natural disaster declarations have no limit.
7. **USDA drought is NOT a valid DST trigger.** Agricultural loan program, not disaster declaration.
8. **Agents ONLY use DSTs posted by government entities.** They don't discover or report DSTs.
9. **Two repos must stay in sync:** claude-projects (source) and dst-compiler (deploy).

## Tech Stack

- Frontend: Single HTML file, React 18, Tailwind v4, Babel (no build process)
- Pipeline: Python 3.11+ (requests, beautifulsoup4, pdfplumber, openpyxl)
- Hosting: GitHub Pages from `Duynomite/dst-compiler` repo
- CI: GitHub Actions (daily 6AM + weekly Monday 10AM)

## Automated Pipeline

```
DAILY:  dst_data_fetcher.py → rebuild JSON, apply corrections, carrier acks
WEEKLY: dst_renewal_checker.py → find renewals/terminations/new declarations
        dst_verifier.py → read every page, FEMA cross-ref, keyword scan
        audit_curated_data.py → 28 structural checks + eCFR monitoring
```

## File Map

| File | Purpose |
|------|---------|
| `index.html` | Agent-facing tool |
| `curated_disasters.json` | Non-FEMA data (164 records) |
| `all_disasters.json` | Curated + FEMA merged (215 records) |
| `dst_data_fetcher.py` | Main pipeline + CORRECTIONS table + STATE_EMERGENCY_DURATION |
| `dst_verifier.py` | Page content verification (3 layers) |
| `dst_renewal_checker.py` | Auto-detect renewals + new declarations (4 strategies) |
| `audit_curated_data.py` | Structural validation (28 checks) |
| `carrier_data_parser.py` | Parse carrier Excel files (Aetna/Wellcare) |
| `four_carrier_crossref.py` | Humana/Wellcare/Healthspring match data |
| `RUNBOOK.md` | How to operate: add records, fix URLs, deploy, troubleshoot |
| `CHANGELOG.md` | Session history, bug log, architectural decisions |

## Current Data State

- **46 verified incidentEnd corrections** (T1:6, T2:5, T3:22, T4:6, T5:7)
- **Carrier badges** on 91/164 records (Aetna 78, Wellcare 59, Humana 27)
- **33 ongoing STATE records** across 17 states
  - 14 with active renewal chains (TX×4, FL×3, LA, NY, HI, OR×2, AZ, NC)
  - 13 recent (<90 days)
  - 6 no-auto-expire monitors (CA×2, NE, NM×2, SD)
- **Staleness warnings:** 0 HIGH, 6 LOW (CA/NE/NM monitors)

## Known Issues

- 3 SSL-intermittent URLs (AR, MS, WA HHS) — government's cert problem, not our URLs
- Federal Register API returns inconsistent results in CI — per-source safeguard blocks data loss
- FL governor site blocks all bots (403) — URLs validated by structure only
- LA JML 26-006 (Jan 2026 winter weather) found by renewal checker but not yet added as STATE record

## SEP Window Formula

```python
# Python (dst_data_fetcher.py)
def calculate_sep_window_end(incident_end):
    month = incident_end.month + 2
    year = incident_end.year
    if month > 12: month -= 12; year += 1
    return date(year, month, calendar.monthrange(year, month)[1])

# JavaScript (index.html)
function calculateSEPWindowEnd(incidentEnd) {
    let m = incidentEnd.getMonth() + 2, y = incidentEnd.getFullYear();
    if (m > 11) { m -= 12; y += 1; }
    return new Date(y, m + 1, 0); // day 0 = last day of target month
}
```

Both implementations ignore the DAY — only use month and year. This prevents JS Date.setMonth() overflow bugs.

## Data Schema (Key Fields)

```json
{
  "id": "STATE-2026-001-FL",
  "source": "STATE",
  "state": "FL",
  "title": "Governor DeSantis EO 26-33 — Cold Front, Drought, Wildfires",
  "incidentType": "Wildfire",
  "declarationDate": "2026-02-09",
  "incidentStart": "2026-01-31",
  "incidentEnd": null,
  "renewalDates": ["2026-03-24"],
  "counties": ["Statewide"],
  "statewide": true,
  "officialUrl": "https://www.flgov.com/...",
  "status": "ongoing",
  "sepWindowStart": "2026-01-31",
  "sepWindowEnd": "2027-03-31",
  "carrierAcknowledgments": {"aetna": true, "wellcare": true, "humana": false, "healthspring": false},
  "endDateSource": "FL 60-day EO auto-expire from Feb 9; no extension found",
  "endDateConfidence": "T4"
}
```
