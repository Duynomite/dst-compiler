# DST Compiler Tool — Handoff Summary

## What We're Building

A standalone tool that finds every valid disaster declaration (DST) that triggers a Medicare Advantage Special Enrollment Period, and lets agents copy the details into SunFire enrollment applications.

## Key Decisions Made

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Enrollment type | Medicare Advantage only (§ 422.62) | Agents sell MA plans. Part A/B uses different window calculation (6 months vs 2 months). |
| SEP window | 2 full calendar months after incident end | Per § 422.62(a)(6). NOT 60 days — calendar months. |
| Max duration | 14 months for ongoing disasters | Per § 422.62 — incident end defaults to 1 year from start if not defined. |
| Search method | County + State | Counties match how FEMA designates disasters. ZIP adds complexity with minimal benefit since agents know both. |
| Data architecture | Live FEMA API + Federal Register API for SBA/USDA + scrapers + curated JSON | FEMA has a free public API with CORS. Federal Register API automates SBA/USDA discovery. Everything else scraped server-side or curated. |
| Automation | GitHub Actions daily cron | Free, no server to maintain, version history, failure notifications. |
| Deployment | GitHub Pages (standalone MVP) | Free hosting, one URL to bookmark. WordPress embedding comes later. |
| Expired DSTs | Hidden completely | Agents should only see what's actionable. No filtering required on their end. |
| Multi-source same event | Show each separately | FEMA DR-4834 and STATE-FL-HELENE are different valid DST triggers under different authorities. |
| Copy format | Plain text for SunFire | DST name/ID, SEP window dates, official URL — three lines, clean paste. |

## What's Different From the Previous Build

| Previous Build | This Build | Why |
|---------------|-----------|-----|
| Full SEP Analyzer with 35+ SEP types | DST-only tool | Sharper focus, higher quality on the one thing that matters most |
| Hardcoded curated data that went stale | Automated daily updates via GitHub Actions | Non-FEMA data stays fresh without manual checks |
| SBA/USDA relied entirely on manual curation | Federal Register API automates SBA/USDA discovery | Every SBA disaster loan and USDA secretarial designation is published in the Federal Register — automated query catches ~80-90% |
| No 14-month maximum enforcement | Enforces 14-month max with renewal/extension support | Previous build let ongoing disasters live forever; renewals correctly reset the clock |
| **SEP window bug for end-of-month dates** | Bug-free algorithm that ignores the day | Previous build's `setMonth()` overflowed on Jan 31, Mar 31, etc. — showing windows a month too long |
| Single massive HTML file with everything | Separated data (JSON) from display (HTML) | Easier to update data without touching UI code |
| No link verification | URL verification on every data update | Agents never see broken links |
| Links sometimes went to agency homepage | Links must go to specific declaration page | Generic homepage links are flagged in UI |
| ZIP + county search with 41,000-entry mapping | County + state only | Simpler, more accurate, fewer things to break |
| No data freshness indicator | Last-updated timestamp | Agents know data is current |
| SEP window for Part A/B and MA mixed together | MA-only (§ 422.62) | Correct regulation for the actual use case |
| One sort order only | Three sort options (state, recent, ending soonest) | Agents can find what they need in different contexts |
| Overstated FMCSA coverage of state declarations | Honest ~15-25% estimate with clear documentation | FMCSA only captures transportation-related state emergencies |

## Architecture in One Sentence

A single HTML file that fetches live FEMA data from the browser and loads a daily-updated JSON file of non-FEMA disasters (collected via Federal Register API, web scrapers, and curated data), all hosted for free on GitHub Pages with automated data refreshes via GitHub Actions.

## Build Order (ALL PHASES COMPLETE)

1. **Phase 1:** HTML tool with live FEMA data + search + display — ✅ COMPLETE
2. **Phase 2:** Copy button formatted for SunFire — ✅ COMPLETE
3. **Phase 3:** Python data fetcher for non-FEMA sources — ✅ COMPLETE
4. **Phase 4:** Integrate non-FEMA data into the frontend — ✅ COMPLETE
5. **Phase 5:** GitHub Actions automation + GitHub Pages hosting — ✅ COMPLETE
6. **Phase 6:** UI polish — ✅ COMPLETE
7. **Phase 7:** End-to-end testing and verification — ✅ COMPLETE
8. **Full-Scale Audit:** 2,480+ checks, 0 user-facing bugs — ✅ COMPLETE
9. **GitHub Deployment:** Live at https://duynomite.github.io/dst-compiler/ — ✅ COMPLETE

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Government website changes break scraper | Medium (1-2x per year) | Non-FEMA data goes stale | Curated fallback data keeps serving. GitHub Actions creates an issue. Fix via Claude Code. |
| FEMA API goes down | Low | No live FEMA data | Frontend shows non-FEMA curated data only with warning banner. FEMA data is NOT stored in curated JSON. |
| CMS changes DST enrollment rules | Low-Medium | Tool may show wrong windows | Monitor CMS memos. Rules change slowly with advance notice. |
| SBA/USDA disasters missed by automation | Medium | Some DSTs not captured | Federal Register monitor flags new declarations. Edge cases added via curated data. |
| Connor forgets to check GitHub Issues | Medium | Broken scraper goes unnoticed | Could add email notification in a future iteration. |

## Compliance Notes

- **CMS March 2025 memo confirmed:** Agents can continue processing DST enrollments through carriers (SunFire). The December 2024 restriction was withdrawn.
- **Election code:** Agents submit enrollment using election code `SEP DST` in SunFire.
- **Three-part validation:** Tool includes a reminder but does not enforce — agents verify verbally.
- **Documentation:** The official declaration URL in the copy output serves as the agent's documentation of the DST basis for enrollment.

## Files to Deliver to Claude Code

When starting the first build session, provide Claude Code with:

1. `CLAUDE.md` (from `planning/05_CLAUDE.md` — rename to `CLAUDE.md` in the project root)
2. `planning/01_PRD.md` (for context if needed)
3. `planning/03_BUILD_PLAN.md` (for phase-by-phase instructions)

The CLAUDE.md is the primary instruction file. The PRD and Build Plan are reference materials.

## Current State (Feb 7, 2026)

The tool is fully built, audited, and deployed. All phases are complete.

**Live URL:** https://duynomite.github.io/dst-compiler/
**GitHub Repo:** https://github.com/Duynomite/dst-compiler (public)
**Data:** 128 active DSTs (16 FEMA live + 53 SBA + 59 FMCSA curated)

### Pending Items
- **GitHub Actions first run**: The daily cron (6AM EST) hasn't fired yet. May need debugging on first run (Python deps, write permissions). Can be triggered manually from the Actions tab.
- **FMCSA data expiring**: All 3 FMCSA declarations have incident end dates in Feb 2026. SEP windows expire April 2026. Record count will drop unless new emergencies declared.
- **SBA-2024-28528-CA (Mountain Fire)**: 14-month max expires Feb 28, 2026. Will auto-hide after that.

### Next Session Instructions
If resuming work, read MEMORY.md first (in `.claude/projects/.../memory/MEMORY.md`). It has full technical context, audit results, deployment info, and known issues. The CLAUDE.md in the project root has business rules and compliance requirements.
