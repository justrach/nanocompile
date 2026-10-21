//! MAP-Elites archive for rust-loop genomes. Canonical file: bench/map_elites.json.
//! validate / merge / render / classify / promote. A successful fast path is never the gate.
const std = @import("std");
const cache = @import("cache.zig");
const Dir = std.Io.Dir;

pub const schema: u32 = 1;
pub const kind = "nanocompile.rust-loop.map-elites";
pub const shard_kind = "nanocompile.rust-loop.map-elites.shard";
const sizes = [_][]const u8{ "small", "mid", "large" };
const edits = [_][]const u8{ "cold", "noop", "body", "sig_dep" };
const backends = [_][]const u8{ "llvm", "cranelift" };
const linkers = [_][]const u8{ "default", "mold", "lld" };
const debug_levels = [_][]const u8{ "full", "line-tables-only", "none" };
const fast_checks = [_][]const u8{ "cargo-check", "none" };
const loops = [_][]const u8{ "check", "graph", "test", "build" };
const actions = [_][]const u8{ "seed", "replace", "reject", "held_out", "promote", "stop" };

fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

fn inList(value: []const u8, allowed: []const []const u8) bool {
    for (allowed) |item| if (eq(item, value)) return true;
    return false;
}

fn fail(ctx: *cache.Context, message: []const u8) !u8 {
    try std.Io.File.stderr().writeStreamingAll(ctx.io, "map-elites: ");
    try std.Io.File.stderr().writeStreamingAll(ctx.io, message);
    try std.Io.File.stderr().writeStreamingAll(ctx.io, "\n");
    return 2;
}

fn asObject(value: std.json.Value) !std.json.ObjectMap {
    return switch (value) {
        .object => |obj| obj,
        else => error.InvalidMapElitesDocument,
    };
}

fn asArray(value: std.json.Value) !std.json.Array {
    return switch (value) {
        .array => |arr| arr,
        else => error.InvalidMapElitesDocument,
    };
}

fn asString(value: std.json.Value) ![]const u8 {
    return switch (value) {
        .string => |s| s,
        else => error.InvalidMapElitesDocument,
    };
}

fn asFloat(value: std.json.Value) !f64 {
    return switch (value) {
        .float => |x| x,
        .integer => |x| @floatFromInt(x),
        .number_string => |s| try std.fmt.parseFloat(f64, s),
        else => error.InvalidMapElitesNumber,
    };
}

fn asBool(value: std.json.Value) !bool {
    return switch (value) {
        .bool => |b| b,
        else => error.InvalidMapElitesDocument,
    };
}

fn get(obj: std.json.ObjectMap, key: []const u8) ?std.json.Value {
    return obj.get(key);
}

pub fn cellKey(size: []const u8, edit: []const u8) !void {
    if (!inList(size, &sizes) or !inList(edit, &edits)) return error.UnknownMapElitesCell;
}

pub fn splitKey(key: []const u8) !struct { size: []const u8, edit: []const u8 } {
    const bar = std.mem.indexOfScalar(u8, key, '|') orelse return error.InvalidMapElitesCell;
    const size = key[0..bar];
    const edit = key[bar + 1 ..];
    try cellKey(size, edit);
    return .{ .size = size, .edit = edit };
}

test "map-elites cell keys" {
    _ = try splitKey("small|body");
    _ = try splitKey("large|sig_dep");
    try std.testing.expectError(error.UnknownMapElitesCell, splitKey("tiny|body"));
    try std.testing.expectError(error.InvalidMapElitesCell, splitKey("nobody"));
}

fn genomeOk(genome: std.json.ObjectMap) !void {
    const pairs = [_]struct { key: []const u8, allowed: []const []const u8 }{
        .{ .key = "dev_backend", .allowed = &backends },
        .{ .key = "linker", .allowed = &linkers },
        .{ .key = "debuginfo", .allowed = &debug_levels },
        .{ .key = "fast_check", .allowed = &fast_checks },
        .{ .key = "loop", .allowed = &loops },
    };
    for (pairs) |pair| {
        if (get(genome, pair.key)) |value| {
            if (!inList(try asString(value), pair.allowed)) return error.InvalidMapElitesGenome;
        }
    }
    const wrapper = if (get(genome, "wrapper")) |v| try asBool(v) else false;
    const sccache = if (get(genome, "sccache")) |v| try asBool(v) else false;
    if (wrapper and sccache) return error.StackedWrappers;
    const loop = if (get(genome, "loop")) |v| try asString(v) else "check";
    const backend = if (get(genome, "dev_backend")) |v| try asString(v) else "llvm";
    if (eq(loop, "test") and eq(backend, "cranelift")) return error.CraneliftValidate;
    if (get(genome, "codegen_units")) |units| switch (units) {
        .null => {},
        .integer => |n| if (n < 1 or n > 256) return error.InvalidCodegenUnits,
        else => return error.InvalidCodegenUnits,
    };
}

