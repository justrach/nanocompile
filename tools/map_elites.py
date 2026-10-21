#!/usr/bin/env python3
"""Validate, merge, and render the rust-loop MAP-Elites archive.

Source of truth: bench/map_elites.json (schema_version 1).
Shards: bench/archive/<sample>.json

    python3 tools/map_elites.py validate [FILE]
    python3 tools/map_elites.py merge [--into FILE] [SHARDS...]
    python3 tools/map_elites.py render [--into FILE]
    python3 tools/map_elites.py classify PROJECT
    python3 tools/map_elites.py promote [--into FILE]

The native driver is `nanocompile map-elites` and accepts the same actions.
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
CANONICAL = REPO / "bench" / "map_elites.json"
SCHEMA = 1
KIND = "nanocompile.rust-loop.map-elites"
SHARD_KIND = KIND + ".shard"
SIZES = ("small", "mid", "large")
EDITS = ("cold", "noop", "body", "sig_dep")
BACKENDS = ("llvm", "cranelift")
LINKERS = ("default", "mold", "lld")
DEBUGINFO = ("full", "line-tables-only", "none")
FAST_CHECK = ("cargo-check", "none")
LOOPS = ("check", "graph", "test")
ACTIONS = ("seed", "replace", "reject", "held_out", "promote", "stop")
CHARLIE = "https://x.com/charliermarsh/status/2112711387285758250"
FORBIDDEN = ("cranelift", "codegen-backend", "cg_clif", "cargo-clif", "rustd", "lust", "relax")

EMPTY = {
    "schema_version": SCHEMA,
    "kind": KIND,
    "attribution": CHARLIE,
    "axes": {"size": list(SIZES), "edit": list(EDITS)},
    "size_rules": {
        "small": "workspace crates <= 1 and Rust LOC < 2000",
        "mid": "workspace crates <= 20 and Rust LOC < 50000",
        "large": "otherwise",
    },
    "fitness": {
        "metric": "median_ms",
        "goal": "min",
        "min_gain_pct": 3.0,
        "max_non_improving": 4,
    },
    "cells": {},
    "history": [],
    "generalization": {"samples": [], "elites_tested": [], "matrix": []},
    "promoted": {"defaults": None, "sample_specific": []},
}


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def fail(message):
    print("map-elites: " + message, file=sys.stderr)
    raise SystemExit(2)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("missing file " + str(path))
    except json.JSONDecodeError as err:
        fail("invalid JSON in %s: %s" % (path, err))


def dump(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def cell_key(size, edit):
    if size not in SIZES or edit not in EDITS:
        fail("unknown cell %s|%s" % (size, edit))
    return "%s|%s" % (size, edit)


def split_key(key):
    if not isinstance(key, str) or "|" not in key:
        fail("cell key must be size|edit, got %r" % key)
    size, edit = key.split("|", 1)
    return size, edit, cell_key(size, edit)


def as_float(value, name):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        fail("%s must be a number" % name)


def as_int(value, name):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        fail("%s must be an integer" % name)


def genome_ok(genome):
    if not isinstance(genome, dict):
        fail("genome must be an object")
    for key, allowed in (
        ("dev_backend", BACKENDS),
        ("linker", LINKERS),
        ("debuginfo", DEBUGINFO),
        ("fast_check", FAST_CHECK),
        ("loop", LOOPS),
    ):
        if key in genome and genome[key] not in allowed:
            fail("genome.%s must be one of %s" % (key, ", ".join(allowed)))
    if genome.get("wrapper") and genome.get("sccache"):
        fail("genome cannot stack nanocompile wrapper with sccache")
    if genome.get("loop") == "test" and genome.get("dev_backend") == "cranelift":
        fail("genome.loop=test cannot use cranelift; validate is LLVM rustc")
    units = genome.get("codegen_units")
    if units is not None and (not isinstance(units, int) or units < 1 or units > 256):
        fail("genome.codegen_units must be null or 1..256")
    return True


def correctness_ok(row):
    correctness = row.get("correctness")
    if not isinstance(correctness, dict):
        return False
    return bool(
        correctness.get("ok")
        and correctness.get("agree_on_broken")
        and correctness.get("validate_is_final")
    )


def check_evaluation(row, where):
    if not isinstance(row, dict):
        fail("%s: evaluation must be an object" % where)
    if "cell" in row:
        size, edit, key = split_key(row["cell"])
    else:
        size, edit, key = row.get("size"), row.get("edit"), None
        if size and edit:
            key = cell_key(size, edit)
        else:
            fail("%s: evaluation needs cell or size+edit" % where)
    row["size"] = size
    row["edit"] = edit
    row["cell"] = key
    if "genome" not in row:
        fail("%s: missing genome" % where)
    genome_ok(row["genome"])
    if "fitness_ms" not in row:
        fail("%s: missing fitness_ms" % where)
    row["fitness_ms"] = as_float(row["fitness_ms"], "fitness_ms")
    if row["fitness_ms"] is None or row["fitness_ms"] < 0:
        fail("%s: fitness_ms must be >= 0" % where)
    if "spread_ms" in row:
        row["spread_ms"] = as_float(row["spread_ms"], "spread_ms")
    if "disk_bytes" in row and row["disk_bytes"] is not None:
        row["disk_bytes"] = as_int(row["disk_bytes"], "disk_bytes")
    if "sample" not in row or not row["sample"]:
        fail("%s: missing sample" % where)
    if "correctness" not in row:
        fail("%s: missing correctness" % where)
    return row


def check_archive(data, path):
    if not isinstance(data, dict):
        fail("%s: root must be an object" % path)
    if data.get("schema_version") != SCHEMA:
        fail("%s: schema_version must be %d" % (path, SCHEMA))
    kind = data.get("kind")
    if kind == SHARD_KIND:
        if not data.get("sample"):
            fail("%s: shard needs sample" % path)
        evals = data.get("evaluations")
        if not isinstance(evals, list):
            fail("%s: shard needs evaluations[]" % path)
        for index, row in enumerate(evals):
            check_evaluation(row, "%s evaluations[%d]" % (path, index))
        return "shard"
    if kind != KIND:
        fail("%s: kind must be %s or %s" % (path, KIND, SHARD_KIND))
    axes = data.get("axes") or {}
    if list(axes.get("size") or []) != list(SIZES):
        fail("%s: axes.size must be %s" % (path, list(SIZES)))
    if list(axes.get("edit") or []) != list(EDITS):
        fail("%s: axes.edit must be %s" % (path, list(EDITS)))
    cells = data.get("cells")
    if not isinstance(cells, dict):
        fail("%s: cells must be an object" % path)
    for key, row in cells.items():
        _, _, expected = split_key(key)
        check_evaluation(row, "%s cells[%s]" % (path, key))
        if row["cell"] != expected:
            fail("%s: cell key %s does not match payload %s" % (path, key, row["cell"]))
    history = data.get("history") or []
    if not isinstance(history, list):
        fail("%s: history must be an array" % path)
    for index, row in enumerate(history):
        if not isinstance(row, dict) or row.get("action") not in ACTIONS:
            fail("%s: history[%d] needs a known action" % (path, index))
        if "cell" in row:
            split_key(row["cell"])
    return "archive"


def better(candidate, elite, min_gain_pct):
    if elite is None:
        return True, "seed"
    old = float(elite["fitness_ms"])
    new = float(candidate["fitness_ms"])
    if old <= 0:
        return new < old, "replace"
    gain = (old - new) / old * 100.0
    if gain >= min_gain_pct:
        return True, "replace"
    return False, "reject"


def min_gain(archive):
    fitness = archive.get("fitness") or {}
    try:
        return float(fitness.get("min_gain_pct", 3.0))
    except (TypeError, ValueError):
        return 3.0


def max_non_improving(archive):
    fitness = archive.get("fitness") or {}
    try:
        return int(fitness.get("max_non_improving", 4))
    except (TypeError, ValueError):
        return 4


def note(archive, action, row, reason):
    archive.setdefault("history", []).append({
        "timestamp": row.get("timestamp") or now_iso(),
        "sample": row.get("sample"),
        "cell": row.get("cell"),
        "action": action,
        "fitness_ms": row.get("fitness_ms"),
        "genome": row.get("genome"),
        "reason": reason,
    })


def occupy(archive, row, action, reason):
    cell = dict(row)
    cell.setdefault("n_evals", 1)
    cell.setdefault("non_improving", 0)
    cell["stopped"] = False
    archive.setdefault("cells", {})[row["cell"]] = cell
    note(archive, action, row, reason)


def apply_candidate(archive, row):
    if not correctness_ok(row):
        note(archive, "reject", row, "correctness gate failed")
        return "reject"
    cells = archive.setdefault("cells", {})
    elite = cells.get(row["cell"])
    win, action = better(row, elite, min_gain(archive))
    if win:
        occupy(archive, row, action, "median %.3f ms" % row["fitness_ms"] if action == "seed"
               else "%.1f%% faster than %.3f ms" % (
                   (float(elite["fitness_ms"]) - row["fitness_ms"]) / float(elite["fitness_ms"]) * 100.0,
                   elite["fitness_ms"]))
        return action
    if elite is not None:
        elite["non_improving"] = int(elite.get("non_improving") or 0) + 1
        elite["n_evals"] = int(elite.get("n_evals") or 1) + 1
        if elite["non_improving"] >= max_non_improving(archive):
            elite["stopped"] = True
            note(archive, "stop", elite, "%d non-improving tries" % elite["non_improving"])
        else:
            note(archive, "reject", row, "gain below %.1f%% vs elite %.3f ms" % (
                min_gain(archive), elite["fitness_ms"]))
    return "reject"


def merge_files(into: Path, shards):
    archive = load(into) if into.is_file() else json.loads(json.dumps(EMPTY))
    if check_archive(archive, str(into)) != "archive":
        fail("%s is a shard; pass --into bench/map_elites.json" % into)
    for path in shards:
        data = load(path)
        kind = check_archive(data, str(path))
        if kind == "shard":
            for row in data.get("evaluations") or []:
                if "sample" not in row:
                    row["sample"] = data.get("sample")
                if "commit" not in row:
                    row["commit"] = data.get("commit")
                apply_candidate(archive, row)
            extra = data.get("generalization")
            if extra:
                matrix = archive.setdefault("generalization", {}).setdefault("matrix", [])
                matrix.extend(extra.get("matrix") or extra.get("rows") or [])
        else:
            for row in (data.get("cells") or {}).values():
                apply_candidate(archive, row)
            archive.setdefault("history", []).extend(data.get("history") or [])
            extra = data.get("generalization") or {}
            dest = archive.setdefault("generalization", {"samples": [], "elites_tested": [], "matrix": []})
            for name in extra.get("samples") or []:
                if name not in dest.setdefault("samples", []):
                    dest["samples"].append(name)
            dest.setdefault("matrix", []).extend(extra.get("matrix") or [])
    dump(into, archive)
    return archive


def classify(root: Path):
    crates = 0
    loc = 0
    cargo = root / "Cargo.toml"
    if not cargo.is_file():
        fail("no Cargo.toml in " + str(root))
    crates = 1
    text = cargo.read_text(encoding="utf-8")
    if "[workspace]" in text:
        crates = max(1, text.count("\"" ) // 2) if "members" in text else 1
        # Count member directories that actually exist.
        members = []
        collecting = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if line.startswith("[") and line.endswith("]"):
                collecting = line[1:-1].strip() == "workspace"
                continue
            if not collecting:
                continue
            if line.startswith("members"):
                line = line.split("=", 1)[-1]
            for part in line.replace("[", " ").replace("]", " ").split(","):
                item = part.strip().strip("\"'")
                if item:
                    members.append(item)
        existing = [m for m in members if (root / m).is_dir()]
        crates = max(1, len(existing) or crates)
    for path in root.rglob("*.rs"):
        if any(part in {"target", ".git", ".nanocompile-loop"} for part in path.parts):
            continue
        try:
            loc += sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    if crates <= 1 and loc < 2000:
        size = "small"
    elif crates <= 20 and loc < 50000:
        size = "mid"
    else:
        size = "large"
    return {"size": size, "crates": crates, "loc": loc}


def render(archive):
    lines = [
        "## MAP-Elites grid",
        "",
        "Canonical archive: [`bench/map_elites.json`](../bench/map_elites.json).",
        "Schema: [`bench/map_elites.schema.json`](../bench/map_elites.schema.json).",
        "Merge shards from `bench/archive/<sample>.json` with "
        "`nanocompile map-elites merge` or `python3 tools/map_elites.py merge`.",
        "",
        "Axes: size (`small` / `mid` / `large`) × edit (`cold` / `noop` / `body` / `sig_dep`).",
        "Fitness is median loop wall time in ms (lower is better). Disk is recorded, not an axis.",
        "",
        "| Size \\ Edit | cold | noop | body | sig_dep |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    cells = archive.get("cells") or {}
    for size in SIZES:
        row = [size]
        for edit in EDITS:
            elite = cells.get("%s|%s" % (size, edit))
            if not elite:
                row.append("—")
                continue
            row.append("%.1f ms (%s, %s)" % (
                elite["fitness_ms"], elite.get("sample", "?"),
                (elite.get("genome") or {}).get("loop", "?")))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("### Elites")
    lines.append("")
    if not cells:
        lines.append("No cells occupied yet.")
        lines.append("")
    else:
        lines.append("| Cell | Sample | Fitness ms | Spread | Disk | Loop | Wrapper | Linker | Backend |")
        lines.append("| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |")
        for key in ("%s|%s" % (s, e) for s in SIZES for e in EDITS):
            elite = cells.get(key)
            if not elite:
                continue
            genome = elite.get("genome") or {}
            lines.append("| %s | %s | %.1f | %s | %s | %s | %s | %s | %s |" % (
                key, elite.get("sample", ""),
                elite["fitness_ms"],
                "%.1f" % elite["spread_ms"] if elite.get("spread_ms") is not None else "—",
                elite.get("disk_bytes") if elite.get("disk_bytes") is not None else "—",
                genome.get("loop"),
                "yes" if genome.get("wrapper") else "no",
                genome.get("linker"),
                genome.get("dev_backend"),
            ))
        lines.append("")
    matrix = (archive.get("generalization") or {}).get("matrix") or []
    lines.append("### Generalization")
    lines.append("")
    if not matrix:
        lines.append("No held-out evaluations yet.")
        lines.append("")
    else:
        lines.append("| Trained | Cell | Tested | Fitness ms | vs local elite | Correct |")
        lines.append("| --- | --- | --- | ---: | ---: | --- |")
        for row in matrix:
            delta = row.get("delta_vs_local_elite_pct")
            lines.append("| %s | %s | %s | %.1f | %s | %s |" % (
                row.get("trained_on"), row.get("genome_from"), row.get("tested_on"),
                row.get("fitness_ms") or 0,
                "%.1f%%" % delta if delta is not None else "—",
                "yes" if row.get("correctness_ok") else "no",
            ))
        lines.append("")
    promoted = archive.get("promoted") or {}
    lines.append("### Promoted defaults")
    lines.append("")
    defaults = promoted.get("defaults")
    if defaults and defaults.get("genome"):
        lines.append("Promoted genome: `%s`" % json.dumps(defaults["genome"], sort_keys=True))
        lines.append("")
        if defaults.get("reason"):
            lines.append(defaults["reason"])
            lines.append("")
    else:
        lines.append("No genome has been promoted to nanocompile defaults yet.")
        lines.append("")
    specific = promoted.get("sample_specific") or []
    if specific:
        lines.append("Sample-specific elites:")
        lines.append("")
        for row in specific:
            lines.append("- `%s`: %s" % (row.get("sample"), row.get("reason", "")))
        lines.append("")
    return "\n".join(lines) + "\n"


GRID_MARKERS = ("<!-- MAP_ELITES_GRID_BEGIN -->", "<!-- MAP_ELITES_GRID_END -->")


def write_render(path: Path, archive):
    body = GRID_MARKERS[0] + "\n\n" + render(archive) + GRID_MARKERS[1] + "\n"
    if path.suffix == ".md" and path.is_file():
        text = path.read_text(encoding="utf-8")
        start = text.find(GRID_MARKERS[0])
        end = text.find(GRID_MARKERS[1])
        if start >= 0 and end >= start:
            end += len(GRID_MARKERS[1])
            # Keep a trailing newline after the block if present.
            path.write_text(text[:start] + body.rstrip() + text[end:], encoding="utf-8")
            return
        path.write_text(text.rstrip() + "\n\n" + body, encoding="utf-8")
        return
    dump(path, {"markdown": render(archive)}) if path.suffix == ".json" else path.write_text(body, encoding="utf-8")


def promote(archive):
    """Promote a genome that wins held-out cells; mark sample-specific ones."""
    cells = archive.get("cells") or {}
    matrix = (archive.get("generalization") or {}).get("matrix") or []
    if not cells:
        return archive
    # Score each occupied elite by mean held-out fitness (and in-sample as fallback).
    scores = {}
    for key, elite in cells.items():
        held = [row["fitness_ms"] for row in matrix
                if row.get("genome_from") == key and row.get("correctness_ok")
                and row.get("fitness_ms") is not None]
        scores[key] = {
            "elite": elite,
            "held_out": held,
            "mean": (sum(held) / len(held)) if held else elite["fitness_ms"],
            "held_n": len(held),
        }
    # A default candidate must have at least one held-out pass, or be the only sample.
    samples = {elite.get("sample") for elite in cells.values()}
    ranked = sorted(scores.values(), key=lambda row: (row["mean"], -row["held_n"]))
    defaults = None
    specific = []
    if ranked:
        best = ranked[0]
        if best["held_n"] > 0 or len(samples) <= 1:
            defaults = {
                "genome": best["elite"].get("genome"),
                "from_cell": best["elite"].get("cell"),
                "trained_on": best["elite"].get("sample"),
                "reason": "lowest mean held-out (or in-sample) fitness among correctness-passing elites",
                "mean_ms": best["mean"],
                "held_out_n": best["held_n"],
            }
    for key, row in scores.items():
        elite = row["elite"]
        if defaults and elite.get("genome") == defaults.get("genome"):
            continue
        if row["held_n"] == 0 and len(samples) > 1:
            specific.append({
                "sample": elite.get("sample"),
                "cell": key,
                "genome": elite.get("genome"),
                "reason": "no held-out win; treat as sample-specific",
            })
    archive["promoted"] = {"defaults": defaults, "sample_specific": specific}
    if defaults:
        note(archive, "promote", {
            "cell": defaults.get("from_cell"),
            "sample": defaults.get("trained_on"),
            "fitness_ms": defaults.get("mean_ms"),
            "genome": defaults.get("genome"),
        }, defaults["reason"])
    return archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("file", nargs="?", default=str(CANONICAL))
    merge = sub.add_parser("merge")
    merge.add_argument("--into", default=str(CANONICAL))
    merge.add_argument("shards", nargs="*")
    render_cmd = sub.add_parser("render")
    render_cmd.add_argument("--into", default=str(REPO / "docs" / "rust-iteration-bench.md"))
    render_cmd.add_argument("--from", dest="source", default=str(CANONICAL))
    classify_cmd = sub.add_parser("classify")
    classify_cmd.add_argument("project")
    promote_cmd = sub.add_parser("promote")
    promote_cmd.add_argument("--into", default=str(CANONICAL))
    args = parser.parse_args(argv)
    if args.action == "validate":
        path = Path(args.file)
        kind = check_archive(load(path), str(path))
        print("PASS: %s (%s)" % (path, kind))
        return 0
    if args.action == "merge":
        shards = [Path(p) for p in args.shards]
        if not shards:
            shards = sorted((REPO / "bench" / "archive").glob("*.json"))
            shards = [p for p in shards if p.name != "README.md"]
        archive = merge_files(Path(args.into), shards)
        print("merged %d shard(s) into %s (%d cells)" % (
            len(shards), args.into, len(archive.get("cells") or {})))
        return 0
    if args.action == "render":
        archive = load(Path(args.source))
        check_archive(archive, args.source)
        write_render(Path(args.into), archive)
        print("rendered grid into %s" % args.into)
        return 0
    if args.action == "classify":
        print(json.dumps(classify(Path(args.project).resolve()), indent=2))
        return 0
    archive = load(Path(args.into))
    check_archive(archive, args.into)
    dump(Path(args.into), promote(archive))
    print("updated promoted defaults in %s" % args.into)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
