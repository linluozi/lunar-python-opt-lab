#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Differential test: upstream lunar-python vs. the patched LunarYear cache.

Every case is rendered by the same worker code under two separate interpreter
processes (one per library checkout) and the resulting JSON lines are compared
byte for byte.  No tolerance, no approximate comparison.

Usage:
    python3 tests/test_diff.py --baseline /tmp/lunar-base --optimized /tmp/lunar-opt
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import random
import subprocess
import sys

SEED = 20261030
N_RANDOM = 1200


def build_cases():
    rng = random.Random(SEED)
    cases = []
    start = dt.date(1900, 1, 31)
    end = dt.date(2100, 12, 31)
    span = (end - start).days
    for _ in range(N_RANDOM):
        d = start + dt.timedelta(days=rng.randrange(span + 1))
        cases.append({"kind": "solar", "y": d.year, "m": d.month, "d": d.day})

    # Boundary and edge dates: calendar limits, leap days, year/month edges,
    # dates around solar terms, and dates used by the upstream test-suite.
    edges = [
        (1900, 1, 31), (1900, 2, 1), (1900, 12, 31), (1901, 1, 1),
        (2000, 2, 29), (2000, 12, 31), (2001, 1, 1), (2024, 2, 10),
        (2023, 1, 22), (2023, 3, 21), (2023, 3, 22), (2023, 6, 21),
        (2023, 9, 23), (2023, 12, 22), (2024, 2, 4), (2024, 2, 9),
        (2024, 2, 19), (2024, 4, 4), (2024, 6, 10), (2024, 9, 17),
        (2025, 1, 1), (2025, 1, 29), (2025, 7, 25), (2025, 12, 31),
        (2033, 12, 22), (2034, 2, 19), (2044, 1, 30), (2099, 12, 31),
        (2100, 1, 1), (2100, 2, 28), (2100, 12, 31),
        (1987, 1, 1), (1987, 12, 31), (1990, 5, 23), (1995, 8, 15),
        (2008, 8, 8), (2012, 2, 29), (2016, 2, 29), (2020, 2, 29),
        (1970, 1, 1), (1969, 12, 31), (1950, 6, 15), (1949, 10, 1),
    ]
    for y, m, d in edges:
        cases.append({"kind": "solar", "y": y, "m": m, "d": d})
    return cases


def render(cases):
    from lunar_python import Solar, Lunar

    lines = []
    for c in cases:
        lunar = Solar.fromYmd(c["y"], c["m"], c["d"]).getLunar()
        payload = {
            "input": c,
            "toString": lunar.toString(),
            "toFullString": lunar.toFullString(),
            "ganzhi": lunar.getYearInGanZhi(),
            "month": lunar.getMonthInChinese(),
            "day": lunar.getDayInChinese(),
            "jieqi": lunar.getJieQi(),
            "shengxiao": lunar.getYearShengXiao(),
        }
        lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return lines


def run_worker(lib, cases):
    env = dict(os.environ)
    env["PYTHONPATH"] = lib + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["LUNAR_DIFF_CASES"] = json.dumps(cases)
    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--worker"],
        input=env["LUNAR_DIFF_CASES"],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )
    if proc.returncode != 0:
        raise SystemExit("worker failed for %s:\n%s" % (lib, proc.stderr))
    return proc.stdout.splitlines()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="/tmp/lunar-base")
    ap.add_argument("--optimized", default="/tmp/lunar-opt")
    ap.add_argument("--worker", action="store_true")
    args = ap.parse_args()

    if args.worker:
        cases = json.loads(sys.stdin.read())
        sys.stdout.write("\n".join(render(cases)) + "\n")
        return

    cases = build_cases()
    base = run_worker(os.path.abspath(args.baseline), cases)
    opt = run_worker(os.path.abspath(args.optimized), cases)
    if len(base) != len(opt):
        raise SystemExit("line count differs: %d vs %d" % (len(base), len(opt)))

    diffs = [(i, a, b) for i, (a, b) in enumerate(zip(base, opt)) if a != b]
    h_base = hashlib.sha256("\n".join(base).encode("utf-8")).hexdigest()
    h_opt = hashlib.sha256("\n".join(opt).encode("utf-8")).hexdigest()
    print("cases: %d" % len(cases))
    print("baseline  sha256: %s" % h_base)
    print("optimized sha256: %s" % h_opt)
    print("differences: %d" % len(diffs))
    if diffs or h_base != h_opt:
        for i, a, b in diffs[:5]:
            print("first diff at case %d:\n  base=%s\n  opt =%s" % (i, a, b))
        raise SystemExit("DIFFERENTIAL TEST FAILED")
    print("RESULT: IDENTICAL (byte-for-byte)")


if __name__ == "__main__":
    main()