test "map-elites genome rejects stacked wrappers and cranelift test" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const stacked = try std.json.parseFromSlice(std.json.Value, a,
        \\{"wrapper":true,"sccache":true,"dev_backend":"llvm","linker":"default","incremental":true,"debuginfo":"full","fast_check":"cargo-check","loop":"check"}
    , .{});
    try std.testing.expectError(error.StackedWrappers, genomeOk(try asObject(stacked.value)));
    const cranelift = try std.json.parseFromSlice(std.json.Value, a,
        \\{"wrapper":false,"sccache":false,"dev_backend":"cranelift","linker":"default","incremental":true,"debuginfo":"full","fast_check":"none","loop":"test"}
    , .{});
    try std.testing.expectError(error.CraneliftValidate, genomeOk(try asObject(cranelift.value)));
}

fn correctnessOk(row: std.json.ObjectMap) bool {
    const correctness = asObject(get(row, "correctness") orelse return false) catch return false;
    const ok = asBool(get(correctness, "ok") orelse return false) catch return false;
    const agree = asBool(get(correctness, "agree_on_broken") orelse return false) catch return false;
    const final = asBool(get(correctness, "validate_is_final") orelse return false) catch return false;
    return ok and agree and final;
}

fn checkEvaluation(row: std.json.ObjectMap) !void {
    const key = if (get(row, "cell")) |value| try asString(value) else blk: {
        const size = try asString(get(row, "size") orelse return error.MissingMapElitesCell);
        const edit = try asString(get(row, "edit") orelse return error.MissingMapElitesCell);
        try cellKey(size, edit);
        break :blk "";
    };
    if (key.len != 0) _ = try splitKey(key);
    try genomeOk(try asObject(get(row, "genome") orelse return error.MissingMapElitesGenome));
    const fitness = try asFloat(get(row, "fitness_ms") orelse return error.MissingFitness);
    if (fitness < 0) return error.InvalidFitness;
    if (get(row, "sample") == null) return error.MissingSample;
    if (get(row, "correctness") == null) return error.MissingCorrectness;
}

fn checkDocument(root: std.json.Value) ![]const u8 {
    const obj = try asObject(root);
    const version = get(obj, "schema_version") orelse return error.InvalidSchemaVersion;
    if ((try asFloat(version)) != 1) return error.InvalidSchemaVersion;
    const document_kind = try asString(get(obj, "kind") orelse return error.InvalidMapElitesKind);
    if (eq(document_kind, shard_kind)) {
        if (get(obj, "sample") == null) return error.MissingSample;
        const evaluations = try asArray(get(obj, "evaluations") orelse return error.MissingEvaluations);
        for (evaluations.items) |item| try checkEvaluation(try asObject(item));
        return "shard";
    }
    if (!eq(document_kind, kind)) return error.InvalidMapElitesKind;
    const axes = try asObject(get(obj, "axes") orelse return error.MissingAxes);
    const size_axis = try asArray(get(axes, "size") orelse return error.MissingAxes);
    const edit_axis = try asArray(get(axes, "edit") orelse return error.MissingAxes);
    if (size_axis.items.len != sizes.len or edit_axis.items.len != edits.len) return error.InvalidAxes;
    for (size_axis.items, sizes) |item, expected| if (!eq(try asString(item), expected)) return error.InvalidAxes;
    for (edit_axis.items, edits) |item, expected| if (!eq(try asString(item), expected)) return error.InvalidAxes;
    const cells = try asObject(get(obj, "cells") orelse return error.MissingCells);
    var it = cells.iterator();
    while (it.next()) |entry| {
        _ = try splitKey(entry.key_ptr.*);
        try checkEvaluation(try asObject(entry.value_ptr.*));
    }
    if (get(obj, "history")) |history| {
        for ((try asArray(history)).items) |item| {
            const row = try asObject(item);
            if (get(row, "action")) |action| {
                if (!inList(try asString(action), &actions)) return error.InvalidHistoryAction;
            }
            if (get(row, "cell")) |cell| {
                const key = try asString(cell);
                if (std.mem.indexOfScalar(u8, key, '|') != null) _ = try splitKey(key);
            }
        }
    }
    return "archive";
}

