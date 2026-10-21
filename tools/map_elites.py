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
LOOPS = ("check", "graph", "test", "build")
PACKAGE_SCOPES = ("workspace", "touched")
FITNESS_METHODS = ("official_first_rebuild", "restore_rebuild_mean_of_medians")
CACHE_STATES = ("empty", "warm_compiler_cache")
SAMPLE_CLASSES = ("fixture", "real")
ACTIONS = ("seed", "replace", "reject", "held_out", "promote", "stop")
CHARLIE = "https://x.com/charliermarsh/status/2112711387285758250"
FORBIDDEN = ("cranelift", "codegen-backend", "cg_clif", "cargo-clif", "rustd", "lust", "relax")
# Tiny harness trees. Real samples (pinned crates, ripgrep, tokio) outvote these.
FIXTURE_PREFIXES = ("rust-loop",)

EMPTY = {
    "schema_version": SCHEMA,
    "kind": KIND,
    "attribution": CHARLIE,
    "axes": {"size": list(SIZES), "edit": list(EDITS)},
    "size_rules": {
        "small": "Rust LOC < 2000",
        "mid": "Rust LOC >= 2000 and < 50000 and workspace crates <= 20",
        "large": "otherwise",
        "sample_class": "fixture = rust-loop* harness trees; real = pinned crates and public mid/large samples",
        "fitness_method": "official_first_rebuild (rust_loop_bench) vs restore_rebuild_mean_of_medians (PR #11). Do not compare fitness_ms across methods.",
        "cache_state": "empty = cleared target and compiler cache; warm_compiler_cache = sccache/nanocompile retained across emptied target/",
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
        ("package_scope", PACKAGE_SCOPES),
    ):
        if key in genome and genome[key] is not None and genome[key] not in allowed:
            fail("genome.%s must be one of %s" % (key, ", ".join(allowed)))
    if genome.get("wrapper") and genome.get("sccache"):
        fail("genome cannot stack nanocompile wrapper with sccache")
    if genome.get("loop") == "test" and genome.get("dev_backend") == "cranelift":
        fail("genome.loop=test cannot use cranelift; validate is LLVM rustc")
    units = genome.get("codegen_units")
    if units is not None and (not isinstance(units, int) or units < 1 or units > 256):
        fail("genome.codegen_units must be null or 1..256")
    return True


def package_scope(genome):
    scope = (genome or {}).get("package_scope")
    if scope in (None, "", "workspace"):
        return "workspace"
    return scope


def is_fixture_sample(sample):
    name = sample or ""
    if name.startswith("midsize") or name.startswith("pinned-"):
        return False
    return name.startswith(FIXTURE_PREFIXES)


def is_held_out(row):
    if bool(row.get("held_out")):
        return True
    sample = str(row.get("sample") or "")
    # Cross-tests use either the --held-out suffix or "<tested>-from-<trained>".
    return "-held-out" in sample or "-from-" in sample


def correctness_ok(row):
    correctness = row.get("correctness")
    if not isinstance(correctness, dict):
        return False
    if not (
        correctness.get("ok")
        and correctness.get("agree_on_broken")
        and correctness.get("validate_is_final")
    ):
        return False
    genome = row.get("genome") or {}
    if package_scope(genome) == "touched" and row.get("edit") == "sig_dep":
        # cargo check -p <hub> does not compile dependents. Occupy sig_dep
        # only when a downstream broken-edit test exists.
        return bool(correctness.get("dependents_agree_on_broken"))
    return True


def correctness_reject_reason(row):
    correctness = row.get("correctness") or {}
    genome = row.get("genome") or {}
    if package_scope(genome) == "touched" and row.get("edit") == "sig_dep":
        if not correctness.get("dependents_agree_on_broken"):
            return (
                "package_scope=touched is cargo check -p hub; it skips dependents. "
                "Fail the sig_dep gate unless correctness.dependents_agree_on_broken "
                "or reframe as a gene with a mandatory workspace check before validate"
            )
    return "correctness gate failed"


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
    if row.get("fitness_method") not in (None, *FITNESS_METHODS):
        fail("%s: unknown fitness_method" % where)
    if row.get("cache_state") not in (None, *CACHE_STATES):
        fail("%s: unknown cache_state" % where)
    if row.get("sample_class") not in (None, *SAMPLE_CLASSES):
        fail("%s: unknown sample_class" % where)
    return row


def annotate_row(row, shard=None):
    shard = shard or {}
    sample = row.get("sample") or shard.get("sample")
    row["sample"] = sample
    row["sample_class"] = row.get("sample_class") or (
        "fixture" if is_fixture_sample(sample) else "real"
    )
    aggregation = (shard.get("fitness") or {}).get("aggregation")
    if not row.get("fitness_method"):
        if aggregation == "mean_of_per_sample_medians" or row.get("per_sample"):
            row["fitness_method"] = "restore_rebuild_mean_of_medians"
        else:
            row["fitness_method"] = "official_first_rebuild"
    genome = row.get("genome") or {}
    if not row.get("cache_state"):
        if row.get("edit") == "cold" and (genome.get("sccache") or genome.get("wrapper")):
            spread = row.get("spread_ms")
            fitness = row.get("fitness_ms") or 0
            # Two-sample wrapper/sccache colds with a huge spread are a miss
            # plus a cache hit, not an empty-cache cold.
            if row.get("fitness_method") == "restore_rebuild_mean_of_medians" or (
                spread and fitness and spread > 0.1 * fitness
            ):
                row["cache_state"] = "warm_compiler_cache"
            else:
                row["cache_state"] = "empty"
        elif row.get("edit") == "cold":
            row["cache_state"] = "empty"
    return row


def history_fallback_rows(data):
    rows = []
    sample = data.get("sample")
    for item in data.get("history") or []:
        if item.get("action") not in ("seed", "replace"):
            continue
        if item.get("fitness_ms") is None or not item.get("genome") or not item.get("cell"):
            continue
        if item.get("reason") not in ("empty-cell", "win"):
            continue
        size, edit = item["cell"].split("|", 1)
        rows.append({
            "cell": item["cell"],
            "size": size,
            "edit": edit,
            "genome": item["genome"],
            "fitness_ms": item["fitness_ms"],
            "correctness": {
                "ok": True,
                "agree_on_broken": True,
                "validate_is_final": True,
            },
            "sample": item.get("sample") or sample,
            "timestamp": item.get("timestamp"),
            "from_history": True,
        })
    return rows


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
        if "cell" in row and row["cell"] and "|" in str(row["cell"]):
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
    if is_held_out(row):
        note(archive, "held_out", row, "held-out evaluation; does not occupy a cell")
        return "held_out"
    if not correctness_ok(row):
        note(archive, "reject", row, correctness_reject_reason(row))
        return "reject"
    cells = archive.setdefault("cells", {})
    elite = cells.get(row["cell"])
    if elite and elite.get("fitness_method") and row.get("fitness_method"):
        if elite.get("fitness_method") != row.get("fitness_method"):
            if (row.get("fitness_method") == "official_first_rebuild"
                    and elite.get("fitness_method") == "restore_rebuild_mean_of_medians"):
                occupy(archive, row, "replace", "official harness supersedes restore+mean")
                return "replace"
            note(archive, "reject", row, "incomparable fitness_method %s vs elite %s" % (
                row.get("fitness_method"), elite.get("fitness_method")))
            return "reject"
    elite_cache = (elite or {}).get("cache_state")
    row_cache = row.get("cache_state")
    if elite and elite_cache == "warm_compiler_cache" and row_cache == "empty":
        occupy(archive, row, "replace", "true-empty cold replaces warm_compiler_cache")
        return "replace"
    if elite and elite_cache == "empty" and row_cache == "warm_compiler_cache":
        note(archive, "reject", row, "warm_compiler_cache cannot replace empty-cache cold")
        return "reject"
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


def unique_matrix(rows):
    seen = set()
    out = []
    for row in rows or []:
        key = (
            row.get("trained_on"),
            row.get("genome_from"),
            row.get("tested_on"),
            row.get("cell"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def merge_files(into: Path, shards):
    archive = load(into) if into.is_file() else json.loads(json.dumps(EMPTY))
    if check_archive(archive, str(into)) != "archive":
        fail("%s is a shard; pass --into bench/map_elites.json" % into)
    for key, row in list((archive.get("cells") or {}).items()):
        archive["cells"][key] = annotate_row(row)
    for path in shards:
        data = load(path)
        kind = check_archive(data, str(path))
        if kind == "shard":
            for row in list(data.get("evaluations") or []) + history_fallback_rows(data):
                if "sample" not in row or not row.get("sample"):
                    row["sample"] = data.get("sample")
                if "commit" not in row:
                    row["commit"] = data.get("commit")
                apply_candidate(archive, annotate_row(row, data))
            extra = data.get("generalization")
            if extra:
                dest = archive.setdefault("generalization", {"samples": [], "elites_tested": [], "matrix": []})
                dest.setdefault("matrix", []).extend(extra.get("matrix") or extra.get("rows") or [])
                for name in extra.get("samples") or []:
                    if name not in dest.setdefault("samples", []):
                        dest["samples"].append(name)
                for key in extra.get("elites_tested") or []:
                    if key not in dest.setdefault("elites_tested", []):
                        dest["elites_tested"].append(key)
                dest["matrix"] = unique_matrix(dest["matrix"])
        else:
            for row in (data.get("cells") or {}).values():
                apply_candidate(archive, annotate_row(row, data))
            archive.setdefault("history", []).extend(data.get("history") or [])
            extra = data.get("generalization") or {}
            dest = archive.setdefault("generalization", {"samples": [], "elites_tested": [], "matrix": []})
            for name in extra.get("samples") or []:
                if name not in dest.setdefault("samples", []):
                    dest["samples"].append(name)
            dest.setdefault("matrix", []).extend(extra.get("matrix") or [])
            dest["matrix"] = unique_matrix(dest["matrix"])
    dest = archive.setdefault("generalization", {"samples": [], "elites_tested": [], "matrix": []})
    dest["matrix"] = unique_matrix(dest.get("matrix") or [])
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
    if loc < 2000:
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
        lines.append("| Cell | Sample | Fitness ms | Method | Cache | Loop | Wrapper | Backend |")
        lines.append("| --- | --- | ---: | --- | --- | --- | --- | --- |")
        for key in ("%s|%s" % (s, e) for s in SIZES for e in EDITS):
            elite = cells.get(key)
            if not elite:
                continue
            genome = elite.get("genome") or {}
            method = elite.get("fitness_method") or "official_first_rebuild"
            cache = elite.get("cache_state") or ("empty" if elite.get("edit") == "cold" else "—")
            lines.append("| %s | %s | %.1f | %s | %s | %s | %s | %s |" % (
                key, elite.get("sample", ""),
                elite["fitness_ms"],
                "restore+mean" if method == "restore_rebuild_mean_of_medians" else "first-rebuild",
                cache,
                genome.get("loop"),
                "yes" if genome.get("wrapper") else "no",
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
    if defaults and (defaults.get("genome") or defaults.get("iteration") or defaults.get("noop")):
        iteration = (defaults.get("iteration") or {}).get("genome") or defaults.get("genome")
        noop = (defaults.get("noop") or {}).get("genome")
        if iteration:
            lines.append("Iteration default (cold/body/sig_dep): `%s`" % json.dumps(iteration, sort_keys=True))
            lines.append("")
            lines.append((defaults.get("iteration") or {}).get("reason") or defaults.get("reason") or "")
            lines.append("")
        if noop:
            lines.append("No-op default: `%s`" % json.dumps(noop, sort_keys=True))
            lines.append("")
            lines.append((defaults.get("noop") or {}).get("reason") or "")
            lines.append("")
    else:
        lines.append("No genome has been promoted to nanocompile defaults yet.")
        lines.append("")
    specific = promoted.get("sample_specific") or []
    if specific:
        lines.append("Sample-specific elites:")
        lines.append("")
        for row in specific:
            lines.append("- `%s` `%s`: %s" % (row.get("cell"), row.get("sample"), row.get("reason", "")))
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
    """Promote genomes that win on real samples; fixtures do not drive defaults."""
    cells = archive.get("cells") or {}
    matrix = (archive.get("generalization") or {}).get("matrix") or []
    if not cells:
        return archive

    def signature(genome):
        genome = genome or {}
        return (
            genome.get("loop"),
            bool(genome.get("wrapper")),
            genome.get("linker") or "default",
            genome.get("dev_backend") or "llvm",
            genome.get("debuginfo") or "full",
            bool(genome.get("incremental")),
            bool(genome.get("sccache")),
            package_scope(genome),
        )

    def is_real(row):
        return (row.get("sample_class") or (
            "fixture" if is_fixture_sample(row.get("sample")) else "real"
        )) == "real"

    has_real = any(is_real(row) for row in cells.values())

    def weight(row):
        if has_real and not is_real(row):
            return 0
        if row.get("edit") == "cold" and row.get("cache_state") == "warm_compiler_cache":
            return 0
        return 2 if is_real(row) else 1

    def majority(rows):
        counts = {}
        for row in rows:
            w = weight(row)
            if w <= 0:
                continue
            key = signature(row.get("genome"))
            counts[key] = counts.get(key, 0) + w
        if not counts:
            return None
        return max(counts.items(), key=lambda item: item[1])[0]

    incremental = [row for row in cells.values() if row.get("edit") in ("cold", "body", "sig_dep")]
    noops = [row for row in cells.values() if row.get("edit") == "noop"]
    inc_sig = majority(incremental)
    noop_sig = majority(noops)
    def without_sample_keys(genome):
        genome = dict(genome or {})
        genome.pop("package", None)
        genome.pop("cargo_command", None)
        return genome

    inc_genome = next(
        (without_sample_keys(row.get("genome")) for row in incremental
         if signature(row.get("genome")) == inc_sig and weight(row) > 0),
        None,
    )
    noop_genome = next(
        (without_sample_keys(row.get("genome")) for row in noops
         if signature(row.get("genome")) == noop_sig and weight(row) > 0),
        None,
    )
    defaults = {
        "iteration": {
            "genome": inc_genome,
            "reason": (
                "weighted majority on real-sample cold/body/sig_dep; "
                "fixture cells do not vote when real elites exist; "
                "warm-cache sccache cold is sample-specific, not a true-cold default"
            ),
            "edits": ["cold", "body", "sig_dep"],
            "voters": "real" if has_real else "fixture",
        } if inc_genome else None,
        "noop": {
            "genome": noop_genome,
            "reason": (
                "weighted majority on real-sample noop; "
                "fixture graph elites do not set the default when a real noop exists"
            ),
            "edits": ["noop"],
            "voters": "real" if has_real else "fixture",
        } if noop_genome else None,
    }
    defaults["genome"] = inc_genome
    specific = []
    for key, elite in cells.items():
        reasons = []
        if has_real and not is_real(elite):
            reasons.append("fixture elite; real samples outvote fixtures")
        if elite.get("edit") == "cold" and elite.get("cache_state") == "warm_compiler_cache":
            reasons.append("warm compiler cache (sccache/wrapper retained), not empty-cache cold")
        if signature(elite.get("genome")) not in {inc_sig, noop_sig}:
            reasons.append("loses the weighted vote for its edit family")
        if reasons:
            specific.append({
                "sample": elite.get("sample"),
                "cell": key,
                "genome": elite.get("genome"),
                "reason": "; ".join(reasons),
                "sample_class": elite.get("sample_class"),
                "cache_state": elite.get("cache_state"),
                "fitness_method": elite.get("fitness_method"),
            })
    _ = matrix
    archive["promoted"] = {"defaults": defaults, "sample_specific": specific}
    if inc_genome:
        note(archive, "promote", {
            "cell": "iteration",
            "sample": "real" if has_real else "majority",
            "fitness_ms": None,
            "genome": inc_genome,
        }, defaults["iteration"]["reason"])
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
