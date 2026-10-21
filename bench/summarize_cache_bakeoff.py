#!/usr/bin/env python3
"""Summarize cache-bakeoff evaluations into win/loss rows."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_rows(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("evaluations"):
        return payload["evaluations"]
    return payload.get("cells") or []


def best_ok(rows, tool, config=None):
    picked = None
    for row in rows:
        if row.get("cache_tool") != tool or row.get("skipped") or not row.get("ok"):
            continue
        if config and row.get("cache_config") != config:
            continue
        ms = row.get("fitness_ms")
        if ms is None:
            continue
        if picked is None or ms < picked["fitness_ms"]:
            picked = row
    return picked


def classify(nano, kache):
    if nano is None and kache is None:
        return "no-data"
    if nano is None:
        return "kache"
    if kache is None:
        return "nanocompile"
    if nano["fitness_ms"] * 1.03 < kache["fitness_ms"]:
        return "nanocompile"
    if kache["fitness_ms"] * 1.03 < nano["fitness_ms"]:
        return "kache"
    return "stall"


def main(argv=None):
    path = Path((argv or sys.argv)[1] if (argv or sys.argv)[1:] else REPO / "bench/archive/cache-bakeoff.json")
    rows = [row for row in load_rows(path) if not row.get("skipped")]
    groups = defaultdict(list)
    for row in rows:
        groups[(row.get("sample_name") or row.get("sample"), row.get("loop"), row.get("scenario"))].append(row)
    table = []
    for key in sorted(groups):
        sample, loop, scenario = key
        nano = best_ok(groups[key], "nanocompile")
        kache = best_ok(groups[key], "kache")
        winner = classify(nano, kache)
        table.append({
            "sample": sample,
            "loop": loop,
            "scenario": scenario,
            "winner": winner,
            "nano_ms": None if nano is None else nano["fitness_ms"],
            "nano_config": None if nano is None else nano.get("cache_config"),
            "nano_hit_rate": None if nano is None else nano.get("hit_rate"),
            "nano_store": None if nano is None else nano.get("store_bytes"),
            "nano_target": None if nano is None else nano.get("target_bytes"),
            "kache_ms": None if kache is None else kache["fitness_ms"],
            "kache_config": None if kache is None else kache.get("cache_config"),
            "kache_hit_rate": None if kache is None else kache.get("hit_rate"),
            "kache_store": None if kache is None else kache.get("store_bytes"),
            "kache_target": None if kache is None else kache.get("target_bytes"),
        })
    counts = defaultdict(int)
    for row in table:
        counts[row["winner"]] += 1
    print(json.dumps({"counts": dict(counts), "rows": table}, indent=2))


if __name__ == "__main__":
    main()
