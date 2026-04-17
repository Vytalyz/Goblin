"""Analyze AF-CAND-0733 shadow week signal trace."""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

TRACE = Path(r"<MT5_COMMON_FILES>/AgenticForex\LiveDemo\AF-CAND-0733\signal_trace.csv")
SUMMARY = Path(r"<MT5_COMMON_FILES>/AgenticForex\LiveDemo\AF-CAND-0733\runtime_summary.json")

rows = []
with open(TRACE) as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

print("=" * 55)
print("  AF-CAND-0733 SHADOW WEEK ANALYSIS")
print("=" * 55)
print(f"Total signals: {len(rows)}")
print(f"Date range: {rows[0]['timestamp_utc']} to {rows[-1]['timestamp_utc']}")
print(f"Bars processed by end: {rows[-1]['bars_processed']}")

# Runtime summary
if SUMMARY.exists():
    with open(SUMMARY) as f:
        rs = json.load(f)
    print(f"\n--- Runtime Summary (from last deinit) ---")
    print(f"  deinit_reason: {rs['deinit_reason']}")
    print(f"  bars_processed: {rs['bars_processed']}")
    print(f"  allowed_hour_bars: {rs['allowed_hour_bars']}")
    print(f"  spread_blocked_bars: {rs['spread_blocked_bars']}")
    print(f"  filter_blocked_bars: {rs['filter_blocked_bars']}")
    print(f"  no_signal_bars: {rs['no_signal_bars']}")
    print(f"  long_signals: {rs['long_signals']}")
    print(f"  short_signals: {rs['short_signals']}")
    print(f"  order_attempts: {rs['order_attempts']}")
    print(f"  order_successes: {rs['order_successes']}")
    print(f"  symbol_tick_failures: {rs['symbol_tick_failures']}")
    print(f"  copyrates_failures: {rs['copyrates_failures']}")

# Signal direction breakdown
longs = sum(1 for r in rows if r["signal"] == "1")
shorts = sum(1 for r in rows if r["signal"] == "-1")
print(f"\n--- Direction Breakdown ---")
print(f"  Long signals:  {longs}")
print(f"  Short signals: {shorts}")
print(f"  L/S ratio: {longs / max(shorts, 1):.2f}")

# By day
by_day = defaultdict(lambda: {"long": 0, "short": 0, "total": 0})
for r in rows:
    day = r["timestamp_utc"][:10]
    by_day[day]["total"] += 1
    if r["signal"] == "1":
        by_day[day]["long"] += 1
    else:
        by_day[day]["short"] += 1

print(f"\n--- Signals by Day ---")
for day in sorted(by_day):
    d = by_day[day]
    print(f"  {day}: {d['total']:3d} signals (L:{d['long']:3d} S:{d['short']:3d})")

# By hour
by_hour = Counter()
for r in rows:
    hour = r["timestamp_utc"][11:13]
    by_hour[hour] += 1

print(f"\n--- Signals by Hour (UTC) ---")
for hour in sorted(by_hour):
    bar = "#" * (by_hour[hour] // 2)
    print(f"  {hour}:00  {by_hour[hour]:3d}  {bar}")

# Spread analysis
spreads = [float(r["spread_pips"]) for r in rows]
print(f"\n--- Spread at Signal Time ---")
print(f"  Min: {min(spreads):.1f} pips")
print(f"  Max: {max(spreads):.1f} pips")
print(f"  Avg: {sum(spreads) / len(spreads):.2f} pips")
spread_over_1 = sum(1 for s in spreads if s > 1.0)
print(f"  Signals with spread > 1.0: {spread_over_1} ({100 * spread_over_1 / len(spreads):.1f}%)")

# Signal clustering (gap > 5 min = new cluster)
clusters = []
current_cluster = [rows[0]]
for i in range(1, len(rows)):
    prev_ts = rows[i - 1]["timestamp_utc"]
    curr_ts = rows[i]["timestamp_utc"]
    prev_min = int(prev_ts[14:16])
    curr_min = int(curr_ts[14:16])
    prev_hour = int(prev_ts[11:13])
    curr_hour = int(curr_ts[11:13])
    same_day = prev_ts[:10] == curr_ts[:10]
    diff = (curr_hour * 60 + curr_min) - (prev_hour * 60 + prev_min)
    if same_day and 0 < diff <= 5:
        current_cluster.append(rows[i])
    else:
        clusters.append(current_cluster)
        current_cluster = [rows[i]]
clusters.append(current_cluster)

print(f"\n--- Signal Clustering (gap > 5 min) ---")
print(f"  Total clusters: {len(clusters)}")
print(f"  Avg signals per cluster: {len(rows) / len(clusters):.1f}")
print(f"  Longest cluster: {max(len(c) for c in clusters)} signals")

# Top 5 longest clusters
sorted_clusters = sorted(clusters, key=len, reverse=True)
print(f"\n--- Top 5 Clusters ---")
for i, c in enumerate(sorted_clusters[:5]):
    directions = Counter(r["signal"] for r in c)
    d_str = f"L:{directions.get('1', 0)} S:{directions.get('-1', 0)}"
    print(f"  #{i+1}: {len(c)} signals, {c[0]['timestamp_utc']} - {c[-1]['timestamp_utc']}, {d_str}")

# Consecutive same-direction
max_consec_long = 0
max_consec_short = 0
cur_l = 0
cur_s = 0
for r in rows:
    if r["signal"] == "1":
        cur_l += 1
        cur_s = 0
    else:
        cur_s += 1
        cur_l = 0
    max_consec_long = max(max_consec_long, cur_l)
    max_consec_short = max(max_consec_short, cur_s)
print(f"\n--- Direction Persistence ---")
print(f"  Max consecutive longs:  {max_consec_long}")
print(f"  Max consecutive shorts: {max_consec_short}")

# Direction flips
flips = sum(1 for i in range(1, len(rows)) if rows[i]["signal"] != rows[i - 1]["signal"])
print(f"  Direction flips: {flips} ({100 * flips / max(len(rows) - 1, 1):.1f}% of transitions)")

# Signal rate (signals per in-window hour)
unique_days = len(by_day)
in_window_hours = unique_days * 6  # 08-13 = 6 hours
print(f"\n--- Signal Rate ---")
print(f"  Trading days observed: {unique_days}")
print(f"  In-window hours: {in_window_hours}")
print(f"  Signals per hour: {len(rows) / max(in_window_hours, 1):.1f}")
print(f"  Signals per day: {len(rows) / max(unique_days, 1):.1f}")
