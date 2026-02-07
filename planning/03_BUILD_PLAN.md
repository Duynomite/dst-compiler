# DST Compiler Tool — Build Plan

## Overview

This plan breaks the build into 7 phases. Each phase is independently testable and produces a working (if incomplete) tool. Phase 1 is the absolute minimum — a tool that shows live FEMA data. Each subsequent phase adds a layer of completeness.

**Estimated total build time:** 5-8 hours of Claude Code work across multiple sessions.

**Rule:** Do not move to the next phase until the current phase passes all its verification checks.

---

## Phase 1: FEMA Live Data + Basic Display

**Goal:** A working HTML page that fetches live FEMA data and displays all active DSTs sorted by state.

**Build:**
1. Create `index.html` with React 18, Tailwind CSS, Babel Standalone (all via CDN)
2. Implement FEMA API fetch on page load:
   - Query: `declarationDate ge '{24 months ago}'`
   - Paginate (1000 records per page) to get all results
   - Consolidate county-level records into disaster-level records (group by `femaDeclarationString`)
3. Implement SEP window calculation in JavaScript:
   - `sepStart = min(declarationDate, incidentBeginDate)`
   - `sepEnd = last day of 2nd full calendar month after incidentEndDate`
   - 14-month maximum for ongoing disasters
   - Filter out expired DSTs
4. Display results sorted by state (alphabetical):
   - State header with count of active DSTs
   - Each DST card: source badge, title, type, declaration number, SEP window dates, status, official link
5. Create `county_state_map.json`:
   - Source: US Census Bureau FIPS county codes (download from census.gov or use a known dataset)
   - ~3,200 entries covering all 50 states + DC + PR + VI + GU + AS + MP
   - Normalize county names: strip "(County)" suffix, title case
   - Format: `{ "AL": ["Autauga", "Baldwin", ...], "AK": ["Aleutians East", ...], ... }`
6. Implement state + county search:
   - State dropdown populated from county_state_map.json
   - County text input with autocomplete filtered by selected state
   - Case-insensitive matching, handle "St." vs "Saint" variants
   - Show matching DSTs plus statewide declarations

**Verify before moving on:**
- [ ] Page loads and fetches FEMA data without errors
- [ ] At least 20+ active FEMA disasters displayed (confirm against fema.gov)
- [ ] DSTs sorted alphabetically by state
- [ ] SEP window dates calculated correctly (test with known disaster — check dates manually)
- [ ] Searching a county shows correct DSTs for that county
- [ ] Statewide declarations (like FEMA Emergency declarations) show for all county searches in that state
- [ ] Expired DSTs are hidden
- [ ] Ongoing disasters show "Ongoing" not a blank end date
- [ ] 14-month maximum enforced on ongoing disasters older than 14 months
- [ ] Official FEMA links work (format: `https://www.fema.gov/disaster/{NUMBER}`)

**Decision needed:** None — proceed after verification.

---

## Phase 2: Copy Button + SunFire Formatting

**Goal:** Agents can copy DST details in the exact format needed for SunFire enrollment notes.

**Build:**
1. Add "Copy" button to each DST card
2. On click, copy to clipboard in this format:
   ```
   DST — Hurricane Helene (FEMA DR-4834)
   SEP Window: Sept 23, 2024 — Ongoing
   Official Declaration: https://www.fema.gov/disaster/4834
   ```
3. Show brief "Copied!" feedback animation
4. Handle edge cases:
   - Ongoing: show "Ongoing" for end date
   - Expiring soon: include days remaining
   - Multi-source same event: each copy includes its own source/ID

**Verify before moving on:**
- [ ] Copy button works on all DST cards
- [ ] Pasted text matches the exact format above
- [ ] "Copied!" feedback appears and disappears
- [ ] Format is clean when pasted into a plain text field (no HTML artifacts)
- [ ] Ongoing disasters show "Ongoing" in copied text
- [ ] Dates formatted as human-readable (e.g., "Jan 23, 2026") not ISO format

**Decision needed:** None.

---

## Phase 3: Python Data Fetcher (Non-FEMA Sources)

**Goal:** A Python script that collects disaster data from HHS, FMCSA, SBA, USDA, State sources and outputs `curated_disasters.json`.

