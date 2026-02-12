# DST Compiler Tool v2.0 — Test Cases

## Happy Path Tests

### HP-1: Basic State Search
**Input:** Select "Tennessee" from state dropdown
**Expected:** Shows all active Tennessee DSTs (currently 4: 2 FEMA + 1-2 FMCSA + potential governor)
**Verify:** Each card shows source badge, title, dates, SEP window, counties, status, official link

### HP-2: County Search
**Input:** Select "Tennessee" → type "Davidson" in county search
**Expected:** Only DSTs that include Davidson County are displayed
**Verify:** FEMA winter storm cards show Davidson in their county list

### HP-3: Copy for SunFire
**Input:** Click "Copy" button on any DST card
**Expected:** Clipboard contains formatted text with: disaster name, declaration ID, SEP window dates, election code (SEP DST), counties
**Verify:** Paste into text editor, confirm all fields present and correctly formatted

### HP-4: Source Filter
**Input:** Filter by "GOV" source (after governor data is added)
**Expected:** Only governor-declared DSTs display
**Verify:** All visible cards have GOV source badge

### HP-5: Sort by Ending Soonest
**Input:** Select "Ending Soonest" sort
**Expected:** DSTs with nearest SEP window end date appear first. Ongoing disasters appear last.
**Verify:** First card has shortest remaining days, last cards show "Ongoing"

### HP-6: Official Source Link
**Input:** Click official declaration link on a FEMA card
**Expected:** Opens FEMA disaster page in new tab with correct declaration number
**Verify:** URL matches disaster ID, page loads, content matches disaster

### HP-7: Multi-Source State Display
**Input:** Select a state with both FEMA and governor declarations (e.g., Georgia)
**Expected:** Both FEMA and governor DSTs display separately with distinct source badges
**Verify:** Each card shows its own source, dates, counties, and official link

---

## Edge Case Tests

### EC-1: SEP Window — End of Month Incident Date
**Input:** Disaster with incident end date of January 31
**Expected SEP End:** March 31 (2 full calendar months)
**NOT:** March 3 (the `setMonth()` overflow bug)
**Verify:** Manually calculate: Jan 31 → end of Feb (28 or 29) → end of March = March 31

### EC-2: SEP Window — Leap Year February
**Input:** Disaster with incident end date in February of a leap year
**Expected:** SEP end date correctly accounts for Feb 29 vs Feb 28
**Verify:** For incident ending Feb 15, 2028 (leap year): SEP end = April 30, 2028

### EC-3: SEP Window — Ongoing Disaster (No End Date)
**Input:** Disaster with `incidentEnd: null`
**Expected:** Status shows "ONGOING", no "days remaining" count, SEP window shows "Ongoing"
**Verify:** No end date calculation attempted, 14-month max rule applied from latest renewal/start

### EC-4: SEP Window — 14-Month Maximum
**Input:** Disaster declared 14+ months ago with no end date
**Expected:** SEP window shows approaching or reached 14-month maximum
**Verify:** Window end = 14 calendar months from SEP start date (or latest renewal)

### EC-5: Statewide Declaration
**Input:** Governor declares statewide emergency (all counties)
**Expected:** Card shows "Statewide" badge, county search in that state always returns this DST
**Verify:** Searching any county in that state shows the statewide declaration

### EC-6: County Name Variations
**Input:** Search for "St. Louis" (with period) and "Saint Louis" (spelled out)
**Expected:** Both variations find St. Louis County/City entries
**Verify:** County search handles common abbreviations

### EC-7: Empty State (No Active DSTs)
**Input:** Select a state with no active DSTs (e.g., Idaho)
**Expected:** "No active DSTs found for Idaho" message displayed
**Verify:** No error, clean empty state message

### EC-8: Declaration with Expiration Date Passed
**Input:** Governor declaration with explicit expiration date in the past
**Expected:** If SEP window is still active (expiration + 2 months), show as ACTIVE. If SEP window expired, don't show.
**Verify:** Correct status calculation based on SEP window, not just declaration expiration

---

## Bad Data Tests

### BD-1: Malformed Curated JSON Entry
**Input:** Entry with missing `incidentStart` field in curated_disasters.json
**Expected:** Entry is skipped, other entries display normally, no crash
**Verify:** Console may log warning but app doesn't break

### BD-2: Invalid State Code
**Input:** Entry with `state: "XX"` (non-existent)
**Expected:** Entry is skipped or displayed without state grouping
**Verify:** No crash, other entries unaffected

### BD-3: Empty Counties Array
**Input:** Entry with `counties: []`
**Expected:** Card shows "No specific counties listed" or "Statewide"
**Verify:** No crash, card still displays other information

### BD-4: Future Declaration Date
**Input:** Entry with `declarationDate` in the future
**Expected:** Flagged by audit script. If displayed, should show but not affect SEP window calculation.
**Verify:** Audit catches this as a warning

