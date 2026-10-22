//! Shared-store TypeScript type-check cache for agent worktrees.
//!
//! `nanocompile tsc|tsgo|tsrs|bun` content-addresses a project (checker
//! version + tsconfig + source hashes) with `$NANO_ROOT` path rewriting so a
//! sibling worktree restores another checkout's zero-error result. Injected
//! type errors change the key and always run the real checker.
const std = @import("std");
const cache = @import("cache.zig");
const identity = @import("identity.zig");
const compiler_stream = @import("compiler_stream.zig");
const Dir = std.Io.Dir;

pub const Checker = enum { tsc, tsgo, tsrs, bun };

const skip_dirs = [_][]const u8{ "node_modules", ".git", ".next", "dist", "out", "coverage", ".turbo", ".open-next", "zig-out", "target", ".cache", ".nanocompile", ".cargo" };
const source_ext = [_][]const u8{ ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx" };

fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

fn exitCode(term: std.process.Child.Term) u8 {
    return switch (term) {
        .exited => |code| code,
        .signal => |signal| @intCast(@min(255, 128 + @as(u32, @backingInt(signal)))),
        else => 1,
    };
}

fn replaceAll(a: std.mem.Allocator, bytes: []const u8, old: []const u8, new: []const u8) ![]u8 {
    if (old.len == 0) return a.dupe(u8, bytes);
    var out: std.ArrayList(u8) = .empty;
    var cursor: usize = 0;
    while (std.mem.indexOfPos(u8, bytes, cursor, old)) |at| {
        try out.appendSlice(a, bytes[cursor..at]);
        try out.appendSlice(a, new);
        cursor = at + old.len;
    }
    try out.appendSlice(a, bytes[cursor..]);
    return out.items;
}

fn isSourceName(name: []const u8) bool {
    for (source_ext) |ext| if (std.mem.endsWith(u8, name, ext)) return true;
    return eq(name, "tsconfig.json") or eq(name, "package.json") or
        std.mem.startsWith(u8, name, "tsconfig.") and std.mem.endsWith(u8, name, ".json");
}

fn skippedComponent(name: []const u8) bool {
    for (skip_dirs) |skip| if (eq(name, skip)) return true;
    return false;
}

fn skippedPath(rel: []const u8) bool {
    var it = std.mem.splitScalar(u8, rel, '/');
    while (it.next()) |part| if (skippedComponent(part)) return true;
    var win = std.mem.splitScalar(u8, rel, '\\');
    while (win.next()) |part| if (skippedComponent(part)) return true;
    return false;
}

const Source = struct { rel: []const u8, path: []const u8, hash: []const u8 };

fn lessSource(_: void, a: Source, b: Source) bool {
    return std.mem.order(u8, a.rel, b.rel) == .lt;
}

pub fn collectSources(ctx: *cache.Context, root: []const u8) ![]const Source {
    var dir = Dir.cwd().openDir(ctx.io, root, .{ .iterate = true }) catch return &.{};
    defer dir.close(ctx.io);
    var walk = try dir.walk(ctx.a);
    defer walk.deinit();
    var out: std.ArrayList(Source) = .empty;
    while (try walk.next(ctx.io)) |item| {
        if (item.kind != .file) continue;
        if (skippedPath(item.path)) continue;
        if (std.mem.endsWith(u8, item.basename, ".tsbuildinfo")) continue;
        if (!isSourceName(item.basename)) continue;
        const abs = try std.fs.path.join(ctx.a, &.{ root, item.path });
        const rel = try normalizeRel(ctx.a, item.path);
        const digest = ctx.digest(abs) catch continue;
        try out.append(ctx.a, .{ .rel = rel, .path = abs, .hash = digest });
    }
    std.mem.sort(Source, out.items, {}, lessSource);
    return out.items;
}

fn normalizeRel(a: std.mem.Allocator, path: []const u8) ![]const u8 {
    const copy = try a.dupe(u8, path);
    for (copy) |*ch| {
        if (ch.* == '\\') ch.* = '/';
    }
    return copy;
}

fn optionValue(args: []const []const u8, name: []const u8) ?[]const u8 {
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (eq(args[i], name) and i + 1 < args.len) return args[i + 1];
        if (args[i].len > name.len + 1 and std.mem.startsWith(u8, args[i], name) and args[i][name.len] == '=')
            return args[i][name.len + 1 ..];
    }
    return null;
}

