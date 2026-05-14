"""Pull pedestrian-involved motor-vehicle crashes from NYPD Open Data and
aggregate counts of pedestrians injured / killed to NTAs + 2020 census tracts
per the same 10 time slots as the crime data.

Categories produced:
  pinj — pedestrians injured (count of victims, not crashes)
  pkll — pedestrians killed
  pall — pinj + pkll (all pedestrian victims; Vision Zero "KSI"-like)
"""
import json, urllib.request, urllib.parse, sys, time
from datetime import datetime
from collections import defaultdict
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

ENDPOINT = 'https://data.cityofnewyork.us/resource/h9gi-nx95.json'
START = '2022-01-01'; END = '2024-12-31'
PAGE = 50000

def fetch(where, select):
    out = []; offset = 0
    while True:
        qs = urllib.parse.urlencode({'$select':select,'$where':where,'$limit':PAGE,'$offset':offset})
        sys.stderr.write(f'  offset={offset:,}\n')
        with urllib.request.urlopen(f'{ENDPOINT}?{qs}') as r:
            chunk = json.load(r)
        out.extend(chunk)
        if len(chunk) < PAGE: break
        offset += PAGE; time.sleep(0.2)
    return out

where = (f"crash_date>='{START}T00:00:00' AND crash_date<='{END}T23:59:59' "
         f"AND (number_of_pedestrians_injured>0 OR number_of_pedestrians_killed>0) "
         f"AND latitude IS NOT NULL AND longitude IS NOT NULL "
         f"AND latitude>40.4 AND latitude<41.0")
select = 'collision_id,crash_date,crash_time,latitude,longitude,number_of_pedestrians_injured,number_of_pedestrians_killed'

print('fetching pedestrian-involved crashes 2022-2024...')
rows = fetch(where, select)
print(f'  {len(rows):,} rows')

# Load polygons
ntas = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/nta.geojson'))
nta_geoms = [shape(f['geometry']) for f in ntas['features']]
nta_ids = [f['properties']['nta2020'] for f in ntas['features']]
nta_tree = STRtree(nta_geoms)

cts = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/ct.geojson'))
ct_geoms = [shape(f['geometry']) for f in cts['features']]
ct_ids = [f['properties']['boroct2020'] for f in cts['features']]
ct_tree = STRtree(ct_geoms)

def classify_slot(date_str, time_str):
    try:
        d = datetime.fromisoformat(date_str.split('T')[0])
        hh = int(time_str.split(':')[0])
    except Exception:
        return None, None
    day = 'wknd' if d.weekday() >= 5 else 'wkdy'
    if 8 <= hh < 10: return day, 'AM'
    if 12 <= hh < 14: return day, 'MD'
    if 17 <= hh < 19: return day, 'PM'
    if 19 <= hh < 23: return day, 'EV'
    if hh >= 23 or hh < 2: return day, 'LN'
    return None, None

CATS = ['pinj','pkll','pall']
SLOTS = ['wkdyAM','wkdyMD','wkdyPM','wkdyEV','wkdyLN',
         'wkndAM','wkndMD','wkndPM','wkndEV','wkndLN']

def make_agg(geoms, ids, tree):
    counts = {c: defaultdict(lambda: defaultdict(int)) for c in CATS}
    totals = {c: defaultdict(int) for c in CATS}
    matched = 0; unmatched = 0; no_geom = 0
    def add(r):
        nonlocal matched, unmatched, no_geom
        try:
            lon = float(r['longitude']); lat = float(r['latitude'])
        except (TypeError, ValueError):
            no_geom += 1; return
        if not (40.4 < lat < 41.0 and -74.4 < lon < -73.6):
            no_geom += 1; return
        p = Point(lon, lat); match = None
        for i in tree.query(p):
            if geoms[i].contains(p): match = ids[i]; break
        if match is None: unmatched += 1; return
        matched += 1
        inj = int(r.get('number_of_pedestrians_injured') or 0)
        kll = int(r.get('number_of_pedestrians_killed') or 0)
        day, slot = classify_slot(r.get('crash_date') or '', r.get('crash_time') or '')
        k = f'{day}{slot}' if (day and slot) else None
        if inj > 0:
            totals['pinj'][match] += inj
            if k: counts['pinj'][match][k] += inj
        if kll > 0:
            totals['pkll'][match] += kll
            if k: counts['pkll'][match][k] += kll
        if inj + kll > 0:
            totals['pall'][match] += (inj + kll)
            if k: counts['pall'][match][k] += (inj + kll)
    def finalize():
        out = {}
        for uid in ids:
            row = {}
            for c in CATS:
                row[c] = {'total_outdoor': totals[c].get(uid, 0)}
                for s in SLOTS:
                    row[c][s] = counts[c].get(uid, {}).get(s, 0)
            out[uid] = row
        return out, dict(matched=matched, unmatched=unmatched, no_geom=no_geom)
    return add, finalize

nta_add, nta_done = make_agg(nta_geoms, nta_ids, nta_tree)
ct_add, ct_done = make_agg(ct_geoms, ct_ids, ct_tree)
for r in rows:
    nta_add(r); ct_add(r)
nta_data, nta_stats = nta_done()
ct_data, ct_stats = ct_done()
print(f'NTA: {nta_stats}')
print(f'CT:  {ct_stats}')

def sum_city(data):
    return {c: sum(data[u][c]['total_outdoor'] for u in data) for c in CATS}
print('citywide totals NTA:', sum_city(nta_data))

with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/crashes_by_nta.json','w') as f:
    json.dump({'years':'2022-2024','data': nta_data}, f)
with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/crashes_by_ct.json','w') as f:
    json.dump({'years':'2022-2024','data': ct_data}, f)
print('wrote crashes_by_nta.json and crashes_by_ct.json')
