# DST Compiler Tool v2.0 — PRD (Product Requirements Document)

## Problem Statement

The DST Compiler Tool helps CPC agents verify which Disaster Special Enrollment Periods (DSTs) are currently active so they can compliantly enroll Medicare Advantage beneficiaries affected by declared disasters. The v1 tool captures FEMA disasters well via live API, but misses governor-declared state emergencies, HHS public health emergencies, and USDA drought designations — source types that independently trigger valid DST SEPs under 42 CFR 422.62(a)(6). This creates a compliance gap where agents cannot verify the legitimacy of DSTs and miss valid enrollment opportunities.

## Context

- CPC is a Medicare Advantage distribution agency with ~25 agents doing ~1,000 submits/month
- DST SEPs allow enrollment outside normal periods when a government entity declares a disaster
- Three levels of government can declare: federal (FEMA, HHS, SBA, USDA, FMCSA), state (governors), and local (county/city)
- CMS reversed proposed DST restrictions in March 2025 — agents CAN process DST enrollments directly with carriers
- The tool is deployed on GitHub Pages and used as a read-only compliance reference
- Agents ONLY use DSTs posted by government entities — they do not discover, report, or add DSTs

## Users

| User | Role | Technical Level | Usage |
|------|------|----------------|-------|
| CPC field agents | Look up active DSTs for client enrollments | Low — need simple search-and-verify | Daily during enrollment conversations |
| CPC compliance/admin | Maintain curated disaster data, verify accuracy | Medium — can edit JSON, run Python scripts | Weekly or after major disasters |
| CPC leadership | Ensure tool accuracy for compliance | Non-technical — needs to see it working | Periodic review |

## Goals

1. **Complete federal source coverage** — Every active FEMA, HHS, SBA, USDA, and FMCSA disaster declaration is captured
2. **Governor declaration coverage** — All active state-level emergency declarations that trigger DST SEPs are included
3. **Date accuracy** — SEP windows are calculated correctly per 42 CFR (2 full calendar months after incident end, 14-month max)
4. **Compliance-ready** — Every DST entry has an official source link, and the 3-part attestation checklist is prominent
5. **Data freshness** — Automated pipeline runs daily; curated data staleness is visible to agents
6. **CPC brand compliance** — Tool matches CPC visual identity standards

## Features (MVP — MUST)

### M1: Governor Declaration Backfill
Populate all currently active governor-declared state emergencies into curated_disasters.json. Research confirms 18+ governor declarations for the Jan 2026 winter storm alone, many without corresponding FEMA declarations (TX, NC, VA, AL, NM, NY, NJ, PA, DE). Each entry must have: state, counties, dates, official governor's office URL.

### M2: Governor/State Source Type in Data Pipeline
Add `STATE` as a fully supported source type in the dst_data_fetcher.py pipeline with its own color badge, validation rules, and display format in the UI.

### M3: HHS Public Health Emergency Coverage
Add any active HHS-declared public health emergencies to curated data. Add Federal Register API monitoring for HHS declarations in the fetcher.

### M4: USDA Drought/Disaster Designation Coverage
Add USDA FSA disaster designations to curated data. Enhance Federal Register API monitoring to capture USDA drought and disaster designations automatically.

### M5: UI Upgrade to CPC Brand Standards
- Tailwind v4 CDN with `@theme` brand tokens (accent, secondary, text, deep-navy, light-cyan)
- Urbanist headings, Jost body text via Google Fonts
- Card styling per CPC standards (white bg, light-cyan border, accent elements)
- Responsive at 1024px and 1440px

### M6: GitHub Actions Verification and Monitoring
- Verify the daily cron job is running successfully
- Ensure failure creates a GitHub Issue for visibility
- Add data freshness timestamp that agents can see

### M7: Data Freshness Warning
- Show "Last Updated" timestamp prominently
- Display warning banner if curated data is more than 7 days old
- Agents must know whether they're looking at current data

### M8: Audit Script Validation Pass
- Run the existing 21-check audit script against all data
- Fix any validation failures
- Add validation for new source types (STATE, HHS, USDA)

### M9: "Last Verified" Date Per Curated Entry
- Each curated disaster entry includes a `lastVerified` date field
- Shows when a human last confirmed this declaration is still active and accurate
- Critical for governor declarations which may expire without formal notice

## Features (Future — SHOULD/COULD/WON'T)

| Feature | Priority | Notes |
|---------|----------|-------|
| Improve county search UX (autocomplete, fuzzy match) | SHOULD | Primary agent workflow is county-based |
| Add local government source type support | COULD | Valid DST trigger but rare and hard to discover |
| Add FMCSA scraper for automated detection | COULD | Only ~3-5 declarations/year, curation is fine |
| Add admin alert when new disasters detected | COULD | Nice for awareness, not agent-facing |
| Historical DST archive for audit trail | WON'T | Agents only need active DSTs |
| Merge full SEP reference from SEPAnalyzer | WON'T | Different tool, different purpose |
| Real-time push notifications to agents | WON'T | Daily updates sufficient for DST timelines |
| Agent-facing "report missing DST" | WON'T | Agents only use DSTs posted by gov entities |

## Constraints

- **Compliance:** Tool is used for Medicare enrollment decisions. Wrong dates or missing declarations = compliance risk
- **No centralized governor API:** Governor declarations must be manually curated from state websites
- **Read-only for agents:** Agents consume data, never contribute to it
- **Single-file architecture:** index.html must remain a standalone file deployed to GitHub Pages
- **No auth required:** Tool is accessible to any CPC agent via URL
- **CMS election code:** All DST enrollments use code `SEP DST`

## Out of Scope

- Agent account management or login
- Enrollment processing or SunFire integration beyond copy-to-clipboard
- Non-DST SEP types (those stay in the separate SEPAnalyzer tool)
- Beneficiary-facing features
- Commission calculation or tracking
- Agent reporting or feedback mechanisms