fn hasFlag(args: []const []const u8, name: []const u8) bool {
    for (args) |arg| {
        if (eq(arg, name)) return true;
        if (arg.len > name.len and std.mem.startsWith(u8, arg, name) and arg[name.len] == '=') return true;
    }
    return false;
}

const Project = struct {
    root: []const u8,
    tsconfig: []const u8,
    buildinfo: ?[]const u8,
};

fn discoverProject(ctx: *cache.Context, args: []const []const u8) !Project {
    const specified = optionValue(args, "--project") orelse optionValue(args, "-p");
    const tsconfig = if (specified) |p|
        try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, p })
    else
        try findTsconfig(ctx, ctx.cwd);
    const root = std.fs.path.dirname(tsconfig) orelse ctx.cwd;
    const info_flag = optionValue(args, "--tsBuildInfoFile");
    const incremental = hasFlag(args, "--incremental") or eq(ctx.env.get("NANOCOMPILE_TS_INCREMENTAL") orelse "1", "1");
    const buildinfo = if (!incremental) null else if (info_flag) |p|
        try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, p })
    else
        try std.fmt.allocPrint(ctx.a, "{s}.tsbuildinfo", .{tsconfig});
    return .{ .root = root, .tsconfig = tsconfig, .buildinfo = buildinfo };
}

fn findTsconfig(ctx: *cache.Context, start: []const u8) ![]const u8 {
    var dir = start;
    while (true) {
        const candidate = try std.fs.path.join(ctx.a, &.{ dir, "tsconfig.json" });
        if (Dir.cwd().statFile(ctx.io, candidate, .{})) |_| return candidate else |_| {}
        const parent = std.fs.path.dirname(dir) orelse break;
        if (eq(parent, dir)) break;
        dir = parent;
    }
    return error.NoTsconfig;
}

fn resolveChecker(ctx: *cache.Context, checker: Checker) ![]const u8 {
    const env_name = switch (checker) {
        .tsc => "NANOCOMPILE_TSC",
        .tsgo => "NANOCOMPILE_TSGO",
        .tsrs => "NANOCOMPILE_TSRS",
        .bun => "NANOCOMPILE_BUN",
    };
    if (ctx.env.get(env_name)) |explicit| return explicit;
    const local = try std.fs.path.join(ctx.a, &.{ ctx.cwd, "node_modules", ".bin", switch (checker) {
        .tsc => "tsc",
        .tsgo => "tsgo",
        .tsrs => "tsrs",
        .bun => "bun",
    } });
    if (Dir.cwd().statFile(ctx.io, local, .{})) |_| return local else |_| {}
    return switch (checker) {
        .tsc => "tsc",
        .tsgo => "tsgo",
        .tsrs => "tsrs",
        .bun => "bun",
    };
}

fn checkerIdentity(ctx: *cache.Context, exe: []const u8) []const u8 {
    return identity.fingerprint(ctx, false, exe) catch exe;
}

fn resultKey(ctx: *cache.Context, checker: Checker, exe: []const u8, args: []const []const u8, project: Project, sources: []const Source) ![]const u8 {
    var hash = cache.Hash.init(.{});
    cache.field(&hash, "nanocompile-typescript-v1");
    cache.field(&hash, @tagName(checker));
    cache.field(&hash, checkerIdentity(ctx, exe));
    cache.field(&hash, try ctx.logicalPath(project.tsconfig));
    cache.field(&hash, try ctx.logicalPath(ctx.cwd));
    for (args) |arg| cache.field(&hash, try ctx.logicalPath(arg));
    for (sources) |src| {
        cache.field(&hash, src.rel);
        cache.field(&hash, src.hash);
    }
    return cache.finish(ctx.a, &hash);
}

