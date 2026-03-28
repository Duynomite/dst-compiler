# Carrier Intelligence Report v2 — DST Data Pipeline Improvements

> Generated 2026-03-27. Based on four-carrier cross-reference (Aetna, Wellcare, Humana, Healthspring).

## How Carriers Find Declarations

### Aetna (108 records in Excel)
- **Primary sources:** FEMA API (DR/EM/FM), governor proclamations, CMS notifications
- **Coverage pattern:** Strong on FEMA + major governor declarations. Tracks FM/FMAG records that we previously excluded.
- **Notable:** Uses CMS-style reference numbers (e.g., CAG4601401) that map to multiple events. One carrier ref can cover 5+ separate governor proclamations.
- **Gaps relative to us:** Missing smaller state declarations (crime emergencies, infrastructure, homelessness). Doesn't track SBA or FMCSA.

### Wellcare (3,885 rows, ~132 unique active)
- **Primary sources:** CMS bulletin monitoring, FEMA API, state government press releases
- **Coverage pattern:** Broadest coverage of any carrier. Tracks categories we don't: forest management proclamations, local board resolutions, proactive/preventive declarations.
- **Notable:** Tracks expired and historical records (3,885 total vs 132 active). Includes Puerto Rico declarations.
- **Questionable entries:** CA Forest Management (preventive, not disaster-response), LA Board Resolution (immigration, not natural disaster). These may not be valid DST triggers per 42 CFR 422.62(b)(18).

### Humana (22-page PDF, ~82 declarations)
- **Primary sources:** FEMA, governor proclamations, CMS
- **Coverage pattern:** Conservative — focuses on disasters with confirmed beneficiary impact. Best source for incident end dates (more accurate than our research in several FL cases).
- **Key intelligence:** Provided confirmed incidentEnd dates for 4 FL records (Milton, May 2024 Tornadoes, Lake County Flooding, NW FL Tornadoes) and OH winter storm.

### Healthspring (separate Excel, overlaps with Humana)
- **Primary sources:** Same as Humana (owned by Cigna, shares data pipeline)
- **Coverage pattern:** Nearly identical to Humana with minor date variations

## Categories We Were Missing

### 1. Omnibus Governor Proclamations
California's Dec 23, 2025 proclamation covered **6 separate events** from throughout the year in a single omnibus declaration. Our previous pipeline treated each proclamation as one event, missing compound declarations.
- **Impact:** 8 new CA records added from 2 omnibus proclamations (Dec 23 + Dec 24)
- **Pipeline fix:** When a carrier flags a state with multiple events under one date, check for omnibus declarations.

### 2. Short-Duration Events
Several events lasted only 1-3 days (tsunamis, single-day monsoons, windstorms). Our previous research focused on longer-running emergencies.
- **Impact:** 4 new short-duration records (CA Tsunami 1 day, CA Windstorm 2 days, CA Monsoon 1 day, NJ storms)
- **Pipeline fix:** Don't skip events just because they're short — the SEP window is 2 calendar months regardless of incident duration.

### 3. Multi-State Storm Systems
The Feb 22, 2026 nor'easter triggered declarations in NY (EO 58), NJ (EO 14), DE, and PA simultaneously. We had none of these before.
- **Impact:** 4 new records from one storm system
- **Pipeline fix:** When one state declares for a storm, check neighboring states within 48 hours.

### 4. Puerto Rico Declarations
PR uses "Orden Ejecutiva" (OE) numbering. Our pipeline had zero PR records despite carriers tracking them.
- **Impact:** 1 new PR record added (OE-2025-022, April rains affecting 28 municipalities)
- **Pipeline fix:** Monitor `docs.pr.gov/files/Estado/OrdenesEjecutivas/` and `ayudalegalpr.org` for PR declarations.

### 5. Long-Running Renewable Emergencies
The Lahaina wildfire emergency (HI) has been continuously renewed since August 2023 — now on its 28th proclamation. Our pipeline didn't track pre-2025 declarations with active renewals.
- **Impact:** 1 new HI record with renewal chain
- **Pipeline fix:** For ongoing emergencies, track renewal dates to prevent 14-month expiration miscalculation.

## Carrier SEP Window Discrepancy

**Critical finding:** Carriers use 12-14 month SEP windows for FMAG/FM records, while the regulatory 2-month calculation from 42 CFR 422.62(b)(18) produces much shorter windows. This means:
- Carriers honor DSTs for longer than the regulatory minimum
- Our tool should use the regulatory calculation (conservative, compliant) but flag when carriers recognize a longer window
- Future enhancement: carrier acknowledgment badges on DST cards

## Pipeline Improvement Recommendations

### Immediate (This Session)
1. ~~Add all ~20 missing records from gap analysis~~ DONE
2. ~~Fix FL incidentEnd dates per Humana data~~ DONE
3. ~~Fix NY EO 57 URL (was pointing to EO 55)~~ DONE

### Short-Term (Next 2-4 Weeks)
4. **Monitor CA CalOES proclamations page** for new omnibus declarations
5. **Add Puerto Rico monitoring** — check `docs.pr.gov` monthly
6. **Multi-state storm correlation** — when adding a state declaration, auto-flag neighboring states
7. **Carrier data refresh** — request updated carrier Excel/PDFs quarterly

### Medium-Term (1-3 Months)
8. **Carrier acknowledgment badges** in UI — show which carriers honor each DST
9. **Automated PR monitoring** — scrape `estado.pr.gov/ordenes-ejecutivas` for new OEs
10. **Omnibus detection** — flag proclamations that cover multiple events for manual split

## Data Quality Metrics

| Metric | Before Phase 3 | After Phase 3 |
|--------|----------------|---------------|
| Curated records | 175 | 184 |
| Total records (incl FEMA) | 226 | 235 |
| Carrier match rate | ~57% (100/175) | ~85%+ (est.) |
| States covered | 28 + DC | 30 + DC + PR |
| CA records | 17 | 25 |
| NJ records | 1 | 5 |
| NY records | 2 | 4 |
| PR records | 0 | 1 |
| Audit pass rate | 4027/4028 | 4233/4235 |

## Skipped Records (Intentional)

| Record | Reason |
|--------|--------|
| CA Forest Management/Wildfire Prevention (Mar 2025) | Proactive/preventive proclamation, no disaster event. Not a valid DST trigger. |
| CA Board Resolution LA (Oct 2025) | Immigration enforcement emergency from LA Board of Supervisors. Not a natural disaster. |
| NY EO 56 Healthcare Staff Shortage (Jan 2026) | Labor/healthcare emergency (nursing strike). DST eligibility uncertain — not a disaster per typical CMS interpretation. |
| WY EO 2025-08 (Government Shutdown) | Federal government shutdown emergency. Marginal DST validity — no carrier confirmed. |
| PR OE-2024-004 (Landslides) | Could not find official EO or confirm details. Carrier reference only. |
| PR OE-2025-022 July expansion | Could not confirm territory-wide July amendment. May not exist as described. |