### BD-5: Curated JSON Completely Unavailable
**Input:** Network error loading curated_disasters.json
**Expected:** FEMA data still displays. Banner: "Some disaster data temporarily unavailable"
**Verify:** FEMA cards render, error message is user-friendly

---

## Business Logic Tests

### BL-1: Governor Declaration Without FEMA Match
**Input:** State (e.g., Texas) has governor declaration but no FEMA declaration for same event
**Expected:** Governor DST card displays for Texas with GOV source badge
**Verify:** Agent can see there IS a valid DST authority even without FEMA

### BL-2: Same Disaster, Multiple Authority Levels
**Input:** Georgia has both FEMA EM-3642 AND Governor Kemp declaration for winter storm
**Expected:** Both display as separate cards — one FEMA, one GOV
**Verify:** Agent sees both valid authorities. Different source badges, potentially different county lists.

### BL-3: FMCSA Statewide vs FEMA County-Specific
**Input:** State has FMCSA statewide declaration AND FEMA county-specific declaration
**Expected:** Both display. FMCSA shows "Statewide". FEMA shows specific counties.
**Verify:** Agent understands FMCSA covers all counties, FEMA covers specific ones

### BL-4: SEP Window Start Date — Earlier of Declaration or Incident
**Input:** Disaster with declarationDate = Feb 15, incidentStart = Feb 10
**Expected SEP Start:** February 10 (earlier of the two)
**Verify:** `Math.min(declarationDate, incidentStart)` logic

### BL-5: Compliance Attestation Visibility
**Input:** Page loads with any DSTs displayed
**Expected:** 3-part compliance attestation is ALWAYS visible (not hidden, not collapsed)
**Verify:** Footer with 42 CFR 422.62(a)(6) reference, all 3 parts listed, verbal attestation note

### BL-6: Data Freshness Warning
**Input:** Curated data timestamp is more than 7 days old
**Expected:** Yellow/amber warning banner: "Curated disaster data may be outdated. Last updated: [date]. Verify current declarations before enrollment."
**Verify:** Banner appears, is visually prominent, includes the date

---

## Operational Failure Tests

### OF-1: FEMA API Down
**Input:** FEMA API returns 500 error or times out
**Expected:** Curated data still displays. Banner: "FEMA live data temporarily unavailable — showing cached data only"
**Verify:** App doesn't crash, curated DSTs visible, error message clear

### OF-2: FEMA API Returns Empty Data
**Input:** FEMA API returns valid JSON with zero records
**Expected:** Only curated data displays. No false "no DSTs" message if curated data exists.
**Verify:** Curated entries still visible

### OF-3: GitHub Actions Pipeline Failure
**Input:** Python fetcher crashes during daily cron
**Expected:** GitHub Issue created automatically. Curated data stays at last-known-good state.
**Verify:** Check GitHub Issues for failure notification

### OF-4: CDN Unavailable (React/Tailwind)
**Input:** CDN scripts fail to load
**Expected:** Page shows basic HTML with error message (not a blank page)
**Verify:** Add `<noscript>` fallback message

---

## Validation Benchmark

This is the single comprehensive test that proves the system is fundamentally correct.

```
Benchmark: January 2026 Winter Storm — Multi-Source Verification

Scenario: Agent in Davidson County, Tennessee needs to verify all valid DSTs

Inputs:
  - State: Tennessee
  - County: Davidson

Expected Outputs:
  FEMA DSTs:
    - DR-4898-TN: Severe Winter Storm
      SEP Window Start: Jan 22, 2026
      Status: ONGOING (no incident end)
      Counties: includes Davidson
      Source link: FEMA.gov

    - EM-3635-TN: Severe Winter Storm (Emergency)
      SEP Window Start: Jan 22-23, 2026
      Status: ONGOING
      Source link: FEMA.gov

  FMCSA DSTs:
    - FMCSA-2026-001-TN: Regional Emergency Declaration
      SEP Window: Jan 20, 2026 — Apr 30, 2026
      Status: ACTIVE
      Counties: Statewide
      Source link: FMCSA.dot.gov

    - FMCSA-2025-013-TN: Heating Fuels Emergency
      SEP Window: Dec 20, 2025 — Apr 30, 2026
      Status: ACTIVE
      Counties: Statewide
      Source link: FMCSA.dot.gov

  Governor DST (after backfill):
    - GOV-TN-2026-001: Governor Emergency Declaration
      Declaration Date: ~Jan 2026
      Status: ACTIVE or ONGOING
      Source link: tn.gov (governor's office)

  Total DSTs for Davidson County, TN: 5 (2 FEMA + 2 FMCSA + 1 GOV)

  Compliance:
    - 3-part attestation visible at all times
    - Each card has "Copy for SunFire" button
    - Each card has official source link
    - No marketing language anywhere

  This benchmark passes when:
    - All 5 DSTs display for Davidson County, TN
    - SEP window dates are correct per 42 CFR
    - Source badges correctly identify FEMA/FMCSA/GOV
    - Copy-to-clipboard produces valid SunFire text
    - 3-part compliance attestation is visible
```
