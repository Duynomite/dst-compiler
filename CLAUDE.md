# CLAUDE.md — DST Compiler Tool

## Project Status
- **Status:** v3.0 — Carrier Cross-Reference + FMAG Inclusion (Phase 1 complete)
- **Last Session:** 2026-03-27
- **Blocker:** None
- **Next Action:** **Expiring-Soon Visual Indicator** (badge on cards nearing SEP window end). Also: UI rendering of extension arrays on FL hurricane cards, carrier acknowledgment badges.
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
├── curated_disasters.json     # Non-FEMA disaster data (105 records, updated by fetcher)
├── all_disasters.json         # Curated + FEMA DR/EM combined (NEW v2.8)
├── medicare_enrollment.json   # County-level Medicare enrollment data (CMS, ~3,200 counties)
├── dst_data_fetcher.py        # Python pipeline: SBA/HHS/FMCSA/STATE/FEMA collectors
├── carrier_data_parser.py     # Carrier Excel parser + cross-referencer (v3.0)
├── carrier_analysis.json      # Carrier match/gap/discrepancy data (v3.0 output)
├── carrier_gaps.json          # Research queue: 135 missing DSTs (v3.0 output)
├── carrier_report.md          # Human-readable gap report (v3.0 output)
├── carrier_intelligence.md    # Source discovery + process improvements (v3.0 output)
├── audit_curated_data.py      # Validation script (28 checks per record, dual-mode)
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
[Updated 2026-03-27 — v3.0 Phase 3 Session 2: Carrier Gap Fills]
- **v3.0 Phase 3 DEPLOYED** at `duynomite.github.io/dst-compiler/`
- **Dual output pipeline**: `curated_disasters.json` (184 records, non-FEMA) + `all_disasters.json` (235 total, curated + FEMA DR/EM/FM)
- **FEMACollector**: Live OpenFEMA API, DR/EM/FM (FM re-included per carrier data analysis)
- **184 curated records** (66 FMCSA + 9 SBA + 111 STATE + 1 HHS) — **+20 records this session from carrier cross-reference gap fills**
- **FL Hurricane Extension Arrays**: Full EO chains documented for Debby (10 extensions), Helene (7), Milton (7). Extensions data model populated for first time.
- **Carrier gap resolution**: 44 remaining gaps → 26 after fuzzy matching + FEMA API analysis. 10 expired, 8 matched existing FM records, all 16 unmatched wildfires have expired FEMA FM records (carrier uses longer windows than regulatory 2-month calc).
- **FL Israel EO 23-208**: Confirmed expired ~Nov 8, 2025. Last extension EO 25-183 (Sep 9). No further renewals found.
- **FL Milton**: Confirmed expired Jan 24, 2026 per Humana data. incidentEnd set. SEP ends Mar 31, 2026.
- **FL data corrections**: May 2024 Tornadoes (end 2025-12-23), Lake County Flooding (end 2025-12-28), NW FL Tornadoes (end 2026-01-06), OH winter storm (end 2026-04-26) — all per Humana carrier data.
- **NY EO 57 URL fix**: Was pointing to EO 55 (Dec 26 storm). Corrected to EO 57 URL.
- **Audit**: 4,233/4,235 + 5,406/5,408 checks pass (1 expected HHS PHE expiry + 1 PR non-gov URL domain)
- **Full audit results** (this session):
  - FEMA API: 18 active disasters, 155 expired (filtered)
  - SBA: 9 active records verified against Federal Register source documents
  - FMCSA: 66 records across 4 declarations (2025-012 extended to Mar 14 + 4 new states)
  - STATE: 36 records across 28 states (18/29 original URLs broken — replacement search in progress)
  - HHS: 1 record — PHE 90-day limit flagged as expired
  - 2,578/2,579 audit checks pass (1 expected HHS PHE expiry failure)
- **Fixes applied this session (Mar 27, 2026)**:
  - FMCSA-2025-012: End date Feb 28 → Mar 14 (new extension found). Added NC, OH, RI, VA (4 new states, 15 total)
  - FMCSA-2025-013: End date Feb 15 → Feb 28 (extension confirmed via PA Propane Gas Assn). Previous session's "2025-012 only" determination was incorrect.
  - Added SBA-2026-04576-PA (Hotel Hampton Fire, Feb 20 2026) + SBA-2026-04576-NJ (contiguous, Warren County)
  - Added 7 new STATE declarations: FL (wildfires), MI×2 (tornadoes + blizzard), MO (tornadoes), NE (wildfires), OK (tornadoes), RI (blizzard)
  - 4 FEMA records updated from ONGOING to closed: EM-3641-IN, EM-3634-MD, EM-3639-WV (Jan 27), EM-3643-DC (Mar 14)
  - HHS-2025-001-WA: PHE 90-day statutory limit flagged as expired
