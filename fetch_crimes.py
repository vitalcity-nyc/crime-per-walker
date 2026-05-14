"""Pull outdoor crime complaints from NYPD Open Data, partition into categories, snap to NTAs.

Outdoor-walking premises: STREET, PARK/PLAYGROUND, HIGHWAY/PARKWAY, BUS STOP, BRIDGE.

We pull:
  - All outdoor felonies (LAW_CAT_CD = FELONY)
  - Selected outdoor misdemeanors (ASSAULT 3, PETIT LARCENY)

Then we categorize each record into one or more of:
  - fel        — all felonies
  - rob        — robbery (felony)
  - asf        — felony assault
  - gla        — grand larceny (felony; excludes motor vehicle)
  - mas        — misdemeanor assault (ASSAULT 3 & RELATED OFFENSES)
  - pla        — petit larceny (misdemeanor)
  - vio        — violent: felony assault + robbery + misdemeanor assault
  - comb       — felonies + misd. assault + petit larceny
"""
import json, urllib.request, urllib.parse, sys, time
from datetime import datetime
from collections import defaultdict
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

ENDPOINT = 'https://data.cityofnewyork.us/resource/qgea-i56i.json'
PREM_TYPES = ['STREET','PARK/PLAYGROUND','HIGHWAY/PARKWAY','BUS STOP','BRIDGE']
START = '2022-01-01'
END = '2024-12-31'
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

prem_in = ','.join(f"'{p}'" for p in PREM_TYPES)
base = (f"prem_typ_desc in({prem_in}) "
        f"AND rpt_dt>='{START}T00:00:00' AND rpt_dt<='{END}T23:59:59' "
        f"AND latitude IS NOT NULL AND longitude IS NOT NULL")
select = 'cmplnt_num,cmplnt_fr_dt,cmplnt_fr_tm,latitude,longitude,prem_typ_desc,ofns_desc,law_cat_cd,rpt_dt'

print('fetching all outdoor felonies...')
rows_fel = fetch("law_cat_cd='FELONY' AND " + base, select)
print(f'  felonies: {len(rows_fel):,}')

print("fetching outdoor misd assault 3...")
rows_mas = fetch("law_cat_cd='MISDEMEANOR' AND ofns_desc='ASSAULT 3 & RELATED OFFENSES' AND " + base, select)
print(f'  misd assault: {len(rows_mas):,}')

print("fetching outdoor misd petit larceny...")
rows_pla = fetch("law_cat_cd='MISDEMEANOR' AND ofns_desc='PETIT LARCENY' AND " + base, select)
print(f'  petit larceny: {len(rows_pla):,}')

all_rows = {}
for r in rows_fel + rows_mas + rows_pla:
    cn = r.get('cmplnt_num')
    if cn and cn not in all_rows:
        all_rows[cn] = r
print(f'  total unique: {len(all_rows):,}')

# Load NTAs
print('loading NTAs')
ntas = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/nta.geojson'))
nta_geoms = [shape(f['geometry']) for f in ntas['features']]
nta_ids = [f['properties']['nta2020'] for f in ntas['features']]
tree = STRtree(nta_geoms)

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
    return None, None

def categories_for(r):
    """Return the list of category keys this record belongs to."""
    law = r.get('law_cat_cd'); ofns = r.get('ofns_desc')
    cats = []
    if law == 'FELONY':
        cats.append('fel')
        if ofns == 'ROBBERY': cats.append('rob')
        if ofns == 'FELONY ASSAULT': cats.append('asf')
        if ofns == 'GRAND LARCENY': cats.append('gla')
        # Violent felony components
        if ofns in ('FELONY ASSAULT', 'ROBBERY'): cats.append('vio')
        # Combined includes all felonies
        cats.append('comb')
    elif law == 'MISDEMEANOR':
        if ofns == 'ASSAULT 3 & RELATED OFFENSES':
            cats += ['mas', 'vio', 'comb']
        elif ofns == 'PETIT LARCENY':
            cats += ['pla', 'comb']
    return cats

# Aggregate
CATS = ['fel','mas','rob','asf','gla','pla','vio','comb']
counts = {c: defaultdict(lambda: defaultdict(int)) for c in CATS}
totals = {c: defaultdict(int) for c in CATS}
by_slot_city = {c: defaultdict(int) for c in CATS}
n_matched = 0; n_unmatched = 0; n_no_geom = 0

for r in all_rows.values():
    try:
        lon = float(r['longitude']); lat = float(r['latitude'])
    except (TypeError, ValueError):
        n_no_geom += 1; continue
    if not (40.4 < lat < 41.0 and -74.4 < lon < -73.6):
        n_no_geom += 1; continue
    p = Point(lon, lat); matched = None
    for i in tree.query(p):
        if nta_geoms[i].contains(p): matched = nta_ids[i]; break
    if matched is None:
        n_unmatched += 1; continue
    n_matched += 1
    cats = categories_for(r)
    day, slot = classify_slot(r.get('cmplnt_fr_dt') or '', r.get('cmplnt_fr_tm') or '')
    k = f'{day}{slot}' if (day and slot) else None
    for c in cats:
        totals[c][matched] += 1
        if k:
            counts[c][matched][k] += 1
            by_slot_city[c][k] += 1

print(f'matched={n_matched:,} unmatched={n_unmatched:,} no_geom={n_no_geom:,}')
print('\nCitywide outdoor counts (3 yr, 24/7):')
for c in CATS:
    print(f'  {c}: {sum(totals[c].values()):>7,}')

out = {}
for nta in nta_ids:
    row = {}
    for c in CATS:
        row[c] = {'total_outdoor': totals[c].get(nta, 0)}
        for k in ('wkdyAM','wkdyMD','wkdyPM','wkndAM','wkndMD','wkndPM'):
            row[c][k] = counts[c].get(nta, {}).get(k, 0)
    out[nta] = row

with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/crimes_by_nta.json','w') as f:
    json.dump({'years':'2022-2024',
               'definitions': {
                   'fel': "All felonies (LAW_CAT_CD=FELONY), outdoor",
                   'rob': "Robbery (felony, OFNS_DESC='ROBBERY'), outdoor",
                   'asf': "Felony assault (OFNS_DESC='FELONY ASSAULT'), outdoor",
                   'gla': "Grand larceny (felony, excludes motor vehicle), outdoor",
                   'mas': "Misdemeanor assault (ASSAULT 3 & RELATED OFFENSES), outdoor",
                   'pla': "Petit larceny (misdemeanor), outdoor",
                   'vio': "Violent: felony assault + robbery + misd. assault",
                   'comb': "All outdoor felonies + misd. assault + petit larceny",
               },
               'citywide_totals': {c: sum(totals[c].values()) for c in CATS},
               'data': out}, f)
print('\nwrote crimes_by_nta.json')