fn minGain(archive: std.json.ObjectMap) f64 {
    const fitness = asObject(get(archive, "fitness") orelse return 3.0) catch return 3.0;
    return asFloat(get(fitness, "min_gain_pct") orelse return 3.0) catch 3.0;
}

fn maxNonImproving(archive: std.json.ObjectMap) i64 {
    const fitness = asObject(get(archive, "fitness") orelse return 4) catch return 4;
    const value = get(fitness, "max_non_improving") orelse return 4;
    return switch (value) {
        .integer => |n| n,
        else => 4,
    };
}

fn better(candidate_ms: f64, elite_ms: ?f64, gain_pct: f64) []const u8 {
    const old = elite_ms orelse return "seed";
    if (old <= 0) return if (candidate_ms < old) "replace" else "reject";
    if ((old - candidate_ms) / old * 100.0 >= gain_pct) return "replace";
    return "reject";
}

test "map-elites replace only beyond noise" {
    try std.testing.expectEqualStrings("seed", better(10, null, 3));
    try std.testing.expectEqualStrings("replace", better(9.6, 10, 3));
    try std.testing.expectEqualStrings("reject", better(9.8, 10, 3));
}

fn readJson(ctx: *cache.Context, path: []const u8) !std.json.Value {
    const resolved = if (std.fs.path.isAbsolute(path)) path else try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, path });
    return (try std.json.parseFromSlice(std.json.Value, ctx.a, try ctx.read(resolved), .{ .allocate = .alloc_always })).value;
}

fn writeJson(ctx: *cache.Context, path: []const u8, value: std.json.Value) !void {
    const resolved = if (std.fs.path.isAbsolute(path)) path else try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, path });
    if (std.fs.path.dirname(resolved)) |dir| try Dir.cwd().createDirPath(ctx.io, dir);
    const encoded = try std.json.Stringify.valueAlloc(ctx.a, value, .{ .whitespace = .indent_2 });
    const file = try Dir.cwd().createFile(ctx.io, resolved, .{ .truncate = true });
    defer file.close(ctx.io);
    try file.writeStreamingAll(ctx.io, encoded);
    try file.writeStreamingAll(ctx.io, "\n");
}

fn emptyArchive(ctx: *cache.Context) !std.json.Value {
    const bytes =
        \\{"schema_version":1,"kind":"nanocompile.rust-loop.map-elites","axes":{"size":["small","mid","large"],"edit":["cold","noop","body","sig_dep"]},"fitness":{"metric":"median_ms","goal":"min","min_gain_pct":3.0,"max_non_improving":4},"cells":{},"history":[],"generalization":{"samples":[],"elites_tested":[],"matrix":[]},"promoted":{"defaults":null,"sample_specific":[]}}
    ;
    return (try std.json.parseFromSlice(std.json.Value, ctx.a, bytes, .{ .allocate = .alloc_always })).value;
}

fn appendHistory(ctx: *cache.Context, archive: *std.json.ObjectMap, action: []const u8, row: std.json.ObjectMap, reason: []const u8) !void {
    var entry: std.json.ObjectMap = .empty;
    if (get(row, "timestamp")) |v| try entry.put(ctx.a, "timestamp", v);
    if (get(row, "sample")) |v| try entry.put(ctx.a, "sample", v);
    if (get(row, "cell")) |v| try entry.put(ctx.a, "cell", v);
    try entry.put(ctx.a, "action", .{ .string = action });
    if (get(row, "fitness_ms")) |v| try entry.put(ctx.a, "fitness_ms", v);
    if (get(row, "genome")) |v| try entry.put(ctx.a, "genome", v);
    try entry.put(ctx.a, "reason", .{ .string = reason });
    var history = if (get(archive.*, "history")) |value| try asArray(value) else std.json.Array.init(ctx.a);
    try history.append(.{ .object = entry });
    try archive.put(ctx.a, "history", .{ .array = history });
}