- **Pipeline improvements (v2.9)**:
  - PHE 90-day expiry tracker: fetcher warns when PHEs approach/pass statutory limit; audit Check 28 validates
  - SBA parser: now matches amendment titles + fallback contiguous county regex
  - URL archive fallback: Wayback Machine lookup for failed URLs + proactive snapshot submission
  - Archive link display in index.html DSTCard component
  - Weekly monitoring scheduled task (dst-weekly-monitor) — checks pipeline health, new declarations, broken URLs every Monday
- **36 governor declarations** covering 28 states + DC
- **1 HHS PHE** (Washington State severe weather — 90-day expiry flagged)
- FEMA live API: Healthy, 18 active disasters
- GitHub Actions cron: Running daily at 6AM EST + weekly Monday 10AM EST
- **eCFR regulatory monitoring**: § 422.62 confirmed UNCHANGED (effective since 2024-06-03) — runs weekly in CI
- **Coverage Gap Analyzer**: 12 FMCSA→STATE gaps flagged for research
- SEP calculations: Verified correct for all edge cases (end-of-month, leap year, year boundary)
- Data integrity pipeline:
  - **Audit script runs in CI** — gates every commit on 27 checks per record (added FEMA URL + domain validation)
  - **Dual audit in CI** — curated_disasters.json (strict) + all_disasters.json (FEMA-tolerant)
  - **Per-source record count thresholds** — blocks if any source drops >20% or to zero; FEMA=0 is warning only
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
1. ~~**URL Verification System**~~ **DONE (v2.1)**
2. ~~**eCFR Regulatory Monitoring**~~ **DONE (v2.2)**
3. ~~**Coverage Gap Analyzer**~~ **DONE (v2.3)**
4. ~~**Carrier Cross-Reference + FMAG**~~ **DONE (v3.0 Phase 1)**
5. ~~**Carrier Gap Research (85 governor declarations)**~~ **DONE (v3.0 Phase 2)** — 135→48 gaps (64% reduction), +29 STATE records
6. ~~**FL Hurricane Extension Arrays**~~ **DONE** — Debby (10 EO extensions), Helene (7), Milton (7). Aug 7 Debby date was CFO/FDACS, not governor. Helene had missing Nov 7 extension. Milton had missing May 30 extension.
7. ~~**Name-matching pass on 48 remaining gaps**~~ **DONE** — Fuzzy matcher + FEMA API: 10 expired, 8 matched FM records, 16 have expired FM records (carrier window discrepancy), 5 already covered under different names, 5 genuinely missing → 2 added (HI rains, GA ID fix), 2 expired (CO flooding, KS Dec fire), 1 already existed (KS Feb).
8. **Expiring-Soon Visual Indicator** — Orange/red badge on cards nearing SEP window end
9. **Federal Register API reliability** — API returns inconsistent results in GitHub Actions. Per-source safeguard blocks data loss.
10. ~~**Verify FL Israel EO 23-208 status**~~ **DONE** — Expired ~Nov 8, 2025 (last extension EO 25-183, Sep 9). No further renewals found. Correctly absent from tool.
11. ~~**Push main repo**~~ **DONE**
12. ~~**Verify FL Milton expiry**~~ **DONE** — Confirmed expired Jan 24, 2026 per Humana data. incidentEnd set. SEP ends Mar 31, 2026.
13. **UI: Render extensions in DSTCard** — Extension arrays populated but not displayed. Show EO chain timeline on FL hurricane cards.
14. **UI: Carrier acknowledgment badges** — Show Aetna/Wellcare badges on matched DST cards.
15. **PR URL improvement** — Replace ayudalegalpr.org with official docs.pr.gov URL for OE-2025-022 when found.
16. **PR OE-2024-004 research** — Landslides declaration from Wellcare data. Could not find official EO. Try docs.pr.gov directly.
17. **22 records expiring Mar 31** — Multiple STATE and SBA records have SEP windows ending 2026-03-31. After expiry, they'll auto-hide from the tool.

