# DST Compiler Tool — Test Cases

## How to Use This Document

These test cases are designed so Connor (non-technical) can verify the tool works correctly by looking at the output. No code knowledge required. For each test, follow the steps and check if the expected result matches what you see.

**When to run these tests:**
- After each build phase is completed
- After any significant code changes
- After a data fetcher update reveals new source issues

---

## Section 1: Happy Path (Normal Usage)

### Test 1.1: Basic FEMA Search

**Steps:**
1. Open the tool
2. Select state: Florida
3. Type county: Miami-Dade

**Expected result:**
- At least 1 FEMA disaster shows (Florida has frequent disaster declarations)
- Each result shows: FEMA badge, disaster name, declaration number, SEP window dates, official link
- Go to `https://www.fema.gov/disasters` and filter by Florida — the tool should show the same active disasters

### Test 1.2: Statewide Declaration Search

**Steps:**
1. Open the tool
2. Select any state that has a known statewide governor declaration or FMCSA emergency
3. Search any county in that state

**Expected result:**
- The statewide declaration appears in results with a "Statewide" badge
- Same statewide declaration appears regardless of which county you pick in that state

### Test 1.3: Multi-Source Same Event

**Steps:**
1. Search for a county affected by a major disaster (like a hurricane or wildfire that triggered both FEMA and state declarations)

**Expected result:**
- Multiple DST entries for the same event appear (e.g., one FEMA, one STATE, maybe one HHS)
- Each has a different source badge and different declaration details
- Each has its own "Copy" button with distinct details
- This is correct — each is a separate valid DST trigger under different declaring authorities

### Test 1.4: Copy Button Format

**Steps:**
1. Find any active DST
2. Click the "Copy" button
3. Open Notepad (or any text editor)
4. Paste (Ctrl+V)

**Expected result:**
The pasted text looks exactly like this (with actual values):
```
DST — Hurricane Helene (FEMA DR-4834)
SEP Window: Sept 23, 2024 — Ongoing
Official Declaration: https://www.fema.gov/disaster/4834
```
- Disaster name and source/ID on first line
- SEP window dates on second line (human-readable dates, not "2024-09-23")
- Official URL on third line
- No extra blank lines, HTML tags, or formatting artifacts

### Test 1.5: Official Link Specificity

**Steps:**
1. Find any 5 DST listings
2. Click each official declaration link

**Expected result:**
- Each link opens a real government webpage about THAT SPECIFIC disaster
- FEMA links go to `https://www.fema.gov/disaster/{NUMBER}` and show the specific disaster (not fema.gov/disasters)
- HHS links go to the specific PHE page (not the general PHE listing)
- FMCSA links go to the specific emergency page (not fmcsa.dot.gov/emergency-declarations)
- SBA links go to the specific disaster loan announcement
- No "Page Not Found" or 404 errors
- If any link goes to a general index page rather than the specific declaration, it should be flagged in the UI with "(general source page)"

### Test 1.5b: Sorting Options

**Steps:**
1. Open the tool with all DSTs visible
2. Select "Most Recent First" sort
3. Verify top results have the most recent declaration dates
4. Select "Ending Soonest" sort
5. Verify top results have the nearest SEP window end dates (ongoing disasters should appear last)
6. Select "By State (A-Z)" sort
7. Verify results are alphabetical by state

**Expected result:**
- All three sort options work correctly
- Sorting is instant (no page reload)
- Default sort on page load is "By State (A-Z)"

### Test 1.6: Browse All DSTs

**Steps:**
1. Open the tool without searching (or select "All States")

**Expected result:**
- All active DSTs displayed, organized by state alphabetically (Alabama first, Wyoming last)
- Each state section shows a count of active DSTs
- Can scroll through all states
- No expired DSTs visible anywhere

---

## Section 2: Edge Cases

### Test 2.1: County With No Active Disasters

**Steps:**
1. Select a state with no known active disasters
2. Type a county name

**Expected result:**
- Clear message: "No active DSTs found for [County], [State]"
- No error, no blank screen, no confusing behavior

### Test 2.2: State With Only Statewide Declarations

**Steps:**
1. Search a county in a state that has statewide FMCSA or governor declarations but no county-specific FEMA disasters

