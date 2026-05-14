"""Extract pedestrian-volume estimates from pedflows.pmtiles, aggregate to census tracts.

Output: ped_hours_by_ct.json — {boroct2020: {am, md, pm, wam, wmd, wpm}}
"""
import json, gzip, math
from collections import defaultdict
from pmtiles.reader import Reader, MmapSource
import mapbox_vector_tile
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

PMTILES = '/Users/joshgreenman/Experiments/nyc-data/pedestrian-flows-nyc/pedflows.pmtiles'
CT_GEOJSON = '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/ct.geojson'
OUT = '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/ped_hours_by_ct.json'
Z = 15

def tile_to_lonlat(x, y, z):
    n = 1 << z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat

def lonlat_to_tile(lon, lat, z):
    x = int((lon + 180) / 360 * (1<<z))
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1/math.cos(math.radians(lat))) / math.pi) / 2 * (1<<z))
    return x, y

print('loading CTs')
cts = json.load(open(CT_GEOJSON))
ct_geoms = []; ct_ids = []
for f in cts['features']:
    g = shape(f['geometry'])
    ct_geoms.append(g)
    ct_ids.append(f['properties']['boroct2020'])
tree = STRtree(ct_geoms)
print(f'  {len(ct_ids)} tracts')

src = MmapSource(open(PMTILES,'rb'))
r = Reader(src)
x0,y0 = lonlat_to_tile(-74.27, 40.91, Z)
x1,y1 = lonlat_to_tile(-73.69, 40.49, Z)

KEYS = ['am','md','pm','wam','wmd','wpm']
totals = defaultdict(lambda: defaultdict(float))
n_feats = 0; n_skipped = 0; n_unmatched = 0

for tx in range(x0, x1+1):
    for ty in range(y0, y1+1):
        data = r.get(Z, tx, ty)
        if not data: continue
        raw = gzip.decompress(data) if data[:2]==b'\x1f\x8b' else data
        try: t = mapbox_vector_tile.decode(raw)
        except Exception: continue
        for layer_name, layer in t.items():
            extent = layer['extent']
            lon0, lat1 = tile_to_lonlat(tx, ty, Z)
            lon1, lat0 = tile_to_lonlat(tx+1, ty+1, Z)
            for f in layer['features']:
                geom = f['geometry']
                coords = geom['coordinates']
                if geom['type'] == 'LineString':
                    pts = coords
                elif geom['type'] == 'MultiLineString':
                    pts = [pt for ls in coords for pt in ls]
                else: continue
                if not pts: continue
                mid = pts[len(pts)//2]
                px, py = mid[0], mid[1]
                if px<0 or px>=extent or py<0 or py>=extent:
                    n_skipped += 1; continue
                lon = lon0 + (px/extent)*(lon1-lon0)
                lat = lat1 + (py/extent)*(lat0-lat1)
                p = Point(lon, lat)
                matched = None
                for i in tree.query(p):
                    if ct_geoms[i].contains(p):
                        matched = ct_ids[i]; break
                if matched is None:
                    n_unmatched += 1; continue
                props = f['properties']
                for k in KEYS:
                    v = props.get(k)
                    if v is not None:
                        totals[matched][k] += float(v)
                n_feats += 1
    if (tx-x0) % 10 == 0:
        print(f'  col {tx-x0}/{x1-x0} feats={n_feats:,}')

print(f'done: feats={n_feats:,} unmatched={n_unmatched:,} outside_tile={n_skipped:,}')

# Sanity vs source totals
agg = json.load(open('/Users/joshgreenman/Experiments/nyc-data/pedestrian-flows-nyc/aggregates.json'))
mapping = {'am':'predwkdyAM','md':'predwkdyMD','pm':'predwkdyPM',
           'wam':'predwkndAM','wmd':'predwkndMD','wpm':'predwkndPM'}
print('calibration:')
for k, src_k in mapping.items():
    ours = sum(d[k] for d in totals.values())
    print(f'  {k}: ours={ours:,.0f}  src={agg["totals"][src_k]:,.0f}  ratio={ours/agg["totals"][src_k]:.3f}')

out = {ct: dict(d) for ct, d in totals.items()}
json.dump(out, open(OUT,'w'))
print(f'wrote {OUT}')
