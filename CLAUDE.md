# CLAUDE.md — DST Compiler Tool

## Project Status
- **Status:** v2.5 — Double-Audited + All Corrections Verified
- **Last Session:** 2026-02-16
- **Blocker:** None
- **Next Action:** Continue coverage gap research (18 states flagged); monitor Feb 14-15 TX/LA/MS tornado declarations
- **Live URL:** https://duynomite.github.io/dst-compiler/

## Your Role
You are acting as CTO for this project. This is a compliance-critical tool — wrong disaster dates or missing declarations directly affect Medicare enrollment compliance. Accuracy > features, always. Read this file and `planning-v2/` folder before taking any action.

## Working Rules
- Read before acting — check Current State and Known Issues first
- Check before major changes — review Architecture and Build Plan
- Accuracy above all else — invalid DSTs, wrong dates, or dead links are compliance violations
- When in doubt, exclude the data — better to miss a marginal disaster than display a wrong one
- Update this file at the END of every session (Current State, Bug Log, Decisions, Session Log)
- Agents ONLY use DSTs posted by government entities — they do NOT discover, report, or add DSTs

## Quick Reference
- **v2 PRD:** `planning-v2/01_PRD.md`
- **v2 Architecture:** `planning-v2/02_ARCHITECTURE.md`
- **v2 Risk Register:** `planning-v2/03_RISK_REGISTER.md`
- **v2 Build Plan:** `planning-v2/04_BUILD_PLAN.md`
- **v2 Test Cases:** `planning-v2/05_TEST_CASES.md`
- **v2 Maintenance Guide:** `planning-v2/06_MAINTENANCE_GUIDE.md`
- **v2 Handoff Summary:** `planning-v2/07_HANDOFF_SUMMARY.md`
- **v1 Planning (archived):** `planning/`

## Project Overview

This is a Disaster Special Enrollment Period (DST) compiler tool for Medicare Advantage telesales agents. It finds every valid government-declared disaster that triggers a Medicare Advantage DST, compiles them into one searchable interface, and lets agents copy declaration details into the SunFire enrollment platform.

**This tool must be accurate above all else.** Invalid DSTs, wrong dates, or dead links are compliance violations. When in doubt, exclude the data — it's better to miss a marginal disaster than to display a wrong one.

## v2.0 Upgrade Scope

The v1 tool captures FEMA disasters well via live API but misses governor-declared state emergencies, HHS, and USDA declarations. v2 fixes this:

1. **Backfill governor declarations** — 18+ states for Jan 2026 winter storm alone
2. **Add HHS/USDA coverage** — Complete federal source types
3. **Upgrade UI to CPC brand** — Tailwind v4 @theme, Urbanist/Jost fonts, brand colors
4. **Verify pipeline** — Confirm GitHub Actions cron runs, fix if broken
5. **Add freshness indicators** — Last updated timestamp, staleness warnings

## Tech Stack

- **Frontend:** Single HTML file, React 18, Tailwind CSS v4 (CDN), Babel Standalone
- **Styling:** Tailwind v4 `@theme` with CPC brand tokens (accent, secondary, deep-navy, etc.)
- **Fonts:** Urbanist (headings) + Jost (body) via Google Fonts
- **Data Fetcher:** Python 3.11+, requests, beautifulsoup4
- **Hosting:** GitHub Pages (static site from the repo)
- **Automation:** GitHub Actions (daily cron job at 6AM EST)
- **No backend server, no database, no npm, no build process.**

## Project Structure

```
dst-compiler/
├── index.html                 # The tool — agents open this (React 18 + Tailwind v4 + CPC brand)
├── curated_disasters.json     # Non-FEMA disaster data (104 records, updated by fetcher)
├── dst_data_fetcher.py        # Python pipeline: SBA/HHS/FMCSA/STATE collectors
├── audit_curated_data.py      # Validation script (22 checks per record)
├── build_governor_entries.py   # Phase 2 utility: builds governor entries (run once)
├── requirements.txt           # Python dependencies (requests, beautifulsoup4)
├── county_state_map.json      # County-to-state lookup (~3,200 entries)
├── .github/
│   └── workflows/
│       └── update-data.yml    # GitHub Actions daily schedule (6AM EST)
├── planning-v2/               # v2.0 planning documents (current)
├── planning/                  # v1.0 planning documents (archived)
└── CLAUDE.md                  # This file
```

## Current State
[Updated 2026-02-16 — v2.5 Full Audit + Data Corrections]
- **v2.5 AUDITED AND LIVE** at `duynomite.github.io/dst-compiler/`
- **104 curated records** (62 FMCSA + 13 SBA + 28 STATE + 1 HHS)
- **Full audit results** (this session):
  - FEMA API: 16 active disasters (correct), 84 expired (filtered)
  - SBA: All 13 records verified against Federal Register source documents
  - FMCSA: All 62 records verified against FMCSA website + secondary sources
  - STATE: 26/28 URLs verified OK (TN connection reset, MS SSL issue — both known)
  - Zero expired records in curated data
  - 2,083/2,083 audit checks pass (100%) — after second audit corrections
- **Fixes applied this session**:
  - 3 more expired SBA records corrected (IL apartment fire, IN contiguous, MN fire) — parser used FR pub date as incident date
  - 1 missing SBA record added: SBA-2026-02924-CA (Oakland Apartment Fire, Jan 19 2026)
  - SBA-2026-02294-LA county list expanded (5→21 parishes) + 3 contiguous state records added (TX, AR, MS)
  - FMCSA-2025-012: Removed VA (never part of this declaration per verified Feb 13 extension doc)
  - FMCSA-2025-013: End date confirmed as Feb 15 (not Feb 28 — that was 2025-012 only); MN is correct (MI was never added)
  - FMCSA-2025-014-WA: End date corrected to Jan 23 (not Feb 20 — no further extension found)
  - SBA-2025-16217-AK: Removed Southeast Fairbanks county (not in FR source doc)
  - SBA-2026-02924-CA: Title corrected to "Oakland Apartment Fire"; removed 7 non-adjacent counties
