"""Summarize a private rust_diagnostic.py run without publishing compiler argv.

Invocation durations include trace/capture overhead and overlap under Cargo's
four jobs. Their sum is attribution, not build wall time or a speedup estimate.
"""
import argparse
import collections
import hashlib
import json
import statistics
from pathlib import Path


def summarize(rows):
    phases = {}
    for phase in dict.fromkeys(row["phase"] for row in rows):
        current = [row for row in rows if row["phase"] == phase]
        groups = collections.defaultdict(list)
        for row in current:
            decisions = row["decisions"]
            outcome = ("hit" if "nanocompile: hit" in decisions else
                       "bypass" if any("bypass:" in item for item in decisions) else
                       "uncached-or-miss")
            groups[outcome].append(row)
        phases[phase] = {
            "calls": len(current),
            "failed_calls": sum(row["exit_code"] != 0 for row in current),
            "outcomes": {key: {"calls": len(value),
                              "summed_invocation_seconds": sum(row["seconds"] for row in value)}
                         for key, value in groups.items()},
            "refusals": dict(collections.Counter(item for row in current for item in row["decisions"]
                                                if "bypass:" in item or "uncached:" in item)),
            "slowest": [{key: row[key] for key in ("crate", "type", "seconds", "decisions")}
                        for row in sorted(current, key=lambda row: row["seconds"], reverse=True)[:15]],
        }
    warm = [row for row in rows if row["phase"].startswith("warm-")]
    crates = collections.defaultdict(list)
    for row in warm:
        if row["crate"] is not None:
            crates[(row["crate"], row["type"])].append(row)
    return {
        "method": "real clean offline Cargo release builds; four jobs; Python capture wrapper and trace enabled; diagnostic only, not a performance comparison; summed invocation durations overlap and include capture overhead; no compiler environments or argv published",
        "phases": phases,
        "warm_crates": sorted(
            [{"crate": crate, "type": kind, "samples": len(values),
              "median_invocation_seconds": statistics.median(row["seconds"] for row in values),
              "decisions": sorted(set(item for row in values for item in row["decisions"]))}
             for (crate, kind), values in crates.items()],
            key=lambda row: row["median_invocation_seconds"], reverse=True),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.state / "calls.jsonl").read_text().splitlines()]
    if not rows:
        parser.error("no diagnostic calls found")
    result = summarize(rows)
    cfg = json.loads((args.state / "config.json").read_text())
    result["binary_sha256"] = hashlib.sha256(Path(cfg["binary"]).read_bytes()).hexdigest()
    result["binary_identity_note"] = "hash of configured executable at summary time; retain that executable unchanged throughout capture"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({phase: value["outcomes"] for phase, value in result["phases"].items()}, indent=2))


if __name__ == "__main__":
    main()