fn seedKey(ctx: *cache.Context, checker: Checker, exe: []const u8, args: []const []const u8, project: Project) ![]const u8 {
    var hash = cache.Hash.init(.{});
    cache.field(&hash, "nanocompile-typescript-seed-v1");
    cache.field(&hash, @tagName(checker));
    cache.field(&hash, checkerIdentity(ctx, exe));
    cache.field(&hash, try ctx.logicalPath(project.tsconfig));
    for (args) |arg| cache.field(&hash, try ctx.logicalPath(arg));
    return cache.finish(ctx.a, &hash);
}

fn remapText(ctx: *cache.Context, text: []const u8, to_logical: bool) ![]u8 {
    var current = text;
    for (ctx.rewrites) |rewrite| {
        if (to_logical) {
            if (rewrite.path.len == 0) continue;
            current = try replaceAll(ctx.a, current, rewrite.path, rewrite.token);
        } else {
            if (rewrite.token.len == 0) continue;
            current = try replaceAll(ctx.a, current, rewrite.token, rewrite.path);
        }
    }
    return try ctx.a.dupe(u8, current);
}

fn restoreSeedBuildinfo(ctx: *cache.Context, checker: Checker, exe: []const u8, args: []const []const u8, project: Project) !void {
    if (project.buildinfo) |info| {
        if (eq(ctx.env.get("NANOCOMPILE_TS_SEED") orelse "1", "1")) {
            const seed = try seedKey(ctx, checker, exe, args, project);
            const names = [_][]const u8{"tsbuildinfo"};
            const dests = [_][]const u8{info};
            if (cache.restoreStaged(ctx, seed, &names, &dests) catch null != null)
                remapFile(ctx, info, false);
        }
    }
}

fn storeSeedBuildinfo(ctx: *cache.Context, checker: Checker, exe: []const u8, args: []const []const u8, project: Project) !void {
    if (project.buildinfo) |info| {
        if (eq(ctx.env.get("NANOCOMPILE_TS_SEED") orelse "1", "1")) {
            if (Dir.cwd().statFile(ctx.io, info, .{})) |_| {
                remapFile(ctx, info, true);
                const seed = try seedKey(ctx, checker, exe, args, project);
                const names = [_][]const u8{"tsbuildinfo"};
                const dests = [_][]const u8{info};
                cache.storeNamedTask(ctx, seed, &names, &dests, "", "") catch {};
                remapFile(ctx, info, false);
            } else |_| {}
        }
    }
}

fn remapFile(ctx: *cache.Context, path: []const u8, to_logical: bool) void {
    const bytes = ctx.read(path) catch return;
    const next = remapText(ctx, bytes, to_logical) catch return;
    ctx.atomic(path, next) catch {};
}

fn replay(ctx: *cache.Context, stdout: []const u8, stderr: []const u8) !void {
    try ctx.out(try remapText(ctx, stdout, false));
    try std.Io.File.stderr().writeStreamingAll(ctx.io, try remapText(ctx, stderr, false));
}

fn childArgv(ctx: *cache.Context, checker: Checker, exe: []const u8, args: []const []const u8, project: Project) ![]const []const u8 {
    var out: std.ArrayList([]const u8) = .empty;
    try out.append(ctx.a, exe);
    if (checker == .bun) {
        var has_check = false;
        for (args) |arg| {
            if (eq(arg, "check")) has_check = true;
        }
        if (!has_check) try out.append(ctx.a, "check");
        try out.appendSlice(ctx.a, args);
        return out.items;
    }
    try out.appendSlice(ctx.a, args);
    if (!hasFlag(args, "--noEmit") and !hasFlag(args, "--emit"))
        try out.append(ctx.a, "--noEmit");
    if (checker == .tsrs and !hasFlag(args, "--checkers") and eq(ctx.env.get("NANOCOMPILE_TSRS_CHECKERS") orelse "4", "4")) {
        try out.append(ctx.a, "--checkers");
        try out.append(ctx.a, ctx.env.get("NANOCOMPILE_TSRS_CHECKERS") orelse "4");
    }
    if (project.buildinfo) |info| {
        if (!hasFlag(args, "--incremental") and eq(ctx.env.get("NANOCOMPILE_TS_INCREMENTAL") orelse "1", "1"))
            try out.append(ctx.a, "--incremental");
        if (!hasFlag(args, "--tsBuildInfoFile")) {
            try out.append(ctx.a, "--tsBuildInfoFile");
            try out.append(ctx.a, info);
        }
    }
    return out.items;
}