- **28 governor declarations** covering 24 states + DC
- **1 HHS PHE** (Washington State severe weather)
- FEMA live API: Healthy, ~16 active disasters
- GitHub Actions cron: Running daily at 6AM EST + weekly Monday 10AM EST
- **eCFR regulatory monitoring**: § 422.62 confirmed UNCHANGED
- **eCFR regulatory monitoring**: § 422.62 confirmed UNCHANGED (effective since 2024-06-03) — runs weekly in CI
- **Coverage Gap Analyzer (NEW v2.3)**: Cross-references FEMA/FMCSA declarations against curated STATE records, flags states with federal disaster coverage but no governor declaration. Runs every fetcher execution. Weekly CI creates GitHub Issue for gaps.
- SEP calculations: Verified correct for all edge cases (end-of-month, leap year, year boundary)
- Data integrity pipeline:
  - **Audit script runs in CI** — gates every commit on 25 checks per record
  - **Per-source record count thresholds** — blocks if any source drops >20% or to zero
  - **Content hash in metadata** — detects silent data corruption
  - **URL verification (HEAD + content relevance)** — catches wrong URLs, dead links, generic pages
  - **Smart domain handling** — FMCSA (403 bots) → structure check, Federal Register (JS) → HEAD only
  - **eCFR regulatory monitoring (Check 25)** — weekly check for amendments to 42 CFR § 422.62(b)(18); creates GitHub Issue if regulation changes
  - **Coverage gap analysis** — FEMA↔STATE cross-reference flags missing governor declarations; weekly CI issue
  - **lastVerified auto-updates** — STATE/HHS records get fresh dates on every fetcher run
  - **Structured GitHub Issue alerting** — specific labels per failure type (data-integrity, audit, urls, regulatory, urgent, coverage-gap)
- UI features:
  - **Tailwind v4 + CPC brand** (Urbanist/Jost fonts, accent/secondary colors)
  - **Cross-state county search** — agents can type any county without selecting a state first
  - **State badge on cards** — visible in all sort modes (not just state-grouped)
  - **FEMA title formatting** — ALL CAPS titles normalized to Title Case
  - **Compliance attestation banner** — 3-part validation displayed between search and results
  - **Integrity status in header** — shows "✓ Links verified", "✓ Reg current", or alerts for issues
  - **Enhanced staleness banner** — surfaces URL issues, regulatory changes, and data age warnings
  - **Regulatory change banner** — red banner if 42 CFR § 422.62 is amended (tells agents to contact compliance)
- Fetcher: **HHS + STATE collectors populated**, lastVerified auto-updates, USDA documented as non-qualifying
- Hardening: noscript fallback, malformed entry defense, curated error banner, county name normalization (Saint/St/Fort/Mt), accessibility (aria-labels, focus rings)
- Validation benchmark: Davidson County TN = 5 DSTs (2 FEMA + 2 FMCSA + 1 GOV) ✅

## TODO — Next Session
1. ~~**URL Verification System**~~ **DONE (v2.1)** — Full HEAD + content relevance checks, weekly CI, smart domain handling
2. ~~**eCFR Regulatory Monitoring**~~ **DONE (v2.2)** — Weekly check for amendments to 42 CFR § 422.62(b)(18), GitHub Issue alerting, UI status display
3. ~~**Coverage Gap Analyzer**~~ **DONE (v2.3)** — FEMA/FMCSA→STATE cross-reference, weekly CI issue creation
4. **Expiring-Soon Visual Indicator** — Orange/red badge on cards nearing SEP window end
5. ~~**"Data Last Updated" in UI**~~ **DONE (v2.0)** — Timestamp in header
6. **Federal Register API reliability** — API returns inconsistent results in GitHub Actions (1 SBA vs 55 locally). Per-source safeguard blocks data loss, but root cause unclear. Consider: caching last-good SBA results, retry logic, or fallback to curated-only mode in CI.
7. **Research remaining coverage gaps** — 18 states flagged by analyzer (most advisory). Priority: MA, NH, VT, RI (heating fuel impact), WA (flooding), WI/IA/IL/MN (winter storm impact).

## Known Issues
- USDA: Confirmed NOT a valid DST trigger for Medicare — USDA drought designations are agricultural loan programs, not disaster declarations under 42 CFR 422.62(b)(18)
- ~~Some governor declaration URLs point to general governor pages (OH, MO, KS)~~ **RESOLVED 2026-02-12** — all 24 STATE URLs now verified, 8 fixed
- ~~Some FMCSA entries may have outdated incident end dates~~ **RESOLVED 2026-02-16** — Updated 2025-012 (Feb 28 extension, +ME/VT), 2026-001 (Feb 20 extension), added 2025-014 WA
- ~~**43 expired SBA records showing as active**~~ **RESOLVED 2026-02-16** — Parser bug: single-day incidents classified as "ongoing". Fixed with Pattern 4 regex + 10 curated overrides.
- ~~**All 28 STATE URLs returning 404**~~ **FALSE ALARM 2026-02-16** — Re-tested with proper User-Agent: 26/28 return 200 OK with correct page titles. TN has server-side connection reset, MS has known SSL issue. Initial test was likely affected by missing User-Agent header or transient network issue.
- **18 FMCSA→STATE coverage gaps** flagged by analyzer — most are advisory (FMCSA covers 30-40 states broadly); research needed for MA, VT, NH, RI, WI, IA, IL, MN, CO, WA
- ~~**4 remaining ongoing SBA records need verification**~~ **RESOLVED 2026-02-16** — IL/IN/MN were expired single-day events (fixed with curated overrides). AK wildfire confirmed truly ongoing per FR text ("and continuing").
- ~~**FMCSA-2025-014-WA cannot be verified**~~ **VERIFIED 2026-02-16** — Declaration confirmed to exist via FMCSA PDF. Extended Dec 23 to Jan 23, 2026 (expired). SEP window active through Mar 31, 2026.
- **FMCSA-2026-001 expires Feb 20** — No extension published yet. Monitor for extension this week. If not extended, SEP window remains active through April 30, 2026.
- **Feb 14-15 TX/LA/MS tornadoes** — Resource activation by TX governor (not formal declaration). Monitor for formal state/federal declarations that would trigger DST.
- LA governor declaration (Jan 2025) was renewed multiple times — tracked as ongoing
- ~~**No automated URL verification**~~ **RESOLVED 2026-02-12** — URL verification system built with HEAD + content relevance checks, weekly CI runs, smart domain handling (FMCSA/FR)
- **3 SSL warnings** — AR (governor.arkansas.gov), MS (governorreeves.ms.gov), WA HHS (aspr.hhs.gov) have intermittent SSL cert issues on their end. URLs are correct; certs are the government's problem. Treated as WARN not FAIL.