**Build:**
1. Create `dst_data_fetcher.py` with the following source modules:

   - **FEMA module** — API fetch (same logic as frontend, used for validation/logging and backup data). Fetches from FEMA API, consolidates county records, calculates SEP windows. FEMA records are logged but NOT written to `curated_disasters.json` (frontend fetches FEMA live).

   - **Federal Register module** — The primary automated collection method for SBA and USDA. Queries `federalregister.gov/api/v1/documents.json` with two separate searches:
     - SBA: `conditions[agencies][]=small-business-administration`, `conditions[type][]=notice`, `conditions[term]=disaster+loan`
     - USDA: `conditions[agencies][]=farm-service-agency`, `conditions[type][]=notice`, `conditions[term]=secretarial+designation+disaster`
     - Parse each result: extract title, publication date, abstract text
     - Extract affected states and counties from notice text (requires text parsing — look for patterns like "counties of X, Y, Z in the State of W")
     - Use the Federal Register document URL as the official declaration link
     - Auto-add results that clearly match disaster declarations with identifiable affected areas
     - Log ambiguous results for manual review

   - **HHS module** — Scrape `aspr.hhs.gov/legal/PHE/Pages/default.aspx`, extract active PHEs. Curated fallback data for when scraping fails.

   - **FMCSA module** — Scrape `fmcsa.dot.gov/emergency-declarations`, extract active emergencies AND state governor declarations listed there. Curated fallback. Note: only captures ~15-25% of governor declarations (transportation-related only).

   - **Drought Monitor module** — Query US Drought Monitor for counties at D3 (Extreme) and D4 (Exceptional) drought severity. Cross-reference against USDA designations found via Federal Register. Log warnings when severely drought-affected counties don't have corresponding USDA designations (discovery signal for potential missing data).

   - **Curated data modules** (three separate arrays within the script):
     - **SBA curated** — Known active SBA disasters not captured by Federal Register query. Typically empty if FR query works well.
     - **USDA curated** — Known active USDA designations not captured by Federal Register query.
     - **State curated** — Known state governor declarations not captured via FMCSA. This is the primary mechanism for state coverage beyond the ~15-25% FMCSA captures. Updated when Connor or agents report new state declarations.

2. Implement data validation:
   - Calculate SEP windows for all disasters
   - Filter out expired
   - Verify official URLs (HEAD request, retry once on timeout)
   - Flag broken links (use fallback URL, mark as "(general source page)" in record)
   - Validate all schema fields per the data validation rules in CLAUDE.md

3. Implement deduplication:
   - Same disaster from different API pages → deduplicate by ID
   - Same event from different sources (e.g., Hurricane from FEMA AND HHS) → keep both (different declaring authorities = different valid DSTs)
   - Federal Register results vs curated data → FR takes precedence (more current), skip curated record with same ID

4. Output `curated_disasters.json` with all non-FEMA active disasters

5. Print summary report:
   - Counts by source (SBA from FR: X, SBA curated: X, USDA from FR: X, etc.)
   - New discoveries from Federal Register (not seen in previous run)
   - Broken links found and fallback status
   - Drought Monitor warnings (severe drought counties without USDA designations)
   - Total active non-FEMA disasters in output

6. Create `requirements.txt`: `requests`, `beautifulsoup4`

**Verify before moving on:**
- [ ] Script runs without errors: `python3 dst_data_fetcher.py`
- [ ] Outputs valid JSON file with correct schema
- [ ] FEMA validation log matches what FEMA API returns live
- [ ] FEMA records are NOT in `curated_disasters.json` (frontend fetches FEMA live)
- [ ] Federal Register query returns SBA results (at least some disaster loan notices)
- [ ] Federal Register query returns USDA results (at least some secretarial designations)
- [ ] HHS PHE data present (at least the known active PHEs)
- [ ] FMCSA data present (check against fmcsa.dot.gov/emergency-declarations)
- [ ] State curated data loaded (even if initially empty)
- [ ] All SEP windows calculated correctly
- [ ] No expired disasters in output
- [ ] URL verification runs and reports results
- [ ] Summary report prints source counts clearly
- [ ] Script completes in under 5 minutes

**Decision needed:** Connor to review the first run's output and confirm: (1) Federal Register is discovering SBA/USDA disasters correctly, (2) any known state governor declarations to seed the curated data.