fn applyCandidate(ctx: *cache.Context, archive: *std.json.ObjectMap, row: std.json.ObjectMap) ![]const u8 {
    if (!correctnessOk(row)) {
        try appendHistory(ctx, archive, "reject", row, "correctness gate failed");
        return "reject";
    }
    var cells = try asObject(get(archive.*, "cells") orelse return error.MissingCells);
    const key = try asString(get(row, "cell") orelse return error.MissingMapElitesCell);
    _ = try splitKey(key);
    const fitness = try asFloat(get(row, "fitness_ms") orelse return error.MissingFitness);
    const elite_ms: ?f64 = if (get(cells, key)) |elite|
        asFloat((try asObject(elite)).get("fitness_ms") orelse return error.MissingFitness) catch null
    else
        null;
    const action = better(fitness, elite_ms, minGain(archive.*));
    if (eq(action, "seed") or eq(action, "replace")) {
        try cells.put(ctx.a, key, .{ .object = row });
        try archive.put(ctx.a, "cells", .{ .object = cells });
        const reason = if (eq(action, "seed"))
            try std.fmt.allocPrint(ctx.a, "median {d:.3} ms", .{fitness})
        else
            try std.fmt.allocPrint(ctx.a, "{d:.1}% faster than {d:.3} ms", .{ (elite_ms.? - fitness) / elite_ms.? * 100.0, elite_ms.? });
        try appendHistory(ctx, archive, action, row, reason);
        return action;
    }
    if (get(cells, key)) |elite_value| {
        var elite = try asObject(elite_value);
        const prev = if (get(elite, "non_improving")) |v| switch (v) {
            .integer => |n| n,
            else => 0,
        } else 0;
        const next = prev + 1;
        try elite.put(ctx.a, "non_improving", .{ .integer = next });
        const evals = if (get(elite, "n_evals")) |v| switch (v) {
            .integer => |n| n,
            else => 1,
        } else 1;
        try elite.put(ctx.a, "n_evals", .{ .integer = evals + 1 });
        if (next >= maxNonImproving(archive.*)) {
            try elite.put(ctx.a, "stopped", .{ .bool = true });
            try appendHistory(ctx, archive, "stop", elite, try std.fmt.allocPrint(ctx.a, "{d} non-improving tries", .{next}));
        } else {
            try appendHistory(ctx, archive, "reject", row, "gain below threshold");
        }
        try cells.put(ctx.a, key, .{ .object = elite });
        try archive.put(ctx.a, "cells", .{ .object = cells });
    }
    return "reject";
}

fn mergeOne(ctx: *cache.Context, archive: *std.json.ObjectMap, incoming: std.json.Value) !void {
    const obj = try asObject(incoming);
    const document_kind = try asString(get(obj, "kind") orelse return error.InvalidMapElitesKind);
    if (eq(document_kind, shard_kind)) {
        const evaluations = try asArray(get(obj, "evaluations") orelse return error.MissingEvaluations);
        for (evaluations.items) |item| {
            var row = try asObject(item);
            if (get(row, "sample") == null) if (get(obj, "sample")) |sample| try row.put(ctx.a, "sample", sample);
            if (get(row, "commit") == null) if (get(obj, "commit")) |commit| try row.put(ctx.a, "commit", commit);
            _ = try applyCandidate(ctx, archive, row);
        }
        return;
    }
    const cells = try asObject(get(obj, "cells") orelse return error.MissingCells);
    var it = cells.iterator();
    while (it.next()) |entry| _ = try applyCandidate(ctx, archive, try asObject(entry.value_ptr.*));
}

fn defaultPath(ctx: *cache.Context, relative: []const u8) ![]const u8 {
    return std.fs.path.resolve(ctx.a, &.{ ctx.cwd, relative });
}

fn parseArgs(ctx: *cache.Context, args: []const [:0]const u8) !struct { action: []const u8, into: ?[]const u8, files: []const []const u8 } {
    if (args.len == 0) return .{ .action = "validate", .into = null, .files = &.{} };
    var into: ?[]const u8 = null;
    var i: usize = 1;
    while (i < args.len) : (i += 1) {
        if (eq(args[i], "--into") and i + 1 < args.len) {
            into = args[i + 1];
            i += 1;
        } else break;
    }
    const rest = args[i..];
    const files = try ctx.a.alloc([]const u8, rest.len);
    for (rest, 0..) |part, index| files[index] = part;
    return .{ .action = args[0], .into = into, .files = files };
}

fn listDirJson(ctx: *cache.Context, directory: []const u8) ![]const []const u8 {
    var names: std.ArrayList([]const u8) = .empty;
    var dir = Dir.cwd().openDir(ctx.io, directory, .{ .iterate = true }) catch return names.items;
    defer dir.close(ctx.io);
    var walk = try dir.walk(ctx.a);
    defer walk.deinit();
    while (try walk.next(ctx.io)) |entry| {
        if (entry.kind == .file and std.mem.endsWith(u8, entry.basename, ".json"))
            try names.append(ctx.a, try std.fs.path.join(ctx.a, &.{ directory, entry.path }));
    }
    return names.items;
}

