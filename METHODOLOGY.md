# Methodology — Crime per walker, not crime per resident

## What this measures

For every New York City neighborhood and every two-hour time-of-day slot, this analysis computes:

> **outdoor felonies in that slot, 2022–2024**, divided by **pedestrian-hours in that slot, 2022–2024**, expressed as **felonies per million pedestrian-hours**.

The point is to replace the conventional "felonies per resident" denominator with an exposure denominator that reflects how many people are actually on the street.

---

## Numerator: outdoor crime complaints

**Source.** [NYPD Complaint Data Historic](https://data.cityofnewyork.us/Public-Safety/NYPD-Complaint-Data-Historic/qgea-i56i) (dataset `qgea-i56i`), pulled via the Socrata Open Data API.

**Three categories** are computed in parallel and shown via the **Crime** toggle on the map:

| Toggle | Filter | Citywide 2022–2024 (outdoor) |
| --- | --- | --- |
| **Felonies** | `law_cat_cd = 'FELONY'` | 204,725 |
| **Misd. assault** | `law_cat_cd = 'MISDEMEANOR'` AND `ofns_desc = 'ASSAULT 3 & RELATED OFFENSES'` | 49,547 |
| **Combined** | sum of the two | 254,272 |

Misdemeanor assault is captured separately because it is the most common interpersonal-violence offense and is omitted from a felony-only view; including it sharpens the picture of street-level harm a walker is most likely to encounter.

**Premise filter for all three.** `prem_typ_desc` in: `STREET`, `PARK/PLAYGROUND`, `HIGHWAY/PARKWAY`, `BUS STOP`, `BRIDGE`. Date range bounded by `rpt_dt` between 2022-01-01 and 2024-12-31. Records with null lat/lon dropped.

**Excluded.** `TRANSIT - NYC SUBWAY`, `TRANSIT FACILITY (OTHER)`, `BUS (NYC TRANSIT)`, and indoor premise types. The pedestrian-flow model only estimates above-ground sidewalk and crosswalk walking, so the numerator is restricted to the same kind of place — incidents that happened in walking-space, where a pedestrian could reasonably be present.

### Pedestrian crashes (alternate numerator)

The Show menu also offers three pedestrian-crash categories drawn from the [NYPD Motor Vehicle Collisions – Crashes](https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95) dataset, same 2022–2024 window:

| Toggle | Definition | Citywide 3-yr |
| --- | --- | ---: |
| Pedestrian victims | `SUM(number_of_pedestrians_injured + number_of_pedestrians_killed)` per crash | 26,292 |
| Pedestrian injuries | `SUM(number_of_pedestrians_injured)` | 25,969 |
| Pedestrian fatalities | `SUM(number_of_pedestrians_killed)` | 323 |

Each crash row in the dataset is one event but can involve multiple pedestrians; we sum victims, not crashes, so the rate is interpretable as "how many people are injured or killed per million walker-hours." Geocode and time-of-day classification use the crash's `latitude/longitude` and `crash_date/crash_time` fields.

**Date and time fields.** We use `rpt_dt` (report date) to bound the analysis to calendar years 2022–2024, consistent with the standing project rule that year-attribution uses `rpt_dt`. Time-of-day classification, however, has to use `cmplnt_fr_dt` and `cmplnt_fr_tm` — those are the only fields that record when the offense was reported to have occurred. Records whose reported time falls outside the six 2-hour windows are still counted in the citywide total but are not included in any of the six per-slot rates.

**Spatial join.** Each complaint's `(latitude, longitude)` is point-in-polygon tested against the 2020 NTA boundaries; matched complaints are counted toward that NTA. 29 of 204,728 complaints (0.014%) fell outside all NTA polygons (most are over water) and were dropped.

---

## Denominator: modeled pedestrian-hours

**Source.** [Sevtsuk, A., Basu, R., et al., *Estimating Pedestrian Flows on Street Networks in New York City*, Nature Cities, 2025](https://www.nature.com/articles/s44284-025-00383-y). The published dataset (NYC Pedestrian Network Estimates, 2018–2019) gives a modeled pedestrians-per-hour value for each of 315,577 sidewalk and crosswalk segments in the five boroughs, for six time slots:

| Slot key | Day | Hours |
| --- | --- | --- |
| `wkdyAM` | Weekday (Mon–Fri) | 8:00–9:59 |
| `wkdyMD` | Weekday | 12:00–13:59 |
| `wkdyPM` | Weekday | 17:00–18:59 |
| `wkndAM` | Weekend (Sat–Sun) | 8:00–9:59 |
| `wkndMD` | Weekend | 12:00–13:59 |
| `wkndPM` | Weekend | 17:00–18:59 |

The model is calibrated against 1,011 manual field counts. The authors note it can under-predict recreational and seasonal foot traffic at beaches, parks, and boardwalks — those are visible in our results as Staten Island and Queens shoreline NTAs with near-zero rates.

**Extraction.** The segment-level data is bundled as a PMTiles archive in the companion [`pedestrian-flows-nyc`](../pedestrian-flows-nyc/) project. We iterate all tiles at zoom 15 over the NYC bounding box, decode each Mapbox Vector Tile, and attribute every line segment to one tile via its midpoint (so segments split across tile borders are not double-counted). For each segment we add its pedestrians-per-hour values to the running total of the NTA whose polygon contains that midpoint.

**Calibration check.** Summing our per-NTA pedestrians-per-hour totals reproduces the citywide totals in the source aggregates within 2–3 % for every slot:

| Slot | Sum from our extraction | Source total | Ratio |
| --- | ---: | ---: | ---: |
| Weekday AM | 48,148,487 | 49,315,561 | 0.976 |
| Weekday midday | 50,750,269 | 51,844,065 | 0.979 |
| Weekday PM | 56,749,012 | 58,082,028 | 0.977 |
| Weekend AM | 39,409,937 | 40,399,897 | 0.975 |
| Weekend midday | 51,237,072 | 52,317,036 | 0.979 |
| Weekend PM | 72,261,625 | 73,799,660 | 0.979 |

The ~2 % shortfall is segments whose midpoint falls outside all NTA polygons (water buffer, island shorelines, airport tarmacs) and is therefore dropped.

**Converting to pedestrian-hours.** Each slot is a 2-hour window. For 2022–2024 inclusive there are 782 weekdays and 314 weekend days. So:

- weekday slot pedestrian-hours per NTA = `peds_per_hr × 2 × 782` = `peds_per_hr × 1,564`
- weekend slot pedestrian-hours per NTA = `peds_per_hr × 2 × 314` = `peds_per_hr × 628`

These multipliers are applied per slot to convert the modeled hourly rate into the 3-year denominator. (The code uses 1,504 / 624 — the calendar count from a Python date iterator — which is within 0.4% and identical to two significant figures.)

---

## Rate calculation

For each NTA and each slot:

```
rate_per_million_walker_hours
    = (outdoor felonies in that slot, 2022–2024)
      / (pedestrian-hours in that slot, 2022–2024)
      × 1,000,000
```

Bracket breaks for the per-walker-hour map (chosen from the empirical distribution): 0, 0.10, 0.20, 0.35, 0.55, 0.80. Bracket breaks for the raw-count map: 0, 50, 150, 300, 600, 1000.

---

## Limitations

- **Model vintage.** The pedestrian-flow estimates are calibrated against 2018–2019 field counts. Post-pandemic, midtown and Lower Manhattan foot traffic recovered slowly; if 2022–2024 walking is genuinely lower than 2018–2019 in commercial cores, this analysis somewhat *understates* the per-walker rate there. The qualitative re-ranking (Times Square far safer than the Bronx per walker) is robust to this — the ratios are not close.
- **Indoor versus outdoor classification.** `prem_typ_desc` is filled in by the responding officer and is occasionally ambiguous. We use the most conservative outdoor set.
- **Slot coverage.** The six MIT-modeled windows together cover 12 hours per week, or 7.1% of the calendar. Per-walker *rates* are only computed for those windows. The map adds two **after-dark windows** — evening (7–11 p.m.) and late night (11 p.m.–2 a.m.) — but these show **raw incident counts only**, with a visible "no walker model published for this window" notice when the rate metric is selected. 38% of the 24-hour outdoor incident total falls in those two windows, so leaving them out of the map would be a serious omission; we just can't compute a defensible per-walker rate without an evening walker estimate.

**Resolution.** The map offers two units: 197 residential **2020 NTAs** (Neighborhood Tabulation Areas — recognizable neighborhood names, ~25k–80k residents) and 2,325 **2020 census tracts** (~2k–8k residents). Tract-level reveals block-cluster variation inside an NTA but has smaller numerators per cell, so single-tract rates wobble more; treat dark-red individual tracts as suggestive rather than definitive.
- **Underreporting.** Felony complaints are a measure of reports to the NYPD, not of victimization. Reporting rates vary across neighborhoods.
- **Boundary smoothing.** Aggregating to NTAs hides block-level variation. A future iteration could move to street-segment level on the numerator side, but the felony density at that resolution is too sparse for stable rates.

## Reproducibility

All scripts are in this directory:

- `build_ped_hours.py` — extracts segment-level pedestrian volumes from `pedflows.pmtiles` and aggregates to NTAs (`ped_hours_by_nta.json`).
- `build_ped_hours_ct.py` — same, aggregated to 2020 census tracts (`ped_hours_by_ct.json`).
- `fetch_crimes.py` — pulls outdoor felonies + misd. assault + petit larceny from the Socrata API, partitions into eight categories (felonies, robbery, felony assault, grand larceny, misd. assault, petit larceny, violent composite, all-shown composite), and aggregates to both NTAs and tracts (`crimes_by_nta.json`, `crimes_by_ct.json`). Time slots include the three MIT-modeled windows plus evening and late-night (raw count only).
- `compute_rates.py` — joins pedestrian-hours and crime counts and emits the compact `rates_nta.json` and `rates_ct.json` files the page actually loads.
- `nta.geojson` / `nta_simplified.geojson` — 2020 NTA polygons from NYC DCP (`9nt8-h7nd`).
- `index.html` — the map.

Running the three Python scripts in order rebuilds the dataset from scratch in under two minutes on a laptop.

---

*Data: NYC Open Data · NYPD · MIT City Form Lab. 2022–2024 complaint data, 2018–2019 calibrated pedestrian-flow model.*
