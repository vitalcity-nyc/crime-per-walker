"""Aggregate MIT pedestrian-flow Origin-Destination (trip purpose) fields from the
full GeoJSON to NTAs and 2020 census tracts.

Each segment has 9 OD trip-flow fields (likely daily-average flows by purpose):
  HME_SCH, HME_MTA, HME_PRK, HME_JOB, HME_AMN,
  JOB_MTA, JOB_AMN, AMN_AMN, AMN_MTA, PRK_MTA

We sum these per-NTA and per-CT (by snapping segment midpoint to the polygon
containing it). Output: walk_purpose_by_nta.json, walk_purpose_by_ct.json,
each {uid: {field: total, ..., 'total': sum_of_all}}.
"""
import ijson, json
from pyproj import Transformer
from shapely.geometry import shape, Point
from shapely.strtree import STRtree
from collections import defaultdict

SRC = '/tmp/pednetwork.geojson'
OD_FIELDS = ['HME_SCH','HME_MTA','HME_PRK','HME_JOB','HME_AMN',
             'JOB_MTA','JOB_AMN','AMN_AMN','AMN_MTA','PRK_MTA']

# EPSG 6538 (NAD83 NY-Long Island) -> WGS84
tx = Transformer.from_crs(6538, 4326, always_xy=True)

print('loading NTAs + CTs')
ntas = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/nta.geojson'))
nta_geoms = [shape(f['geometry']) for f in ntas['features']]
nta_ids = [f['properties']['nta2020'] for f in ntas['features']]
nta_tree = STRtree(nta_geoms)

cts = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/ct.geojson'))
ct_geoms = [shape(f['geometry']) for f in cts['features']]
ct_ids = [f['properties']['boroct2020'] for f in cts['features']]
ct_tree = STRtree(ct_geoms)

nta_totals = defaultdict(lambda: {k:0.0 for k in OD_FIELDS})
ct_totals  = defaultdict(lambda: {k:0.0 for k in OD_FIELDS})
n_segs = 0; n_nta_miss = 0; n_ct_miss = 0

with open(SRC, 'rb') as fh:
    for feat in ijson.items(fh, 'features.item'):
        n_segs += 1
        p = feat.get('properties', {})
        # Midpoint of segment in EPSG:6538
        geom = feat.get('geometry') or {}
        coords = geom.get('coordinates') or []
        if geom.get('type') == 'LineString':
            pts = coords
        elif geom.get('type') == 'MultiLineString':
            pts = [pt for ls in coords for pt in ls]
        else:
            continue
        if not pts: continue
        mid = pts[len(pts)//2]
        try:
            lon, lat = tx.transform(mid[0], mid[1])
        except Exception:
            continue
        pt = Point(lon, lat)
        # Snap to NTA
        nta_match = None
        for i in nta_tree.query(pt):
            if nta_geoms[i].contains(pt):
                nta_match = nta_ids[i]; break
        if nta_match is None: n_nta_miss += 1
        # Snap to CT
        ct_match = None
        for i in ct_tree.query(pt):
            if ct_geoms[i].contains(pt):
                ct_match = ct_ids[i]; break
        if ct_match is None: n_ct_miss += 1
        # Accumulate OD totals
        for k in OD_FIELDS:
            v = p.get(k)
            if v is None: continue
            try: v = float(v)
            except: continue
            if nta_match: nta_totals[nta_match][k] += v
            if ct_match:  ct_totals[ct_match][k]   += v
        if n_segs % 50000 == 0:
            print(f'  {n_segs:,} segments processed')

print(f'done: {n_segs:,} segments  nta_miss={n_nta_miss:,} ct_miss={n_ct_miss:,}')

def finalize(totals):
    out = {}
    for uid, d in totals.items():
        row = {k: round(v, 1) for k, v in d.items()}
        row['total'] = round(sum(d.values()), 1)
        out[uid] = row
    return out

nta_out = finalize(nta_totals)
ct_out = finalize(ct_totals)

with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/walk_purpose_by_nta.json','w') as f:
    json.dump({'fields': OD_FIELDS, 'data': nta_out}, f, separators=(',',':'))
with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/walk_purpose_by_ct.json','w') as f:
    json.dump({'fields': OD_FIELDS, 'data': ct_out}, f, separators=(',',':'))

# Citywide totals — sanity check vs aggregates.json
agg = json.load(open('/Users/joshgreenman/Experiments/nyc-data/pedestrian-flows-nyc/aggregates.json'))
print('\nCalibration check vs aggregates.json (NTA sums):')
for k in OD_FIELDS:
    ours = sum(d[k] for d in nta_totals.values())
    src = agg['totals'].get(k, None)
    if src is None:
        print(f'  {k}: ours={ours:,.0f}  (not in aggregates)')
    else:
        print(f'  {k}: ours={ours:,.0f}  src={src:,.0f}  ratio={ours/src:.3f}')

print('wrote walk_purpose_by_{nta,ct}.json')
