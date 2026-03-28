# DST Compiler — Runbook

> How to operate, maintain, and extend the DST compiler system.
> For project context, see CLAUDE.md. For history, see CHANGELOG.md.

---

## System Overview

```
DAILY (GitHub Actions 6AM EST):
  dst_data_fetcher.py
    → Collects SBA (Federal Register API), HHS, FMCSA, STATE, FEMA (OpenFEMA API)
    → Applies CORRECTIONS table (46 verified T1-T5 incidentEnd dates)
    → Flags stale ongoing records via STATE_EMERGENCY_DURATION table
    → Injects carrier acknowledgments from carrier_analysis.json
    → Writes curated_disasters.json + all_disasters.json
    → Auto-commits if data changed

WEEKLY (Monday 10AM EST):
  dst_renewal_checker.py --auto-apply
    → Strategy 1: TX predicted URL check (monthly renewals)
    → Strategy 2: NY/FL sequential EO check
    → Strategy 3: Archive page keyword scan (all states)
    → Strategy 4: New declaration discovery + FEMA cross-check
    → Auto-applies verified renewals to curated_disasters.json

  dst_verifier.py
    → Layer 1: FEMA API cross-reference (incidentEndDate comparison)
    → Layer 2: Declaration page content scan (HTML + PDF, keyword + hash)
    → Layer 3: Staleness check (state auto-expire limits)

  audit_curated_data.py --ci
    → 28 structural checks per record
    → eCFR regulatory monitoring (Check 25)
    → HHS PHE 90-day expiry (Check 28)
    → URL verification (HEAD + content)
```

---

## Common Operations

### Add a New State Declaration

1. Find the governor's executive order URL (must be specific, not a homepage)
2. Add a `build_record()` call in `dst_data_fetcher.py` under `_get_curated_state()`
3. Use the next available ID: `STATE-{YEAR}-{NUM}-{ST}` (check existing IDs first)
4. Set `incident_end=None` if ongoing, or the actual date if known
5. Add renewal dates if the declaration has been extended
6. Run: `python3 dst_data_fetcher.py && python3 audit_curated_data.py`
7. Verify the record appears in `curated_disasters.json`
8. Commit + push to both repos (claude-projects AND dst-compiler)

### Set an incidentEnd Date (Declaration Ended)

Only use verified T1-T5 sources (see Verification Framework below).

1. Add entry to CORRECTIONS table in `dst_data_fetcher.py`:
   ```python
   "STATE-20XX-NNN-ST": ("YYYY-MM-DD", "T#", "Source description"),
   ```
2. Run fetcher — the record's SEP window will recalculate automatically
3. If SEP window has passed, the record will be auto-removed

### Update a Renewal (Declaration Extended)

1. Find the record in `dst_data_fetcher.py`
2. Add the new date to `renewal_dates_list`
3. Update `official_url` to the latest renewal's URL
4. Update `last_verified` to today
5. Run fetcher + audit

### Handle URL Rot (Broken Declaration Link)

1. Search for replacement URL on the governor's website
2. Try Wayback Machine: `web.archive.org/web/*/[original-url]`
3. Update `official_url` in the `build_record()` call
4. Run `python3 dst_verifier.py --pages-only` to verify

### Deploy Changes

Two repos must stay in sync:
- `Duynomite/claude-projects` — source of truth (DST Tool NEW/dst-compiler/)
- `Duynomite/dst-compiler` — GitHub Pages deployment

```bash
# 1. Commit to claude-projects
cd ~/Downloads/Claude
git add "DST Tool NEW/dst-compiler/..." && git commit && git push

# 2. Copy to deploy repo and push
SRC="DST Tool NEW/dst-compiler"
DEST="/tmp/dst-compiler-deploy"
cp $SRC/{curated_disasters.json,all_disasters.json,dst_data_fetcher.py,index.html} $DEST/
cd $DEST && git add -A && git commit && git push
```

---

## Verification Framework (T1-T5)

Per 42 CFR 407.23(b)(2): "The SEP ends 2 months after the end date identified in the declaration."

Every incidentEnd correction must have a documented source:

| Tier | Source | Example |
|------|--------|---------|
| T1 | End date in declaration text | "EO effective through Feb 22" |
| T2 | Governor termination proclamation | Gov. Ivey formally terminated Feb 2 |
| T3 | Official incident end announcement | CAL FIRE containment, FEMA incident period |
| T4 | State statutory auto-expire (verified no extension) | WI 60-day cap, KS 15-day cap |
| T5 | Carrier-confirmed + research alignment | Aetna says Feb 22, matches 30-day pattern |

**NOT valid:** Duration estimates, "typical" timelines, fire containment used as declaration end without verification.

---

## State Emergency Duration Laws

| State | Limit | Statute | Extension Mechanism |
|-------|-------|---------|---------------------|
| KS | 15 days | K.S.A. 48-924 | Legislative concurrent resolution |
| NV | 15 days | NRS 414.070 | — |
| ME | 14 days | 37-B MRSA §742 | — |
| IN | 30 days | IC 10-14-3-12 | Governor renewal |
| KY | 30 days | KRS 39A.090 | General Assembly extension |
| MD | 30 days | GPS 14-107 | Governor renewal |
| NY | 30 days | Per EO | Sequential EOs (57 → 57.1 → 57.2) |
| LA | 30 days | Per renewal | Monthly re-issuance (JML-26-xxx) |
| TX | 30 days | Per renewal | Monthly proclamations |
| FL | 60 days | Per EO | Extension EO before expiry |
| WI | 60 days | § 323.10 | Joint legislative resolution |
| PA | 90 days | Constitution Art. IV §20 | Legislative extension |
| **AZ** | **None** | A.R.S. 26-303 | 120d is PUBLIC HEALTH ONLY |
| **NM** | **None** | Bills HB0040/HB0080 failed | Governor must formally terminate |
| NE, CA, MA, etc. | None | Various | Governor must formally terminate |

