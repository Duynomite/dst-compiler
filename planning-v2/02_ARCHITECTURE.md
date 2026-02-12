# DST Compiler Tool v2.0 — Architecture Overview

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        AGENT BROWSER                            │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    index.html (React 18)                   │  │
│  │                                                           │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐   │  │
│  │  │ FEMA Live    │  │ Curated JSON │  │ County/State   │   │  │
│  │  │ API Fetch    │  │ Fetch        │  │ Map Fetch      │   │  │
│  │  └──────┬───── │  └──────┬───────│  └───────┬────────│   │  │
│  │         │       │         │        │          │         │  │
│  │         ▼       │         ▼        │          ▼         │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │              Data Merge & Dedup Engine            │   │  │
│  │  │   FEMA (live) + SBA + FMCSA + HHS + USDA + GOV  │   │  │
│  │  └──────────────────────┬───────────────────────────┘   │  │
│  │                         │                                │  │
│  │                         ▼                                │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │              SEP Window Calculator                │   │  │
│  │  │   Start/End dates per 42 CFR 422.62(a)(6)       │   │  │
│  │  │   2 full calendar months after incident end      │   │  │
│  │  │   14-month max with renewal support              │   │  │
│  │  └──────────────────────┬───────────────────────────┘   │  │
│  │                         │                                │  │
│  │                         ▼                                │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │              Filter/Sort/Search UI                │   │  │
│  │  │   State dropdown → County autocomplete → Results │   │  │
│  │  │   Source filter, Sort options, Status badges      │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  │                                                          │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │              Compliance Layer                     │   │  │
│  │  │   3-part attestation, copy-for-SunFire, links    │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    AUTOMATED DATA PIPELINE                       │
│                                                                  │
│  ┌──────────────┐    ┌────────────────────────────────────┐     │
│  │ GitHub Actions│───>│ dst_data_fetcher.py                │     │
│  │ Daily 6AM EST│    │                                    │     │
│  │ + Manual     │    │  Federal Register API ──> SBA      │     │
│  └──────────────┘    │  Federal Register API ──> USDA     │     │
│                      │  Federal Register API ──> HHS      │     │
│                      │  Curated entries ──> FMCSA         │     │
│                      │  Curated entries ──> Governor/STATE │     │
│                      │  Curated entries ──> LOCAL          │     │
│                      │                                    │     │
│                      │  ┌──────────────────────────────┐  │     │
│                      │  │ Validation (21+ checks/record)│  │     │
│                      │  └──────────────────────────────┘  │     │
│                      │                                    │     │
│                      │  Output: curated_disasters.json    │     │
│                      └────────────────────────────────────┘     │
│                                                                  │
│  ┌──────────────┐    ┌────────────────────────────────────┐     │
│  │ Git auto-    │    │ GitHub Pages auto-deploy            │     │
│  │ commit if    │───>│ duynomite.github.io/dst-compiler/  │     │
│  │ data changed │    └────────────────────────────────────┘     │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL DATA SOURCES                         │
│                                                                  │
│  [FEMA API] ──────── Free, no auth, live in browser             │
│  [Federal Register API] ── Free, no auth, Python fetcher        │
│  [Governor websites] ──── Manual curation, 50 state sites       │
│  [FMCSA archive] ──────── Manual curation, infrequent updates  │
│  [USDA FSA] ────────────── Federal Register + manual curation   │
│  [HHS ASPR] ────────────── Federal Register + manual curation   │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

1. **Live path (FEMA):** Agent opens page → browser fetches FEMA API directly → merges with curated data → displays results. Fresh every page load.

2. **Automated path (SBA, USDA, HHS via Federal Register):** GitHub Actions runs Python fetcher daily → queries Federal Register API → validates records → writes curated_disasters.json → commits to repo → GitHub Pages auto-deploys.

3. **Manual path (Governor, FMCSA, LOCAL):** Admin edits curated_disasters.json (or runs fetcher with updated curated entries) → pushes to GitHub → auto-deploys. This is the path for governor declarations.

## Deployment and Hosting