## Bug Log
| # | Date | Description | Severity | Status | Resolution |
|---|------|-------------|----------|--------|------------|
| 1 | 2026-02-11 | SBA-2024-28528-CA status was `ongoing` but daysRemaining=17 | Low | Fixed | Updated to `expiring_soon` during Phase 2 |
| 2 | 2026-02-12 | 8 of 24 STATE officialUrl entries were incorrect (wrong year or generic homepage) | High | Fixed | AL, AR, KY, SC had 2025 URLs for 2026 declarations; MO, OH, NM, IN had generic homepages. All 8 replaced with specific 2026 declaration URLs |
| 3 | 2026-02-12 | Git rebase --ours/--theirs confusion during push | Low | Fixed | During rebase, --ours = upstream (remote), --theirs = local commit. Verified by record count |
| 4 | 2026-02-12 | Federal Register API inconsistent: 55 SBA locally vs 1 in GitHub Actions | High | Mitigated | Per-source safeguard blocks data loss. Root cause: FR API returns fewer results to CI. Safeguard proven to catch the "55→1" drop scenario. |
| 5 | 2026-02-12 | audit_curated_data.py had hardcoded date (2026-02-11) and absolute path | Medium | Fixed | Replaced with date.today() + os.path.dirname() relative path. Script now CI-compatible. |
| 6 | 2026-02-12 | Regulatory citation was § 422.62(a)(6) everywhere — actual citation is § 422.62(b)(18) | Medium | Fixed | Confirmed via eCFR API that DST SEP is paragraph (b)(18). Updated all references in index.html, dst_data_fetcher.py, CLAUDE.md |
| 7 | 2026-02-16 | SBA single-day incidents classified as "ongoing" with 14-month SEP windows | **Critical** | Fixed | `_extract_incident_dates()` had 3 regex patterns but none handled "Incident Period: [single date]." (no "through"/"and continuing"). Added Pattern 4 for single-day events + tightened Pattern 3. 43 expired SBA records removed, 10 curated overrides added. |
| 8 | 2026-02-16 | STATE URL verification false alarm — initial test showed 404s | Low | Resolved | Re-tested with proper User-Agent header: 26/28 URLs return 200 OK with correct content. TN has server-side connection reset, MS has known SSL issue. Initial 404 results were likely caused by network issue or missing User-Agent in test script. |
| 9 | 2026-02-16 | SBA-2025-05997-IL/IN and SBA-2025-23887-MN using FR pub date as incidentStart | **Critical** | Fixed | Same root cause as Bug #7: parser fell back to FR publication date instead of parsing incident period. IL/IN: pub=2025-04-08, actual=2025-02-22 (expired Apr 30). MN: pub=2025-12-29, actual=2025-10-26 (expired Dec 31). Added override IDs + curated entries. |
| 10 | 2026-02-16 | Missing SBA-2026-02924-CA (Oakland Apartment Fire) | High | Fixed | FR doc published Feb 13, 2026 not captured by fetcher. Added as curated entry. Single-day fire Jan 19, 2026 in Alameda County. SEP ends Mar 31, 2026. |
| 11 | 2026-02-16 | FMCSA-2025-012 missing Virginia | Medium | Fixed | VA added in Dec 23 extension but not captured in curated data. Added VA to state list (11→12 states). |
| 12 | 2026-02-16 | FMCSA-2025-013 stale end date + MN/MI swap | Medium | Fixed | Feb 13 extension pushed end date from Feb 15→Feb 28 and replaced MN with MI. Updated end date for all states, added MI, kept MN with original Feb 15 end date. |
| 13 | 2026-02-16 | SBA-2026-02294-LA incomplete county list | Medium | Fixed | Amendment (FR 2026-03026, Feb 17) expanded from 5→21 parishes + added contiguous counties in TX (2), AR (3), MS (5). Created override + 4 curated entries. |
| 14 | 2026-02-16 | FMCSA-2025-012 incorrectly included Virginia | Medium | Fixed | VA was never part of this declaration per verified Feb 13 extension document (papropane.com source). Removed VA from state list (12→11 states). |
| 15 | 2026-02-16 | FMCSA-2025-013 had wrong state (MI) and wrong end date (Feb 28) | Medium | Fixed | MI was never part of this declaration — MN was correct all along. End date Feb 28 applied to 2025-012 only, not 2025-013. Reverted to MN with Feb 15 end date. |
| 16 | 2026-02-16 | FMCSA-2025-014-WA end date was Feb 20, should be Jan 23 | Medium | Fixed | Dec 23 extension expired Jan 23, 2026 per FMCSA PDF. No further extension found. SEP window still active (ends Mar 31, 2026). |
| 17 | 2026-02-16 | SBA-2025-16217-AK included Southeast Fairbanks county not in FR doc | Low | Fixed | FR doc 2025-16217 lists Denali, Yukon-Koyukuk (primary) + Matanuska-Susitna (contiguous). Southeast Fairbanks not mentioned. Removed. |
| 18 | 2026-02-16 | SBA-2026-02924-CA had wrong title and 7 extra counties | Medium | Fixed | FR doc says "Oakland Apartment Fire" (not "Complex"). Only 7 counties in FR doc (Alameda + 6 contiguous), not 14. Corrected. |

