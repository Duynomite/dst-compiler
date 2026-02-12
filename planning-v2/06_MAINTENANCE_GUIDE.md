# DST Compiler Tool v2.0 — Maintenance & Resumption Guide

## Dependencies

### External APIs
| API | URL | Auth | What Happens If Down |
|-----|-----|------|---------------------|
| FEMA Disaster Summaries | `fema.gov/api/open/v2/DisasterDeclarationsSummaries` | None | Frontend shows curated data only + warning banner |
| Federal Register | `federalregister.gov/api/v1/documents.json` | None | Daily pipeline fails → curated data stays at last-known state |
| GitHub Pages | `duynomite.github.io/dst-compiler/` | None | Tool inaccessible to agents |
| GitHub Actions | Actions tab on repo | Repo access | Pipeline doesn't run → data becomes stale |

### CDN Dependencies (Frontend)
| Library | CDN | Fallback |
|---------|-----|----------|
| React 18 | unpkg.com | None — tool won't render |
| ReactDOM 18 | unpkg.com | None — tool won't render |
| Babel Standalone | unpkg.com | None — JSX won't compile |
| Tailwind v4 | cdn.jsdelivr.net | Styling breaks, content still readable |
| Google Fonts | fonts.googleapis.com | System fonts used — minor visual difference |

### Python Dependencies (Pipeline)
| Package | Purpose |
|---------|---------|
| requests | HTTP client for API calls |
| beautifulsoup4 | HTML parsing for scraping fallbacks |
| Python 3.11+ | Runtime |

## Known Fragile Points

### 1. Governor Declaration Data (HIGHEST RISK)
**What:** Governor declarations have no centralized API. Data is manually curated.
**Symptoms:** Missing governor DSTs, expired declarations still showing, wrong county lists.
**Fix:** Research individual state governor websites. Update `curated_disasters.json` with correct data. Run audit script to validate.
**Frequency:** Check after any major disaster. Monthly review for expirations.

### 2. FEMA API Query Window
**What:** The frontend queries FEMA for declarations from the last 24 months. If a disaster SEP window extends beyond 24 months (theoretically possible with renewals), it could be missed.
**Symptoms:** Older disaster disappears even though SEP window is still active.
**Fix:** Extend the lookback window in the FEMA API query, or add the disaster to curated data.

### 3. Federal Register API Search Terms
**What:** SBA and USDA detection depends on specific search queries to the Federal Register API. If document titles or agencies change naming conventions, the search may miss entries.
**Symptoms:** New SBA/USDA declarations not appearing in curated data after pipeline run.
**Fix:** Review Federal Register search queries in `dst_data_fetcher.py`, adjust search terms.

### 4. County Name Normalization
**What:** Different sources use different county naming conventions (e.g., "St. Louis" vs "Saint Louis", "De Kalb" vs "DeKalb"). Mismatches mean county search fails.
**Symptoms:** Agent searches for a county but matching DST doesn't appear.
**Fix:** Update `county_state_map.json` or normalize names in curated data to match.

## How to Resume This Project

### For a New Claude Code Session

**Read these files first (in order):**
1. `CLAUDE.md` (project root) — Current state, known issues, decisions
2. `planning-v2/01_PRD.md` — What we're building and why
3. `planning-v2/04_BUILD_PLAN.md` — Current phase and what's next

**Check before making changes:**
1. Run `python audit_curated_data.py` — baseline validation
2. Check GitHub Actions tab — is the cron running?
3. Open live site — does FEMA data load?

**Current state:** [Updated after each session]

### Key Files

| File | Purpose | Edit Frequency |
|------|---------|---------------|
| `index.html` | Main application (React 18 + Tailwind) | During UI changes only |
| `curated_disasters.json` | Non-FEMA disaster data | After every major disaster or monthly review |
| `dst_data_fetcher.py` | Data pipeline (SBA, USDA, HHS, FMCSA, GOV automation) | When adding new sources or fixing detection |
| `audit_curated_data.py` | Data validation (21+ checks/record) | When adding new validation rules |
| `county_state_map.json` | County autocomplete (~3,200 counties) | Rarely — only if county names are wrong |
| `.github/workflows/update-data.yml` | Daily cron + manual trigger | Rarely |

