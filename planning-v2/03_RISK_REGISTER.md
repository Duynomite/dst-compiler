# DST Compiler Tool v2.0 — Risk Register

## Technical Risks

| # | Risk | Severity | Mitigation | Validate In |
|---|------|----------|------------|-------------|
| R1 | Governor declaration data is incomplete — no centralized source exists for all 50 states | **HIGH** | Research and backfill all active governor declarations for Jan 2026 winter storm. Document the state emergency management URLs used. Accept that 100% coverage is not achievable — aim for all states with active FEMA declarations + known governor-only states. | Phase 2 |
| R2 | Governor declarations expire silently — no notification when a governor lifts a state of emergency | **HIGH** | Add `lastVerified` date to every curated entry. Include `expirationDate` when known. Flag entries not verified in 30+ days. Admin review checklist for curated data. | Phase 2 |
| R3 | GitHub Actions cron has never been verified as running successfully | **MEDIUM** | Manually trigger the workflow, verify output, confirm commit behavior. Check Actions tab for run history. | Phase 1 |
| R4 | FEMA API changes response format or URL structure | **LOW** | API has been stable for years. If it breaks, tool shows curated data only + "FEMA data unavailable" banner. No agent data loss — degraded but functional. | Phase 1 |
| R5 | Tailwind v4 CDN upgrade breaks existing UI | **MEDIUM** | Test thoroughly after migration. Tailwind v4 `@theme` replaces the v3 `tailwind.config` approach. `@apply` is NOT available via CDN — verify no existing code uses it. | Phase 3 |
| R6 | County data in governor declarations is imprecise — some governors declare statewide, others list regions not matching FIPS county names | **MEDIUM** | Normalize all county names to match county_state_map.json. For statewide declarations, flag as "Statewide" (all counties qualify). | Phase 2 |
| R7 | Federal Register API returns too many results or misses relevant SBA/USDA entries | **LOW** | Current search filters for SBA are working (53 records). USDA filter needs tuning — currently returns 0 results. Test with specific known USDA designations. | Phase 2 |
| R8 | Curated data JSON manually edited with formatting errors | **LOW** | Audit script validates JSON structure and all 21 field checks. Run audit after every manual edit. | Phase 1 |

## Assumptions to Validate Early

| # | Assumption | Risk if Wrong | Validate In |
|---|-----------|---------------|-------------|
| A1 | GitHub Actions cron job runs successfully on the existing repo | Pipeline doesn't update data automatically — tool becomes stale | Phase 1 |
| A2 | All Jan 2026 winter storm governor declarations are still active | Could display expired DSTs to agents — compliance risk | Phase 2 |
| A3 | The existing FEMA API query (`declarationDate >= 24 months ago`) captures all relevant active disasters | Could miss older disasters with still-active SEP windows | Phase 1 |
| A4 | The existing SEP window calculation in index.html is correct for all edge cases | Wrong dates shown to agents | Phase 1 (test cases) |
| A5 | Tailwind v4 CDN works with the existing React 18 + Babel setup | UI breaks on upgrade | Phase 3 |
| A6 | Federal Register API reliably catches new SBA disaster declarations | SBA coverage drops without automated detection | Phase 2 |

## Blocker Items (Owner Action Required)

| # | Item | Owner | Required Before |
|---|------|-------|----------------|
| B1 | Confirm GitHub repo access and ability to push to `main` branch | Connor | Phase 1 |
| B2 | Verify GitHub Actions is enabled on the repo | Connor | Phase 1 |
| B3 | Decision: Should we add a "Data verified as of [date]" attestation for compliance documentation? | Connor | Phase 3 |
