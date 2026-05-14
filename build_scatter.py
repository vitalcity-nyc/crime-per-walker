"""Produce scatter data: for each NTA with population, compute
    - per-resident rate: outdoor felonies (all hours, 3 yr) per 1,000 residents per year
    - per-walker rate:   felonies per million walker-hours, weekday PM

Output: scatter_data.json — sorted list of points.
"""
import json
from operator import itemgetter

pop = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/population_by_nta.json'))
rates = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/rates_nta.json'))['data']

points = []
for nta, info in rates.items():
    P = pop.get(nta)
    if not P or P < 1000:  # skip empty / very small NTAs
        continue
    felonies_3yr_24_7 = info['t']['fel']
    if felonies_3yr_24_7 == 0:
        continue
    per_resident = felonies_3yr_24_7 / P / 3 * 1000   # felonies/1000 residents/year
    per_walker = info['r']['fel'][2]                  # wkdyPM (slot index 2) felonies/M walker-hr
    if per_walker is None or per_walker < 0:
        continue
    points.append({
        'nta': nta,
        'name': info['n'], 'boro': info['b'],
        'pop': P,
        'fel_3yr': felonies_3yr_24_7,
        'per_resident': round(per_resident, 2),
        'per_walker': round(per_walker, 3),
    })

# Rank each NTA on both axes (rank 1 = highest)
points.sort(key=lambda x: -x['per_resident'])
for i, p in enumerate(points):
    p['rank_resident'] = i + 1
points.sort(key=lambda x: -x['per_walker'])
for i, p in enumerate(points):
    p['rank_walker'] = i + 1

# Sort by absolute rank difference (most re-ranked NTAs first) for callouts
for p in points:
    p['rank_shift'] = p['rank_resident'] - p['rank_walker']

points.sort(key=lambda x: -abs(x['rank_shift']))
print('Top 10 NTAs by rank-shift magnitude (large positive = looks worse per resident than per walker):')
for p in points[:10]:
    print(f"  {p['name'][:35]:<37} {p['boro'][:3]} pop={p['pop']:>7,} resRank={p['rank_resident']:>3} walkerRank={p['rank_walker']:>3} shift={p['rank_shift']:+d}")
print(f'\ntotal points: {len(points)}')

with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/scatter_data.json','w') as f:
    json.dump({'note': 'per_resident = felonies/1000 residents/year (all hours, 3yr avg). per_walker = felonies/M walker-hr (weekday PM 5-7p). Felonies only. Population via CDC PLACES (2010 tract definitions, mapped to 2020 NTAs).',
               'points': points}, f, separators=(',',':'))
print('wrote scatter_data.json')