fn bypass(ctx: *cache.Context, argv: []const []const u8, reason: []const u8) !u8 {
    ctx.trace(reason);
    ctx.event("ts_bypass");
    var child = try std.process.spawn(ctx.io, .{ .argv = argv, .environ_map = ctx.env });
    return exitCode(try child.wait(ctx.io));
}

pub fn execute(ctx: *cache.Context, checker: Checker, args: []const []const u8) !u8 {
    if (checker == .bun) {
        var typecheck = args.len == 0;
        for (args) |arg| {
            if (eq(arg, "check")) typecheck = true;
        }
        if (!typecheck) {
            const exe = try resolveChecker(ctx, .bun);
            var argv: std.ArrayList([]const u8) = .empty;
            try argv.append(ctx.a, exe);
            try argv.appendSlice(ctx.a, args);
            return bypass(ctx, argv.items, "bypass: bun invocation is not check");
        }
    }
    if (ctx.env.get("NANOCOMPILE_DISABLE")) |v| if (eq(v, "1")) {
        const exe = try resolveChecker(ctx, checker);
        var argv: std.ArrayList([]const u8) = .empty;
        try argv.append(ctx.a, exe);
        try argv.appendSlice(ctx.a, args);
        return bypass(ctx, argv.items, "bypass: disabled");
    };
    const project = discoverProject(ctx, args) catch |err|
        return bypass(ctx, &.{ try resolveChecker(ctx, checker) }, try std.fmt.allocPrint(ctx.a, "bypass: {s}", .{@errorName(err)}));
    ctx.rewrites = try ctx.a.dupe(cache.PathRewrite, &.{.{ .token = "$NANO_ROOT", .path = project.root }});
    ctx.prepare() catch return bypass(ctx, &.{ try resolveChecker(ctx, checker) }, "bypass: cache unavailable");
    const maintenance = cache.Lock.acquire(ctx, "maintenance", false) catch
        return bypass(ctx, &.{ try resolveChecker(ctx, checker) }, "bypass: cache lock unavailable");
    defer maintenance.release();
    const exe = try resolveChecker(ctx, checker);
    const sources = try collectSources(ctx, project.root);
    const key = try resultKey(ctx, checker, exe, args, project, sources);
    const flight = cache.Lock.acquire(ctx, key, true) catch
        return bypass(ctx, &.{exe}, "bypass: key lock unavailable");
    defer flight.release();

    // Result entries are stream-only. Putting .tsbuildinfo in the same entry
    // made a cold worktree miss when the dest file was absent (output-count
    // mismatch) even though source hashes matched. Seed restore is separate.
    if (cache.restoreStaged(ctx, key, &.{}, &.{}) catch null) |streams| {
        try restoreSeedBuildinfo(ctx, checker, exe, args, project);
        try replay(ctx, streams.stdout, streams.stderr);
        ctx.trace("hit");
        ctx.event("ts_hit");
        ctx.event("hit");
        return 0;
    }

    try restoreSeedBuildinfo(ctx, checker, exe, args, project);

    const argv = try childArgv(ctx, checker, exe, args, project);
    const result = compiler_stream.run(ctx, argv) catch |err|
        return bypass(ctx, argv, try std.fmt.allocPrint(ctx.a, "bypass: spawn {s}", .{@errorName(err)}));
    const code = exitCode(result.term);
    if (code != 0) {
        ctx.event("ts_miss");
        ctx.event("ts_failed");
        ctx.event("failed");
        return code;
    }
    var deps: std.ArrayList(cache.Dependency) = .empty;
    for (sources) |src| try deps.append(ctx.a, .{ .path = src.path, .hash = src.hash });
    const stdout = try remapText(ctx, result.stdout, true);
    const stderr = try remapText(ctx, result.stderr, true);
    cache.store(ctx, key, deps.items, &.{}, stdout, stderr) catch |err|
        ctx.trace(try std.fmt.allocPrint(ctx.a, "uncached: {s}", .{@errorName(err)}));
    try storeSeedBuildinfo(ctx, checker, exe, args, project);
    ctx.event("ts_miss");
    ctx.event("miss");
    return 0;
}

