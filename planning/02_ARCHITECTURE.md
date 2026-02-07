# DST Compiler Tool — Architecture Overview

## System Overview

The DST Compiler Tool has two components that work independently:

1. **The Frontend** — A single HTML file that agents open in their browser. It displays disaster data and handles search/copy interactions. It fetches FEMA data live from the FEMA API every time it loads.

2. **The Data Fetcher** — A Python script that runs daily on GitHub Actions. It scrapes non-FEMA government sources (HHS, FMCSA, SBA, USDA, State), validates the data, and commits an updated JSON file to the GitHub repository.

These two components connect through a shared data file: the fetcher produces it, the frontend reads it.

```
┌─────────────────────────────────────────────────────────┐
│                    AGENT'S BROWSER                       │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │           DST Compiler Tool (HTML)               │   │
│  │                                                   │   │
│  │  ┌──────────┐    ┌────────────────────────────┐  │   │
│  │  │  Search   │    │    DST Results Display      │  │   │
│  │  │  State +  │───▶│  - Source badge             │  │   │
│  │  │  County   │    │  - Disaster name            │  │   │
│  │  └──────────┘    │  - SEP window dates          │  │   │
│  │                   │  - Official link             │  │   │
│  │                   │  - [Copy] button             │  │   │
│  │                   └────────────────────────────┘  │   │
│  │                                                   │   │
│  │  DATA SOURCES:                                    │   │
│  │  ┌─────────────┐  ┌──────────────────────────┐   │   │
│  │  │ FEMA API    │  │ curated_disasters.json    │   │   │
│  │  │ (live fetch │  │ (loaded from GitHub or    │   │   │
│  │  │  on load)   │  │  embedded in HTML)        │   │   │
│  │  └──────┬──────┘  └────────────┬─────────────┘   │   │
│  └─────────┼──────────────────────┼─────────────────┘   │
│            │                      │                       │
└────────────┼──────────────────────┼───────────────────────┘
             │                      │
             ▼                      ▼
    ┌────────────────┐    ┌──────────────────┐
    │  FEMA Open API │    │  GitHub Repo      │
    │  (free, public │    │                   │
    │   no auth)     │    │  Updated daily    │
    └────────────────┘    │  by GitHub Actions │
                          └────────┬──────────┘
                                   │
                          ┌────────┴──────────┐
                          │  Data Fetcher      │
                          │  (Python script)   │
                          │                    │
                          │  Scrapes:          │
                          │  - HHS PHE page    │
                          │  - FMCSA emergency │
                          │  - Federal Register│
                          │                    │
                          │  Curates:          │
                          │  - SBA disasters   │
                          │  - USDA drought    │
                          │  - State governors │
                          └────────────────────┘
```

## Component Details

### Frontend (HTML File)

**Technology:** Single HTML file containing React 18 (via CDN), Tailwind CSS (via CDN), and Babel Standalone (for JSX). No build process, no npm, no server.

**Why single file:** Simplest possible deployment. Can be opened directly from a file system, hosted on GitHub Pages, or embedded in WordPress. One file to version, one file to maintain.

**Data loading on page open:**
1. Fetch live FEMA data from `https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries`
2. Load `curated_disasters.json` (non-FEMA sources) — either embedded in the HTML or fetched from the same hosting location
3. Merge both datasets, deduplicate by ID, calculate SEP windows, filter out expired
4. Display results organized by state

**Key frontend logic:**
- **SEP window calculator:** Implements 42 CFR § 422.62 rules (2 calendar months after incident end, 14-month max for ongoing)
- **County matcher:** Matches search input against disaster-designated counties and statewide declarations
- **Status calculator:** Determines ONGOING / ACTIVE / EXPIRING SOON based on current date and window end
- **Copy formatter:** Generates SunFire-ready text for clipboard

### Data Fetcher (Python Script)

**Technology:** Python 3.11+, using `requests` for HTTP, `beautifulsoup4` for HTML parsing, standard library for everything else. Minimal dependencies.

**What it does on each run (in order):**

1. **FEMA API** — Fetches all disasters with active DST windows. Consolidates county-level records into disaster-level records. Used for validation/logging and as a backup if the live frontend fetch fails. FEMA records are NOT written to `curated_disasters.json` (the frontend fetches FEMA live).

2. **Federal Register API** — The primary automated collection method for SBA and USDA disasters. Queries the free public API at `federalregister.gov/api/v1/documents.json` for:
   - SBA disaster loan notices (agency: `small-business-administration`, term: `disaster loan`)
   - USDA secretarial designations (agency: `farm-service-agency`, term: `secretarial designation disaster`)
   - Parses each notice to extract affected states, counties, declaration dates
   - Uses the Federal Register document URL as the official declaration link
   - New discoveries that pass validation are added to the output automatically
   - Ambiguous results are logged for manual review