fn classifyProject(ctx: *cache.Context, root: []const u8) !struct { size: []const u8, crates: usize, loc: usize } {
    const cargo = try std.fs.path.join(ctx.a, &.{ root, "Cargo.toml" });
    _ = Dir.cwd().statFile(ctx.io, cargo, .{}) catch return error.MissingCargoToml;
    const text = try ctx.read(cargo);
    var crates: usize = 1;
    if (std.mem.indexOf(u8, text, "[workspace]") != null) {
        var count: usize = 0;
        var lines = std.mem.splitScalar(u8, text, '\n');
        var collecting = false;
        while (lines.next()) |raw| {
            const hash = std.mem.indexOfScalar(u8, raw, '#') orelse raw.len;
            const line = std.mem.trim(u8, raw[0..hash], " \t\r");
            if (line.len == 0) continue;
            if (line[0] == '[' and line[line.len - 1] == ']') {
                collecting = eq(std.mem.trim(u8, line[1 .. line.len - 1], " "), "workspace");
                continue;
            }
            if (!collecting) continue;
            var rest = line;
            if (std.mem.startsWith(u8, line, "members"))
                rest = if (std.mem.indexOfScalar(u8, line, '=')) |at| line[at + 1 ..] else "";
            var parts = std.mem.splitScalar(u8, rest, ',');
            while (parts.next()) |part| {
                const item = std.mem.trim(u8, part, " \t[]\"'");
                if (item.len == 0) continue;
                const folder = try std.fs.path.join(ctx.a, &.{ root, item });
                if (Dir.cwd().statFile(ctx.io, folder, .{})) |_| {
                    count += 1;
                } else |_| {}
            }
        }
        if (count > 0) crates = count;
    }
    var loc: usize = 0;
    var dir = try Dir.cwd().openDir(ctx.io, root, .{ .iterate = true });
    defer dir.close(ctx.io);
    var walk = try dir.walk(ctx.a);
    defer walk.deinit();
    while (try walk.next(ctx.io)) |entry| {
        if (entry.kind != .file or !std.mem.endsWith(u8, entry.basename, ".rs")) continue;
        if (std.mem.indexOf(u8, entry.path, "target") != null) continue;
        const bytes = ctx.read(try std.fs.path.join(ctx.a, &.{ root, entry.path })) catch continue;
        loc += std.mem.count(u8, bytes, "\n");
        if (bytes.len > 0 and bytes[bytes.len - 1] != '\n') loc += 1;
    }
    const size: []const u8 = if (loc < 2000) "small" else if (crates <= 20 and loc < 50000) "mid" else "large";
    return .{ .size = size, .crates = crates, .loc = loc };
}

fn renderGrid(ctx: *cache.Context, archive: std.json.ObjectMap) ![]const u8 {
    var out: std.ArrayList(u8) = .empty;
    try out.appendSlice(ctx.a, "## MAP-Elites grid\n\n");
    try out.appendSlice(ctx.a, "Canonical archive: [`bench/map_elites.json`](../bench/map_elites.json).\n\n");
    try out.appendSlice(ctx.a, "| Size \\ Edit | cold | noop | body | sig_dep |\n| --- | ---: | ---: | ---: | ---: |\n");
    const cells = try asObject(get(archive, "cells") orelse return error.MissingCells);
    for (sizes) |size| {
        try out.appendSlice(ctx.a, try std.fmt.allocPrint(ctx.a, "| {s}", .{size}));
        for (edits) |edit| {
            const key = try std.fmt.allocPrint(ctx.a, "{s}|{s}", .{ size, edit });
            if (get(cells, key)) |elite_value| {
                const elite = try asObject(elite_value);
                const ms = try asFloat(get(elite, "fitness_ms") orelse return error.MissingFitness);
                const sample = if (get(elite, "sample")) |v| try asString(v) else "?";
                try out.appendSlice(ctx.a, try std.fmt.allocPrint(ctx.a, " | {d:.1} ms ({s})", .{ ms, sample }));
            } else try out.appendSlice(ctx.a, " | —");
        }
        try out.appendSlice(ctx.a, " |\n");
    }
    try out.appendSlice(ctx.a, "\n");
    return out.items;
}

