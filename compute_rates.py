"""Compute incidents per million pedestrian-hours per unit per slot, for each category.

Rates are only defined for slots with a published pedestrian-flow estimate (AM/MD/PM).
Evening (EV) and late-night (LN) slots have raw counts only.
"""
import json
from datetime import date, timedelta

START = date(2022,1,1); END = date(2024,12,31)
wkdy = wknd = 0; d = START
while d <= END:
    if d.weekday() >= 5: wknd += 1
    else: wkdy += 1
    d += timedelta(days=1)
print(f'wkdy days={wkdy} wknd days={wknd}')

# Slot duration (hours) and ped-window mapping.
# Only AM/MD/PM map to a published ped-volume estimate.
SLOT_HOURS = {
    'wkdyAM': 2*wkdy, 'wkdyMD': 2*wkdy, 'wkdyPM': 2*wkdy,
    'wkdyEV': 4*wkdy, 'wkdyLN': 3*wkdy,
    'wkndAM': 2*wknd, 'wkndMD': 2*wknd, 'wkndPM': 2*wknd,
    'wkndEV': 4*wknd, 'wkndLN': 3*wknd,
}
PROP_MAP = {'wkdyAM':'am','wkdyMD':'md','wkdyPM':'pm',
            'wkndAM':'wam','wkndMD':'wmd','wkndPM':'wpm'}
ALL_SLOTS = list(SLOT_HOURS.keys())
RATEABLE = set(PROP_MAP.keys())
CATS = ['fel','mas','rob','asf','gla','pla','vio','comb','pinj','pkll','pall']

def walk_dna(od_row):
    """Convert raw OD trip totals into 4 walk-purpose shares (%)."""
    if not od_row: return None
    total = (od_row.get('HME_SCH',0) + od_row.get('HME_MTA',0) + od_row.get('HME_PRK',0)
             + od_row.get('HME_JOB',0) + od_row.get('HME_AMN',0)
             + od_row.get('JOB_MTA',0) + od_row.get('JOB_AMN',0)
             + od_row.get('AMN_AMN',0) + od_row.get('AMN_MTA',0))
    if total <= 0: return None
    commuter = od_row.get('HME_JOB',0) + od_row.get('HME_MTA',0) + od_row.get('JOB_MTA',0)
    leisure  = od_row.get('HME_AMN',0) + od_row.get('AMN_AMN',0) + od_row.get('JOB_AMN',0) + od_row.get('AMN_MTA',0)
    school   = od_row.get('HME_SCH',0)
    park     = od_row.get('HME_PRK',0)
    return {
        'commuter': round(100*commuter/total, 1),
        'leisure':  round(100*leisure/total, 1),
        'school':   round(100*school/total, 1),
        'park':     round(100*park/total, 1),
        'total':    round(total, 0),
    }

def build(ped_path, crimes_path, geo_path, geo_id_key, out_path, label, walk_purpose_path=None, crashes_path=None):
    """Emit compact per-slot arrays for the web map."""
    ped = json.load(open(ped_path))
    crimes = json.load(open(crimes_path))['data']
    geo = json.load(open(geo_path))
    walk_purpose = {}
    if walk_purpose_path:
        walk_purpose = json.load(open(walk_purpose_path))['data']
    crashes = {}
    if crashes_path:
        crashes = json.load(open(crashes_path))['data']
    data = {}
    for f in geo['features']:
        uid = f['properties'][geo_id_key]
        name = f['properties'].get('ctlabel') or f['properties'].get('ntaname') or ''
        boro = f['properties'].get('boroname','')
        fped = ped.get(uid, {}); fcrime = crimes.get(uid, {}); fcrash = crashes.get(uid, {})
        def src_for(cat): return fcrash if cat in ('pinj','pkll','pall') else fcrime
        p_arr = []
        c_arr = {c: [] for c in CATS}
        r_arr = {c: [] for c in CATS}
        for slot in ALL_SLOTS:
            rateable = slot in RATEABLE
            peds = fped.get(PROP_MAP[slot], 0.0) if rateable else 0.0
            ped_hours = peds * SLOT_HOURS[slot] if rateable else 0
            p_arr.append(round(peds, 1) if rateable else None)
            for cat in CATS:
                n = src_for(cat).get(cat, {}).get(slot, 0)
                c_arr[cat].append(n)
                if rateable and ped_hours > 0:
                    r_arr[cat].append(round(n / ped_hours * 1_000_000, 2))
                else:
                    r_arr[cat].append(None)
        totals = {cat: src_for(cat).get(cat, {}).get('total_outdoor', 0) for cat in CATS}
        dna = walk_dna(walk_purpose.get(uid))
        data[uid] = {'n':name,'b':boro,'p':p_arr,'c':c_arr,'r':r_arr,'t':totals,'d':dna}
    out = {'years':'2022-2024','slots':ALL_SLOTS,'cats':CATS,
           'rateable_slots':sorted(RATEABLE),'slot_hours':SLOT_HOURS,'data':data}
    with open(out_path, 'w') as f:
        json.dump(out, f, separators=(',',':'))
    print(f'wrote {out_path} ({label}: {len(data)} units)')

build('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/ped_hours_by_nta.json',
      '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/crimes_by_nta.json',
      '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/nta.geojson',
      'nta2020',
      '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/rates_nta.json',
      'NTA',
      '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/walk_purpose_by_nta.json',
      '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/crashes_by_nta.json')

build('/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/ped_hours_by_ct.json',
      '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/crimes_by_ct.json',
      '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/ct.geojson',
      'boroct2020',
      '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/rates_ct.json',
      'CT',
      '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/walk_purpose_by_ct.json',
      '/Users/joshgreenman/Experiments/nyc-data/crime-per-walker/crashes_by_ct.json')
