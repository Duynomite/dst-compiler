#!/usr/bin/env python3
"""
Fuzzy matcher: cross-references carrier_gaps.json against all_disasters.json
to find gaps that already have FEMA FM (or other) coverage under different names.

Output: match report showing which gaps are already covered, which need research.
"""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

def normalize_fire_name(title: str) -> str:
    """Normalize a fire/disaster name for comparison."""
    title = title.upper().strip()
    # Remove common prefixes/suffixes
    title = re.sub(r'\bFIRE\b', '', title)
    title = re.sub(r'\bCOMPLEX\b', '', title)
    title = re.sub(r'\bWILDFIRE[S]?\b', '', title)
    title = re.sub(r'\bFEMA[-/]?FM[-/]?\d+[-/]?\w*\b', '', title)
    title = re.sub(r'\(.*?\)', '', title)  # Remove parentheticals
    title = re.sub(r'\bARI?ZONI?A\b', 'AZ', title)  # Fix Aetna misspelling
    title = re.sub(r'\bCOUNTY\b', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title

def normalize_county(county: str) -> str:
    """Normalize county names for comparison."""
    c = county.upper().strip()
    c = re.sub(r'\bCOUNTY\b', '', c)
    c = re.sub(r'\bCOUNTIES\b', '', c)
    c = re.sub(r'\bPARISH\b', '', c)
    c = re.sub(r'\s+', ' ', c).strip()
    return c

def similarity(a: str, b: str) -> float:
    """String similarity ratio."""
    return SequenceMatcher(None, a, b).ratio()

def main():
    base = Path(__file__).parent

    with open(base / 'carrier_gaps.json') as f:
        gaps_data = json.load(f)

    with open(base / 'all_disasters.json') as f:
        all_data = json.load(f)

    existing = all_data['disasters']

    # Index existing records by state
    by_state = {}
    for rec in existing:
        st = rec.get('state', '')
        by_state.setdefault(st, []).append(rec)

    gaps = gaps_data['gaps']
    matches = []
    unmatched = []
    already_expired = []

    for gap in gaps:
        state = gap['state']
        gap_title = gap['title']
        gap_type = gap['incident_type']
        gap_norm = normalize_fire_name(gap_title)
        gap_counties = set(normalize_county(c) for c in gap.get('counties', []))

        # Check if SEP already expired
        from datetime import date
        sep_end = gap.get('sep_end')
        if sep_end:
            try:
                end = date.fromisoformat(sep_end)
                if end < date.today():
                    already_expired.append(gap)
                    continue
            except (ValueError, TypeError):
                pass

        best_match = None
        best_score = 0.0

        state_records = by_state.get(state, [])
        for rec in state_records:
            rec_title = rec.get('title', '')
            rec_norm = normalize_fire_name(rec_title)

            # Name similarity
            name_sim = similarity(gap_norm, rec_norm)

            # Check if gap fire name is contained in record title or vice versa
            containment = 0.0
            if gap_norm and rec_norm:
                if gap_norm in rec_norm or rec_norm in gap_norm:
                    containment = 0.85
                # Check individual words
                gap_words = set(gap_norm.split()) - {'', 'THE', 'OF', 'AND', 'IN'}
                rec_words = set(rec_norm.split()) - {'', 'THE', 'OF', 'AND', 'IN'}
                if gap_words and rec_words:
                    overlap = len(gap_words & rec_words) / max(len(gap_words), len(rec_words))
                    containment = max(containment, overlap * 0.9)

            # County overlap
            rec_counties = set()
            for c in rec.get('affectedCounties', []):
                if isinstance(c, dict):
                    rec_counties.add(normalize_county(c.get('name', '')))
                else:
                    rec_counties.add(normalize_county(str(c)))

            county_match = 0.0
            if gap_counties and rec_counties:
                # Check for any overlap
                for gc in gap_counties:
                    for rc in rec_counties:
                        if gc and rc and (gc in rc or rc in gc):
                            county_match = 0.5
                            break

            # Check if record is statewide (covers everything)
            if rec.get('affectedCounties') and any(
                (isinstance(c, dict) and c.get('name', '').upper() == 'STATEWIDE') or
                (isinstance(c, str) and c.upper() == 'STATEWIDE')
                for c in rec['affectedCounties']
            ):
                county_match = 0.3  # Statewide covers the county but weaker signal

            score = max(name_sim, containment) + county_match

            if score > best_score:
                best_score = score
                best_match = rec

        threshold = 0.65  # Minimum combined score for a match
        if best_match and best_score >= threshold:
            matches.append({
                'gap': gap,
                'match': best_match,
                'score': best_score,
                'gap_norm': gap_norm,
                'match_norm': normalize_fire_name(best_match.get('title', '')),
            })
        else:
            unmatched.append({
                'gap': gap,
                'best_candidate': best_match,
                'best_score': best_score,
            })

    # Print results
    print("=" * 80)
    print(f"CARRIER GAP FUZZY MATCHING REPORT")
    print(f"=" * 80)
    print(f"\nTotal gaps: {len(gaps)}")
    print(f"Already expired (SEP ended): {len(already_expired)}")
    print(f"Matched to existing records: {len(matches)}")
    print(f"Unmatched (need research): {len(unmatched)}")

    if already_expired:
        print(f"\n{'─' * 80}")
        print(f"EXPIRED GAPS (no action needed — SEP window closed)")
        print(f"{'─' * 80}")
        for gap in already_expired:
            print(f"  [{gap['state']}] {gap['title']} — SEP ended {gap['sep_end']}")

    if matches:
        print(f"\n{'─' * 80}")
        print(f"MATCHED — Already covered by existing records")
        print(f"{'─' * 80}")
        for m in sorted(matches, key=lambda x: -x['score']):
            g = m['gap']
            r = m['match']
            print(f"\n  CARRIER GAP: [{g['state']}] {g['title']}")
            print(f"    Type: {g['incident_type']} | Authority: {g['declaring_authority']}")
            print(f"    Counties: {', '.join(g.get('counties', []))}")
            print(f"  MATCHES →  {r['id']}: {r['title']}")
            print(f"    Score: {m['score']:.2f} | Name: '{m['gap_norm']}' vs '{m['match_norm']}'")

    if unmatched:
        print(f"\n{'─' * 80}")
        print(f"UNMATCHED — Need research or are genuinely missing")
        print(f"{'─' * 80}")
        # Group by type
        by_type = {}
        for u in unmatched:
            t = u['gap']['incident_type']
            by_type.setdefault(t, []).append(u)

        for itype, items in sorted(by_type.items()):
            print(f"\n  [{itype}] ({len(items)} gaps)")
            for u in items:
                g = u['gap']
                print(f"    [{g['state']}] {g['title']}")
                print(f"      Counties: {', '.join(g.get('counties', []))}")
                print(f"      SEP: {g.get('sep_start', '?')} → {g.get('sep_end', '?')}")
                if u['best_candidate']:
                    bc = u['best_candidate']
                    print(f"      Closest: {bc['id']}: {bc['title']} (score: {u['best_score']:.2f})")
                else:
                    print(f"      No candidates in state")

    # Write summary JSON for downstream use
    summary = {
        'run_date': str(date.today()),
        'total_gaps': len(gaps),
        'expired': len(already_expired),
        'matched': len(matches),
        'unmatched': len(unmatched),
        'matched_details': [
            {
                'gap_state': m['gap']['state'],
                'gap_title': m['gap']['title'],
                'gap_type': m['gap']['incident_type'],
                'matched_id': m['match']['id'],
                'matched_title': m['match']['title'],
                'score': round(m['score'], 2),
            }
            for m in matches
        ],
        'unmatched_details': [
            {
                'state': u['gap']['state'],
                'title': u['gap']['title'],
                'type': u['gap']['incident_type'],
                'counties': u['gap'].get('counties', []),
                'sep_end': u['gap'].get('sep_end'),
                'declaring_authority': u['gap'].get('declaring_authority'),
            }
            for u in unmatched
        ],
    }

    with open(base / 'gap_match_results.json', 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"\n\nResults written to gap_match_results.json")

if __name__ == '__main__':
    main()
