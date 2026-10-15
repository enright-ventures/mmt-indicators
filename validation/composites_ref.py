"""Reference implementation of the Swordfish Composites TPO method.

Three jobs:
  1. kscript_composites(): a line-for-line port of the OpenMarket kScript
     "Swordfish Composites" (current_version, fetched 2026-10-07), so the wrun
     port can be compared number for number.
  2. swordfish_crosscheck(): the same closed periods resolved by the validated
     Python engine in trading-suite/swordfish (resolve_tpo_distribution,
     value_area_overlap_ratio and the ingest state machine of
     market_profile_composite_engine), to show the kScript method is that method.
  3. pairing_check(): native 30m candles versus the kScript's paired 15m candles.

Usage:
  python3 composites_ref.py fetch            # download ETHUSDT 15m + 30m klines
  python3 composites_ref.py check            # pairing + swordfish cross-check
  python3 composites_ref.py levels Daily     # print composites (compare with wrun)
"""

import json
import math
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SWORDFISH = "/Users/Shared/Projects/trading-suite/swordfish"

HALF_HOUR = 1800  # seconds
DAY = 86400
WEEK = 7 * DAY


# ---------------------------------------------------------------- data

def fetch_klines(symbol, interval, days):
    """Binance USD-M futures klines, oldest first, as [open_sec, o, h, l, c, v]."""
    step = {"15m": 900, "30m": 1800}[interval]
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * DAY * 1000
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        url = (
            "https://fapi.binance.com/fapi/v1/klines?symbol=%s&interval=%s&limit=1500&startTime=%d"
            % (symbol, interval, cursor)
        )
        with urllib.request.urlopen(url, timeout=30) as response:
            batch = json.loads(response.read())
        if not batch:
            break
        for k in batch:
            rows.append([k[0] // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
        cursor = batch[-1][0] + step * 1000
        if len(batch) < 1500:
            break
    # The last row is the forming candle (Binance returns it); keep it, the
    # kScript also receives the forming bar last (anchor "latest").
    return rows


def load(interval):
    with open(os.path.join(DATA, "ETHUSDT_%s.json" % interval)) as handle:
        return json.load(handle)


# ---------------------------------------------------------------- calendar (UTC, seconds)

def civil(ts):
    z = math.floor(ts / DAY) + 719468
    era = math.floor(z / 146097)
    doe = z - era * 146097
    yoe = math.floor((doe - math.floor(doe / 1460) + math.floor(doe / 36524) - math.floor(doe / 146096)) / 365)
    y = yoe + era * 400
    doy = doe - (365 * yoe + math.floor(yoe / 4) - math.floor(yoe / 100))
    mp = math.floor((5 * doy + 2) / 153)
    d = doy - math.floor((153 * mp + 2) / 5) + 1
    m = mp + (3 if mp < 10 else -9)
    return [y + (1 if m <= 2 else 0), m, d]


def utc_start(value):
    year = math.floor(value / 10000)
    month = math.floor(value / 100) % 100
    day = value % 100
    if year < 1970 or month < 1 or month > 12 or day < 1 or day > 31 or value != math.floor(value):
        return -1
    y = year - (1 if month <= 2 else 0)
    era = math.floor(y / 400)
    yoe = y - era * 400
    mp = month + (-3 if month > 2 else 9)
    doy = math.floor((153 * mp + 2) / 5) + day - 1
    doe = yoe * 365 + math.floor(yoe / 4) - math.floor(yoe / 100) + doy
    ts = (era * 146097 + doe - 719468) * DAY
    check = civil(ts)
    return ts if check == [year, month, day] else -1


def month_start(ts, offset):
    d = civil(ts)
    serial = d[0] * 12 + d[1] - 1 + offset
    year = math.floor(serial / 12)
    month = serial - year * 12 + 1
    return utc_start(year * 10000 + month * 100 + 1)


def bounds(ts, mode):
    day = math.floor(ts / DAY)
    if mode == "Daily":
        return [day * DAY, (day + 1) * DAY]
    if mode == "Monthly":
        return [month_start(ts, 0), month_start(ts, 1)]
    monday = math.floor((day + 3) / 7) * 7 - 3
    return [monday * DAY, (monday + 7) * DAY]


def date_label(ts):
    d = civil(ts)
    return "%02d/%02d" % (d[2], d[1])


# ---------------------------------------------------------------- rows

def auto_row(price):
    target = price * 0.0005
    base = math.pow(10, math.floor(math.log10(target)))
    n = target / base
    chosen = base * (1 if n <= 1.5 else 2 if n <= 3.5 else 5 if n <= 7.5 else 10)
    scale = math.pow(10, max(0, -math.floor(math.log10(target))))
    return js_round(chosen * scale) / scale


def js_round(x):
    """JavaScript Math.round: half rounds toward +infinity."""
    return math.floor(x + 0.5)


def price_row_floor(price, step):
    """kScript priceRow: floor bins, tolerating numerical noise at a row edge."""
    quotient = price / step
    edge = math.floor(quotient + 0.5)
    return edge if abs(quotient - edge) <= 0.00000001 else math.floor(quotient)


def price_row_nearest(price, step):
    """Swordfish _nearest_row: ROUND_HALF_UP of price / step (positive prices)."""
    return math.floor(price / step + 0.5)


# ---------------------------------------------------------------- profiles

class Profile:
    __slots__ = ("start", "end", "members", "lo", "hi", "poc", "vah", "val", "first", "last")

    def __init__(self, start=0, end=0, members=0, lo=0, hi=0, poc=0, vah=0, val=0, first=0, last=0):
        self.start, self.end, self.members = start, end, members
        self.lo, self.hi, self.poc, self.vah, self.val = lo, hi, poc, vah, val
        self.first, self.last = first, last

    def key(self):
        return (self.start, self.end, self.members, self.poc, self.vah, self.val)


def resolve(working, lo, hi):
    """kScript resolve(): POC nearest the midpoint then lower, 70% VA one row at a time."""
    total = 0
    maximum = 0
    poc = lo
    distance = 1000000000000
    midpoint = (lo + hi) / 2
    for r in range(lo, hi + 1):
        n = working.get(r, 0)
        total += n
        dist = abs(r - midpoint)
        if n > maximum or (n == maximum and (dist < distance or (dist == distance and r < poc))):
            maximum = n
            poc = r
            distance = dist
    included = working.get(poc, 0)
    up = down = vah = val = poc
    side = 0
    while included < math.ceil(total * 0.70):
        a = working.get(up + 1, 0) if up < hi else 0
        b = working.get(down - 1, 0) if down > lo else 0
        if down <= lo or (up < hi and (a > b or (a == b and side == -1))):
            up += 1
            included += a
            if a > 0:
                vah = up
            side = 1
        else:
            down -= 1
            included += b
            if b > 0:
                val = down
            side = -1
    return poc, vah, val


def overlap(a, b):
    return max(0, min(a.vah, b.vah) - max(a.val, b.val) + 1) / min(a.vah - a.val + 1, b.vah - b.val + 1)


def kscript_composites(brackets, cadence="Daily", calc_days=30, calc_weeks=13, calc_months=3,
                       display_days=30, display_weeks=13, display_months=3, keep=8,
                       anchor_date=0, manual_row=0.0, tick=0.0, binning="floor"):
    """Port of the kScript isLastBar block for the default (no manual merge/split) path.

    brackets: 30m rows [open_sec, o, h, l, c, v], oldest first, the LAST row is
    the forming bracket (as the kScript's requestBars(anchor: latest) delivers).
    Returns a dict with the closed periods, the composites, the drawn slice and
    the settings the run resolved.
    """
    price_row = price_row_floor if binning == "floor" else price_row_nearest
    available = brackets
    size = len(available)
    if size <= 1:
        return None
    watermark = available[-1][0]
    period_size = DAY if cadence == "Daily" else WEEK
    periods_wanted = calc_days if cadence == "Daily" else calc_weeks
    latest_period = bounds(watermark, cadence)
    cutoff = latest_period[0] - periods_wanted * period_size
    display_cutoff = latest_period[0] - (display_days if cadence == "Daily" else display_weeks) * period_size
    if cadence == "Monthly":
        cutoff = month_start(watermark, -calc_months)
        display_cutoff = month_start(watermark, -display_months)
    history_fault = ""
    if anchor_date > 0:
        fixed_start = utc_start(anchor_date)
        aligned = bounds(fixed_start, cadence)
        if fixed_start < 0 or aligned[0] != fixed_start or fixed_start >= latest_period[0]:
            history_fault = "Invalid fixed UTC start; use a past period boundary"
        else:
            cutoff = fixed_start
            if available[0][0] > cutoff:
                history_fault = "Fixed start unavailable in source history; choose a later start"
    rows = [r for r in available if r[0] >= cutoff]
    size = len(rows)
    if size <= 1:
        return None

    row_price = manual_row if manual_row > 0 else auto_row(rows[0][1])
    row_ticks = 0
    if tick > 0:
        row_ticks = max(1, -price_row_floor(-row_price, tick))
        row_price = row_ticks * tick

    bucket_rows, bucket_counts = [], []
    pending, completed, all_periods = [], [], []
    empty = Profile()
    active = empty
    current = {}
    low_row, high_row = 10 ** 12, -(10 ** 12)
    session, prior = -1, -1
    complete = False
    bracket_count = closed = skipped = gaps = 0
    fault = history_fault
    if anchor_date > 0 and rows[0][0] != cutoff:
        fault = history_fault or "Fixed start missing from source; profiles withheld"
    period = [0, 0]

    def merged_profile(left, right):
        working = {}
        for q in range(left.first, right.last):
            working[bucket_rows[q]] = working.get(bucket_rows[q], 0) + bucket_counts[q]
        lo = min(left.lo, right.lo)
        hi = max(left.hi, right.hi)
        poc, vah, val = resolve(working, lo, hi)
        return Profile(left.start, right.end, left.members + right.members, lo, hi, poc, vah, val, left.first, right.last)

    for i in range(size - 1):
        if fault:
            break
        bar = rows[i]
        ts = bar[0]
        if cadence == "Monthly" and ts >= latest_period[0]:
            break
        if ts >= period[1]:
            period = bounds(ts, cadence)
        if prior >= 0 and ts != prior + HALF_HOUR:
            gaps += 1
            complete = False
            if active.members > 0:
                completed.append(active)
            active = empty
            pending = []
        if session != period[0]:
            current = {}
            low_row, high_row = 10 ** 12, -(10 ** 12)
            session = period[0]
            complete = ts == session
            bracket_count = 0
        prior = ts
        if ts % HALF_HOUR != 0 or not (bar[2] >= bar[3] and bar[3] > 0 and bar[1] > 0 and bar[4] > 0) or (i > 0 and ts <= rows[i - 1][0]):
            fault = "Invalid source bars; profiles withheld"
            break
        if tick > 0:
            lo = math.floor(price_row_floor(bar[3], tick) / row_ticks) if binning == "floor" else price_row(price_row(bar[3], tick) * tick, row_price)
            hi = math.floor(price_row_floor(bar[2], tick) / row_ticks) if binning == "floor" else price_row(price_row(bar[2], tick) * tick, row_price)
        else:
            lo = price_row(bar[3], row_price)
            hi = price_row(bar[2], row_price)
        low_row = min(low_row, lo)
        high_row = max(high_row, hi)
        if high_row - low_row > 4095:
            fault = "Row span exceeds 4096; increase row increment"
            break
        current[lo] = current.get(lo, 0) + 1
        current[hi + 1] = current.get(hi + 1, 0) - 1
        bracket_count += 1
        if ts + HALF_HOUR == period[1]:
            if complete and bracket_count == (period[1] - period[0]) // HALF_HOUR:
                closed += 1
                running = 0
                for r in range(low_row, high_row + 1):
                    running += current.get(r, 0)
                    current[r] = running
                levels = resolve(current, low_row, high_row)
                first = len(bucket_rows)
                for r in range(low_row, high_row + 1):
                    count = current.get(r, 0)
                    if count > 0:
                        bucket_rows.append(r)
                        bucket_counts.append(count)
                p = Profile(session, period[1], 1, low_row, high_row, levels[0], levels[1], levels[2], first, len(bucket_rows))
                all_periods.append(p)
                if active.members > 0 and p.start == active.end and overlap(active, p) >= 0.50:
                    active = merged_profile(active, p)
                else:
                    if active.members > 0:
                        completed.append(active)
                    active = empty
                    pending.append(p)
                    for start in range(len(pending) - 1):
                        candidate = pending[start]
                        for j in range(start + 1, len(pending)):
                            candidate = merged_profile(candidate, pending[j])
                        if candidate.members == 2:
                            passes = overlap(pending[start], pending[start + 1]) >= 0.50
                        else:
                            passes = True
                            for j in range(start, len(pending)):
                                member = pending[j]
                                passes = passes and overlap(member, candidate) >= 0.50 and candidate.val <= member.poc <= candidate.vah
                        if passes:
                            active = candidate
                            pending = []
                            break
            else:
                skipped += 1
                if active.members > 0:
                    completed.append(active)
                active = empty
                pending = []
    if active.members > 0:
        completed.append(active)

    draw_start = max(0, len(completed) - keep)
    while draw_start < len(completed) and completed[draw_start].end <= display_cutoff:
        draw_start += 1
    return {
        "row_price": row_price,
        "cutoff": cutoff,
        "watermark": watermark,
        "display_cutoff": display_cutoff,
        "closed": closed,
        "skipped": skipped,
        "gaps": gaps,
        "fault": fault,
        "periods": all_periods,
        "completed": completed,
        "drawn": completed[draw_start:] if not fault else [],
        "bucket_rows": bucket_rows,
        "bucket_counts": bucket_counts,
    }


# ---------------------------------------------------------------- swordfish cross-check

def swordfish_crosscheck(result):
    """Resolve every closed period with the swordfish engine and replay its ingest rules."""
    sys.path.insert(0, SWORDFISH)
    from swordfish.infrastructure.tpo_calendar_engine import resolve_tpo_distribution
    from swordfish.infrastructure.market_profile_composite_engine import value_area_overlap_ratio

    rows, counts = result["bucket_rows"], result["bucket_counts"]

    def distribution(first, last):
        merged = {}
        for q in range(first, last):
            merged[rows[q]] = merged.get(rows[q], 0) + counts[q]
        return merged

    # 1. Every closed period: POC, VAH, VAL.
    mismatches = 0
    for p in result["periods"]:
        poc, vah, val, _total = resolve_tpo_distribution(distribution(p.first, p.last), row_size_ticks=1)
        if (poc, vah, val) != (p.poc, p.vah, p.val):
            mismatches += 1
            print("PERIOD MISMATCH", date_label(p.start), (p.poc, p.vah, p.val), "swordfish", (poc, vah, val))
    print("periods resolved by swordfish:", len(result["periods"]), "mismatches:", mismatches)

    # 2. The ingest state machine of MarketProfileCompositeEngine (gap reset,
    #    Rule 2 extension against the recomputed active VA, Rule 1 pairs,
    #    Rule 3 aggregates, longest suffix first), on the same closed periods.
    class Rec:
        def __init__(self, start, end, first, last):
            self.start, self.end, self.first, self.last = start, end, first, last
            self.poc, self.vah, self.val, _ = resolve_tpo_distribution(distribution(first, last), row_size_ticks=1)

    def ratio(a, b):
        return value_area_overlap_ratio(a_val_ticks=a.val, a_vah_ticks=a.vah, b_val_ticks=b.val, b_vah_ticks=b.vah, row_size_ticks=1)

    def merge(members):
        out = Rec(members[0].start, members[-1].end, members[0].first, members[-1].last)
        out.members = len(members)
        return out

    composites = []
    active = None
    active_members = []
    window = []
    previous_end = None
    for p in result["periods"]:
        record = Rec(p.start, p.end, p.first, p.last)
        if previous_end is not None and record.start > previous_end:
            if active is not None:
                composites.append(active)
            active, active_members, window = None, [], [record]
            previous_end = record.end
            continue
        previous_end = record.end
        if active is not None:
            if ratio(active, record) >= 0.50:
                active_members.append(record)
                active = merge(active_members)
            else:
                composites.append(active)
                active, active_members, window = None, [], [record]
            continue
        if not window:
            window = [record]
            continue
        run = window + [record]
        selected = None
        for start in range(len(run) - 1):
            suffix = run[start:]
            if len(suffix) == 2:
                if ratio(suffix[0], suffix[1]) >= 0.50:
                    selected = suffix
                    break
                continue
            aggregate = merge(suffix)
            if all(ratio(m, aggregate) >= 0.50 and aggregate.val <= m.poc <= aggregate.vah for m in suffix):
                selected = suffix
                break
        if selected is not None:
            active_members = list(selected)
            active = merge(active_members)
            window = []
        else:
            window = run
    if active is not None:
        composites.append(active)

    mine = [(c.start, c.end, c.poc, c.vah, c.val) for c in result["completed"]]
    theirs = [(c.start, c.end, c.poc, c.vah, c.val) for c in composites]
    # Incomplete periods break runs in the kScript (pending reset); the
    # swordfish ingest only sees eligible profiles and resets on the calendar
    # gap they leave, so both see the same runs.
    print("composites kScript:", len(mine), "swordfish ingest:", len(theirs), "identical:", mine == theirs)
    if mine != theirs:
        for a, b in zip(mine, theirs):
            if a != b:
                print("  first difference", a, b)
                break
    return mine == theirs and mismatches == 0


def pairing_check(fine, coarse):
    """Native 30m candles against the kScript's 15m pairs (closed brackets only)."""
    by_time = {r[0]: r for r in fine}
    compared = differ = 0
    for r in coarse[:-1]:
        a = by_time.get(r[0])
        b = by_time.get(r[0] + 900)
        if a is None or b is None:
            continue
        compared += 1
        if max(a[2], b[2]) != r[2] or min(a[3], b[3]) != r[3]:
            differ += 1
            if differ <= 5:
                print("  pair differs", r[0], (max(a[2], b[2]), min(a[3], b[3])), (r[2], r[3]))
    print("30m brackets compared:", compared, "high/low differ:", differ)
    return differ == 0


def paired_brackets(fine):
    """The kScript's pairing of 15m bars into 30m brackets (forming bracket last)."""
    out = []
    fi = 0
    n = len(fine)
    while fi < n:
        first = fine[fi]
        if first[0] % HALF_HOUR == 0:
            if fi + 1 < n and fine[fi + 1][0] == first[0] + 900:
                second = fine[fi + 1]
                out.append([first[0], first[1], max(first[2], second[2]), min(first[3], second[3]), second[4], first[5] + second[5]])
                fi += 2
            else:
                if fi == n - 1:
                    out.append(list(first))
                fi += 1
        else:
            fi += 1
    return out


def describe(result, cadence):
    unit = {"Daily": "D", "Weekly": "W", "Monthly": "M"}[cadence]
    step = result["row_price"]
    print("row %g | calc from %s | closed %d | gaps %d | incomplete %d | %s" % (
        step, date_label(result["cutoff"]), result["closed"], result["gaps"], result["skipped"], result["fault"] or "ok"))
    for p in result["drawn"]:
        print("%d%s %s to %s  VAH %g  POC %g  VAL %g" % (
            p.members, unit, date_label(p.start), date_label(p.end - 1), p.vah * step, p.poc * step, p.val * step))


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    if command == "fetch":
        os.makedirs(DATA, exist_ok=True)
        for interval, days in (("15m", 120), ("30m", 120)):
            rows = fetch_klines("ETHUSDT", interval, days)
            with open(os.path.join(DATA, "ETHUSDT_%s.json" % interval), "w") as handle:
                json.dump(rows, handle)
            print(interval, len(rows), "rows")
        return
    fine, coarse = load("15m"), load("30m")
    if command == "check":
        ok_pairs = pairing_check(fine, coarse)
        ok = True
        for cadence in ("Daily", "Weekly"):
            for binning in ("floor", "nearest"):
                for manual_row in (0.0, 0.01):
                    result = kscript_composites(coarse, cadence=cadence, binning=binning, manual_row=manual_row)
                    print("--- %s | %s bins | row %s" % (cadence, binning, "tick" if manual_row else "auto 0.05%"))
                    ok = swordfish_crosscheck(result) and ok
        paired = kscript_composites(paired_brackets(fine), cadence="Daily")
        native = kscript_composites(coarse, cadence="Daily")
        same = [p.key() for p in paired["completed"]] == [p.key() for p in native["completed"]]
        print("Daily composites from paired 15m == from native 30m:", same)
        print("ALL CHECKS PASS" if ok and ok_pairs and same else "CHECKS FAILED")
        return
    if command == "levels":
        cadence = sys.argv[2] if len(sys.argv) > 2 else "Daily"
        describe(kscript_composites(coarse, cadence=cadence), cadence)


if __name__ == "__main__":
    main()
