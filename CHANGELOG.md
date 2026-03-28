# DST Compiler — Changelog

> Complete history of sessions, bugs, and architectural decisions.
> For operational procedures, see RUNBOOK.md. For session context, see CLAUDE.md.

---

## Version History

| Version | Date | Records | Audit | Summary |
|---------|------|---------|-------|---------|
| v1.0 | 2026-02 | ~50 | N/A | Initial build — FEMA API + basic curated data |
| v2.0 | 2026-02-11 | 105 | 2644/2644 | Governor backfill, CPC brand UI, 5-phase build |
| v2.1 | 2026-02-12 | 105 | 2783/2783 | Data integrity protocol, URL verification, eCFR monitoring |
| v2.3 | 2026-02-16 | 146 | 2923/2923 | Coverage gap analyzer, 4 new STATE + FMCSA records |
| v2.4 | 2026-02-16 | 103 | 2063/2063 | Critical SBA parser fix (43 false ongoing removed) |
| v2.5 | 2026-02-16 | 104 | 2083/2083 | Full audit + FMCSA corrections |
| v2.7 | 2026-02-17 | 105 | 2103/2103 | Banner fix, MA declaration, enrollment data |
| v2.8 | 2026-02-22 | 105+FEMA | 2335+2731 | FEMA API in pipeline, FM exclusion (later reversed) |
| v2.9 | 2026-03-27 | 130 | 2578+2992 | Staleness audit, 12+ missing records, PHE tracker |
| v3.0 P1 | 2026-03-27 | 175 | 2578/2579 | Carrier cross-reference, FMAG reversed, carrier_data_parser |
| v3.0 P2 | 2026-03-27 | 188 | 3981/3982 | 29 new STATE records from carrier gap research |
| v3.0 P3 | 2026-03-27 | 166→164 | 3775+4948 | Verification framework, carrier badges, URL fixes, ongoing audit |
| v3.0 Final | 2026-03-28 | 164 | 3775+4948 | Verifier + renewal checker, AZ law fix, NY/CT/MA/MI corrections |

---

## Session Log

| Date | Session | Summary | Tests |
|------|---------|---------|-------|
| 2026-02-11 | Planning | Full v2.0 audit and planning (7 documents) | N/A |
| 2026-02-11 | Phases 1-5 | Validated pipeline, backfilled 25 records, UI rewrite, fetcher upgrade, hardening | 2644/2644 |
| 2026-02-12 | Deploy + Integrity | Deployed v2.0. URL verification, eCFR monitoring, cross-state search, 8 URL fixes | 2783/2783 |
| 2026-02-16 | Gap Analyzer | 7 missing records found, coverage gap analyzer built, 4 new STATE records | 2923/2923 |
| 2026-02-16 | SBA Parser Fix | Critical: single-day SBA incidents false-ongoing. 43 records removed. Pattern 4 added. | 2063/2063 |
| 2026-02-16 | Full Audit | SBA FR verification, FMCSA corrections (VA/MI/MN/WA), Oakland fire added | 2083/2083 |
| 2026-02-17 | Banner + MA | Banner beneficiary overcount fixed (-3.5M). MA declaration added. RI/TX rejected. | 2103/2103 |
| 2026-02-22 | FEMA Integration | FEMACollector, dual output, FM exclusion (6-layer analysis), dual-mode audit | 2335+2731 |
| 2026-03-27 | Staleness Audit | 118 DSTs audited. 7 expired SBA, 18 broken URLs, 12+ missing. PHE tracker built. | 2578+2992 |
| 2026-03-27 | v3.0 Phase 1 | Carrier parser (Aetna+Wellcare). 100 matched, 135 gaps. FMAG REVERSED — carriers honor it. | 2578/2579 |
| 2026-03-27 | v3.0 Phase 2 | 29 new STATE records (16 states). Non-standard DSTs validated (crime, immigration, etc.) | 3981/3982 |
| 2026-03-27 | v3.0 Phase 3 | Gap fills (+20), carrier badges, URL fixes, PR removed, HHS resolved | 4327+5500 |
| 2026-03-27 | Verification Framework | T1-T5 hierarchy, 46 verified corrections, 7 reverted estimates, AZ law fix | 3775+4948 |
| 2026-03-28 | Verifier + Checker | dst_verifier.py (3-layer page scan), dst_renewal_checker.py (4-strategy auto-detect) | 3775+4948 |

---

## Bug Log

| # | Date | Severity | Description | Resolution |
|---|------|----------|-------------|------------|
| 7 | 2026-02-16 | **Critical** | SBA single-day incidents classified as "ongoing" (14-month windows) | Added Pattern 4 regex, 43 records removed |
| 9 | 2026-02-16 | **Critical** | SBA IL/IN/MN using FR publication date as incidentStart | Override IDs + curated entries |
| 21 | 2026-03-27 | **Critical** | FMCSA-2025-012 end date wrong + 4 missing states | Extension to Mar 14, added NC/OH/RI/VA |
| 1-6 | 2026-02-11/12 | Low-Med | SBA status, URLs, git rebase, FR API, hardcoded date, citation | All fixed |
| 8-20 | 2026-02-16/17 | Low-High | URL false alarm, Oakland fire, FMCSA state swaps, banner overcount, MA missing | All fixed |
| 22-25 | 2026-03-27 | Med-High | FMCSA-013 date, broken URLs, HHS PHE lapsed, missing declarations | All fixed |

---

## Key Decisions

| Date | Decision | Why |
|------|----------|-----|
| 2026-02-11 | USDA drought NOT a valid DST | Agricultural loan programs, not disaster declarations per 42 CFR 422.62(b)(18) |
| 2026-02-12 | URL verification must be automated | 8/24 STATE URLs were wrong — manual curation proven insufficient |
| 2026-02-12 | eCFR regulatory monitoring weekly | CMS could amend § 422.62 and silently break our SEP calculations |
| 2026-02-16 | FMCSA→STATE gaps are advisory | FMCSA covers 30-40 states broadly; many won't have governor declarations |
| 2026-02-22 | FM declarations excluded from FEMA | 6-layer Stafford Act analysis: FM ≠ "emergency" or "major disaster" |
| 2026-03-27 | **FM/FMAG REVERSED — now included** | All 3 carriers honor FMAG. Agents need carrier-recognized DSTs. |
| 2026-03-27 | Carrier data = discovery + validation | Government sources authoritative for dates. Carriers discover gaps + validate. |
| 2026-03-27 | Fire containment ≠ declaration end | Governor can keep declaration active for recovery. T1-T5 hierarchy built. |
| 2026-03-27 | NM has NO statutory auto-expire | Proposed 90-day bills (HB0040/HB0080) failed. Each state is different. |
| 2026-03-28 | AZ 120-day limit is PUBLIC HEALTH ONLY | A.R.S. 26-303 doesn't apply to natural disaster declarations |
