"""Fetch 2020 census-tract populations from CDC PLACES (free, no key) and
aggregate to 2020 NTAs via the ct.geojson nta2020 field.

Output: population_by_nta.json — {nta2020: int}
"""
import json, urllib.request, urllib.parse
from collections import defaultdict

NYC_COUNTIES = ['005','047','061','081','085']  # Bronx, Brooklyn, Manhattan, Queens, Staten Island

print('fetching tract populations from CDC PLACES...')
tract_pop = {}
for cfips in NYC_COUNTIES:
    full_cfips = '36' + cfips
    qs = urllib.parse.urlencode({
        '$select': 'locationname,totalpopulation',
        '$where': f"countyfips='{full_cfips}'",
        '$limit': 5000,
    })
    url = f'https://data.cdc.gov/resource/cwsq-ngmh.json?{qs}'
    with urllib.request.urlopen(url) as r:
        rows = json.load(r)
    for row in rows:
        tract_pop[row['locationname']] = int(row['totalpopulation'])
    print(f'  county {cfips}: {len(rows):,} tracts')
print(f'total tracts: {len(tract_pop):,}')

# Aggregate to 2020 NTAs
ct = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/ct.geojson'))
nta_pop = defaultdict(int)
nta_name = {}
matched = 0; unmatched = 0
for f in ct['features']:
    geoid = f['properties']['geoid']
    nta = f['properties']['nta2020']
    nta_name[nta] = f['properties']['ntaname']
    p = tract_pop.get(geoid)
    if p is None:
        unmatched += 1
        continue
    matched += 1
    nta_pop[nta] += p

print(f'tract->NTA: matched={matched} unmatched={unmatched}')
print(f'NTAs with population: {len(nta_pop)}')
total = sum(nta_pop.values())
print(f'NYC total (sum): {total:,}')

# Sanity: NYC 2020 population was ~8.34M
out = {nta: pop for nta, pop in nta_pop.items()}
with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/population_by_nta.json','w') as f:
    json.dump(out, f)
print('wrote population_by_nta.json')

# Sample by boro
boro_totals = defaultdict(int)
for f in ct['features']:
    nta = f['properties']['nta2020']
    boro = f['properties']['boroname']
    boro_totals[boro] += tract_pop.get(f['properties']['geoid'], 0)
print('borough totals:', dict(boro_totals))