---

## Phase 4: Integrate Curated Data into Frontend

**Goal:** The HTML tool displays both live FEMA data AND curated non-FEMA data from the JSON file.

**Build:**
1. Modify `index.html` to load `curated_disasters.json` on page load (fetch from same directory or embedded)
2. Merge FEMA live data with curated data
3. Deduplicate by ID (live FEMA takes precedence over curated FEMA)
4. Add source badges with color coding:
   - FEMA: Blue
   - HHS: Red
   - SBA: Orange
   - USDA: Brown
   - FMCSA: Purple
   - STATE: Green
5. Add "Statewide" badge for statewide declarations
6. Add "Last updated" timestamp for curated data
7. Update search to include non-FEMA results:
   - County search matches county names in disaster records
   - Also shows all statewide declarations for the selected state
   - Also shows multi-state declarations that include the selected state

**Verify before moving on:**
- [ ] Tool shows FEMA + non-FEMA disasters
- [ ] Source badges display correctly with distinct colors
- [ ] Statewide declarations appear for any county search in that state
- [ ] Non-FEMA disasters have correct SEP windows
- [ ] Copy button works for non-FEMA disasters too
- [ ] "Last updated" timestamp displays
- [ ] Total disaster count is higher than FEMA-only (confirming non-FEMA data loaded)
- [ ] No duplicate disasters (same ID appearing twice)

**Decision needed:** None.

---

## Phase 5: GitHub Actions Automation

**Goal:** The data fetcher runs automatically every day and updates the JSON file without manual intervention.

**Build:**
1. Create GitHub repository structure:
   ```
   dst-compiler/
   ├── index.html
   ├── curated_disasters.json
   ├── dst_data_fetcher.py
   ├── requirements.txt
   ├── .github/
   │   └── workflows/
   │       └── update-data.yml
   ├── planning/
   └── CLAUDE.md
   ```
2. Create GitHub Actions workflow (`update-data.yml`):
   - Trigger: Daily at 6:00 AM EST (cron: `0 11 * * *`)
   - Also trigger: Manual dispatch (so Connor can run it on demand)
   - Steps:
     1. Checkout repo
     2. Set up Python 3.11
     3. Install dependencies
     4. Run `dst_data_fetcher.py`
     5. If `curated_disasters.json` changed, commit and push
     6. If script failed, create a GitHub Issue to alert Connor
3. Enable GitHub Pages on the repository (serves `index.html` and `curated_disasters.json` as a static site)
4. Write step-by-step GitHub setup guide for Connor (see Appendix A below)

**Verify before moving on:**
- [ ] GitHub Actions workflow runs successfully (check Actions tab)
- [ ] `curated_disasters.json` is updated with fresh data
- [ ] GitHub Pages serves the tool at `https://{username}.github.io/dst-compiler/`
- [ ] Manual dispatch trigger works (Connor can click "Run workflow" in GitHub)
- [ ] When the script fails, a GitHub Issue is created
- [ ] The HTML tool loads correctly from GitHub Pages

**Decision needed:** Connor needs to create a GitHub account and follow the setup guide.

---

## Phase 6: UI Polish and Agent Experience

**Goal:** The tool looks professional and is pleasant to use during a live call.

**Build:**
1. Clean, professional color scheme (medical/insurance industry appropriate)
2. Responsive layout that works well on a standard desktop monitor
3. Loading state while FEMA data fetches (spinner or skeleton)
4. Error state if FEMA API fails (show curated FEMA data as fallback)
5. "No disasters found" message when county search returns empty
6. Expiring soon visual indicator (orange/red badge with days remaining)
7. Statewide declaration visual prominence (full-width card or banner)
8. Smooth search interaction:
   - State dropdown filters county list dynamically
   - County input has type-ahead/autocomplete
   - Results update instantly on selection
9. All-disasters view (browse all active DSTs by state without searching)
10. Sorting controls:
    - By State (A-Z) — default
    - Most Recent First — by declaration date descending
    - Ending Soonest — by SEP window end date ascending (ongoing last)
11. Compact compliance reminder footer: brief mention of three-part validation requirement

