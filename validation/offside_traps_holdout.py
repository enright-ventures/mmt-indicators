"""Out-of-sample check of the promising trap levels: thresholds from Oct 2025 - Mar 2026, results on Apr - Oct 2026."""
import datetime as dt
import numpy as np
from offside_traps import load, summarise, swings
from offside_traps_levels import composite_levels, prior_week_vwap_levels, two_sided_traps, DAY_BARS

b = load()
n = len(b["t"])
split = int(np.searchsorted(b["t"], int(dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc).timestamp())))
header = ("| Group | n | +30m | +1h | +2h | +4h | hit 2h | 1R exp | 1R win | 2R exp | median risk bp |\n"
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
sets = {
    "daily composite VAH/VAL": [x for x in composite_levels(b, "Daily") if x[3].endswith(("VAH", "VAL"))],
    "prior week VWAP": [x for x in prior_week_vwap_levels(b) if x[3].endswith("VWAP")],
    "4h swing": [(a, e, p, k) for a, p, s, k, e in swings(b["t"], b["h"], b["l"], n, 4 * 3600, 3, DAY_BARS * 14, "4h swing")],
}
print(header)
for name, lv in sets.items():
    evs = two_sided_traps(b, lv)
    for side, lab in ((1, "failed breakdown, long"), (-1, "failed breakout, short")):
        sel = [e for e in evs if e["side"] == side]
        first = [e for e in sel if e["k"] < split]
        second = [e for e in sel if e["k"] >= split]
        med1 = np.median([e["trapped"] for e in first]) if first else 0
        print(summarise(b, first, f"{name}, {lab}: first half"))
        print(summarise(b, second, f"{name}, {lab}: second half"))
        print(summarise(b, [e for e in second if e["trapped"] > med1], f"  second half, more trapped (first-half median {med1:,.0f} BTC)"))
