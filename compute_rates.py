"""Compute incidents per million pedestrian-hours per NTA per slot, for each crime category."""
import json
from collections import defaultdict
from datetime import date, timedelta
import statistics

START = date(2022, 1, 1); END = date(2024, 12, 31)
wkdy = wknd = 0
d = START
while d <= END:
    if d.weekday() >= 5: wknd += 1
    else: wkdy += 1
    d += timedelta(days=1)
print(f'wkdy days={wkdy}  wknd days={wknd}')

SLOT_HOURS = {
    'wkdyAM': 2*wkdy, 'wkdyMD': 2*wkdy, 'wkdyPM': 2*wkdy,
    'wkndAM': 2*wknd, 'wkndMD': 2*wknd, 'wkndPM': 2*wknd,
}
PROP_MAP = {'wkdyAM':'am','wkdyMD':'md','wkdyPM':'pm',
            'wkndAM':'wam','wkndMD':'wmd','wkndPM':'wpm'}
CATS = ['fel','mas','rob','asf','gla','pla','vio','comb']

ped = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/ped_hours_by_nta.json'))
crimes = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/crimes_by_nta.json'))['data']
nta_geo = json.load(open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/nta.geojson'))

out = {}
for f in nta_geo['features']:
    nta = f['properties']['nta2020']
    row = {'name': f['properties']['ntaname'], 'boro': f['properties']['boroname']}
    fped = ped.get(nta, {})
    fcrime = crimes.get(nta, {})
    for slot, hrs in SLOT_HOURS.items():
        peds = fped.get(PROP_MAP[slot], 0.0)
        ped_hours = peds * hrs
        row[slot] = {'peds_per_hr': round(peds, 1), 'ped_hours_3yr': round(ped_hours)}
        for cat in CATS:
            n = fcrime.get(cat, {}).get(slot, 0)
            rate = (n / ped_hours * 1_000_000) if ped_hours > 0 else None
            row[slot][cat] = n
            row[slot][f'{cat}_rate'] = round(rate, 2) if rate is not None else None
    # 24/7 totals
    row['totals'] = {cat: fcrime.get(cat, {}).get('total_outdoor', 0) for cat in CATS}
    out[nta] = row

# Distribution + leaderboard for each category, wkdy PM
print()
for cat in CATS:
    items = [(nta, r) for nta, r in out.items()
             if r['wkdyPM'][f'{cat}_rate'] is not None and r['wkdyPM']['peds_per_hr'] > 30000]
    items.sort(key=lambda x: -x[1]['wkdyPM'][f'{cat}_rate'])
    print(f'\n=== {cat} — top 5 weekday PM (rate per million walker-hr) ===')
    for nta, r in items[:5]:
        s = r['wkdyPM']
        print(f"  {r['name'][:38]:<40} {r['boro'][:3]} rate={s[f'{cat}_rate']:>5.2f}  n={s[cat]:>4}  peds/hr={s['peds_per_hr']:>7.0f}")

with open('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/rates_by_nta.json','w') as f:
    json.dump({'years':'2022-2024','slot_hours':SLOT_HOURS,
               'categories':{
                   'fel':'Outdoor felonies (all)',
                   'mas':'Outdoor misdemeanor assault',
                   'comb':'Outdoor felonies + misdemeanor assault',
               },
               'data': out}, f)
print('\nwrote rates_by_nta.json')