pub fn parseChecker(name: []const u8) ?Checker {
    if (eq(name, "tsc")) return .tsc;
    if (eq(name, "tsgo")) return .tsgo;
    if (eq(name, "tsrs")) return .tsrs;
    if (eq(name, "bun")) return .bun;
    if (eq(name, "tscheck")) return .tsc;
    return null;
}

test "source collection skips node_modules and sorts relative paths" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    const root = try Dir.cwd().realPathFileAlloc(io, try std.fs.path.join(a, &.{ ".zig-cache", "tmp", &tmp.sub_path }), a);
    try Dir.cwd().createDirPath(io, try std.fs.path.join(a, &.{ root, "src" }));
    try Dir.cwd().createDirPath(io, try std.fs.path.join(a, &.{ root, "node_modules", "lib" }));
    try tmp.dir.writeFile(io, .{ .sub_path = "src/a.ts", .data = "export const a = 1;\n" });
    try tmp.dir.writeFile(io, .{ .sub_path = "tsconfig.json", .data = "{}\n" });
    try tmp.dir.writeFile(io, .{ .sub_path = "node_modules/lib/x.ts", .data = "export {}\n" });
    var env = std.process.Environ.Map.init(a);
    var ctx: cache.Context = .{ .a = a, .io = io, .env = &env, .root = "/unused", .cwd = root };
    const sources = try collectSources(&ctx, root);
    try std.testing.expectEqual(@as(usize, 2), sources.len);
    try std.testing.expectEqualStrings("src/a.ts", sources[0].rel);
    try std.testing.expectEqualStrings("tsconfig.json", sources[1].rel);
}

test "result keys differ when a source file changes" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var env = std.process.Environ.Map.init(a);
    var ctx: cache.Context = .{ .a = a, .io = std.testing.io, .env = &env, .root = "/unused", .cwd = "/work/a" };
    ctx.rewrites = &.{.{ .token = "$NANO_ROOT", .path = "/work/a" }};
    const project = Project{ .root = "/work/a", .tsconfig = "/work/a/tsconfig.json", .buildinfo = null };
    const clean = [_]Source{.{ .rel = "src/a.ts", .path = "/work/a/src/a.ts", .hash = "aaa" }};
    const dirty = [_]Source{.{ .rel = "src/a.ts", .path = "/work/a/src/a.ts", .hash = "bbb" }};
    const args = [_][]const u8{"--noEmit"};
    const k1 = try resultKey(&ctx, .tsc, "tsc", &args, project, &clean);
    const k2 = try resultKey(&ctx, .tsc, "tsc", &args, project, &dirty);
    try std.testing.expect(!eq(k1, k2));
    ctx.rewrites = &.{.{ .token = "$NANO_ROOT", .path = "/work/b" }};
    ctx.cwd = "/work/b";
    const sibling = Project{ .root = "/work/b", .tsconfig = "/work/b/tsconfig.json", .buildinfo = null };
    const sib_src = [_]Source{.{ .rel = "src/a.ts", .path = "/work/b/src/a.ts", .hash = "aaa" }};
    const k3 = try resultKey(&ctx, .tsc, "tsc", &args, sibling, &sib_src);
    try std.testing.expectEqualStrings(k1, k3);
}

test "diagnostic remap is reversible across worktree roots" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var env = std.process.Environ.Map.init(a);
    var ctx: cache.Context = .{ .a = a, .io = std.testing.io, .env = &env, .root = "/unused", .cwd = "/work/a" };
    ctx.rewrites = &.{.{ .token = "$NANO_ROOT", .path = "/work/a" }};
    const stored = try remapText(&ctx, "/work/a/src/app.ts(1,2): error TS2322", true);
    try std.testing.expectEqualStrings("$NANO_ROOT/src/app.ts(1,2): error TS2322", stored);
    ctx.rewrites = &.{.{ .token = "$NANO_ROOT", .path = "/work/b" }};
    const replayed = try remapText(&ctx, stored, false);
    try std.testing.expectEqualStrings("/work/b/src/app.ts(1,2): error TS2322", replayed);
}