3. **HHS PHE** — Scrapes `https://aspr.hhs.gov/legal/PHE/Pages/default.aspx` for active public health emergencies. Falls back to curated data if scraping fails.

4. **FMCSA** — Scrapes `https://www.fmcsa.dot.gov/emergency-declarations` for active transportation emergencies and state governor declarations listed there. Only captures ~15-25% of governor declarations (transportation-related only).

5. **Curated data** — Reads manually maintained arrays for:
   - SBA disasters not captured by Federal Register query
   - USDA designations not captured by Federal Register query
   - State governor declarations not captured by FMCSA
   - These are updated by the maintainer (via Claude Code) when new declarations are discovered

6. **US Drought Monitor** — Checks for counties at D3/D4 drought severity as a discovery signal. Logs warnings when extreme drought counties don't have corresponding USDA designations.

7. **Validation** — Calculates SEP windows, filters expired disasters, checks official URLs (HEAD requests), validates data schema.

8. **Output** — Writes `curated_disasters.json` with all non-FEMA disasters that have active DST windows.

**What it does NOT do:**
- Write FEMA records to `curated_disasters.json` (frontend fetches FEMA live)
- Scrape 3,000+ county websites (impractical)
- Scrape 50 state governor websites individually (no centralized database exists; uses FMCSA as a partial aggregator)
- Run in the browser (CORS restrictions prevent this)

### Data Schema

Every disaster record (from any source) follows this structure:

```json
{
  "id": "FEMA-DR-4834-FL",
  "source": "FEMA",
  "state": "FL",
  "title": "Hurricane Helene",
  "incidentType": "Hurricane",
  "declarationDate": "2024-09-26",
  "incidentStart": "2024-09-23",
  "incidentEnd": null,
  "counties": ["Miami-Dade", "Broward", "Palm Beach"],
  "statewide": false,
  "officialUrl": "https://www.fema.gov/disaster/4834",
  "status": "ongoing",
  "sepWindowStart": "2024-09-23",
  "sepWindowEnd": null,
  "daysRemaining": null,
  "confidenceLevel": "verified",
  "lastUpdated": "2026-02-07T06:00:00Z"
}
```

**Field definitions:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (format: `SOURCE-ID-STATE`) |
| `source` | string | One of: FEMA, HHS, SBA, USDA, FMCSA, STATE |
| `state` | string | Two-letter state code |
| `title` | string | Human-readable disaster name |
| `incidentType` | string | Hurricane, Wildfire, Drought, Winter Storm, etc. |
| `declarationDate` | string | ISO date of official declaration |
| `incidentStart` | string | ISO date of incident beginning |
| `incidentEnd` | string/null | ISO date of incident end, or null if ongoing |
| `renewalDates` | array/null | List of ISO date strings for declaration renewals/extensions, or null |
| `counties` | array | List of affected county names, or ["Statewide"] |
| `statewide` | boolean | True if declaration covers entire state |
| `officialUrl` | string | URL to official government declaration |
| `status` | string | Calculated: ongoing, active, expiring_soon, expired (display as: ONGOING, ACTIVE, EXPIRING SOON, hidden) |
| `sepWindowStart` | string | Calculated start of SEP window |
| `sepWindowEnd` | string/null | Calculated end of SEP window, or null |
| `daysRemaining` | number/null | Days until SEP window closes, or null if ongoing |
| `confidenceLevel` | string | verified (API), scraped, curated |
| `lastUpdated` | string | ISO timestamp of last verification |

### SEP Window Calculation Logic

This is the most compliance-critical piece of the tool. Implemented identically in both the Python fetcher and the JavaScript frontend.

```
INPUTS:
  declarationDate  — date the disaster was officially declared
  incidentStart    — start date of the incident
  incidentEnd      — end date of the incident (null if ongoing)

CALCULATION:
  sepStart = min(declarationDate, incidentStart)

  IF incidentEnd is null:
    maxDate = latest of sepStart or any date in renewalDates array
    sepEnd = maxDate + 14 calendar months (last day of that month)
    status = "ongoing" (unless past 14-month max, then "expired")
    NOTE: Declaration renewals/extensions RESET the 14-month clock from the renewal date.

  IF incidentEnd exists:
    sepEnd = last day of the 2nd full calendar month after incidentEnd
    Example: incidentEnd = Jan 15 → sepEnd = March 31
    Example: incidentEnd = March 1 → sepEnd = May 31
    Example: incidentEnd = Nov 30 → sepEnd = January 31 (next year)

  IF sepEnd < today: status = "expired" (hide from display)
  IF sepEnd within 30 days: status = "expiring_soon"
  ELSE: status = "active"
```

**Critical: "2 full calendar months" means:**
1. Go to the month after the incident end month
2. Go forward 2 more months
3. Take the last day of that month

This is NOT "60 days from incident end." The difference can be up to 16 days.

### Data Sources Detail