## Known Issues
- USDA: Confirmed NOT a valid DST trigger for Medicare — USDA drought designations are agricultural loan programs, not disaster declarations under 42 CFR 422.62(b)(18)
- ~~Some governor declaration URLs point to general governor pages (OH, MO, KS)~~ **RESOLVED 2026-02-12** — all 24 STATE URLs now verified, 8 fixed
- ~~Some FMCSA entries may have outdated incident end dates~~ **RESOLVED 2026-02-16** — Updated 2025-012 (Feb 28 extension, +ME/VT), 2026-001 (Feb 20 extension), added 2025-014 WA
- ~~**43 expired SBA records showing as active**~~ **RESOLVED 2026-02-16** — Parser bug: single-day incidents classified as "ongoing". Fixed with Pattern 4 regex + 10 curated overrides.
- ~~**All 28 STATE URLs returning 404**~~ **FALSE ALARM 2026-02-16** — Re-tested with proper User-Agent: 26/28 return 200 OK with correct page titles. TN has server-side connection reset, MS has known SSL issue. Initial test was likely affected by missing User-Agent header or transient network issue.
- **12 FMCSA→STATE coverage gaps** flagged by analyzer — most are advisory (FMCSA covers 30-40 states broadly). Added FL, MI, MO, NE, OK, RI this session. Remaining: VT, NH, WI, IA, IL, MN, CO, ND, SD, WY, MT, WA
- ~~**4 remaining ongoing SBA records need verification**~~ **RESOLVED 2026-02-16** — IL/IN/MN were expired single-day events (fixed with curated overrides). AK wildfire confirmed truly ongoing per FR text ("and continuing").
- ~~**FMCSA-2025-014-WA cannot be verified**~~ **VERIFIED 2026-02-16** — Declaration confirmed to exist via FMCSA PDF. Extended Dec 23 to Jan 23, 2026 (expired). SEP window active through Mar 31, 2026.
- **FMCSA-2026-001 expired Feb 20** — No extension found. SEP window remains active through April 30, 2026.
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
| 19 | 2026-02-17 | Banner beneficiary count overcounting by ~3.5M | Medium | Fixed | Used full state totals for county-only SBA disasters (AK, AZ, CA, NV). Replaced simple state-level dedup with statewide vs county-level logic. Banner: ~66.1M → ~62.5M. |
| 20 | 2026-02-17 | Missing MA governor declaration (Gov. Healey, Jan 23 2026) | Medium | Fixed | Winter storm/heating fuels emergency. Referenced by FMCSA. Added as STATE-2026-001-MA (statewide). |
| 21 | 2026-03-27 | FMCSA-2025-012 end date wrong + 4 missing states | **Critical** | Fixed | Extension to Mar 14, 2026 missed (was Feb 28). Added NC, OH, RI, VA. Previous session incorrectly noted "VA is NOT included" — Feb 27 extension added it. |
| 22 | 2026-03-27 | FMCSA-2025-013 end date wrong | Medium | Fixed | Extension to Feb 28 was incorrectly attributed to 2025-012 only. Confirmed via PA Propane Gas Assn that 2025-013 was also extended to Feb 28. |
| 23 | 2026-03-27 | 18/29 STATE URLs broken (404/403/SSL) after 33 days | High | Partial | 5 fixed (IN, KY, ME, NY, PA). Remaining ~13 may be transient (many matched agent-found URLs already in code). Weekly monitor will re-check Monday. |
| 24 | 2026-03-27 | HHS-2025-001-WA PHE 90-day limit likely lapsed | Medium | Monitoring | 90-day statutory limit from Dec 24 = Mar 24. CMS still lists as "current emergency" (page updated Mar 16). No renewal or termination notice found. Treated as active pending verification. |
| 25 | 2026-03-27 | 12+ missing STATE/SBA declarations (Feb-Mar 2026) | High | Fixed | "Blizzard of 2026" (Feb 22-24), OK/MI/MO tornadoes (Mar), NE wildfires (Mar), PA Hotel Fire (SBA). Added 7 STATE + 2 SBA records. |

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
| 2026-02-17 | Banner dedup: statewide vs county-level distinction | States with ONLY county-specific disasters (AK, AZ, CA, NV) should sum county enrollments, not full state totals. Prevents ~3.5M overcount. Fallback to full state if no county names match enrollment data. | Always use full state totals (rejected: inflates number by 5.6%) |
| 2026-02-17 | RI and TX tornado declarations NOT added despite initial research suggesting them | RI: only preparedness measures found, no formal EO. TX tornado: URLs were from June 2023 Perryton tornado, not Feb 2026. Accuracy > coverage. | Add with low confidence (rejected: compliance tool must be certain) |
| 2026-02-17 | Medicare enrollment data integrated into banner and state headers | Shows ~62.5M affected beneficiaries across 47 states. County-level granularity for SBA-only states. Data from CMS Monthly Enrollment (Oct 2025). | Per-card beneficiary counts (rejected: too noisy for agent workflow) |
| 2026-02-22 | FEMA API integration via FEMACollector in Python pipeline | Fetches live DR/EM declarations from OpenFEMA API into all_disasters.json. Frontend still fetches FEMA live; backend now also captures for audit/analysis. Dual output: curated (strict) + all (FEMA-tolerant). | FEMA in curated JSON (rejected: dedup complexity), frontend-only FEMA (existing: maintained) |
| 2026-02-22 | FM (Fire Management) declarations excluded from FEMA data | 6-layer regulatory analysis: 42 CFR 422.62(b)(18) uses Stafford Act terms "emergency or major disaster"; FM is neither (42 USC 5187). Medicare.gov doesn't list FEMA Administrator as declaring authority. Carriers don't recognize FM. ClearMatch anomaly = concurrent governor/DR declarations. | Include FM (rejected: compliance risk, FM is not "emergency" or "major disaster" under Stafford Act) |
| 2026-02-22 | Dual-mode audit (curated vs all_disasters) | curated_disasters.json gets strict validation (no FEMA allowed); all_disasters.json gets FEMA-tolerant validation (FEMA=0 is warning, not failure). Separate CI steps with different flags. | Single audit mode (rejected: different validation rules needed) |
| 2026-03-27 | PHE 90-day statutory expiry tracking | HHS PHEs expire after 90 days (Section 319 PHS Act) unless renewed. Added automatic tracking in fetcher + audit Check 28. Prevents silent expiration where record stays "ongoing" indefinitely. | Manual monitoring only (rejected: WA PHE proved this fails) |
| 2026-03-27 | **REVERSED: FM/FMAG declarations NOW INCLUDED** | Carrier data analysis (Aetna 109, Wellcare 3,885, Humana PDF) revealed all 3 major carriers honor FMAG as valid DST triggers — 36 active FMAG records tracked by Wellcare alone. v2.8 excluded FM per Stafford Act analysis (FM ≠ "major disaster" or "emergency"). But agents need the same DSTs carriers honor, and the accompanying governor declarations ARE valid under § 422.62(b)(18). Pragmatic compliance: include FM with FEMA URLs, let the governor declaration be the legal basis. | Keep FM excluded (rejected: agents can't enroll beneficiaries for carrier-honored DSTs) |
| 2026-03-27 | Carrier data as discovery + validation + acknowledgment | Parsed Aetna + Wellcare Excel files. 100 matched to our data, 135 gaps (missing from us), 73 SEP window discrepancies. Government sources remain authoritative for dates/links. Carrier data used to discover gaps and validate. Future: show carrier acknowledgment badges on DST cards. | Carrier data as primary source (rejected: compliance risk), Carrier data ignored (rejected: missing 135+ valid DSTs) |
| 2026-03-27 | Carrier intelligence as process improvement driver | Analyzed carrier data collection patterns to improve our pipeline. Key findings: NIFC/InciWeb for wildfire discovery, US Drought Monitor for drought emergencies, municipal declarations for local emergencies. Carrier data serves as early warning system for new governor declarations. | One-time import only (rejected: loses ongoing intelligence value) |
| 2026-03-27 | Wayback Machine archive fallback for STATE URLs | Governor sites rotate/archive pages (62% failure rate after 33 days). Archive.org snapshots persist. Proactive snapshots on weekly URL verification + fallback lookup for failed URLs. | Accept URL rot (rejected: compliance tool requires working declaration links) |
| 2026-03-27 | Weekly Claude Code scheduled task for monitoring | Automated monitoring catches staleness before it becomes a 33-day gap. Checks: pipeline health, new SBA/FMCSA/HHS declarations, STATE URL health, expiring DSTs. ~15 min/week human review vs periodic full audits. | Manual-only monitoring (rejected: proven to miss entire weather seasons) |
| 2026-03-27 | HHS WA PHE treated as active despite 90-day flag | CMS "Current Emergencies" page (updated Mar 16) still lists it. No termination found. PHE renewals are administrative and don't always generate public notices. Conservative compliance approach = treat as active. | Set incidentEnd to Mar 24 (rejected: CMS listing suggests renewal occurred) |

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
| 2026-02-17 | Audit + Banner Fix + MA Declaration | (1) Full-scale audit: 5 parallel audit tracks (data integrity, SEP calculations, enrollment dedup, beneficiary counts, missing declarations). (2) Fixed banner beneficiary overcounting: replaced simple state-level dedup with statewide vs county-only logic (~66.1M → ~62.5M, saving 3.5M overcount from AK/AZ/CA/NV). (3) Added MA governor declaration (STATE-2026-001-MA, Gov. Healey Jan 23 2026 winter storm). (4) Verified RI (no formal EO) and TX tornado (URLs from 2023, not 2026) — NOT added. (5) Medicare enrollment analysis: 34.7M beneficiaries in ongoing DSTs (55.6% of total). (6) Deployed v2.7 to GitHub Pages. | v2.7 ✅ | 2103/2103 (100%) |
| 2026-02-22 | FEMA API Integration + FM Compliance Research | (1) Added FEMACollector class to dst_data_fetcher.py — fetches live DR/EM from OpenFEMA API, excludes FM. (2) Dual output: curated_disasters.json (unchanged) + all_disasters.json (curated + FEMA). (3) Updated audit with FEMA checks 26-27, --all-disasters flag. (4) Updated CI workflow with dual audit, FEMA-aware record count validation. (5) Updated frontend with FEMA source support. (6) Deep regulatory research on FM exclusion: 6-layer analysis (Stafford Act, CFR, Medicare.gov, SSA POMS, carriers, industry) confirms FM is NOT "emergency" or "major disaster" per 42 CFR 422.62(b)(18). (7) All validation passed: 2335 curated + 2731 all-disasters checks (100%). (8) Merged to main via PR #11. | v2.8 ✅ | 2335+2731 (100%) |
| 2026-03-27 | Full 118-DST Audit + Pipeline Freshness | (1) Audited all 118 DSTs: 7 expired SBA, 4 FEMA date changes, 2 FMCSA extensions missed, 18/29 STATE URLs broken, HHS PHE likely expired, 12+ missing declarations. (2) Added PHE 90-day expiry tracker (fetcher + audit Check 28). (3) SBA parser improvements (amendment matching + contiguous fallback regex). (4) Wayback Machine archive fallback for STATE URL rot. (5) Data corrections: 118→130 records (FMCSA-012 extended to Mar 14 + 4 new states, FMCSA-013 extended to Feb 28, PA Hotel Fire + NJ contiguous, 7 new STATE declarations). (6) Fixed 5 broken STATE URLs. (7) Created weekly monitoring scheduled task. (8) Deployed to GitHub Pages. | v2.9 ✅ | 2578+2992 (100%, 1 expected HHS fail) |
| 2026-03-27 | v3.0 Phase 1: Carrier Cross-Reference + FMAG | (1) Built `carrier_data_parser.py` — standalone tool parsing Aetna (108 records) + Wellcare (132 active) Excel files. (2) Cross-referenced against curated_disasters.json: 100 matched, 135 gaps, 73 SEP discrepancies. (3) Generated 4 reports: carrier_analysis.json, carrier_gaps.json, carrier_report.md, carrier_intelligence.md. (4) Intelligence findings: 57 missing wildfires, 36 FMAG records carriers honor, carrier URL domains to monitor, amendment/renewal patterns. (5) **REVERSED FM/FMAG exclusion** — all 3 carriers honor FMAG; added 33 FM fire records to FEMA pipeline. Updated both Python fetcher and JS frontend. (6) Added `extensions` + `carrierAcknowledgments` optional fields to `build_record()` (backward-compatible). (7) Added openpyxl dependency. (8) Audit: 2578/2579 pass (no regression). | v3.0 Phase 1 ✅ | 2578/2579 (no regression) |
| 2026-03-27 | v3.0 Phase 2: Carrier Gap Research | (1) Triaged 135 carrier gaps: 60 already captured, 75 new → 58 unique events after Aetna/Wellcare dedup. (2) Launched 4 parallel research agents across 25+ states (FL hurricanes, OR/NM/AK, TX/OK/MT/KS+12 others, non-standard DST validity). (3) Added 29 new STATE records across 16 states: FL (7: Debby/Helene/Milton hurricanes, 2024+2025 tornadoes, Lake County flooding, immigration), TX (4: border crisis, drought, flooding, wildfires), OR (5: Alder Springs, Rowena, statewide wildfire, homelessness, Dec storms), NM (6: Española+Albuquerque crime, Cotton Fire, Lincoln+Dona Ana floods, Torrance water), NY (1: vaccine access EO 52), AK (3: windstorm, winter storm, power outage), KY (plane crash), MN (wildfires), LA (Tallulah water + Hurricane Ida 4yr renewal), MA (blizzard), OK (wildfires), MT (flooding + wind), CT (blizzard), GA (water supply), NE (power), UT (wildfires). (4) Non-standard DSTs validated: crime emergencies (NM), homelessness (OR), immigration (FL/TX), healthcare/vaccine (NY), infrastructure (LA/GA/NM). (5) Audit fixes: FM ID validation, --all-disasters file path, Check 8 accepts long-running declarations with recent renewals. (6) Deployed to GitHub Pages. | v3.0 Phase 2 ✅ | 3981/3982 (1 expected HHS) |
| 2026-03-27 | v3.0 Phase 2 Continued: Extensions + Gap Resolution | (1) FL Hurricane Extension Arrays: researched full EO chains via 3 parallel agents. Debby: 10 extensions (removed Aug 7 CFO/FDACS date, not governor). Helene: 7 extensions (added missing Nov 7 EO 2025-231, corrected dates ±1-2 days). Milton: 7 extensions (added missing May 30 EO 2025-119); WARNING: no 2026 renewals found, may have expired ~Jan 24, 2026. (2) Fuzzy gap matcher built (fuzzy_gap_matcher.py): 44 gaps → 10 expired + 8 matched existing FM + 5 already covered under different names + 16 expired FM (carrier window discrepancy) + 5 genuinely missing. (3) FEMA API analysis: all 47 "missing" FM records have expired SEP windows per 2-month calc. Carriers use 12-14 month windows — regulatory discrepancy documented. (4) FL Israel EO 23-208: confirmed expired ~Nov 8, 2025 (last extension EO 25-183, Sep 9). Not in our tool, correctly absent. (5) Added HI Feb 20-22 rains (STATE-2026-002-HI, Proclamation 2602068). Fixed GA Spalding County ID collision (STATE-2026-001 → 003). CO flooding expired per 2-month calc (correctly excluded by build_record). (6) New analysis files: carrier_gap_analysis.md, gap_match_results.json. | v3.0 Phase 2+ ✅ | 4027+5200 (1 expected HHS) |
| 2026-03-27 | v3.0 Phase 3 Session 2: Carrier Gap Fills | (1) Applied 5 P2 data corrections from Humana carrier data: FL Milton incidentEnd=2026-01-24, FL May 2024 Tornadoes end=2025-12-23, FL Lake County Flooding end=2025-12-28, FL NW FL Tornadoes end=2026-01-06, OH winter storm end=2026-04-26. (2) 4 parallel research agents across PR, CA, NY/NJ/DE, FL+others. (3) Added 20 new records: CA (8: Pack Fire, Tsunami, Aug Storms, Monsoons, Gifford Fire, Windstorm, Sept Storm, Dec Storms), NJ (4: EO 409 winter, EO 392 flooding, EO 394 flooding, EO 14 nor'easter), NY (2: EO 55 Dec winter storm, EO 58 Feb nor'easter), DE (1: Feb nor'easter), WI (1: EO 272 flooding), PA (1: Feb blizzard), NM (1: EO 2025-362 Mora flooding), HI (1: Lahaina wildfires 27th+ proclamation since Aug 2023), PR (1: OE-2025-022 April rains, 28 municipalities). (4) Fixed NY EO 57 URL (was incorrectly pointing to EO 55). (5) Skipped: CA Forest Mgmt (preventive), CA LA Board Resolution (immigration), NY EO 56 (healthcare strike), WY EO 2025-08 (govt shutdown), 2 unconfirmed PR records. (6) carrier_intelligence_v2.md written. (7) Audit: 4233/4235 + 5406/5408 (2 expected: HHS PHE expiry + PR non-gov URL). | v3.0 Phase 3 ✅ | 4233+5406 (2 expected) |

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

FEMA disasters include both "Major Disaster" (DR) and "Emergency" (EM) declarations. Both are valid DST triggers. Include both types. "Fire Management" (FM) declarations are NOT valid DST triggers — exclude them. FM is a separate Stafford Act category (42 USC 5187), not an "emergency" or "major disaster" as required by 42 CFR 422.62(b)(18). FM is declared by the FEMA Administrator, not the President. Medicare.gov lists only President, HHS Secretary, and Governor as qualifying declaring authorities. Qualifying wildfires are captured via governor STATE declarations and/or subsequent DR declarations.

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