## Decisions Made
| Date | Decision | Why | Alternatives |
|------|----------|-----|-------------|
| 2026-02-11 | Upgrade dst-compiler (not rebuild, not SEPAnalyzer) | Working FEMA API + pipeline + deployment; problem is data coverage, not architecture | Rebuild from scratch, upgrade SEPAnalyzer |
| 2026-02-11 | No agent-facing "report DST" feature | Agents only use DSTs posted by gov entities; agent input creates compliance risk | Add report/feedback mechanism |
| 2026-02-11 | Governor declarations = manual curation | No centralized API across 50 states; automation impossible | Scrape 50 state sites (too fragile) |
| 2026-02-11 | USDA drought NOT a valid DST trigger | USDA designations are agricultural loan programs, not disaster declarations under 42 CFR 422.62(b)(18) | Include USDA as data source (rejected: compliance risk) |
| 2026-02-11 | HHS PHE for WA is severe weather, NOT bird flu | Research confirmed the Dec 2025 PHE was for atmospheric rivers/flooding | Mislabel as HPAI (rejected: inaccurate) |
| 2026-02-12 | Cross-state county search (no state required) | Agents often know county but not state abbreviation; reduces friction | Keep state-first search only (rejected: bad UX) |
| 2026-02-12 | Auto-select state on county pick | When agent picks "Davidson, TN" from cross-state dropdown, state auto-fills. Prevents showing statewide disasters from all 50 states. | Leave state empty after county pick (rejected: wrong results) |
| 2026-02-12 | URL verification must be automated | 8 of 24 STATE URLs were wrong — manual curation alone is insufficient for compliance tool | Keep manual-only checks (rejected: proven failure rate) |
| 2026-02-12 | Data Integrity Protocol v2.1 | 4-phase protocol: CI audit (24 checks), per-source thresholds, URL verification (HEAD + content), integrity UI | Manual-only monitoring (rejected: human error rate proven) |
| 2026-02-12 | SSL errors as WARN not FAIL | AR/MS/WA have intermittent SSL cert issues — their problem, not our URLs | Block on SSL errors (rejected: would block 3 valid records) |
| 2026-02-12 | FMCSA URLs validated by structure not HTTP | FMCSA returns 403 to all bots — validate URL pattern instead | Try harder to reach FMCSA (rejected: 403 is intentional) |
| 2026-02-12 | eCFR regulatory monitoring via weekly CI | If CMS amends § 422.62, our SEP window calculations could silently become wrong. eCFR API is free, no auth, returns version dates. Weekly check catches amendments within 7 days | Manual monitoring of Federal Register (too slow, easy to miss) |
| 2026-02-12 | Corrected citation to § 422.62(b)(18) | eCFR API confirmed DST SEP is paragraph (b)(18), not (a)(6). All code references updated. | Leave incorrect citation (rejected: compliance risk) |
| 2026-02-12 | IPAWS not viable for governor declarations | Tested IPAWS Archived Alerts API — 4.8M alerts but mostly weekly tests and NWS weather. Governor emergency declarations don't reliably appear | Integrate IPAWS as data source (rejected: signal-to-noise ratio too low) |
| 2026-02-12 | SBA Content API unavailable | SBA disaster.json endpoint returned 404 — appears deprecated. Federal Register API remains best SBA source | Switch to SBA Content API (rejected: endpoint dead) |
| 2026-02-16 | Coverage Gap Analyzer as automated process | No centralized governor declaration database exists. Cross-referencing FEMA/FMCSA against STATE records catches the most common gap: federal disaster response without corresponding governor declaration curated | Manual-only monitoring (rejected: proven to miss 7 records), Scrape 50 state sites (rejected: too fragile, maintenance nightmare) |
| 2026-02-16 | FMCSA→STATE gaps are advisory, not blocking | FMCSA covers 30-40 states broadly for transportation; many won't have governor declarations because impact wasn't locally severe enough. Gaps are flagged for review, not auto-resolved | Block pipeline on any gap (rejected: too many false positives) |
| 2026-02-16 | Curated SBA overrides for confirmed expired single-day events | Parser fix alone can't retroactively correct records already in curated_disasters.json from prior fetcher runs. Override IDs suppress the bad FR-parsed versions; curated entries with correct single-day end dates return None from build_record() (expired), ensuring clean data | Delete records manually from JSON (rejected: fragile, doesn't prevent re-fetch) |
| 2026-02-16 | Pattern 3 regex tightened to require "and continuing" | Original Pattern 3 had `$` fallback that could match non-continuing text, incorrectly classifying records as ongoing | Keep loose regex (rejected: caused false ongoing classifications) |

## Session Log
| Date | Session | What Was Done | Phase Completed | Tests Passing |
|------|---------|---------------|-----------------|---------------|
| 2026-02-11 | Planning | Full v2.0 audit and planning (7 documents) | Pre-Phase 1 | N/A |
| 2026-02-11 | Phase 1 | Validated: audit script (100%), GitHub Actions (running), FEMA API (healthy), SEP calcs (3/3 edge cases pass) | Phase 1 ✅ | 2019/2019 (1 minor status fix) |
| 2026-02-11 | Phase 2 | Backfilled 25 new entries: 24 STATE + 1 HHS. Fixed SBA status bug. 2469/2469 audit checks pass. | Phase 2 ✅ | 2469/2469 (100%) |
| 2026-02-11 | Phase 3 | Complete UI rewrite: Tailwind v4 + CPC brand, source filter, staleness banner, lastVerified display, state-grouped view | Phase 3 ✅ | Visual verification |
| 2026-02-11 | Phase 4 | Fetcher upgrade: HHS collector populated (WA PHE), STATE collector populated (24 entries), lastVerified field added to build_record(), USDA documented as non-qualifying, audit script updated to check 22 | Phase 4 ✅ | 2644/2644 (100%) |
| 2026-02-11 | Phase 5 | Hardening: noscript fallback, malformed entry try/catch, curated error banner, county normalization (Fort/Mt), NaN date defense, accessibility (aria-labels, focus rings), SEP edge cases verified (5/5) | Phase 5 ✅ | All edge cases pass |
| 2026-02-12 | Deploy + Polish | Deployed v2.0 to GitHub Pages. Added compliance banner, state badge on cards, FEMA title formatting. Resolved git rebase conflict with cron. Added cross-state county search. Fixed 8 incorrect STATE URLs (wrong year or generic pages). Full URL audit of all 24 governor declarations. | Deployed ✅ | 2644/2644 (100%) |
| 2026-02-12 | Data Integrity Protocol | Full 4-phase integrity system: (1) CI-compatible audit (dynamic dates, relative paths, 24 checks), (2) Per-source record count thresholds, (3) URL verification (HEAD + content relevance, smart domain handling for FMCSA/FR), (4) Integrity status in UI header + enhanced staleness banner, (5) Structured GitHub Issue alerting with specific labels, (6) Content hash + source counts in metadata. | v2.1 ✅ | 2783/2783 (100%), 136/139 URLs PASS |
| 2026-02-12 | eCFR + API Research | (1) Built eCFR regulatory monitoring (Check 25) — weekly queries eCFR API for amendments to § 422.62(b)(18), GitHub Issue alerting on change, UI status display. (2) Corrected regulatory citation from (a)(6) to (b)(18) across all code. (3) Researched 21 government APIs — tested IPAWS (not viable for governor decls), SBA Content API (404/dead), FEMA Declaration Denials (niche). (4) Confirmed: Federal Register API + FEMA API remain our best sources; no new APIs worth integrating now. | v2.2 ✅ | 2783/2783, eCFR PASS |
| 2026-02-16 | Data Backfill + Gap Analyzer | (1) Identified 7 missing records via comprehensive web research. (2) Added 4 governor declarations: NJ (Sherrill), MD (Moore), DC (Bowser), ME (Mills). (3) Added FMCSA 2025-014 WA flooding. (4) Updated FMCSA 2025-012 extension: end date Feb 28, added ME+VT (9→11 states). (5) Built CoverageGapAnalyzer: cross-references FEMA/FMCSA against STATE records, flags states with federal disasters but no governor declaration. (6) Added weekly CI step to create GitHub Issues for coverage gaps. (7) All 146 records pass audit (2,923 checks, 100%). (8) All 4 new STATE URLs verified (200 OK, content match). | v2.3 ✅ | 2923/2923 (100%) |
| 2026-02-16 | Critical SBA Audit + Parser Fix | (1) Comprehensive audit: FEMA API (16 active, 162 filtered), SBA Federal Register verification, STATE URL verification. (2) Discovered critical parser bug: single-day SBA incidents ("Incident Period: Jan 25, 2025.") classified as "ongoing" with 14-month windows. (3) Added Pattern 4 to `_extract_incident_dates()`, tightened Pattern 3 regex. (4) Added 10 curated SBA overrides for confirmed expired single-day events. (5) Re-ran fetcher: 146→103 records (43 expired SBA removed). SBA: 55→12. (6) Audit passed: 2,063/2,063 checks (100%). (7) STATE URLs verified OK (26/28, false alarm on earlier 404 report). | v2.4 ✅ | 2063/2063 (100%) |
| 2026-02-16 | Full Audit + Data Corrections | (1) Second comprehensive audit: verified all SBA records against FR source docs, checked FMCSA for updates, searched for new declarations. (2) Found 3 more expired SBA records (IL/IN apartment fire, MN fire). (3) Found missing SBA-2026-02924-CA (Oakland fire). (4) Found FMCSA updates and SBA-2026-02294-LA amendment. (5) Third audit (double-check): verified FMCSA against secondary sources, found first agent had incorrect data for VA, MI/MN, and WA end date. All corrections applied. (6) Final state: 104 records, 2,083/2,083 checks pass (100%). | v2.5 ✅ | 2083/2083 (100%) |

