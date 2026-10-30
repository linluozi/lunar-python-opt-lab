#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Benchmark for the lunar-python LunarYear cache optimization.

Workload: convert N solar dates sampled uniformly from a fixed 24-year window
(2000-01-01 .. 2023-12-31) into full lunar strings.  Because the dates are
shuffled across years, an implementation that only caches the most recent
LunarYear rebuilds the whole year (jieqi + new moons) on almost every call.

Usage:
    python3 benchmark/bench.py --lib /tmp/lunar-base --impl baseline  --out benchmark/baseline.json
    python3 benchmark/bench.py --lib /tmp/lunar-opt  --impl optimized --out benchmark/optimized.json

Every individual timing sample is written to benchmark/raw/<impl>-<scale>-<i>.json.
Timing uses time.perf_counter().  The random seed is fixed and recorded.
"""
import argparse
import datetime as dt
import json
import os
import platform
import random
import resource
import statistics
import sys
import time

SEED = 20261030
SCALES = (80, 240, 720)
WARMUP = 3
SAMPLES = 5
WINDOW_START = dt.date(2000, 1, 1)
WINDOW_END = dt.date(2023, 12, 31)


def percentile(sorted_values, q):
    """Linear-interpolated percentile (q in [0, 1]) without numpy."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def make_dates(n):
    rng = random.Random(SEED)
    span = (WINDOW_END - WINDOW_START).days
    dates = []
    for _ in range(n):
        d = WINDOW_START + dt.timedelta(days=rng.randrange(span + 1))
        dates.append((d.year, d.month, d.day))
    return dates


def run_pass(dates, Solar):
    out = []
    for y, m, d in dates:
        lunar = Solar.fromYmd(y, m, d).getLunar()
        out.append(
            "%s|%s|%s|%s|%s|%s"
            % (
                lunar.toString(),
                lunar.getYearInGanZhi(),
                lunar.getMonthInChinese(),
                lunar.getDayInChinese(),
                lunar.getJieQi(),
                lunar.getYearShengXiao(),
            )
        )
    return out


def cpu_model():
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def mem_total_kb():
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True, help="directory containing the lunar_python package")
    ap.add_argument("--impl", required=True, choices=["baseline", "optimized"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--raw-dir", default=None)
    ap.add_argument("--upstream-tests", default="")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    lib = os.path.abspath(args.lib)
    sys.path.insert(0, lib)
    import lunar_python  # noqa: E402

    imported_from = os.path.dirname(os.path.dirname(os.path.abspath(lunar_python.__file__)))
    if imported_from != lib:
        raise SystemExit("lunar_python imported from %s, expected %s" % (imported_from, lib))
    from lunar_python import Solar  # noqa: E402

    raw_dir = args.raw_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    max_n = max(SCALES)
    all_dates = make_dates(max_n)
    # Touch every distinct year once so peak RSS includes the cache contents.
    years = sorted({d[0] for d in all_dates})

    results = []
    for n in SCALES:
        dates = all_dates[:n]
        for _ in range(WARMUP):
            run_pass(dates, Solar)
        samples = []
        for i in range(SAMPLES):
            t0 = time.perf_counter()
            run_pass(dates, Solar)
            elapsed = time.perf_counter() - t0
            samples.append(elapsed)
            record = {
                "impl": args.impl,
                "scale": n,
                "sample_index": i,
                "seconds": elapsed,
                "n_dates": n,
                "distinct_years": len({d[0] for d in dates}),
                "seed": SEED,
                "timer": "time.perf_counter",
                "python": platform.python_version(),
                "lib": lib,
            }
            with open(os.path.join(raw_dir, "%s-%d-%d.json" % (args.impl, n, i)), "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2)
        s = sorted(samples)
        results.append(
            {
                "scale": n,
                "n_dates": n,
                "distinct_years": len({d[0] for d in dates}),
                "samples_s": samples,
                "median_s": statistics.median(samples),
                "p25_s": percentile(s, 0.25),
                "p75_s": percentile(s, 0.75),
                "rel_stdev": (statistics.pstdev(samples) / statistics.mean(samples)) if len(samples) > 1 else 0.0,
            }
        )

    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    doc = {
        "impl": args.impl,
        "lib": lib,
        "command": " ".join([sys.executable] + sys.argv),
        "seed": SEED,
        "warmup": WARMUP,
        "samples_per_scale": SAMPLES,
        "scales": list(SCALES),
        "window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "distinct_years_in_window": len(years),
        "timer": "time.perf_counter",
        "environment": {
            "cpu": cpu_model(),
            "mem_total_kb": mem_total_kb(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "machine": platform.machine(),
        },
        "peak_rss_kb": peak_rss_kb,
        "upstream_tests": args.upstream_tests,
        "note": args.note,
        "results": results,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"impl": args.impl, "peak_rss_kb": peak_rss_kb,
                      "results": [{"scale": r["scale"], "median_s": r["median_s"],
                                   "p25_s": r["p25_s"], "p75_s": r["p75_s"],
                                   "rel_stdev": r["rel_stdev"]} for r in results]}, indent=2))


if __name__ == "__main__":
    main()
