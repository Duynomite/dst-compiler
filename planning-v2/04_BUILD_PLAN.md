# DST Compiler Tool v2.0 — Build Plan

## Phase Overview

| Phase | Focus | Effort | Key Deliverable |
|-------|-------|--------|----------------|
| 1 | Validation & Pipeline Verification | 1-2 hours | Confirmed working pipeline, audit clean |
| 2 | Data Backfill — Governor + HHS + USDA | 2-3 hours | Complete source coverage in curated_disasters.json |
| 3 | UI Upgrade to CPC Brand Standards | 2-3 hours | Tailwind v4, CPC brand, freshness indicators |
| 4 | Fetcher Upgrade — USDA + HHS automation | 1-2 hours | Federal Register API monitoring expanded |
| 5 | Hardening | 1-2 hours | Edge cases, error handling, validation |
| 6 | Ship | 1 hour | Deploy, verify, document |

---

## Phase 1: Validation & Pipeline Verification

**Goal:** Confirm everything that exists works correctly before changing anything.

### Tasks
1. Run `audit_curated_data.py` against current `curated_disasters.json` — document all failures
2. Manually trigger GitHub Actions workflow — verify it runs, commits, and deploys
3. Check GitHub Actions run history — has the daily cron ever fired?
4. Open live site and verify FEMA API fetch works (check debug panel Ctrl+Shift+D)
5. Test SEP window calculation against 3 known disasters:
   - Disaster with closed incident (verify 2 full calendar months)
   - Ongoing disaster (verify 14-month max)
   - End-of-month incident date (verify no `setMonth()` overflow)
6. Verify county search returns correct results for 3 test counties
7. Document any issues found

### Test Criteria
- Audit script passes with 0 FAIL (warnings acceptable)
- GitHub Actions runs successfully on manual trigger
- FEMA data loads in browser (timestamp visible in header)
- SEP window calculations match expected dates for all 3 test cases

### Done When
- [ ] Audit script runs clean
- [ ] GitHub Actions verified working
- [ ] FEMA live fetch confirmed
- [ ] SEP calculations verified for 3 edge cases
- [ ] All issues documented in CLAUDE.md Known Issues

---

## Go/No-Go Gate

```
Before starting Phase 2:
- [ ] Phase 1 tests pass
- [ ] No regressions from previous phases
- [ ] CLAUDE.md Current State updated
- [ ] Any new decisions logged in Decisions Made
- [ ] Any bugs found logged in Bug Log
```

---

## Phase 2: Data Backfill — Governor + HHS + USDA

**Goal:** Fill all source coverage gaps in curated_disasters.json.

### Tasks

#### 2a: Governor Declarations (Jan 2026 Winter Storm)
Research and add entries for all confirmed governor-declared emergencies:

| State | Governor | Status | FEMA Match? |
|-------|----------|--------|-------------|
| Texas | Abbott | Needs backfill | No FEMA |
| North Carolina | Stein | Needs backfill | No FEMA |
| Virginia | Spanberger | Needs backfill | No FEMA |
| Alabama | Ivey | Needs backfill | No FEMA |
| New Mexico | Lujan Grisham | Needs backfill | No FEMA |
| New York | Hochul | Needs backfill | No FEMA |
| New Jersey | Sherrill | Needs backfill | No FEMA |
| Pennsylvania | Shapiro | Needs backfill | No FEMA |
| Delaware | Meyer | Needs backfill | No FEMA |
| Georgia | Kemp | Needs backfill | Has FEMA EM-3642 |
| Kentucky | Beshear | Needs backfill | Has FEMA EM-3633 |
| Louisiana | Landry | Needs backfill | Has FEMA EM-3638 |
| Arkansas | Sanders | Needs backfill | Has FEMA EM-3636 |
| Maryland | Moore | Needs backfill | Has FEMA EM-3634 |
| Indiana | — | Needs backfill | Has FEMA EM-3641 |
| Mississippi | Reeves | Needs backfill | Has FEMA |
| West Virginia | Morrisey | Needs backfill | Has FEMA |
| D.C. | — | Needs backfill | No FEMA |