## Definition of Done
- [ ] All test cases pass (happy path, edge cases, bad data, business logic, operational failures)
- [ ] Validation benchmark passes (Davidson County TN = 5 DSTs from 3 sources)
- [ ] All active governor declarations backfilled
- [ ] Error messages are plain language
- [ ] Freshness indicators working (timestamp + staleness banner)
- [ ] All external dependencies documented in Maintenance Guide
- [ ] Governor data curation workflow documented
- [ ] Hardening phase completed (input validation, error handling, compliance review)
- [ ] Git history clean with meaningful commits
- [ ] Deployed to GitHub Pages and verified live
- [ ] Bug Log current (even if empty)
- [ ] Architecture Decision Log reflects all v2 decisions
- [ ] This file fully updated with final state
- [ ] CPC MEMORY.md tool inventory updated

## Critical Business Rules

### 1. SEP Window Calculation (42 CFR § 422.62(b)(18))

This is the most compliance-critical logic in the entire tool. It must be implemented identically in both `index.html` (JavaScript) and `dst_data_fetcher.py` (Python).

```
SEP Start = earlier of declarationDate and incidentStart

If incidentEnd exists:
  SEP End = last day of the 2nd full calendar month after incidentEnd

  Algorithm:
    1. Take the MONTH of incidentEnd (ignore the day entirely)
    2. Add 2 to that month number
    3. Take the last day of the resulting month

  Examples:
    incidentEnd = Jan 15  → SEP End = March 31    (Jan + 2 = March, last day = 31)
    incidentEnd = Jan 31  → SEP End = March 31    (same month, same result)
    incidentEnd = Feb 28  → SEP End = April 30    (Feb + 2 = April, last day = 30)
    incidentEnd = Mar 31  → SEP End = May 31      (Mar + 2 = May, last day = 31)
    incidentEnd = Nov 15  → SEP End = January 31  (Nov + 2 = January next year)
    incidentEnd = Nov 30  → SEP End = January 31  (same month, same result)
    incidentEnd = Dec 31  → SEP End = Feb 28/29   (Dec + 2 = February, check leap year)

If incidentEnd is null (ongoing):
  Check for renewal/extension dates first.
  maxDate = latest of: sepStart, or any renewalDate in renewalDates array
  SEP End = last day of 14th full calendar month after maxDate

  Algorithm:
    1. Take the MONTH of maxDate
    2. Add 14 to that month number
    3. Take the last day of the resulting month

  If today > SEP End: disaster is EXPIRED → hide it

IMPORTANT: "2 full calendar months" is NOT "60 days."
  Jan 15 + 60 days = March 16
  Jan 15 + 2 calendar months = March 31
  Difference: 15 days. Getting this wrong is a compliance violation.
```

**CRITICAL BUG WARNING — DO NOT USE JavaScript Date.setMonth() for this calculation.**

JavaScript's `setMonth()` overflows when the day doesn't exist in the target month. For example, `new Date(2026, 0, 31).setMonth(1)` gives March 3, not February 28. This causes the entire window calculation to shift by a month for end-of-month dates.

**Correct JavaScript implementation:**
```javascript
function calculateSEPWindowEnd(incidentEnd) {
  const month = incidentEnd.getMonth(); // 0-indexed
  const year = incidentEnd.getFullYear();
  let targetMonth = month + 2;
  let targetYear = year;
  if (targetMonth > 11) {
    targetMonth -= 12;
    targetYear += 1;
  }
  // Day 0 of next month = last day of target month
  return new Date(targetYear, targetMonth + 1, 0);
}
```

**Correct Python implementation:**
```python
import calendar
from datetime import date

def calculate_sep_window_end(incident_end):
    month = incident_end.month
    year = incident_end.year
    target_month = month + 2
    target_year = year
    if target_month > 12:
        target_month -= 12
        target_year += 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    return date(target_year, target_month, last_day)
```

Both implementations ignore the day of incidentEnd entirely — they only use the month and year. This prevents the overflow bug.

### 2. This Tool Is for Medicare Advantage Only