| Source | Method | Automation Level | Refresh Rate | Coverage |
|--------|--------|-----------------|--------------|----------|
| **FEMA** | Live API from browser | Fully automated | Real-time (on page load) | 100% of FEMA disasters |
| **HHS PHE** | Web scrape + curated fallback | Semi-automated | Daily (GitHub Actions) | ~90% of active PHEs |
| **FMCSA** | Web scrape of emergency page | Semi-automated | Daily (GitHub Actions) | ~90% of FMCSA emergencies + ~15-25% of state governor declarations |
| **SBA** | Federal Register API + curated fallback | Mostly automated | Daily (GitHub Actions) | ~80-90% (Federal Register captures most formal declarations) |
| **USDA** | Federal Register API + Drought Monitor + curated fallback | Mostly automated | Daily (GitHub Actions) | ~70-85% (Federal Register + drought signal) |
| **State Governors** | FMCSA scrape + Federal Register cross-reference + curated | Semi-automated + manual | Daily (GitHub Actions) | ~15-25% initially, improving with curation |
| **Local** | Not included in MVP | N/A | N/A | 0% (future feature) |

### FEMA API Details

```
Base URL: https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries
Auth: None required (free, open access)
Rate limit: 1000 requests/day recommended
CORS: Enabled (works from browser)

Key query parameters:
  $filter    — OData filter (e.g., declarationDate ge '2024-01-01')
  $orderby   — Sort order (e.g., declarationDate desc)
  $top       — Page size (max 1000)
  $skip      — Pagination offset

Key response fields:
  femaDeclarationString  — e.g., "DR-4834-FL"
  declarationDate        — ISO date
  incidentBeginDate      — ISO date
  incidentEndDate        — ISO date or null
  designatedArea         — County name
  state                  — Two-letter code
  incidentType           — e.g., "Hurricane"
  declarationType        — DR, EM, or FM
  declarationTitle       — Human-readable title

Link pattern: https://www.fema.gov/disaster/{disasterNumber}
```

**Important FEMA behavior:** FEMA returns one record per county per disaster. A single hurricane affecting 50 counties = 50 API records. The tool must consolidate these into a single disaster with a list of affected counties.

### Deployment Architecture

**Phase 1 (MVP — what we're building):**
```
GitHub Repository
├── index.html              (the tool — agents open this)
├── curated_disasters.json  (non-FEMA data, updated by fetcher)
├── dst_data_fetcher.py     (Python script)
├── requirements.txt        (Python dependencies)
├── .github/
│   └── workflows/
│       └── update-data.yml (GitHub Actions schedule)
├── planning/               (these planning documents)
└── CLAUDE.md               (project instructions)
```

Agents access the tool via GitHub Pages (free static hosting from the repo) or by downloading the HTML file directly.

**Phase 2 (WordPress integration — later):**
The HTML file gets embedded in a page on clearpathcoverage.com/agents/ behind the login wall. The JSON data file is either embedded in the HTML or loaded from GitHub Pages.

### Link Verification Strategy

Every official URL is verified during each data fetcher run:
1. Send HTTP HEAD request to the URL
2. If 2xx or 3xx (redirect): URL is valid
3. If 4xx or 5xx: URL is broken — flag for review, use fallback generic URL
4. If timeout: Retry once, then flag

**Fallback URLs by source:**

| Source | Specific URL Pattern | Fallback (if specific breaks) |
|--------|---------------------|-------------------------------|
| FEMA | `https://www.fema.gov/disaster/{NUMBER}` | `https://www.fema.gov/disasters` |
| HHS | Varies | `https://aspr.hhs.gov/legal/PHE/Pages/default.aspx` |
| SBA | Varies | `https://www.sba.gov/funding-programs/disaster-assistance` |
| USDA | Varies | `https://www.fsa.usda.gov/resources/programs/disaster-assistance-programs` |
| FMCSA | `https://www.fmcsa.dot.gov/emergency-declarations/{SLUG}` | `https://www.fmcsa.dot.gov/emergency-declarations` |
| STATE | Varies widely | Source-specific, stored in curated data |

**Important:** Disasters with only a generic fallback URL should be flagged in the UI (e.g., "Declaration link: general source page") so agents know the link goes to an index page, not the specific declaration.

### Error Handling and Graceful Degradation

| Failure | Impact | Behavior |
|---------|--------|----------|
| FEMA API down | No live FEMA data | Show non-FEMA curated data only, display warning: "FEMA data unavailable — showing non-FEMA sources only. Refresh to retry." |
| GitHub Actions fails | Non-FEMA data goes stale | Tool still works with last good data, timestamp shows age |
| Individual scraper breaks | One source has stale data | Other sources unaffected, stale source shows last-good data |
| All data stale (>48 hours) | Risk of missing new disasters | Show warning banner: "Data may be outdated" |
| Broken official URL | Agent clicks dead link | Link excluded from display, flagged in fetcher logs |