### How to Roll Back
1. `git log --oneline` — find the commit before the problem
2. `git revert <commit-hash>` — create a new commit that undoes the change
3. Push to `main` — GitHub Pages auto-deploys the rollback
4. NEVER use `git reset --hard` on `main` — this loses history

## Architecture Decision Log

| Date | Decision | Why | Alternatives Considered |
|------|----------|-----|------------------------|
| Feb 2026 (v1) | Live FEMA API in browser, not Python | Freshest possible data, zero pipeline delay | Python fetch + embed (chose against: 24hr stale) |
| Feb 2026 (v1) | GitHub Actions daily cron for non-FEMA | SBA/USDA change infrequently; daily is sufficient | Hourly (overkill), weekly (too stale) |
| Feb 2026 (v1) | Separate curated JSON from HTML | Clean separation; pipeline can update data without touching UI code | Embed in HTML (v1 SEPAnalyzer approach — rejected for maintainability) |
| Feb 2026 (v2) | Upgrade to Tailwind v4 @theme | CPC brand tokens as native Tailwind utilities; matches dev standards | Keep v3 (chose against: v4 @theme is a genuine improvement for brand consistency) |
| Feb 2026 (v2) | Governor declarations as manual curation | No centralized API exists; automation impossible | Scrape 50 state websites (too fragile, too many formats) |
| Feb 2026 (v2) | No agent-facing "report DST" feature | Agents only use DSTs posted by government entities; agent input creates compliance risk | Add report feature (rejected: compliance concern) |

## Assumptions Made During Planning

| # | Assumption | Risk if Wrong | How to Validate |
|---|-----------|---------------|-----------------|
| 1 | FEMA API will remain free and unauthenticated | Tool loses live FEMA data; fall back to curated | Monitor FEMA API docs; check for auth headers in 401 responses |
| 2 | GitHub Actions free tier (2,000 min/month) is sufficient | Pipeline stops running | Monitor Actions usage; single run takes <2 min, daily = ~60 min/month |
| 3 | Governor declarations expire when governors issue revocation orders | Could show expired DSTs | Monthly verification of active governor declarations |
| 4 | County names in FEMA API match county_state_map.json | County search misses matches | Test with known FEMA disaster counties |
| 5 | Tailwind v4 CDN works with React 18 + Babel | UI breaks after upgrade | Test in Phase 3 before any other changes |

## Data Curation Workflow (For Admin)

### When a New Disaster Is Declared

1. **Check FEMA first** — if FEMA has declared, it will appear automatically (live API). No action needed for FEMA.

2. **Check for governor declaration:**
   - Search `[state] governor emergency declaration [disaster name]`
   - Find the official executive order on governor's website
   - Create a new entry in `curated_disasters.json`:
     ```json
     {
       "id": "GOV-[ST]-[YEAR]-[SEQ]",
       "source": "STATE",
       "state": "[ST]",
       "title": "Governor [Name] Emergency Declaration — [Disaster]",
       "incidentType": "[Type]",
       "declarationDate": "YYYY-MM-DD",
       "incidentStart": "YYYY-MM-DD",
       "incidentEnd": null,
       "counties": ["County1", "County2"] or "Statewide",
       "officialUrl": "https://governor.[state].gov/...",
       "status": "ongoing",
       "confidence": "curated",
       "lastVerified": "YYYY-MM-DD"
     }
     ```

3. **Check SBA/USDA** — these should be caught by the Federal Register API fetcher. If not, add manually.

4. **Run validation:** `python audit_curated_data.py`

5. **Push to GitHub:** `git add . && git commit -m "Add [disaster] declarations" && git push`

6. **Verify live:** Check duynomite.github.io/dst-compiler/ within ~60 seconds

### Monthly Maintenance Checklist

- [ ] Review all curated entries with `lastVerified` > 30 days old
- [ ] Check if any governor declarations have been lifted/expired
- [ ] Verify GitHub Actions has been running (check Actions tab)
- [ ] Run audit script: `python audit_curated_data.py`
- [ ] Spot-check 3 random official source URLs still resolve
- [ ] Update `lastVerified` dates for entries confirmed still active