pub fn execute(ctx: *cache.Context, args: []const [:0]const u8) !u8 {
    const parsed = try parseArgs(ctx, args);
    if (eq(parsed.action, "validate")) {
        const path = if (parsed.files.len > 0) parsed.files[0] else "bench/map_elites.json";
        const document = readJson(ctx, path) catch |err| return fail(ctx, @errorName(err));
        const document_kind = checkDocument(document) catch |err| return fail(ctx, @errorName(err));
        try ctx.out(try std.fmt.allocPrint(ctx.a, "PASS: {s} ({s})\n", .{ path, document_kind }));
        return 0;
    }
    if (eq(parsed.action, "merge")) {
        const into = parsed.into orelse "bench/map_elites.json";
        const archive_value = readJson(ctx, into) catch try emptyArchive(ctx);
        const archive_kind = checkDocument(archive_value) catch |err| return fail(ctx, @errorName(err));
        if (!eq(archive_kind, "archive")) return fail(ctx, "--into must be an archive");
        var archive = try asObject(archive_value);
        var files = parsed.files;
        if (files.len == 0) files = try listDirJson(ctx, try defaultPath(ctx, "bench/archive"));
        for (files) |path| {
            const incoming = readJson(ctx, path) catch |err| return fail(ctx, @errorName(err));
            _ = checkDocument(incoming) catch |err| return fail(ctx, @errorName(err));
            mergeOne(ctx, &archive, incoming) catch |err| return fail(ctx, @errorName(err));
        }
        try writeJson(ctx, into, .{ .object = archive });
        const cells = try asObject(get(archive, "cells") orelse return error.MissingCells);
        try ctx.out(try std.fmt.allocPrint(ctx.a, "merged {d} shard(s) into {s} ({d} cells)\n", .{ files.len, into, cells.count() }));
        return 0;
    }
    if (eq(parsed.action, "render")) {
        const path = parsed.into orelse "docs/rust-iteration-bench.md";
        const source = if (parsed.files.len > 0) parsed.files[0] else "bench/map_elites.json";
        const document = readJson(ctx, source) catch |err| return fail(ctx, @errorName(err));
        _ = checkDocument(document) catch |err| return fail(ctx, @errorName(err));
        const markdown = try renderGrid(ctx, try asObject(document));
        const resolved = if (std.fs.path.isAbsolute(path)) path else try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, path });
        const begin = "<!-- MAP_ELITES_GRID_BEGIN -->";
        const end = "<!-- MAP_ELITES_GRID_END -->";
        const existing = ctx.read(resolved) catch "";
        const payload = try std.fmt.allocPrint(ctx.a, "{s}\n\n{s}{s}", .{ begin, markdown, end });
        const out = if (std.mem.indexOf(u8, existing, begin)) |start|
            if (std.mem.indexOf(u8, existing[start..], end)) |rel|
                try std.fmt.allocPrint(ctx.a, "{s}{s}{s}", .{ existing[0..start], payload, existing[start + rel + end.len ..] })
            else
                payload
        else if (existing.len == 0)
            try std.fmt.allocPrint(ctx.a, "{s}\n", .{payload})
        else
            try std.fmt.allocPrint(ctx.a, "{s}\n\n{s}\n", .{ existing, payload });
        if (std.fs.path.dirname(resolved)) |dir| try Dir.cwd().createDirPath(ctx.io, dir);
        const file = try Dir.cwd().createFile(ctx.io, resolved, .{ .truncate = true });
        defer file.close(ctx.io);
        try file.writeStreamingAll(ctx.io, out);
        if (out.len == 0 or out[out.len - 1] != '\n') try file.writeStreamingAll(ctx.io, "\n");
        try ctx.out(try std.fmt.allocPrint(ctx.a, "rendered grid into {s}\n", .{path}));
        return 0;
    }
    if (eq(parsed.action, "classify")) {
        const path = if (parsed.files.len > 0) parsed.files[0] else ctx.cwd;
        const root = if (std.fs.path.isAbsolute(path)) path else try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, path });
        const info = classifyProject(ctx, root) catch |err| return fail(ctx, @errorName(err));
        try ctx.out(try std.json.Stringify.valueAlloc(ctx.a, .{ .size = info.size, .crates = info.crates, .loc = info.loc }, .{ .whitespace = .indent_2 }));
        try ctx.out("\n");
        return 0;
    }
    return error.UnknownMapElitesAction;
}