For each entry, collect:
- Official executive order or proclamation URL (governor's website)
- Declaration date and expiration date (if stated)
- Counties affected (statewide or specific list)
- Incident dates

#### 2b: Other Governor Declarations (2025)
Research active governor declarations from 2025 that may still have open SEP windows:
- Check states with known 2025 disasters (KY, TN, MO, TX floods/storms)
- Add if SEP window is still active (incident end + 2 months)

#### 2c: HHS Public Health Emergencies
- Check ASPR.hhs.gov for any currently active PHE declarations
- Check Federal Register for recent HHS emergency declarations
- Add entries if any are active

#### 2d: USDA Drought/Disaster Designations
- Check USDA FSA disaster designation page for active designations
- Check Federal Register for recent USDA disaster designations
- Focus on designations in states where CPC operates
- Add entries with county-level specificity

#### 2e: Validate All New Entries
- Run audit script against updated curated_disasters.json
- Verify every official source URL resolves
- Verify county names match county_state_map.json

### Test Criteria
- All new entries pass 21-check audit validation
- Every entry has a working official source URL
- County names normalized to match county_state_map.json
- No duplicate disasters (same event from different source types should be separate entries — an agent needs to see all valid authority sources)

### Done When
- [ ] 18+ governor declarations added for Jan 2026 winter storm
- [ ] Relevant 2025 governor declarations added
- [ ] HHS entries added (or documented as "none active")
- [ ] USDA entries added (or documented as "none active with open SEP window")
- [ ] Audit script passes on all new entries
- [ ] All source URLs verified

---

## Go/No-Go Gate

```
Before starting Phase 3:
- [ ] Phase 2 tests pass
- [ ] No regressions from Phase 1
- [ ] CLAUDE.md Current State updated
- [ ] Any new decisions logged
- [ ] Any bugs found logged
```

---

## Phase 3: UI Upgrade to CPC Brand Standards

**Goal:** Upgrade index.html to CPC visual identity with Tailwind v4 @theme tokens.

### Tasks
1. Replace Tailwind v3 CDN with Tailwind v4: `cdn.jsdelivr.net/npm/@tailwindcss/browser@4`
2. Add `@theme` block with CPC brand tokens:
   - `--color-accent: #3DCEB2`
   - `--color-secondary: #2D5A7A`
   - `--color-text: #34252F`
   - `--color-deep-navy: #10202C`
   - `--color-light-cyan: #D8E6E3`
   - `--color-mid-blue: #4B7797`
   - `--color-soft-blue: #A7B8C5`
   - `--font-heading: "Urbanist", sans-serif`
   - `--font-body: "Jost", sans-serif`
3. Add Google Fonts link (Urbanist + Jost)
4. Update header: CPC secondary background, proper typography
5. Update cards: white bg, light-cyan border, accent elements per CPC card standard
6. Update source badges: maintain color differentiation but align with CPC palette
7. Update compliance footer: accent/warning styling per CPC patterns
8. Add "Last Updated" timestamp prominently in header
9. Add staleness warning banner (yellow/amber if curated data > 7 days old)
10. Add `lastVerified` display for curated entries
11. Test responsive at 1024px and 1440px
12. Verify no console errors

### Test Criteria
- All CPC brand colors applied correctly
- Urbanist headings, Jost body text
- Cards follow CPC card pattern
- Responsive at both breakpoints
- Zero console errors
- Staleness banner appears when appropriate
- Source badges still visually distinguishable

### Done When
- [ ] Tailwind v4 @theme with CPC tokens working
- [ ] Typography correct (Urbanist headings, Jost body)
- [ ] Cards match CPC standard
- [ ] Freshness indicators working
- [ ] Responsive verified at 1024px and 1440px
- [ ] Zero console errors

---

## Go/No-Go Gate

```
Before starting Phase 4:
- [ ] Phase 3 tests pass
- [ ] No regressions from Phases 1-2
- [ ] CLAUDE.md Current State updated
- [ ] Any new decisions logged
- [ ] Any bugs found logged
```

---

## Phase 4: Fetcher Upgrade — USDA + HHS Automation

**Goal:** Enhance dst_data_fetcher.py to automatically discover USDA and HHS declarations via Federal Register API.

### Tasks
1. Add USDA Federal Register API query to fetcher:
   - Search for FSA disaster designations
   - Filter by recent dates (24-month lookback)
   - Parse county/state information from documents
2. Add HHS Federal Register API query to fetcher:
   - Search for public health emergency declarations
   - Filter by recent dates
3. Add `STATE` source type support to fetcher validation
4. Add `lastVerified` field to curated entry schema
5. Update `audit_curated_data.py` to validate new source types and `lastVerified` field
6. Test fetcher end-to-end: run locally, compare output to current data

### Test Criteria
- Fetcher runs without errors
- USDA query returns relevant results (or documents "no active USDA disasters")
- HHS query returns relevant results (or documents "no active HHS emergencies")
- New entries pass audit validation
- No regression in existing SBA/FMCSA data collection

### Done When
- [ ] Fetcher handles USDA via Federal Register
- [ ] Fetcher handles HHS via Federal Register
- [ ] STATE source type validated by audit script
- [ ] `lastVerified` field supported
- [ ] End-to-end local test successful

---

## Go/No-Go Gate

```
Before starting Phase 5:
- [ ] Phase 4 tests pass
- [ ] No regressions from Phases 1-3
- [ ] CLAUDE.md Current State updated
- [ ] Any new decisions logged
- [ ] Any bugs found logged
```

---

## Phase 5: Hardening

**Goal:** Edge cases, error handling, and compliance verification.

### Tasks
1. **Input validation:**
   - State dropdown handles all 50 states + DC + territories
   - County search handles special characters, apostrophes, hyphens
   - County search handles "Saint" vs "St.", "De" prefixes, etc.
2. **Error handling:**
   - FEMA API timeout or failure → show banner "FEMA data temporarily unavailable" + show curated data only
   - Curated JSON load failure → show banner with clear message
   - Malformed disaster entry → skip gracefully, don't crash
3. **SEP window edge cases:**
   - End-of-month incident dates (Jan 31, Mar 31, etc.)
   - Leap year February dates
   - Ongoing disasters with renewal dates
   - Disasters spanning year boundaries
4. **Compliance review:**
   - 3-part attestation text matches 42 CFR 422.62(a)(6) exactly
   - Election code "SEP DST" displayed correctly
   - No marketing language — tool is reference-only
   - All official source links open in new tab
5. **Performance:**
   - Page loads within 2 seconds (excluding FEMA API fetch)
   - FEMA API fetch completes within 5 seconds
   - Search/filter operations are instant
6. **Accessibility:**
   - All interactive elements keyboard navigable
   - Color badges have text labels (not color-only)
   - Copy button confirms action

### Test Criteria
- All edge cases from Test Cases document pass
- Error states show user-friendly messages
- No console errors under any scenario
- Page loads within target time

### Done When
- [ ] All hardening tasks completed
- [ ] Edge case tests pass
- [ ] Error handling verified (simulate API failure)
- [ ] Compliance text verified against CFR
- [ ] Performance within targets

---

## Go/No-Go Gate

```
Before starting Phase 6:
- [ ] Phase 5 tests pass
- [ ] No regressions from ALL previous phases
- [ ] CLAUDE.md Current State updated
- [ ] Any new decisions logged
- [ ] Any bugs found logged
```

---

## Phase 6: Ship

### Checklist
- [ ] All test cases pass (happy path, edge cases, bad data, business logic, operational failures)
- [ ] Validation benchmark passes with exact expected outputs
- [ ] Error messages are plain language
- [ ] Observability in place (freshness timestamp, staleness banner, debug panel)
- [ ] All external dependencies documented in Maintenance Guide
- [ ] Known fragile points documented (governor data curation)
- [ ] Hardening phase completed
- [ ] Git history clean with meaningful commits
- [ ] Deployed to GitHub Pages and verified live
- [ ] Test 3 critical user flows on live site:
  1. Search by state → verify correct DSTs display
  2. Search by county → verify county filtering works
  3. Copy for SunFire → verify clipboard content is correct
- [ ] Bug Log current (even if empty)
- [ ] Architecture Decision Log reflects all v2 decisions
- [ ] CLAUDE.md fully updated with final state
- [ ] Maintenance Guide complete and accurate
- [ ] MEMORY.md tool inventory updated
- [ ] Retrospective written in retrospectives.md