We use the § 422.62 window (2 calendar months after incident end, 14-month max for ongoing). We do NOT use the § 406.27 window (6 months) which applies to Original Medicare Part A/B enrollment. These are different regulations with different timeframes.

### 3. Three-Part Validation

Per CMS guidance, agents must verify three things via verbal attestation:
1. Beneficiary resides (or resided) in the declared disaster area
2. Beneficiary was eligible for another enrollment period during the disaster
3. Beneficiary missed enrollment due to the disaster

The tool should display a compact reminder of these three requirements. This is informational — the tool does not enforce or track compliance. That's between the agent and their supervisor.

### 4. Expired DSTs Are Hidden

Never display a DST with an expired SEP window. Filter them out before rendering. "Expired" means today's date is after the calculated SEP end date.

### 5. Status Labels

```
ONGOING    — incidentEnd is null and within 14-month window
ACTIVE     — incidentEnd exists and SEP window has 31+ days remaining
EXPIRING SOON — incidentEnd exists and SEP window has 30 or fewer days remaining
(hidden)   — SEP window has passed
```

### 6. Every DST Must Link to the SPECIFIC Declaration (Not a Homepage)

Official links must go to the specific disaster declaration page, NOT the agency's general homepage or disaster index. An agent clicking the link should land on a page about that exact disaster.

**Acceptable:** `https://www.fema.gov/disaster/4834` (specific disaster page)
**Unacceptable:** `https://www.fema.gov/disasters` (general disaster listing)

If a specific URL cannot be found or verified, the DST should be flagged with "(general source page)" next to the link so agents know it doesn't go to the exact declaration.

If a URL is dead (404, 500, timeout), do NOT display that DST to agents. Log the issue for the maintainer to fix.

**URL patterns by source:**
- FEMA: `https://www.fema.gov/disaster/{disasterNumber}` — always specific, highly reliable
- HHS: Varies per PHE — each declaration has its own ASPR page
- SBA: `https://www.sba.gov/funding-programs/disaster-assistance/{slug}` — inconsistent, verify each
- USDA: Federal Register notice URL — specific to each designation
- FMCSA: `https://www.fmcsa.dot.gov/emergency-declarations/{slug}` — each emergency has its own page
- STATE: Varies by state — governor's office press release or executive order URL

**Fallback URLs (only when specific URL unavailable — always flagged in UI):**
- FEMA: `https://www.fema.gov/disaster/{NUMBER}` (specific — always available for FEMA)
- HHS: `https://aspr.hhs.gov/legal/PHE/Pages/default.aspx`
- SBA: `https://www.sba.gov/funding-programs/disaster-assistance`
- USDA: `https://www.fsa.usda.gov/resources/programs/disaster-assistance-programs`
- FMCSA: `https://www.fmcsa.dot.gov/emergency-declarations`

### 7. Copy Format for SunFire

When an agent clicks "Copy," the clipboard receives:
```
DST — {Disaster Title} ({Source} {Declaration ID})
SEP Window: {Start Date} — {End Date or "Ongoing"}
Official Declaration: {URL}
```

Dates in the copy output must be human-readable: "Jan 23, 2026" not "2026-01-23".

## Data Sources

### FEMA (Live API — fetched in browser)

```
URL: https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries
Auth: None
CORS: Enabled
Rate: 1000 requests/day recommended

Query: $filter=declarationDate ge '{24_MONTHS_AGO}'&$orderby=declarationDate desc&$top=1000&$skip={OFFSET}

Response: Array of records, one per county per disaster.
Must consolidate by femaDeclarationString to get one disaster with multiple counties.

Official link pattern: https://www.fema.gov/disaster/{disasterNumber}
```

**Date filter: 24 months.** This covers the 14-month maximum for ongoing disasters plus a safety buffer for late-ending incidents with 2-month post-incident windows.

**Pagination:** FEMA returns max 1000 records per request. A major hurricane season can generate 2000+ records (one per county per disaster). Implement a fetch loop:
1. Fetch with `$skip=0`
2. If response contains 1000 records, fetch again with `$skip=1000`
3. Continue until response has fewer than 1000 records
4. Combine all pages before consolidation

