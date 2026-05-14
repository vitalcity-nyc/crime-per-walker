"""Pull outdoor felony complaints from NYPD Open Data and snap to NTAs.

Outdoor-walking categories: STREET, PARK/PLAYGROUND, HIGHWAY/PARKWAY, BUS STOP, BRIDGE.
(Subway felonies and bus-interior crime excluded — the pedestrian-flow model only measures
above-ground sidewalk/crosswalk walking, so we want numerator and denominator to be the
same kind of place.)

Date range: 2022-01-01 through 2024-12-31 (3 full calendar years), bounded by RPT_DT.
Slot classification uses CMPLNT_FR_DT/CMPLNT_FR_TM (the only fields with time-of-day).
"""
import json, urllib.request, urllib.parse, sys, time
from datetime import datetime
from collections import defaultdict
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

ENDPOINT_HIST = 'https://data.cityofnewyork.us/resource/qgea-i56i.json'
ENDPOINT_CURR = 'https://data.cityofnewyork.us/resource/5uac-w243.json'

PREM_TYPES = ['STREET','PARK/PLAYGROUND','HIGHWAY/PARKWAY','BUS STOP','BRIDGE']
START = '2022-01-01'
END = '2024-12-31'

PAGE = 50000

def fetch(endpoint, where, select):
    out = []
    offset = 0
    while True:
        qs = urllib.parse.urlencode({
            '$select': select,
            '$where': where,
            '$limit': PAGE,
            '$offset': offset,
        })
        url = f'{endpoint}?{qs}'
        sys.stderr.write(f'  fetching offset={offset:,}\n')
        with urllib.request.urlopen(url) as r:
            chunk = json.load(r)
        out.extend(chunk)
        if len(chunk) < PAGE:
            break
        offset += PAGE
        time.sleep(0.2)
    return out

prem_in = ','.join(f"'{p}'" for p in PREM_TYPES)
where = (f"law_cat_cd='FELONY' AND prem_typ_desc in({prem_in}) "
         f"AND rpt_dt>='{START}T00:00:00' AND rpt_dt<='{END}T23:59:59' "
         f"AND latitude IS NOT NULL AND longitude IS NOT NULL")
select = 'cmplnt_num,cmplnt_fr_dt,cmplnt_fr_tm,latitude,longitude,prem_typ_desc,ofns_desc,rpt_dt'

print('fetching from historic endpoint...')
rows = fetch(ENDPOINT_HIST, where, select)
print(f'historic: {len(rows):,} rows')

# Some 2024 reports may live in the current-year dataset too; merge by cmplnt_num just in case
print('fetching from current-year endpoint...')
try:
    rows_curr = fetch(ENDPOINT_CURR, where, select)
    print(f'current: {len(rows_curr):,} rows')
except Exception as e:
    print(f'current-year fetch failed: {e}')
    rows_curr = []

seen = {r['cmplnt_num']: r for r in rows}
for r in rows_curr:
    seen.setdefault(r['cmplnt_num'], r)
rows = list(seen.values())
print(f'merged unique: {len(rows):,} rows')

# Load NTAs and build spatial index
print('loading NTAs')
ntas = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/nta.geojson'))
nta_geoms = [shape(f['geometry']) for f in ntas['features']]
nta_ids = [f['properties']['nta2020'] for f in ntas['features']]
tree = STRtree(nta_geoms)

def classify_slot(date_str, time_str):
    """Return (day_type, slot) or (None, None) if outside the 6 slots."""
    try:
        d = datetime.fromisoformat(date_str.split('T')[0])
        hh, mm = time_str.split(':')[:2]
        hh = int(hh); mm = int(mm)
    except Exception:
        return None, None
    is_weekend = d.weekday() >= 5  # 5=Sat, 6=Sun
    day = 'wknd' if is_weekend else 'wkdy'
    # 8:00 <= AM < 10:00; 12:00 <= MD < 14:00; 17:00 <= PM < 19:00
    if 8 <= hh < 10:
        return day, 'AM'
    if 12 <= hh < 14:
        return day, 'MD'
    if 17 <= hh < 19:
        return day, 'PM'
    return None, None

counts = defaultdict(lambda: defaultdict(int))   # nta -> {wkdyAM, wkdyMD, ...} (in-slot)
counts_total = defaultdict(int)                  # nta -> total outdoor felonies (24/7)
counts_total_by_slot = defaultdict(int)          # cityside totals by slot for sanity
n_matched = 0; n_unmatched = 0; n_no_slot = 0; n_no_geom = 0
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
        counts_total_by_slot[k] += 1
    else:
        n_no_slot += 1

print(f'matched={n_matched:,} unmatched={n_unmatched:,} no_slot={n_no_slot:,} no_geom={n_no_geom:,}')
print('citywide by slot:', dict(counts_total_by_slot))

out = {}
for nta in set(list(counts.keys()) + list(counts_total.keys())):
    out[nta] = {'total_outdoor': counts_total[nta]}
    for k in ('wkdyAM','wkdyMD','wkdyPM','wkndAM','wkndMD','wkndPM'):
        out[nta][k] = counts[nta].get(k, 0)

with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/felonies_by_nta.json', 'w') as f:
    json.dump({'years': '2022-2024', 'data': out}, f)
print('wrote felonies_by_nta.json')
