# DST Compiler Tool — Product Requirements Document (PRD)

## Problem Statement

Medicare telesales agents at Clear Path Coverage have no reliable way to identify valid Disaster Special Enrollment Periods (DSTs) during customer calls. Agents currently search manually across scattered government websites, miss valid disasters, and lack confidence in what they find. An estimated 80% of valid DST opportunities go unused — not because customers don't qualify, but because agents can't find the declarations.

This is a revenue problem and a service problem. Every missed DST is a missed enrollment opportunity for the customer and a missed sale for the agency.

## Context

Under 42 CFR § 422.62(a)(6), Medicare beneficiaries affected by a government-declared disaster may enroll in, switch, or disenroll from Medicare Advantage plans outside normal enrollment windows. The regulation defines valid DST triggers broadly: any emergency or disaster declared by a "Federal, State, or local government entity."

Valid federal sources include FEMA, HHS, SBA, USDA, and FMCSA — but most of the industry only tracks FEMA. State governor declarations and local government declarations also qualify. Comprehensive coverage across all these sources is a competitive advantage.

The DST Compiler Tool will be the single source of truth for all active disaster declarations that trigger Medicare SEPs.

### Regulatory Context

- **MA/Part D DST window (§ 422.62):** 2 full calendar months after the declared incident end date. Maximum 14 calendar months from SEP start if no end date is defined.
- **Three-part validation required:** (1) Residence in disaster area, (2) Was eligible for another EP during the disaster, (3) Missed enrollment due to the disaster.
- **Verbal attestation is sufficient** — no signature required.
- **CMS March 2025 memo:** Agents may continue processing DST enrollments. CMS withdrew December 2024 restrictions.

## Users

**Primary users:** ~50 telesales Medicare insurance agents at Clear Path Coverage.

- Non-technical users on live phone calls with customers
- Need answers in under 10 seconds
- Will copy/paste DST details into SunFire enrollment platform
- Know the customer's county and state (and usually ZIP)
- Do not need to understand data sources or regulatory details — the tool handles that

**Secondary user:** Connor Van Duyn (agency owner), who will maintain and update the tool.

- Non-technical but comfortable running simple commands
- Will use Claude Code for maintenance and fixes
- Needs clear documentation for any manual processes

## Goals

1. **Accuracy:** Every DST displayed is verified, valid, and currently active. No expired or invalid DSTs shown.
2. **Completeness:** Capture 100% of federal disaster declarations (FEMA, HHS, SBA, USDA, FMCSA) and governor-level state declarations.
3. **Speed:** Agent finds all active DSTs for a customer's county in under 10 seconds.
4. **Compliance:** Correct SEP window dates per 42 CFR § 422.62. Working links to official declarations. Three-part validation reminder visible.
5. **Copy-ready output:** One-click copy of DST details formatted for SunFire enrollment notes.
6. **Low maintenance:** Automated daily data updates via GitHub Actions. No manual data curation required for federal sources.

### How We Measure Success

- Agent can search any US county and see all active DSTs in under 10 seconds
- 100% of displayed DSTs have working links to official declarations
- SEP window dates match the regulatory calculation (2 calendar months after incident end, 14-month max)
- FEMA data is no more than 30 minutes stale (live API)
- Non-FEMA data is no more than 24 hours stale (daily GitHub Actions update)

## Features (MVP)

### 1. County + State Search
Agent selects a state and types/selects a county. Tool instantly shows all active DSTs for that county, plus any statewide declarations for that state.

**Why it matters:** This is the core interaction. County is the most accurate match against how disasters are actually declared (FEMA designates by county, governor declarations are statewide).

### 2. DST Listings with Sorting Options
All active DSTs displayed in a clean, scannable list. Each listing shows:
- Source badge (FEMA, HHS, SBA, USDA, FMCSA, STATE)
- Disaster name and type
- Declaration number/ID
- SEP window start and end dates (or "Ongoing")
- Days remaining in SEP window
- Status indicator (ONGOING, ACTIVE, EXPIRING SOON)
- "Statewide" badge for declarations covering the entire state

**Sort options:**
- By State (A-Z) — default
- Most Recent First — by declaration date descending
- Ending Soonest — by SEP window end date ascending (ongoing disasters last)

