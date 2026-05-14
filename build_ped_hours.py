"""Extract pedestrian-volume estimates from pedflows.pmtiles, aggregate to NTAs.

Output: ped_hours_by_nta.json — {nta2020: {wkdyAM, wkdyMD, wkdyPM, wkndAM, wkndMD, wkndPM}}
Values are pedestrians-per-hour summed across all segment midpoints within the NTA.
The per-hour value is the headline number; we convert to ped-hours-per-year when computing rates.
"""
import json, gzip, math, sys
from collections import defaultdict
from pmtiles.reader import Reader, MmapSource
import mapbox_vector_tile
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

PMTILES = '/Users/joshgreenman/Experiments/nyc-data/pedestrian-flows-nyc/pedflows.pmtiles'
NTA_GEOJSON = '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/nta.geojson'
OUT = '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/ped_hours_by_nta.json'

Z = 15

def tile_to_lonlat(x, y, z):
    n = 1 << z
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    return lon, math.degrees(lat_rad)

def lonlat_to_tile(lon, lat, z):
    x = int((lon + 180) / 360 * (1<<z))
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1/math.cos(math.radians(lat))) / math.pi) / 2 * (1<<z))
    return x, y

print('loading NTAs')
ntas = json.load(open(NTA_GEOJSON))
nta_geoms = []
nta_ids = []
for f in ntas['features']:
    g = shape(f['geometry'])
    nta_geoms.append(g)
    nta_ids.append(f['properties']['nta2020'])
tree = STRtree(nta_geoms)

print('opening pmtiles')
src = MmapSource(open(PMTILES, 'rb'))
r = Reader(src)

# NYC bbox
x0, y0 = lonlat_to_tile(-74.27, 40.91, Z)
x1, y1 = lonlat_to_tile(-73.69, 40.49, Z)
print(f'tile grid {x1-x0+1} x {y1-y0+1}')

KEYS = ['am','md','pm','wam','wmd','wpm']
totals = defaultdict(lambda: defaultdict(float))
n_feats = 0
n_unmatched = 0
n_tiles = 0
n_skipped_outside = 0

for tx in range(x0, x1+1):
    for ty in range(y0, y1+1):
        data = r.get(Z, tx, ty)
        if not data:
            continue
        n_tiles += 1
        raw = gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data
        try:
            t = mapbox_vector_tile.decode(raw)
        except Exception:
            continue
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
                else:
                    continue
                if not pts:
                    continue
                # Midpoint of fragment (in tile-pixel space)
                mid = pts[len(pts)//2]
                px, py = mid[0], mid[1]
                # tippecanoe clips at tile boundary, so fragments outside [0, extent] would not exist
                # but to dedupe segments split across tiles, only attribute fragments whose midpoint
                # is in the current tile (not in buffer).
                if px < 0 or px >= extent or py < 0 or py >= extent:
                    n_skipped_outside += 1
                    continue
                lon = lon0 + (px/extent) * (lon1 - lon0)
                lat = lat1 + (py/extent) * (lat0 - lat1)
                p = Point(lon, lat)
                idxs = tree.query(p)
                matched = None
                for i in idxs:
                    if nta_geoms[i].contains(p):
                        matched = nta_ids[i]
                        break
                if matched is None:
                    n_unmatched += 1
                    continue
                props = f['properties']
                for k in KEYS:
                    v = props.get(k)
                    if v is not None:
                        totals[matched][k] += float(v)
                n_feats += 1
    if (tx - x0) % 10 == 0:
        print(f'  col {tx-x0}/{x1-x0} feats={n_feats:,} tiles={n_tiles:,} unmatched={n_unmatched:,}')

print(f'done: features={n_feats:,} tiles={n_tiles:,} unmatched={n_unmatched:,} outside_tile={n_skipped_outside:,}')

# Sanity: sum across NTAs vs aggregates.json totals
agg = json.load(open('/Users/joshgreenman/Experiments/nyc-data/pedestrian-flows-nyc/aggregates.json'))
mapping = {'am':'predwkdyAM','md':'predwkdyMD','pm':'predwkdyPM',
           'wam':'predwkndAM','wmd':'predwkndMD','wpm':'predwkndPM'}
print('sanity check (ours vs source totals):')
for k, src_k in mapping.items():
    ours = sum(d[k] for d in totals.values())
    src_v = agg['totals'][src_k]
    print(f'  {k}: ours={ours:,.0f}  src={src_v:,.0f}  ratio={ours/src_v:.3f}')

# Write out
out = {nta: dict(d) for nta, d in totals.items()}
with open(OUT, 'w') as f:
    json.dump(out, f)
print(f'wrote {OUT}')