**Verify before moving on:**
- [ ] Tool looks professional (not like a developer prototype)
- [ ] Loading state displays while data fetches
- [ ] Search is fast and responsive
- [ ] "No disasters found" displays cleanly
- [ ] Expiring-soon disasters are visually distinct
- [ ] Statewide declarations are visually prominent
- [ ] Page works correctly at common screen sizes (1366px, 1920px)
- [ ] All text is readable, no overlapping elements
- [ ] Compliance reminder is visible but not intrusive

**Decision needed:** Connor to review UI and provide feedback on colors, layout, and overall feel.

---

## Phase 7: End-to-End Testing and Verification

**Goal:** Confirm every piece works together correctly with real data.

**Build:**
1. Run the full data fetcher and verify output
2. Load the tool with real data and perform test searches
3. Verify specific known disasters:
   - Pick 5 known FEMA disasters, confirm they appear with correct dates
   - Pick 3 non-FEMA disasters, confirm they appear
   - Check a statewide declaration, confirm it shows for multiple counties
4. Verify SEP window calculations against manual calculations (at least 5 tests)
5. Verify all official links (click each one, confirm it loads the right page)
6. Test copy button output in a text editor
7. Test error scenarios:
   - Disconnect internet → does the tool show curated data?
   - Remove the JSON file → does it still show FEMA live data?
8. Review GitHub Actions logs from the last 3 runs
9. Document any issues found in CLAUDE.md "Known Issues" section

**Verify before moving on (this IS the final verification):**
- [ ] Tool displays correct data for at least 10 different county searches
- [ ] SEP window calculations match manual calculations for 5 test cases
- [ ] All visible official links load correct government pages
- [ ] Copy button produces correct format for 5 different DSTs
- [ ] GitHub Actions has run successfully at least 3 times
- [ ] Data freshness timestamp is accurate
- [ ] No JavaScript errors in browser console
- [ ] No expired DSTs visible in the interface
- [ ] 14-month maximum correctly hides old ongoing disasters

---

## Appendix A: GitHub Setup Guide for Connor

**You will need:** A computer with a web browser. That's it.

### Step 1: Create a GitHub Account (5 minutes)
1. Go to `https://github.com` and click "Sign up"
2. Use your email, create a username and password
3. Verify your email

### Step 2: Create the Repository (2 minutes)
1. Click the "+" icon (top right) → "New repository"
2. Name: `dst-compiler`
3. Description: "DST Compiler Tool for Medicare agents"
4. Set to **Private** (only you can see it)
5. Check "Add a README file"
6. Click "Create repository"

### Step 3: Enable GitHub Pages (1 minute)
1. Go to your repository → Settings → Pages
2. Under "Source," select "Deploy from a branch"
3. Branch: `main`, folder: `/ (root)`
4. Click Save

### Step 4: Upload Files (done via Claude Code)
Claude Code will push the project files to this repository. You'll provide the repository URL.

### Step 5: Verify GitHub Actions (1 minute)
1. Go to your repository → Actions tab
2. You should see the "Update DST Data" workflow
3. It runs daily automatically, or click "Run workflow" to trigger manually

### Step 6: Access Your Tool
Your tool will be available at: `https://{your-username}.github.io/dst-compiler/`
Bookmark this URL. Share it with your agents.

### Ongoing Maintenance
- **If GitHub Actions fails:** You'll see a GitHub Issue created automatically. Open Claude Code and ask it to fix the issue.
- **To add a new curated disaster:** Open Claude Code, describe the disaster, and ask it to add it to the data fetcher.
- **To force a data update:** Go to Actions tab → "Update DST Data" → "Run workflow"

---

## Appendix B: Session Planning

Each phase maps to roughly one Claude Code session:

| Session | Phases | Duration | Prerequisites |
|---------|--------|----------|---------------|
| 1 | Phase 1 + 2 | ~2 hours | None |
| 2 | Phase 3 | ~1.5 hours | Session 1 complete |
| 3 | Phase 4 | ~1 hour | Sessions 1-2 complete |
| 4 | Phase 5 | ~1 hour | GitHub account created, Sessions 1-3 complete |
| 5 | Phase 6 | ~1.5 hours | Sessions 1-4 complete |
| 6 | Phase 7 | ~1 hour | All previous sessions complete |