---

## SEP Window Calculation (42 CFR § 422.62(b)(18))

```
SEP Start = earlier of declarationDate and incidentStart

If incidentEnd exists:
  SEP End = last day of 2nd full calendar month after incidentEnd month
  Example: incidentEnd Jan 15 → SEP End Mar 31 (NOT Mar 16 = 60 days)

If incidentEnd is null (ongoing):
  maxDate = latest of declarationDate or any renewalDate
  SEP End = last day of 14th full calendar month after maxDate

CRITICAL: "2 calendar months" ≠ "60 days"
  Jan 15 + 60 days = Mar 16
  Jan 15 + 2 calendar months = Mar 31
```

---

## Data Sources

| Source | Method | Refresh | Records |
|--------|--------|---------|---------|
| FEMA | OpenFEMA API (live in browser + backend) | Real-time | ~51 active |
| SBA | Federal Register API | Daily | ~9 |
| HHS | Curated + scrape attempt | Daily | 1 |
| FMCSA | Curated + scrape attempt (403 blocks bots) | Daily | ~66 |
| STATE | Manual curation + renewal checker | Weekly | ~89 |
| Carriers | Excel files (Aetna/Wellcare/Humana) | Quarterly | Validation only |

---

## Carrier Acknowledgment System

Carrier data is validation-only, not authoritative. Government sources are the source of truth.

- `carrier_analysis.json` stores Aetna + Wellcare match data
- `four_carrier_crossref.py` embeds Humana + Healthspring data
- `inject_carrier_acknowledgments()` post-processes records before JSON write
- UI shows colored pills: Aetna (purple), Wellcare (blue), Humana (green), Healthspring (orange)

---

## File Map

| File | Purpose |
|------|---------|
| `index.html` | The agent-facing tool (React 18 + Tailwind v4) |
| `curated_disasters.json` | Non-FEMA disaster data (updated by fetcher) |
| `all_disasters.json` | Curated + FEMA merged (for audit/analysis) |
| `dst_data_fetcher.py` | Main pipeline: collectors + CORRECTIONS + carrier acks |
| `dst_verifier.py` | Page content verification (FEMA cross-ref + keyword scan + hash) |
| `dst_renewal_checker.py` | Auto-detect renewals + terminations + new declarations |
| `audit_curated_data.py` | 28-check structural validation |
| `carrier_data_parser.py` | Parse carrier Excel files |
| `four_carrier_crossref.py` | Humana/Wellcare crossref data + matching |
| `carrier_analysis.json` | Match/gap/discrepancy data from carrier parser |
| `medicare_enrollment.json` | County-level Medicare enrollment (CMS) |
| `county_state_map.json` | County-to-state lookup (~3,200 entries) |
| `.github/workflows/update-data.yml` | CI: daily fetch + weekly verification |

---

## Quarterly Carrier Data Refresh

Carrier acknowledgment badges are based on a one-time Excel import (March 2026). To refresh:

1. Request updated DST tracking files from carriers:
   - **Aetna:** Excel file with active DST list (contact compliance team)
   - **Wellcare:** Excel file or live page scrape (`1b3050-423b.icpage.net/Wellcare-SEP-Declarations---FEMAState`)
   - **Humana:** PDF of active DST declarations (contact compliance team)
   - **Healthspring:** Excel file (same contact as Humana — Cigna subsidiary)

2. Place Excel files in project root, run parser:
   ```bash
   python3 carrier_data_parser.py --aetna new_aetna.xlsx --wellcare new_wellcare.xlsx
   ```
   This regenerates `carrier_analysis.json` with updated match/gap data.

3. For Humana PDF: update the `HUMANA` array in `four_carrier_crossref.py` manually (parse PDF visually).

4. Run fetcher to re-inject carrier acks:
   ```bash
   python3 dst_data_fetcher.py
   ```

5. Check for new gaps (records carriers have that we don't):
   ```bash
   python3 -c "import json; gaps=[g for g in json.load(open('carrier_analysis.json')).get('gaps',[]) if g]; print(f'{len(gaps)} gaps')"
   ```

---

## Troubleshooting

### Audit fails in CI
Check which check failed. Common causes:
- Check 27: URL domain doesn't match source type → fix officialUrl
- Check 28: HHS PHE 90-day limit → research renewal
- Check 25: eCFR version changed → regulation may have been amended (urgent)

### Fetcher produces fewer records than expected
Per-source thresholds block if any source drops >20%. Check:
1. Federal Register API returning fewer results (intermittent)
2. FEMA API timeout (retry)
3. Records expired naturally (check CORRECTIONS table)

### Governor website reorganized (URLs broken)
1. Run `python3 dst_verifier.py --pages-only` to find all broken URLs
2. Search for replacement URLs
3. Try Wayback Machine for archived versions
4. Update officialUrl in build_record() calls

### New governor takes office (URL patterns change)
Governor transitions reset EO numbering and change website domains:
- FL: DeSantis → new governor (if applicable)
- NJ: Murphy → Sherrill (EO numbering reset from 400s to 1)
- Update STATE_EO_ARCHIVES in renewal checker
- Update TX_RECORD_SLUGS if governor name changes in URL pattern
