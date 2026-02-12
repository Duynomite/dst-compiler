# DST Compiler Tool v2.0 — Handoff Summary

## What We're Building

An upgrade to the existing DST Compiler Tool (deployed at duynomite.github.io/dst-compiler/) that closes critical source coverage gaps. The v1 tool captures FEMA disasters well via live API but misses governor-declared state emergencies, HHS public health emergencies, and USDA drought designations — all of which independently trigger valid Medicare DST SEPs. The v2 upgrade backfills all active governor declarations, adds HHS/USDA source coverage, upgrades the UI to CPC brand standards, and ensures the automated data pipeline is running correctly. This is a compliance-critical tool — agents use it to verify DST legitimacy before enrolling beneficiaries.

## Documents Produced

| # | Document | What It Covers |
|---|----------|---------------|
| 1 | **PRD** (`01_PRD.md`) | Problem statement, users, goals, 9 MUST features, future features, constraints, out of scope |
| 2 | **Architecture** (`02_ARCHITECTURE.md`) | Component diagram, data flow (live + automated + manual paths), deployment, dependencies, security assessment, observability |
| 3 | **Risk Register** (`03_RISK_REGISTER.md`) | 8 technical risks with mitigations, 6 assumptions to validate, 3 blocker items requiring owner action |
| 4 | **Build Plan** (`04_BUILD_PLAN.md`) | 6 phases with go/no-go gates: Validation → Data Backfill → UI Upgrade → Fetcher Upgrade → Hardening → Ship |
| 5 | **Test Cases** (`05_TEST_CASES.md`) | 7 happy path, 8 edge case, 5 bad data, 6 business logic, 4 operational failure tests + validation benchmark |
| 6 | **Maintenance Guide** (`06_MAINTENANCE_GUIDE.md`) | Dependencies, fragile points, resumption guide, data curation workflow, monthly maintenance checklist |

## Open Decisions for Owner

1. **B1: GitHub repo access** — Confirm you can push to `main` branch on the dst-compiler repo
2. **B2: GitHub Actions** — Verify Actions is enabled on the repo (check Settings → Actions)
3. **B3: Data verification attestation** — Should the tool show a "Data verified as of [date]" footer for compliance documentation purposes?

## Prerequisites Before Building

- [x] GitHub repo exists and is deployed (`duynomite.github.io/dst-compiler/`)
- [x] FEMA API access (free, no auth)
- [x] Federal Register API access (free, no auth)
- [ ] Confirm GitHub repo push access (B1)
- [ ] Confirm GitHub Actions enabled (B2)
- [ ] Governor declaration research completed (Phase 2 will handle, but having initial URLs helps)

## Assumptions to Validate Early

| Assumption | How to Validate | Phase |
|-----------|----------------|-------|
| GitHub Actions cron is running | Check Actions tab for run history | Phase 1 |
| Existing SEP window calculation is bug-free | Test 3 edge cases (end-of-month, leap year, ongoing) | Phase 1 |
| FEMA API query window (24 months) catches all relevant disasters | Check oldest active disaster against query cutoff | Phase 1 |
| Tailwind v4 CDN works with existing React 18 + Babel setup | Test upgrade in isolation before full UI migration | Phase 3 |

## Validation Benchmark

**Scenario:** Agent searches for Davidson County, Tennessee

**Passing criteria:**
- 5 DSTs display (2 FEMA + 2 FMCSA + 1 GOV)
- SEP window dates are correct per 42 CFR
- Source badges correctly identify each authority level
- Copy-to-clipboard produces valid SunFire enrollment text
- 3-part compliance attestation visible at all times
- Every card has a working official source link

## Recommended First Steps in Claude Code

1. Read this handoff summary + CLAUDE.md
2. Read `planning-v2/04_BUILD_PLAN.md` for Phase 1 tasks
3. Start Phase 1: Run audit script, check GitHub Actions, verify SEP calculations
4. Do NOT change any code until Phase 1 validation is complete