**Why it matters:** Agents need to scan quickly and understand what's available at a glance. Different sort options help agents find what they need depending on context — browsing all DSTs, checking for new ones, or finding time-sensitive windows.

### 3. Official Declaration Links
Every DST has a clickable link to the official government declaration page. Links are verified during each data update. Broken links are flagged and excluded from display.

**Why it matters:** Compliance requires documentation. A broken link destroys agent confidence and creates compliance risk.

### 4. Copy Button for SunFire
One-click copy that puts formatted DST details on the clipboard:

```
DST — [Disaster Name] ([Source] [Declaration Number])
SEP Window: [Start Date] — [End Date or "Ongoing"]
Official Declaration: [URL]
```

**Why it matters:** Agents paste this directly into SunFire enrollment notes. The format must be clean, consistent, and include everything needed for the enrollment record.

### 5. Correct SEP Window Calculation
Per 42 CFR § 422.62(a)(6):
- **SEP Start:** Earlier of declaration date or incident start date
- **SEP End:** Last day of the 2nd full calendar month after the incident end date
- **Ongoing:** No end date, but subject to 14-month maximum from SEP start
- **Maximum:** 14 full calendar months from SEP start date (or from renewal/extension date)

**Why it matters:** "2 full calendar months" is NOT "60 days." Getting this wrong is a compliance violation. Example: incident ends Jan 15 → SEP ends March 31, not March 16.

### 6. Live FEMA API Integration
FEMA data fetched in real-time from the browser when the tool loads. No staleness for the largest disaster source.

**Why it matters:** FEMA is ~60-70% of all disasters agents encounter. Live data means agents always see current information.

### 7. Automated Non-FEMA Data Updates
Python script runs daily via GitHub Actions. Scrapes HHS, FMCSA, and monitors Federal Register. Updates curated SBA, USDA, and State data. Commits updated data file to the repository automatically.

**Why it matters:** The owner should not be manually checking government websites. Automation ensures data freshness.

### 8. Data Freshness Indicator
Small timestamp on the page showing when non-FEMA data was last updated. Not a focal point, but visible so agents can confirm data is current.

**Why it matters:** Builds trust. If something breaks, someone will notice the stale timestamp.

## Features (Future — Not Building Yet)

These are listed so the architecture can accommodate them later:

- **ZIP code search:** Accept ZIP input and map to county. Requires a ZIP-to-county mapping table (~41,000 entries).
- **Three-part validation checklist:** Interactive checklist reminding agents to confirm residence, eligible EP, and missed enrollment. Generates compliance documentation.
- **Talk tracks:** Pre-written compliant scripts agents can use when discussing DSTs with customers.
- **Other SEP types:** Expand beyond DST to cover all 35+ Medicare SEPs (MOV, LEC, MCD, etc.).
- **WordPress integration:** Embed the tool in the Clear Path Coverage agent portal behind the login wall.
- **Dark mode:** Theme toggle for agent preference.
- **Local government declarations:** Manual entry form for adding county/city/tribal declarations discovered by agents in the field.
- **Email/Slack notifications:** Alert when new disasters are declared or when data update failures occur.

## Constraints

1. **No backend server for MVP.** The tool is a static HTML file. FEMA data is fetched client-side. Non-FEMA data is embedded or loaded from a static JSON file.
2. **Non-technical maintainer.** All maintenance tasks must be achievable through Claude Code or simple documented commands.
3. **CMS compliance.** SEP window calculations must follow 42 CFR § 422.62 exactly. All declaration links must point to official government sources.
4. **Web scraping fragility.** Government websites change without notice. The tool must degrade gracefully when a scraper breaks (show stale data with a warning, not crash).
5. **GitHub free tier.** GitHub Actions limited to 2,000 minutes/month on free tier. Daily runs of a ~5-minute script = ~150 minutes/month, well within limits.
6. **CORS restrictions.** Only FEMA has a browser-friendly API. All other government sources must be scraped server-side (via the Python script), not from the browser.

## Out of Scope

- Original Medicare Part A/B enrollment (different window calculation — 6 months under § 406.27)
- User authentication or agent accounts
- Mobile-optimized UI (desktop browser is the primary use case)
- Carrier-specific plan recommendations
- Automated enrollment submission
- Local government declaration scraping (too many sources, no centralized data)
- Historical disaster archive (only active DSTs are shown)
- Print/PDF export
