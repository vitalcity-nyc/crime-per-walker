"""Pull outdoor crime complaints from NYPD, partition into categories, aggregate to NTA AND CT.

Outdoor-walking premises: STREET, PARK/PLAYGROUND, HIGHWAY/PARKWAY, BUS STOP, BRIDGE.

Time slots:
  AM = 8:00–9:59   (rate available)
  MD = 12:00–13:59 (rate available)
  PM = 17:00–18:59 (rate available)
  EV = 19:00–22:59 (raw count only — no walker model)
  LN = 23:00–01:59 (raw count only — no walker model)

Categories: fel, rob, asf, gla, mas, pla, vio, comb.
"""
import json, urllib.request, urllib.parse, sys, time
from datetime import datetime
from collections import defaultdict
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

ENDPOINT = 'https://data.cityofnewyork.us/resource/qgea-i56i.json'
PREM_TYPES = ['STREET','PARK/PLAYGROUND','HIGHWAY/PARKWAY','BUS STOP','BRIDGE']
START = '2022-01-01'; END = '2024-12-31'; PAGE = 50000

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

prem_in = ','.join(f"'{p}'" for p in PREM_TYPES)
base = (f"prem_typ_desc in({prem_in}) "
        f"AND rpt_dt>='{START}T00:00:00' AND rpt_dt<='{END}T23:59:59' "
        f"AND latitude IS NOT NULL AND longitude IS NOT NULL")
select = 'cmplnt_num,cmplnt_fr_dt,cmplnt_fr_tm,latitude,longitude,prem_typ_desc,ofns_desc,law_cat_cd,rpt_dt'

print('fetching outdoor felonies...'); rows_fel = fetch("law_cat_cd='FELONY' AND " + base, select)
print(f'  {len(rows_fel):,}')
print('fetching outdoor misd assault 3...'); rows_mas = fetch("law_cat_cd='MISDEMEANOR' AND ofns_desc='ASSAULT 3 & RELATED OFFENSES' AND " + base, select)
print(f'  {len(rows_mas):,}')
print('fetching outdoor misd petit larceny...'); rows_pla = fetch("law_cat_cd='MISDEMEANOR' AND ofns_desc='PETIT LARCENY' AND " + base, select)
print(f'  {len(rows_pla):,}')

all_rows = {}
for r in rows_fel + rows_mas + rows_pla:
    cn = r.get('cmplnt_num')
    if cn and cn not in all_rows:
        all_rows[cn] = r
print(f'unique: {len(all_rows):,}')

print('loading polygons')
ntas = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/nta.geojson'))
nta_geoms = [shape(f['geometry']) for f in ntas['features']]
nta_ids = [f['properties']['nta2020'] for f in ntas['features']]
nta_tree = STRtree(nta_geoms)

cts = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/ct.geojson'))
ct_geoms = [shape(f['geometry']) for f in cts['features']]
ct_ids = [f['properties']['boroct2020'] for f in cts['features']]
ct_tree = STRtree(ct_geoms)
print(f'  NTAs={len(nta_ids)} CTs={len(ct_ids)}')

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

def categories_for(r):
    law = r.get('law_cat_cd'); ofns = r.get('ofns_desc')
    cats = []
    if law == 'FELONY':
        cats.append('fel')
        if ofns == 'ROBBERY': cats.append('rob')
        if ofns == 'FELONY ASSAULT': cats.append('asf')
        if ofns == 'GRAND LARCENY': cats.append('gla')
        if ofns in ('FELONY ASSAULT','ROBBERY'): cats.append('vio')
        cats.append('comb')
    elif law == 'MISDEMEANOR':
        if ofns == 'ASSAULT 3 & RELATED OFFENSES':
            cats += ['mas','vio','comb']
        elif ofns == 'PETIT LARCENY':
            cats += ['pla','comb']
    return cats

CATS = ['fel','mas','rob','asf','gla','pla','vio','comb']
SLOTS = ['wkdyAM','wkdyMD','wkdyPM','wkdyEV','wkdyLN',
         'wkndAM','wkndMD','wkndPM','wkndEV','wkndLN']

def empty_agg():
    return {c: {'total_outdoor': 0, **{s: 0 for s in SLOTS}} for c in CATS}

def make_aggregator(geoms, ids, tree):
    counts = {c: defaultdict(lambda: defaultdict(int)) for c in CATS}
    totals = {c: defaultdict(int) for c in CATS}
    matched_n = 0; unmatched_n = 0; no_geom = 0
    def add(r):
        nonlocal matched_n, unmatched_n, no_geom
        try:
            lon = float(r['longitude']); lat = float(r['latitude'])
        except (TypeError, ValueError):
            no_geom += 1; return
        if not (40.4 < lat < 41.0 and -74.4 < lon < -73.6):
            no_geom += 1; return
        p = Point(lon, lat); matched = None
        for i in tree.query(p):
            if geoms[i].contains(p): matched = ids[i]; break
        if matched is None: unmatched_n += 1; return
        matched_n += 1
        cats = categories_for(r)
        day, slot = classify_slot(r.get('cmplnt_fr_dt') or '', r.get('cmplnt_fr_tm') or '')
        k = f'{day}{slot}' if (day and slot) else None
        for c in cats:
            totals[c][matched] += 1
            if k: counts[c][matched][k] += 1
    def finalize():
        out = {}
        for uid in ids:
            row = {}
            for c in CATS:
                row[c] = {'total_outdoor': totals[c].get(uid, 0)}
                for s in SLOTS:
                    row[c][s] = counts[c].get(uid, {}).get(s, 0)
            out[uid] = row
        return out, dict(matched=matched_n, unmatched=unmatched_n, no_geom=no_geom)
    return add, finalize

nta_add, nta_done = make_aggregator(nta_geoms, nta_ids, nta_tree)
ct_add, ct_done = make_aggregator(ct_geoms, ct_ids, ct_tree)
for r in all_rows.values():
    nta_add(r); ct_add(r)
nta_data, nta_stats = nta_done()
ct_data, ct_stats = ct_done()
print(f'NTA: {nta_stats}')
print(f'CT:  {ct_stats}')

# Citywide
def city_totals(data):
    out = {c: {'total_outdoor':0, **{s:0 for s in SLOTS}} for c in CATS}
    for uid, row in data.items():
        for c in CATS:
            out[c]['total_outdoor'] += row[c]['total_outdoor']
            for s in SLOTS: out[c][s] += row[c][s]
    return out

print('Citywide totals (NTA-aggregated):')
ct_t = city_totals(nta_data)
for c in CATS:
    print(f'  {c}: total={ct_t[c]["total_outdoor"]:>6,} | EV={ct_t[c]["wkdyEV"]+ct_t[c]["wkndEV"]:>5,} LN={ct_t[c]["wkdyLN"]+ct_t[c]["wkndLN"]:>5,}')

with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/crimes_by_nta.json','w') as f:
    json.dump({'years':'2022-2024','data': nta_data}, f)
with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/crimes_by_ct.json','w') as f:
    json.dump({'years':'2022-2024','data': ct_data}, f)
print('wrote crimes_by_nta.json and crimes_by_ct.json')