**Expected result:**
- Statewide declarations appear
- No county-specific results (correct — there aren't any)
- Clear indication these are statewide

### Test 2.3: Disaster Incident Ended But SEP Still Active

**Steps:**
1. Find a disaster where `incidentEnd` is in the past but the 2-month SEP window hasn't closed yet
   Example: Incident ended January 15, 2026. Today is February 7, 2026. SEP runs through March 31, 2026.

**Expected result:**
- Disaster shows as "ACTIVE" (not "Ongoing" and not "Expired")
- SEP end date shown as March 31, 2026
- Days remaining shown accurately
- This is a critical compliance point — incident over ≠ SEP over

### Test 2.4: Very Long Ongoing Disaster (14-Month Max)

**Steps:**
1. Look for any disaster that has been ongoing for more than 14 months from its SEP start date
   (If none exist in real data, this can be tested by temporarily adding a test disaster with `incidentStart` 15 months ago and `incidentEnd: null`)

**Expected result:**
- The disaster is NOT displayed (it has exceeded the 14-month maximum per § 422.62)
- OR if very close to 14 months, it shows with correct "expiring" status

### Test 2.5: County Name Variations

**Steps:**
1. Search for "Saint Louis" (vs "St. Louis")
2. Search for "Miami-Dade" (hyphenated)
3. Search for county with "(County)" suffix

**Expected result:**
- Search is flexible enough to match common variations
- At minimum, exact match works
- FEMA sometimes returns "Miami-Dade (County)" — the tool should handle this

### Test 2.6: FEMA API Slow or Down

**Steps:**
1. Open the tool with airplane mode on (or disconnect Wi-Fi briefly)

**Expected result:**
- Tool does NOT show a blank page or crash
- Shows non-FEMA curated data (HHS, SBA, USDA, FMCSA, STATE sources)
- Shows a clear warning like "FEMA data unavailable — showing non-FEMA sources only. Refresh to retry."
- When connection is restored, refreshing the page shows FEMA data again

---

## Section 3: Bad Data Handling

### Test 3.1: Missing Incident End Date

**Steps:**
1. Verify that disasters with `incidentEnd: null` display correctly

**Expected result:**
- Shows "Ongoing" for the end date (not "null" or blank)
- Status shows "ONGOING"
- SEP window end shows as ongoing (with 14-month max noted)
- Copy button output shows "Ongoing" for the end date

### Test 3.2: Future Declaration Date

**Steps:**
1. If any disaster has a `declarationDate` in the future (data error), check display

**Expected result:**
- Should either hide the disaster or show it with accurate dates
- Should NOT show negative "days remaining"
- Should NOT break the page layout

### Test 3.3: Invalid Official URL in Data

**Steps:**
1. During data fetcher run, check for any URLs that return 404 or errors

**Expected result:**
- Data fetcher logs the broken link
- The disaster is either excluded from the JSON or included with a fallback URL
- The frontend never shows a link that leads to a 404 page

---

## Section 4: Business Logic (Compliance-Critical)

### Test 4.1: SEP Window Calculation — 2 Calendar Months

**These are the most important tests. Calculate by hand and compare.**

| Incident End Date | Expected SEP End Date | Explanation |
|-------------------|----------------------|-------------|
| January 15, 2026 | March 31, 2026 | 2 full months after Jan = Feb + Mar, last day of Mar |
| January 31, 2026 | March 31, 2026 | Same month → same result |
| February 28, 2026 | April 30, 2026 | 2 full months after Feb = Mar + Apr, last day of Apr |
| March 1, 2026 | May 31, 2026 | 2 full months after Mar = Apr + May, last day of May |
| March 31, 2026 | May 31, 2026 | Same month → same result |
| November 15, 2025 | January 31, 2026 | 2 full months after Nov = Dec + Jan, last day of Jan |
| November 30, 2025 | January 31, 2026 | Same month → same result |
| December 31, 2025 | February 28, 2026 | 2 full months after Dec = Jan + Feb, last day of Feb (non-leap year) |

**Steps:** For each row, find (or create a test record with) the given incident end date and verify the tool shows the expected SEP end date.

**CRITICAL:** If ANY of these don't match, the window calculation is wrong and must be fixed before launch.

### Test 4.2: SEP Start Date — Earlier of Declaration or Incident Start

| Declaration Date | Incident Start | Expected SEP Start |
|-----------------|----------------|-------------------|
| 2024-09-26 | 2024-09-23 | Sept 23, 2024 (incident started first) |
| 2025-01-07 | 2025-01-10 | Jan 7, 2025 (declared before incident start) |
| 2025-06-15 | 2025-06-15 | June 15, 2025 (same date) |

**Steps:** For each row, verify the tool shows the correct SEP start date.

### Test 4.3: 14-Month Maximum for Ongoing Disasters

| SEP Start Date | Today's Date | Expected Behavior |
|---------------|-------------|-------------------|
| Dec 1, 2024 | Feb 7, 2026 | ACTIVE (14 months = Feb 28, 2026) |
| Nov 1, 2024 | Feb 7, 2026 | EXPIRED (14 months = Jan 31, 2026 — past) |
| Jan 1, 2025 | Feb 7, 2026 | ACTIVE (14 months = Mar 31, 2026) |

**Steps:** Verify that ongoing disasters older than 14 months are hidden.

### Test 4.3b: 14-Month Maximum with Declaration Renewal

Per § 422.62, the 14-month clock resets when a disaster declaration is renewed or extended.

| SEP Start | Renewal Date | Today | Expected Behavior |
|-----------|-------------|-------|-------------------|
| Jan 1, 2025 | None | Feb 7, 2026 | ACTIVE (14 months from Jan 1 = Mar 31, 2026) |
| Jan 1, 2025 | Jul 1, 2025 | Feb 7, 2026 | ACTIVE (14 months from Jul 1 = Sep 30, 2026) |
| Jan 1, 2024 | None | Feb 7, 2026 | EXPIRED (14 months from Jan 1, 2024 = Mar 31, 2025 — past) |
| Jan 1, 2024 | Jan 1, 2025 | Feb 7, 2026 | ACTIVE (14 months from renewal Jan 1, 2025 = Mar 31, 2026) |

**Steps:** Verify that renewed disasters use the renewal date (not original start) for the 14-month calculation.

### Test 4.4: Status Labels

| Condition | Expected Status |
|-----------|----------------|
| Incident end is null and within 14-month window | ONGOING |
| Incident ended, SEP window has 31+ days left | ACTIVE |
| Incident ended, SEP window has 30 or fewer days left | EXPIRING SOON |
| SEP window has passed | Not displayed (hidden) |

**Steps:** Find or create test records for each condition and verify the status label.

### Test 4.5: Data Fetcher Completeness Check

**Steps:**
1. Go to `https://www.fema.gov/disasters` — count active disasters
2. Go to `https://www.fmcsa.dot.gov/emergency-declarations` — count active emergencies
3. Go to `https://aspr.hhs.gov/legal/PHE/Pages/default.aspx` — count active PHEs
4. Compare against what the tool shows

**Expected result:**
- FEMA count matches exactly (tool uses live API)
- FMCSA count is close (within 1-2, allowing for scraping gaps)
- HHS count matches active PHEs

### Test 4.6: Copy Output Contains Required Fields

**Steps:**
1. Copy any DST
2. Verify the pasted text contains ALL of these:
   - DST source and declaration identifier
   - SEP window start and end dates (or "Ongoing")
   - URL to official declaration

**Expected result:**
All three fields present. This is the minimum an agent needs for the SunFire enrollment application.

---

## Section 5: Data Fetcher Tests

### Test 5.1: Script Runs Successfully

**Steps:**
```bash
python3 dst_data_fetcher.py
```

**Expected result:**
- No Python errors or tracebacks
- Summary printed showing disaster counts by source
- `curated_disasters.json` file created/updated
- Completion time under 5 minutes

### Test 5.2: JSON Output Valid

**Steps:**
```bash
python3 -c "import json; data=json.load(open('curated_disasters.json')); print(f'{len(data)} disasters loaded')"
```

**Expected result:**
- No JSON parse errors
- Reports a reasonable number of disasters (likely 30-150+)

### Test 5.3: No Expired Disasters in Output

**Steps:**
```bash
python3 -c "
import json
from datetime import datetime
data = json.load(open('curated_disasters.json'))
expired = [d for d in data if d.get('status') == 'expired']
print(f'Expired: {len(expired)} (should be 0)')
for d in expired:
    print(f'  {d[\"id\"]}: {d[\"status\"]}')
"
```

**Expected result:**
- Zero expired disasters in the output

### Test 5.4: All URLs Accessible

**Steps:**
```bash
python3 dst_data_fetcher.py --verify-links
```

**Expected result:**
- Report shows URL check results
- Zero broken links (or broken links are documented with fallback URLs)

### Test 5.5: Federal Register API Returns SBA Results

**Steps:**
1. Run the data fetcher
2. Check the summary output for SBA disaster counts
3. Cross-reference: go to `https://www.federalregister.gov` and search for recent SBA disaster loan notices

**Expected result:**
- Summary shows "SBA from Federal Register: X" with at least some results
- SBA disasters in the JSON output have Federal Register URLs as official links (format: `https://www.federalregister.gov/documents/...`)
- If Federal Register returns zero SBA results, this may be correct (no recent SBA declarations) — verify manually

### Test 5.6: Federal Register API Returns USDA Results

**Steps:**
1. Run the data fetcher
2. Check the summary output for USDA disaster counts
3. Cross-reference: go to `https://www.federalregister.gov` and search for recent USDA secretarial disaster designations

**Expected result:**
- Summary shows "USDA from Federal Register: X" with at least some results
- USDA disasters in the JSON output have Federal Register URLs as official links
- If zero USDA results, verify manually against Federal Register

### Test 5.7: No FEMA Records in curated_disasters.json

**Steps:**
```bash
python3 -c "
import json
data = json.load(open('curated_disasters.json'))
fema = [d for d in data if d.get('source') == 'FEMA']
print(f'FEMA records in curated JSON: {len(fema)} (should be 0)')
"
```

**Expected result:**
- Zero FEMA records in `curated_disasters.json` (frontend fetches FEMA live — curated JSON should only contain non-FEMA sources)

### Test 5.8: GitHub Actions Log Check

**Steps:**
1. Go to GitHub repository → Actions tab
2. Click on the most recent "Update DST Data" run
3. Read the log output

**Expected result:**
- Green checkmark (successful run)
- Log shows disaster counts matching what the script shows locally
- If any warnings, they're about scraper issues (not data corruption)