**Consolidation:** Group records by `femaDeclarationString` (e.g., "DR-4834-FL"). Collect all unique `designatedArea` values into the `counties` array. Use the declaration-level fields (declarationDate, incidentBeginDate, incidentEndDate, declarationTitle, incidentType) from any record in the group (they're identical across counties).

FEMA disasters include both "Major Disaster" (DR) and "Emergency" (EM) declarations. Both are valid DST triggers. Include both types. "Fire Management" (FM) declarations are NOT valid DST triggers — exclude them.

**Territory coverage:** FEMA covers all US territories. Use the `state` field which includes: PR, VI, GU, AS, MP.

### HHS Public Health Emergencies (Scraped)

URL to scrape: `https://aspr.hhs.gov/legal/PHE/Pages/default.aspx`
Identify active vs. expired PHEs on the page.
Curated fallback data maintained in the Python script for when scraping fails.

**Which HHS declarations qualify as DSTs:** Any Public Health Emergency (PHE) declared by the HHS Secretary under Section 319 of the Public Health Service Act qualifies as a valid federal government-declared disaster/emergency for DST purposes. Most PHEs are nationwide/statewide. Active PHEs are relatively rare (usually 0-3 at any time).

### FMCSA Emergencies (Scraped)

URL to scrape: `https://www.fmcsa.dot.gov/emergency-declarations`
Includes FMCSA regional emergencies. Also lists some state governor declarations that triggered transportation exemptions under 49 CFR § 390.23.

**IMPORTANT LIMITATION:** FMCSA only captures state declarations that involve motor carrier/transportation relief — roughly 15-25% of all governor emergency declarations. States are NOT required to notify FMCSA. Many state emergencies (droughts, public health, civil unrest, localized environmental incidents) will NOT appear on the FMCSA page. Do not rely on FMCSA as a comprehensive source of state declarations.

### Federal Register API (Primary Automated Collection for SBA + USDA)

The Federal Register API is the most important cross-cutting data source after FEMA. Every formal federal disaster declaration from SBA, USDA, and other agencies is published here. This API powers the automated collection of SBA and USDA disasters described in the sections below.

```
Base URL: https://www.federalregister.gov/api/v1/documents.json
Auth: None required (free, open access)
Rate limit: No formal limit, but be respectful (one query per source per run)
Format: JSON response with pagination

Key parameters:
  conditions[agencies][]  — Filter by publishing agency (e.g., "small-business-administration")
  conditions[type][]      — Document type (e.g., "notice", "rule")
  conditions[term]        — Full-text search term
  per_page                — Results per page (max 1000)
  page                    — Page number for pagination
  order                   — Sort order ("newest" recommended)

Useful agency slugs:
  small-business-administration          — SBA disaster loans
  farm-service-agency                    — USDA secretarial designations
  federal-emergency-management-agency    — FEMA (validation/cross-reference only)
```

**How to use it in the fetcher:**
1. Query for SBA notices containing "disaster loan" from the past 24 months
2. Query for FSA notices containing "secretarial designation" OR "disaster designation" from the past 24 months
3. Parse each result: extract title, publication date, affected states/counties from abstract/body
4. Use the Federal Register document URL as the official declaration link (e.g., `https://www.federalregister.gov/documents/2026/01/15/2026-00123/...`)
5. Cross-reference against existing curated data to avoid duplicates
6. For SBA results: add directly to curated_disasters.json if the notice clearly identifies a disaster declaration with affected areas
7. For USDA results: add directly if the notice is a secretarial designation with affected counties
8. For ambiguous results: log for manual review, do NOT auto-add

**Important:** Federal Register notices sometimes batch multiple counties or states into a single document. The parser needs to handle multi-state notices and extract each state's affected counties separately.

### SBA Disaster Loans (Federal Register API + Curated)

SBA has no public disaster API. Collection uses the Federal Register API (see above) as the primary method.

**Primary: Federal Register API (automated)**
Query: `conditions[agencies][]=small-business-administration`, `conditions[type][]=notice`, `conditions[term]=disaster+loan`, `per_page=50`, `order=newest`

Every SBA disaster loan declaration is published in the Federal Register as a formal notice. The fetcher queries daily, parses results for disaster loan declarations, extracts affected states/counties and declaration dates from the notice text. The Federal Register URL serves as the official declaration link (specific to each disaster, not a generic page).

**Secondary: Curated fallback**
Manually maintained array in the Python script for any SBA declarations the Federal Register query misses (rare, but possible for older declarations or unusual notice formats).

**Which SBA declarations qualify as DSTs:** SBA Physical Disaster Loan declarations (under Section 7(b)(1) of the Small Business Act) and SBA Economic Injury Disaster Loan (EIDL) declarations qualify. These are issued when the SBA Administrator determines that a disaster has caused substantial economic injury or physical damage. Each SBA declaration specifies affected counties. The Federal Register notice URL is the preferred official link.

### USDA Drought/Secretarial Designations (Federal Register API + Drought Monitor + Curated)

USDA has no single disaster API. Collection uses the Federal Register API (see above) as the primary method, supplemented by the Drought Monitor.

**Primary: Federal Register API (automated)**
Query: `conditions[agencies][]=farm-service-agency`, `conditions[type][]=notice`, `conditions[term]=secretarial+designation+disaster`, `per_page=50`, `order=newest`

Every USDA Secretarial Disaster Designation is published in the Federal Register. The fetcher queries daily, parses results for designation notices, extracts affected states/counties (including contiguous counties) from the notice text. The Federal Register URL is the official declaration link.

**Secondary: US Drought Monitor (discovery signal)**
```
URL: https://droughtmonitor.unl.edu/DmData/DataDownload/ComprehensiveStatistics.aspx
```
The Drought Monitor publishes weekly county-level drought severity data. While drought conditions alone don't trigger a DST (the secretarial designation does), the Drought Monitor serves as an early warning: when counties reach D3/D4 (Extreme/Exceptional) drought, a secretarial designation often follows. The fetcher flags these counties and logs a warning to check for upcoming designations.

**Tertiary: Curated fallback**
Manually maintained array for any USDA designations the Federal Register query misses or for designations that use non-standard notice formats.

**Which USDA declarations qualify as DSTs:** Secretarial Disaster Designations issued under the Consolidated Farm and Rural Development Act qualify. These are typically drought-related and specify affected counties (plus contiguous counties). The Federal Register URL is the preferred official declaration link.

### State Governor Declarations (FMCSA Scrape + Federal Register + Curated)

This is the hardest source to automate. No centralized national database of governor declarations exists. Collection uses a three-layer approach:

**Layer 1: FMCSA scrape (automated, ~15-25% coverage)**
The FMCSA emergency page lists state governor declarations that triggered transportation exemptions. The fetcher scrapes this daily. This captures governor declarations for major disasters (hurricanes, wildfires, winter storms) but misses declarations for non-transportation emergencies (droughts, public health, localized environmental incidents).

**Layer 2: Federal Register cross-referencing (automated, discovery signal)**
When a governor declaration triggers a federal response (FEMA, SBA, etc.), the Federal Register notice often references the underlying state declaration. The fetcher can extract these references and log them as potential state DSTs for review.

**Layer 3: Curated data (manual, critical for coverage)**
Manually maintained array in the Python script. This is the primary mechanism for governor declarations not captured by FMCSA. When you or your agents discover a governor declaration:
1. Tell Claude Code the disaster details (state, title, date, affected area, URL to executive order)
2. Claude Code adds it to the curated array in `dst_data_fetcher.py`
3. The next GitHub Actions run picks it up

**Coverage reality:** Starting coverage will be approximately 15-25% (FMCSA-captured declarations only). Coverage improves over time as curated data grows. The tool's UI should include a small note: "State governor declarations may not be comprehensive. Report missing declarations to your admin."

**Which state declarations qualify as DSTs:** Any emergency or disaster declared by a state's governor or equivalent executive authority qualifies. This includes executive orders, proclamations, and state-of-emergency declarations. The official URL should point to the specific executive order or proclamation page on the governor's website or state register.

## Data Schema

Every disaster record (from any source) must conform to this schema:

```json
{
  "id": "string — unique, format: SOURCE-ID-STATE",
  "source": "string — one of: FEMA, HHS, SBA, USDA, FMCSA, STATE",
  "state": "string — two-letter state code",
  "title": "string — human-readable disaster name",
  "incidentType": "string — Hurricane, Wildfire, Drought, etc.",
  "declarationDate": "string — ISO date YYYY-MM-DD",
  "incidentStart": "string — ISO date YYYY-MM-DD",
  "incidentEnd": "string|null — ISO date or null if ongoing",
  "renewalDates": "array|null — list of ISO date strings for renewals/extensions, or null",
  "counties": "array — list of county names, or ['Statewide']",
  "statewide": "boolean — true if covers entire state",
  "officialUrl": "string — verified URL to official declaration",
  "status": "string — calculated: ongoing, active, expiring_soon, expired (display as: ONGOING, ACTIVE, EXPIRING SOON, hidden)",
  "sepWindowStart": "string — calculated ISO date",
  "sepWindowEnd": "string|null — calculated ISO date or null",
  "daysRemaining": "number|null — days until SEP closes or null",
  "confidenceLevel": "string — verified, scraped, curated",
  "lastUpdated": "string — ISO timestamp",
  "lastVerified": "string|undefined — ISO date (YYYY-MM-DD) when entry was last verified, required for STATE/HHS"
}
```

## UI Requirements

### Search
- State dropdown (all 50 states + DC + PR + VI + GU + AS + MP)
- County text input with type-ahead autocomplete
- County list sourced from a static `county_state_map.json` file (derived from US Census Bureau FIPS county codes — ~3,200 entries)
- County name normalization: strip "(County)" suffix, case-insensitive matching, handle "St." vs "Saint" variants
- Results update instantly on county selection
- Show matching county-specific DSTs AND statewide declarations for selected state
- "No active DSTs found for {County}, {State}" when empty

### Sorting
Default sort: alphabetically by state, then by most recent declaration date within each state.

Sort options available to agents:
- **By State (A-Z)** — default, best for browsing all DSTs
- **Most Recent First** — sorted by declaration date descending, best for seeing what's new
- **Ending Soonest** — sorted by SEP window end date ascending (ongoing last), best for time-sensitive DSTs

### DST Cards
- Source badge (color-coded: FEMA blue, HHS red, SBA orange, USDA brown, FMCSA purple, STATE green)
- "Statewide" badge when applicable
- Disaster title and type
- Declaration ID
- SEP Window: start — end (or "Ongoing")
- Days remaining (for non-ongoing)
- Status badge (ONGOING / ACTIVE / EXPIRING SOON)
- Official declaration link (clickable, opens in new tab)
- Copy button

### Layout
- Professional, clean design appropriate for insurance/medical industry
- Light color scheme (not dark mode for MVP)
- Compact header: tool name, search bar, last-updated timestamp
- Results area: scrollable list of DST cards
- Footer: brief three-part validation reminder
- Desktop-optimized (1366px and 1920px widths)
- No mobile optimization needed for MVP

### Colors (Source Badges)
```
FEMA:  #3B82F6 (blue)
HHS:   #EF4444 (red)
SBA:   #F97316 (orange)
USDA:  #92400E (brown)
FMCSA: #A855F7 (purple)
STATE: #22C55E (green)
```

## Deduplication Rules

**By ID:** If the same `id` appears in both live FEMA data and curated data, keep the live FEMA version (it's more current). This prevents duplicate display.

**Same event, different sources:** Hurricane Helene may appear as FEMA-DR-4834-FL, HHS-HELENE-FL, and STATE-FL-HELENE. These are **three separate valid DSTs** because they come from different declaring authorities. Keep all of them. Each has its own source badge, declaration details, and copy output.

**Same FEMA disaster, multiple states:** DR-4834-FL and DR-4834-GA are separate records (different states, different county lists). Keep both.

**Curated JSON should NOT include FEMA disasters.** The frontend fetches FEMA live. The curated JSON contains only non-FEMA sources (HHS, SBA, USDA, FMCSA, STATE). This eliminates the FEMA deduplication issue entirely. The Python data fetcher may fetch FEMA for validation/logging, but should NOT write FEMA records to `curated_disasters.json`.

## Data Validation Rules

Before displaying any disaster record, validate:
1. `declarationDate` is not in the future (if it is, exclude the record)
2. `incidentStart` is not more than 24 months in the past (if it is, likely expired — calculate to confirm)
3. `incidentStart <= incidentEnd` if both exist (if reversed, flag as data error, exclude)
4. `officialUrl` is present and non-empty
5. `counties` array is non-empty
6. `state` is a valid US state/territory code
7. Calculated SEP window end date is in the future (if past, hide the record)

## Common Mistakes to Avoid

1. **"60 days" instead of "2 calendar months"** — These are different. Always use calendar months.
2. **Treating ongoing as indefinite** — Must enforce 14-month maximum. Check for renewal dates that reset the clock.
3. **Showing expired DSTs** — Filter before rendering, not after.
4. **One FEMA record = one disaster** — Wrong. FEMA returns one record per county. Must consolidate.
5. **Trusting curated URLs without verification** — Government sites change. Verify with HEAD requests.
6. **Forgetting statewide declarations** — When agent searches a county, also show statewide DSTs for that state.
7. **Duplicate DSTs from merge** — When merging live FEMA + curated FEMA, deduplicate by ID.
8. **ISO dates in copy output** — Always format as human-readable for agents.
9. **Not handling FEMA API pagination** — API returns max 1000 records per request. May need multiple pages.
10. **Crashing when FEMA API is down** — Degrade gracefully, show non-FEMA curated data with a warning banner. Do NOT cache FEMA data in curated_disasters.json.

## Testing

Run these checks after every significant change:
1. SEP window math: manually calculate 5 disasters, compare to tool
2. Official links: click 5 random links, confirm they work
3. Copy format: paste into Notepad, verify format
4. Search: try 3 counties, confirm correct results
5. Expired filter: no expired DSTs visible
6. Browser console: no JavaScript errors

## Maintenance Notes

**When a scraper breaks:**
1. Check the GitHub Actions log to identify which source failed
2. Visit the source website manually to see if the page layout changed
3. Update the scraper code in `dst_data_fetcher.py` to match the new layout
4. Curated fallback data will continue serving stale-but-valid data in the meantime

**When adding a new curated disaster:**
1. Add the record to the appropriate curated array in `dst_data_fetcher.py`
2. Follow the exact schema above
3. Verify the official URL works
4. Run the fetcher locally: `python3 dst_data_fetcher.py`
5. Commit and push — GitHub Actions will pick it up

**When CMS changes DST rules:**
1. Update the SEP window calculation in BOTH `index.html` and `dst_data_fetcher.py`
2. Update this CLAUDE.md with the new rules
3. Re-run all Section 4 test cases from the test document