| Aspect | Detail | Cost |
|--------|--------|------|
| **Hosting** | GitHub Pages (static site from main branch) | Free |
| **URL** | `https://duynomite.github.io/dst-compiler/` | Free |
| **CI/CD** | GitHub Actions (daily cron + push deploy) | Free tier (2,000 min/month) |
| **Domain** | GitHub subdomain (no custom domain) | Free |
| **SSL** | Included with GitHub Pages | Free |
| **Total cost** | **$0/month** | |

Deploy process: Push to `main` branch → GitHub Pages auto-builds → Live within ~60 seconds.

## Dependency Map

### Frontend (loaded via CDN in browser)

| Dependency | Version | CDN URL | Risk if Down |
|-----------|---------|---------|-------------|
| React 18 | 18.x | unpkg.com/react@18 | Tool won't render — critical |
| ReactDOM 18 | 18.x | unpkg.com/react-dom@18 | Tool won't render — critical |
| Babel Standalone | latest | unpkg.com/@babel/standalone | JSX won't compile — critical |
| Tailwind v4 | 4.x | cdn.jsdelivr.net/npm/@tailwindcss/browser@4 | Styling breaks — visual only |
| Google Fonts | — | fonts.googleapis.com | Fallback fonts render — minor |

### External APIs (fetched at runtime or by pipeline)

| API | Auth | Rate Limit | Fallback if Down |
|-----|------|-----------|-----------------|
| FEMA Disaster Summaries | None | Generous (no published limit) | Show cached curated data only + warning banner |
| Federal Register API | None | No published limit | Curated data stays at last-known state |
| GitHub Pages | None | Standard GH limits | Tool inaccessible — agents wait |

### Backend (Python data fetcher)

| Dependency | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11 | Runtime |
| requests | latest | HTTP client for API calls |
| beautifulsoup4 | latest | HTML parsing for scraping fallbacks |

## Security & Data Sensitivity Assessment

**This tool handles NO sensitive data.**

- No PII, no PHI, no financial data
- No authentication required
- No user accounts or sessions
- All data sources are public government records
- Tool is read-only — agents cannot modify data
- No cookies, no localStorage of sensitive info

**Security posture:** Minimal. Standard GitHub Pages security (HTTPS, no server-side code). No additional hardening needed.

The only risk vector is **data integrity** — wrong disaster dates or counties could lead to invalid enrollments. This is mitigated through the validation pipeline and audit script, not through security controls.

## Observability Plan

**Tier: Internal tool (used regularly)**

| What | How | When |
|------|-----|------|
| FEMA API fetch status | Header timestamp + console logging | Every page load |
| Curated data freshness | "Last Updated" timestamp in header | Every page load |
| Staleness warning | Yellow banner if curated data > 7 days old | Automatic |
| Pipeline failures | GitHub Actions creates Issue on failure | Daily cron |
| Data validation | audit_curated_data.py (21 checks/record) | Part of pipeline run |
| Debug console | Ctrl+Shift+D overlay with fetch stats | On-demand |

## File Structure (v2.0)

```
dst-compiler/
├── index.html                 # Main app (React 18 + Tailwind v4)
├── curated_disasters.json     # Non-FEMA disaster data (auto-updated)
├── county_state_map.json      # County autocomplete data (~3,200 counties)
├── dst_data_fetcher.py        # Python data collection pipeline
├── audit_curated_data.py      # Validation script (21+ checks)
├── requirements.txt           # Python deps
├── CLAUDE.md                  # Project instructions for Claude Code
├── .github/
│   └── workflows/
│       └── update-data.yml    # Daily cron + manual trigger
├── planning-v2/               # v2.0 planning documents
│   ├── 01_PRD.md
│   ├── 02_ARCHITECTURE.md     # This file
│   ├── 03_RISK_REGISTER.md
│   ├── 04_BUILD_PLAN.md
│   ├── 05_TEST_CASES.md
│   └── 06_MAINTENANCE_GUIDE.md
└── planning/                  # v1.0 planning (archived reference)
    ├── 01_PRD.md
    ├── 02_ARCHITECTURE.md
    ├── 03_BUILD_PLAN.md
    ├── 04_TEST_CASES.md
    └── 06_HANDOFF_SUMMARY.md
```
