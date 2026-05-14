"""Pull outdoor felonies AND outdoor misdemeanor assaults from NYPD Open Data, snap to NTAs.

Outdoor-walking premises: STREET, PARK/PLAYGROUND, HIGHWAY/PARKWAY, BUS STOP, BRIDGE.
Categories produced:
  - 'fel'  = all felonies (LAW_CAT_CD = FELONY)
  - 'mas'  = misdemeanor assault (LAW_CAT_CD = MISDEMEANOR AND OFNS_DESC = 'ASSAULT 3 & RELATED OFFENSES')
  - 'comb' = sum of the two
"""
import json, urllib.request, urllib.parse, sys, time
from datetime import datetime
from collections import defaultdict
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

ENDPOINT_HIST = 'https://data.cityofnewyork.us/resource/qgea-i56i.json'
PREM_TYPES = ['STREET','PARK/PLAYGROUND','HIGHWAY/PARKWAY','BUS STOP','BRIDGE']
START = '2022-01-01'
END = '2024-12-31'
PAGE = 50000

def fetch(where, select):
    out = []
    offset = 0
    while True:
        qs = urllib.parse.urlencode({
            '$select': select, '$where': where, '$limit': PAGE, '$offset': offset,
        })
        url = f'{ENDPOINT_HIST}?{qs}'
        sys.stderr.write(f'  offset={offset:,}\n')
        with urllib.request.urlopen(url) as r:
            chunk = json.load(r)
        out.extend(chunk)
        if len(chunk) < PAGE: break
        offset += PAGE
        time.sleep(0.2)
    return out

prem_in = ','.join(f"'{p}'" for p in PREM_TYPES)
base = (f"prem_typ_desc in({prem_in}) "
        f"AND rpt_dt>='{START}T00:00:00' AND rpt_dt<='{END}T23:59:59' "
        f"AND latitude IS NOT NULL AND longitude IS NOT NULL")
where_fel = "law_cat_cd='FELONY' AND " + base
where_mas = "law_cat_cd='MISDEMEANOR' AND ofns_desc='ASSAULT 3 & RELATED OFFENSES' AND " + base
select = 'cmplnt_num,cmplnt_fr_dt,cmplnt_fr_tm,latitude,longitude,prem_typ_desc,ofns_desc,law_cat_cd,rpt_dt'

print('fetching felonies...')
rows_fel = fetch(where_fel, select)
print(f'  felonies: {len(rows_fel):,}')
print('fetching misdemeanor assault...')
rows_mas = fetch(where_mas, select)
print(f'  misd. assault: {len(rows_mas):,}')

# dedupe within each set
seen_fel = {r['cmplnt_num']: r for r in rows_fel if r.get('cmplnt_num')}
seen_mas = {r['cmplnt_num']: r for r in rows_mas if r.get('cmplnt_num')}
print(f'  unique fel: {len(seen_fel):,}  unique mas: {len(seen_mas):,}')

print('loading NTAs')
ntas = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/nta.geojson'))
nta_geoms = [shape(f['geometry']) for f in ntas['features']]
nta_ids = [f['properties']['nta2020'] for f in ntas['features']]
tree = STRtree(nta_geoms)

def classify_slot(date_str, time_str):
    try:
        d = datetime.fromisoformat(date_str.split('T')[0])
        hh, mm = time_str.split(':')[:2]
        hh = int(hh); mm = int(mm)
    except Exception:
        return None, None
    is_weekend = d.weekday() >= 5
    day = 'wknd' if is_weekend else 'wkdy'
    if 8 <= hh < 10: return day, 'AM'
    if 12 <= hh < 14: return day, 'MD'
    if 17 <= hh < 19: return day, 'PM'
    return None, None

def aggregate(rows, label):
    counts = defaultdict(lambda: defaultdict(int))  # nta -> slot -> n
    counts_total = defaultdict(int)                 # 24/7 totals
    by_slot_city = defaultdict(int)
    n_matched = 0; n_unmatched = 0; n_no_geom = 0; n_no_slot = 0
    for r in rows:
        try:
            lon = float(r['longitude']); lat = float(r['latitude'])
        except (TypeError, ValueError):
            n_no_geom += 1; continue
        if not (40.4 < lat < 41.0 and -74.4 < lon < -73.6):
            n_no_geom += 1; continue
        p = Point(lon, lat)
        matched = None
        for i in tree.query(p):
            if nta_geoms[i].contains(p):
                matched = nta_ids[i]; break
        if matched is None:
            n_unmatched += 1; continue
        n_matched += 1
        counts_total[matched] += 1
        day, slot = classify_slot(r.get('cmplnt_fr_dt') or '', r.get('cmplnt_fr_tm') or '')
        if day and slot:
            k = f'{day}{slot}'
            counts[matched][k] += 1
            by_slot_city[k] += 1
        else:
            n_no_slot += 1
    print(f'  {label}: matched={n_matched:,} unmatched={n_unmatched:,} no_slot={n_no_slot:,} no_geom={n_no_geom:,}')
    print(f'  {label} citywide by slot:', dict(by_slot_city))
    return counts, counts_total

print('\naggregating felonies'); fel_counts, fel_total = aggregate(seen_fel.values(), 'fel')
print('\naggregating misd. assault'); mas_counts, mas_total = aggregate(seen_mas.values(), 'mas')

ALL_NTAS = set(nta_ids)
out = {}
for nta in ALL_NTAS:
    row = {}
    for cat, c, t in [('fel', fel_counts, fel_total), ('mas', mas_counts, mas_total)]:
        row[cat] = {'total_outdoor': t.get(nta, 0)}
        for k in ('wkdyAM','wkdyMD','wkdyPM','wkndAM','wkndMD','wkndPM'):
            row[cat][k] = c.get(nta, {}).get(k, 0)
    # combined
    row['comb'] = {'total_outdoor': row['fel']['total_outdoor'] + row['mas']['total_outdoor']}
    for k in ('wkdyAM','wkdyMD','wkdyPM','wkndAM','wkndMD','wkndPM'):
        row['comb'][k] = row['fel'][k] + row['mas'][k]
    out[nta] = row

with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/crimes_by_nta.json','w') as f:
    json.dump({'years':'2022-2024',
               'definitions': {
                   'fel': "All felonies (LAW_CAT_CD = FELONY), outdoor premises only",
                   'mas': "Misdemeanor assault (ASSAULT 3 & RELATED OFFENSES), outdoor premises only",
                   'comb': "Sum of fel + mas",
               },
               'data': out}, f)
print('wrote crimes_by_nta.json')
