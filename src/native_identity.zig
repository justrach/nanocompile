//! Selected Apple driver/linker identity for future producer keys.
//! Persistent link inputs and negative lookups remain separate dependencies.
const std = @import("std");
const builtin = @import("builtin");
const cache = @import("cache.zig");
const identity = @import("identity.zig");
const Dir = std.Io.Dir;

pub const Selection = struct {
    driver: []const u8,
    clang: []const u8,
    linker: []const u8,
    sdk: []const u8,
    resource_dir: []const u8,
    files: []const []const u8,
    hash: []const u8,
};

fn query(ctx: *cache.Context, argv: []const []const u8) ![]const u8 {
    const result = try std.process.run(ctx.a, ctx.io, .{ .argv = argv, .environ_map = ctx.env });
    switch (result.term) {
        .exited => |code| if (code != 0) return error.NativeSelectionFailed,
        else => return error.NativeSelectionFailed,
    }
    const value = std.mem.trim(u8, result.stdout, "\r\n");
    if (value.len == 0 or std.mem.indexOfScalar(u8, value, '\n') != null) return error.NativeSelectionFailed;
    return value;
}

// Query buffers use independent allocations; the caller's arena is not
// threadsafe. Results are consumed only after both workers have joined.
const Query = struct {
    argv: []const []const u8,
    result: ?std.process.RunResult = null,
    failure: ?anyerror = null,

    fn run(q: *Query, io: std.Io, env: *const std.process.Environ.Map) void {
        q.result = std.process.run(std.heap.page_allocator, io, .{ .argv = q.argv, .environ_map = env }) catch |err| {
            q.failure = err;
            return;
        };
    }

    fn deinit(q: *Query) void {
        if (q.result) |result| {
            std.heap.page_allocator.free(result.stdout);
            std.heap.page_allocator.free(result.stderr);
        }
    }

    fn raw(q: *const Query) !std.process.RunResult {
        if (q.failure) |err| return err;
        return q.result orelse error.NativeSelectionFailed;
    }

    fn value(q: *const Query) ![]const u8 {
        const result = try q.raw();
        switch (result.term) {
            .exited => |code| if (code != 0) return error.NativeSelectionFailed,
            else => return error.NativeSelectionFailed,
        }
        const text = std.mem.trim(u8, result.stdout, "\r\n");
        if (text.len == 0 or std.mem.indexOfScalar(u8, text, '\n') != null) return error.NativeSelectionFailed;
        return text;
    }

    fn plan(q: *const Query, ctx: *cache.Context) !DriverPlan {
        return checkedPlan(ctx, try q.raw());
    }
};

fn queryWorker(queries: []Query, next: *std.atomic.Value(usize), io: std.Io, env: *const std.process.Environ.Map) void {
    while (true) {
        const index = next.fetchAdd(1, .monotonic);
        if (index >= queries.len) return;
        queries[index].run(io, env);
    }
}

fn real(ctx: *cache.Context, path: []const u8) ![]const u8 {
    if (!std.fs.path.isAbsolute(path)) return error.NativeSelectionFailed;
    return Dir.cwd().realPathFileAlloc(ctx.io, path, ctx.a);
}

const DriverPlan = struct { clang: []const u8, linker: []const u8, resource: []const u8 };

// Clang's -### diagnostic quotes every argument. Only accept its bounded
// two-command C compile/link plan; unknown rendering uses the older queries.
fn arguments(a: std.mem.Allocator, line: []const u8) ![]const []const u8 {
    var args: std.ArrayList([]const u8) = .empty;
    var i: usize = 0;
    while (i < line.len) {
        while (i < line.len and (line[i] == ' ' or line[i] == '\t')) : (i += 1) {}
        if (i == line.len) break;
        if (line[i] != '"') return error.UnsupportedDriverPlan;
        i += 1;
        var arg: std.ArrayList(u8) = .empty;
        while (i < line.len and line[i] != '"') : (i += 1) {
            if (line[i] == '\\') {
                i += 1;
                if (i == line.len or (line[i] != '\\' and line[i] != '"')) return error.UnsupportedDriverPlan;
            }
            if (line[i] < 32 or line[i] == 127) return error.UnsupportedDriverPlan;
            try arg.append(a, line[i]);
        }
        if (i == line.len) return error.UnsupportedDriverPlan;
        i += 1;
        if (i < line.len and line[i] != ' ' and line[i] != '\t') return error.UnsupportedDriverPlan;
        try args.append(a, arg.items);
    }
    return args.items;
}

fn parsePlan(a: std.mem.Allocator, bytes: []const u8) !DriverPlan {
    if (std.mem.indexOf(u8, bytes, "Configuration file:") != null) return error.UnsupportedNativeConfiguration;
    var commands: std.ArrayList([]const []const u8) = .empty;
    var installed: ?[]const u8 = null;
    var headers: u8 = 0;
    var lines = std.mem.splitScalar(u8, bytes, '\n');
    while (lines.next()) |raw| {
        const line = std.mem.trim(u8, raw, " \t\r");
        if (line.len == 0) continue;
        if (line[0] == '"') {
            if (commands.items.len == 2) return error.UnsupportedDriverPlan;
            try commands.append(a, try arguments(a, line));
        } else {
            const prefixes = [_][]const u8{ "Apple clang version ", "Target: ", "Thread model: ", "InstalledDir: " };
            var known = false;
            for (prefixes, 0..) |prefix, index| {
                if (!std.mem.startsWith(u8, line, prefix)) continue;
                const bit: u8 = @as(u8, 1) << @intCast(index);
                if (headers & bit != 0 or line.len == prefix.len or commands.items.len != 0) return error.UnsupportedDriverPlan;
                headers |= bit;
                if (index == 3) installed = line[prefix.len..];
                known = true;
                break;
            }
            if (!known) return error.UnsupportedDriverPlan;
        }
    }
    if (headers != 15 or commands.items.len != 2) return error.UnsupportedDriverPlan;
    const frontend = commands.items[0];
    const link = commands.items[1];
    if (frontend.len < 4 or link.len < 2 or !std.mem.eql(u8, frontend[1], "-cc1") or !std.mem.eql(u8, frontend[frontend.len - 1], "/dev/null")) return error.UnsupportedDriverPlan;
    if (!std.fs.path.isAbsolute(frontend[0]) or !std.fs.path.isAbsolute(link[0]) or !std.mem.eql(u8, std.fs.path.dirname(frontend[0]) orelse "", installed.?)) return error.UnsupportedDriverPlan;
    var resource: ?[]const u8 = null;
    for (frontend, 0..) |arg, i| if (std.mem.eql(u8, arg, "-resource-dir")) {
        if (resource != null or i + 1 == frontend.len or !std.fs.path.isAbsolute(frontend[i + 1])) return error.UnsupportedDriverPlan;
        resource = frontend[i + 1];
    };
    return .{ .clang = frontend[0], .linker = link[0], .resource = resource orelse return error.UnsupportedDriverPlan };
}

fn checkedPlan(ctx: *cache.Context, result: std.process.RunResult) !DriverPlan {
    if (std.mem.indexOf(u8, result.stdout, "Configuration file:") != null or std.mem.indexOf(u8, result.stderr, "Configuration file:") != null) return error.UnsupportedNativeConfiguration;
    switch (result.term) {
        .exited => |code| if (code != 0) return error.UnsupportedDriverPlan,
        else => return error.UnsupportedDriverPlan,
    }
    if (result.stdout.len != 0) return error.UnsupportedDriverPlan;
    return parsePlan(ctx.a, result.stderr);
}

// Live selection spawns four processes (driver plan and three xcrun queries).
// Memoize it like other trusted installed-tool state: keyed by the driver and
// every environment variable xcrun or the driver consults for selection, and
// valid only while the xcode-select link, both developer roots, xcrun, every
// selected tool, the SDK, its parent and the identity files keep their
// inode/size/mtime/ctime. Stamps changed at or after selection began are never
// trusted. NANOCOMPILE_SELECTION_MEMO=0 always queries live.
const SelectionMemo = struct {
    schema: u32 = 1,
    started: i96,
    clang: []const u8,
    linker: []const u8,
    sdk: []const u8,
    resource_dir: []const u8,
    files: []const []const u8,
    hash: []const u8,
    stamps: []const identity.Stamp,
};

fn selectionEnvironment(name: []const u8) bool {
    if (std.mem.eql(u8, name, "PATH") or std.mem.eql(u8, name, "HOME")) return true;
    for ([_][]const u8{ "SDKROOT", "DEVELOPER_DIR", "TOOLCHAINS", "XCODE", "XCRUN", "xcrun", "CCC_", "CLANG", "DYLD_", "LD_", "MACOSX_", "COMPILER_PATH", "CPATH", "LIBRARY_PATH" }) |prefix|
        if (std.mem.startsWith(u8, name, prefix)) return true;
    return false;
}

fn selectionKey(ctx: *cache.Context, domain: []const u8, values: []const []const u8) ![]const u8 {
    var h = cache.Hash.init(.{});
    cache.field(&h, domain);
    for (values) |value| cache.field(&h, value);
    const names = try ctx.a.dupe([]const u8, ctx.env.keys());
    std.mem.sort([]const u8, names, {}, struct {
        fn less(_: void, x: []const u8, y: []const u8) bool {
            return std.mem.order(u8, x, y) == .lt;
        }
    }.less);
    for (names) |name| if (selectionEnvironment(name)) {
        cache.field(&h, name);
        cache.field(&h, ctx.env.get(name).?);
    };
    return cache.finish(ctx.a, &h);
}

fn memoEnabled(ctx: *cache.Context) bool {
    return !std.mem.eql(u8, ctx.env.get("NANOCOMPILE_SELECTION_MEMO") orelse "1", "0");
}

fn stampsCurrent(ctx: *cache.Context, stamps: []const identity.Stamp, started: i96) bool {
    for (stamps) |expected| {
        if (expected.exists and (expected.ctime >= started or expected.mtime >= started)) return false;
        const current = identity.stamp(ctx, expected.path) catch return false;
        if (!identity.equal(expected, current)) return false;
    }
    return true;
}

fn collectStamps(ctx: *cache.Context, paths: []const []const u8) ![]const identity.Stamp {
    var stamps: std.ArrayList(identity.Stamp) = .empty;
    outer: for (paths) |path| {
        for (stamps.items) |existing| if (std.mem.eql(u8, existing.path, path)) continue :outer;
        try stamps.append(ctx.a, try identity.stamp(ctx, path));
    }
    return stamps.items;
}

const selection_roots = [_][]const u8{ "/var/db/xcode_select_link", "/Library/Developer/CommandLineTools", "/Applications/Xcode.app", "/usr/bin/xcrun" };

pub fn apple(ctx: *cache.Context, driver: []const u8) !Selection {
    if (builtin.os.tag != .macos) return error.UnsupportedNativeSelection;
    for ([_][]const u8{ "CCC_OVERRIDE_OPTIONS", "CCC_ADD_ARGS", "DYLD_INSERT_LIBRARIES", "LD_PRELOAD" }) |key|
        if (ctx.env.get(key) != null) return error.UnsupportedNativeConfiguration;
    // Only Apple's default dispatch shim is covered initially. Other native
    // drivers, target/linker overrides and SDK flags need their own selection.
    const resolved_driver = try real(ctx, driver);
    if (!std.mem.eql(u8, resolved_driver, "/usr/bin/clang") and
        !std.mem.eql(u8, resolved_driver, "/usr/bin/cc")) return error.UnsupportedNativeSelection;
    if (!memoEnabled(ctx)) return appleLive(ctx, driver, resolved_driver);
    const key = try selectionKey(ctx, "apple-native-selection-memo-v1", &.{ driver, resolved_driver });
    const path = try ctx.path(&.{ "selection-memos", key });
    if (ctx.read(path)) |bytes| memo: {
        const payload = cache.unseal(ctx, bytes) catch break :memo;
        const parsed = std.json.parseFromSlice(SelectionMemo, ctx.a, payload, .{ .allocate = .alloc_always }) catch break :memo;
        const m = parsed.value;
        if (m.schema != 1 or !cache.validHash(m.hash) or m.stamps.len < selection_roots.len or !stampsCurrent(ctx, m.stamps, m.started)) break :memo;
        return .{ .driver = driver, .clang = m.clang, .linker = m.linker, .sdk = m.sdk, .resource_dir = m.resource_dir, .files = m.files, .hash = m.hash };
    } else |_| {}
    const started = std.Io.Clock.real.now(ctx.io).nanoseconds;
    var paths: std.ArrayList([]const u8) = .empty;
    try paths.appendSlice(ctx.a, &selection_roots);
    try paths.appendSlice(ctx.a, &.{ driver, resolved_driver });
    const before = try collectStamps(ctx, paths.items);
    const selected = try appleLive(ctx, driver, resolved_driver);
    const bin = std.fs.path.dirname(selected.clang) orelse return selected;
    const usr = std.fs.path.dirname(bin) orelse return selected;
    try paths.appendSlice(ctx.a, &.{ selected.clang, selected.linker, selected.sdk, std.fs.path.dirname(selected.sdk) orelse selected.sdk, selected.resource_dir, bin, usr, std.fs.path.dirname(usr) orelse usr });
    if (ctx.env.get("SDKROOT") == null) {
        // The default SDK path is commonly a link that a new SDK can retarget.
        const default_sdk = query(ctx, &.{ "/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path" }) catch return selected;
        try paths.appendSlice(ctx.a, &.{ default_sdk, std.fs.path.dirname(default_sdk) orelse default_sdk });
    }
    try paths.appendSlice(ctx.a, selected.files);
    const stamps = try collectStamps(ctx, paths.items);
    for (before) |earlier| for (stamps) |later| if (std.mem.eql(u8, earlier.path, later.path) and !identity.equal(earlier, later)) return selected;
    if (stampsCurrent(ctx, stamps, started)) {
        const memo: SelectionMemo = .{ .started = started, .clang = selected.clang, .linker = selected.linker, .sdk = selected.sdk, .resource_dir = selected.resource_dir, .files = selected.files, .hash = selected.hash, .stamps = stamps };
        const bytes = std.json.Stringify.valueAlloc(ctx.a, memo, .{}) catch return selected;
        ctx.atomic(path, cache.seal(ctx, bytes) catch return selected) catch {};
    }
    return selected;
}

/// Memoized `xcrun --find tool` under the same selection-state contract.
pub fn xcrunFind(ctx: *cache.Context, tool: []const u8) ![]const u8 {
    const live = struct {
        fn find(c: *cache.Context, name: []const u8) ![]const u8 {
            const result = try std.process.run(c.a, c.io, .{ .argv = &.{ "/usr/bin/xcrun", "--find", name }, .environ_map = c.env });
            switch (result.term) {
                .exited => |code| if (code != 0) return error.UnsupportedAppleHelper,
                else => return error.UnsupportedAppleHelper,
            }
            const found = std.mem.trim(u8, result.stdout, "\r\n ");
            if (!std.fs.path.isAbsolute(found) or std.mem.indexOfScalar(u8, found, '\n') != null) return error.UnsupportedAppleHelper;
            return found;
        }
    }.find;
    if (builtin.os.tag != .macos or !memoEnabled(ctx)) return live(ctx, tool);
    const FindMemo = struct { schema: u32 = 1, started: i96, found: []const u8, stamps: []const identity.Stamp };
    const key = try selectionKey(ctx, "xcrun-find-memo-v1", &.{tool});
    const path = try ctx.path(&.{ "selection-memos", key });
    if (ctx.read(path)) |bytes| memo: {
        const payload = cache.unseal(ctx, bytes) catch break :memo;
        const parsed = std.json.parseFromSlice(FindMemo, ctx.a, payload, .{ .allocate = .alloc_always }) catch break :memo;
        const m = parsed.value;
        if (m.schema != 1 or m.stamps.len < selection_roots.len or !stampsCurrent(ctx, m.stamps, m.started)) break :memo;
        return m.found;
    } else |_| {}
    const started = std.Io.Clock.real.now(ctx.io).nanoseconds;
    const before = try collectStamps(ctx, &selection_roots);
    const found = try live(ctx, tool);
    const dir = std.fs.path.dirname(found) orelse return found;
    var paths: std.ArrayList([]const u8) = .empty;
    try paths.appendSlice(ctx.a, &selection_roots);
    try paths.appendSlice(ctx.a, &.{ found, dir, std.fs.path.dirname(dir) orelse dir });
    const stamps = try collectStamps(ctx, paths.items);
    for (before, stamps[0..before.len]) |earlier, later| if (!identity.equal(earlier, later)) return found;
    if (stampsCurrent(ctx, stamps, started)) {
        const bytes = std.json.Stringify.valueAlloc(ctx.a, FindMemo{ .started = started, .found = found, .stamps = stamps }, .{}) catch return found;
        ctx.atomic(path, cache.seal(ctx, bytes) catch return found) catch {};
    }
    return found;
}

fn appleLive(ctx: *cache.Context, driver: []const u8, resolved_driver: []const u8) !Selection {
    var queries = [_]Query{
        .{ .argv = &.{ driver, "-v", "-###", "-x", "c", "/dev/null", "-o", "/dev/null" } },
        .{ .argv = &.{ "/usr/bin/xcrun", "--find", "clang" } },
        .{ .argv = &.{ "/usr/bin/xcrun", "--find", "ld" } },
        .{ .argv = &.{ "/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path" } },
    };
    defer for (&queries) |*q| q.deinit();
    var next: std.atomic.Value(usize) = .init(0);
    var group: std.Io.Group = .init;
    defer group.cancel(ctx.io);
    // At most two active queries per invocation, including this calling worker.
    if ((std.Thread.getCpuCount() catch 1) > 1)
        group.concurrent(ctx.io, queryWorker, .{ &queries, &next, ctx.io, ctx.env }) catch {};
    queryWorker(&queries, &next, ctx.io, ctx.env);
    try group.await(ctx.io);
    const plan = queries[0].plan(ctx) catch |err| switch (err) {
        error.UnsupportedNativeConfiguration => return err,
        else => null,
    };
    const clang = try real(ctx, try queries[1].value());
    const linker = try real(ctx, if (plan) |selected| selected.linker else try query(ctx, &.{ driver, "-print-prog-name=ld" }));
    const xcrun_linker = try real(ctx, try queries[2].value());
    if (!std.mem.eql(u8, linker, xcrun_linker)) return error.NativeSelectionFailed;
    const resource = try real(ctx, if (plan) |selected| selected.resource else try query(ctx, &.{ driver, "-print-resource-dir" }));
    if (plan) |selected| {
        if (!std.mem.eql(u8, clang, try real(ctx, selected.clang))) return error.NativeSelectionFailed;
    } else {
        const verbose = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ driver, "-v", "--version" }, .environ_map = ctx.env });
        switch (verbose.term) {
            .exited => |code| if (code != 0) return error.NativeSelectionFailed,
            else => return error.NativeSelectionFailed,
        }
        if (std.mem.indexOf(u8, verbose.stdout, "Configuration file:") != null or std.mem.indexOf(u8, verbose.stderr, "Configuration file:") != null) return error.UnsupportedNativeConfiguration;
    }
    const default_sdk = try queries[3].value();
    const selected_sdk = ctx.env.get("SDKROOT") orelse default_sdk;
    const sdk = try real(ctx, selected_sdk);
    const bin = std.fs.path.dirname(clang) orelse return error.NativeSelectionFailed;
    if (!std.mem.eql(u8, bin, std.fs.path.dirname(linker) orelse "")) return error.NativeSelectionFailed;
    const usr = std.fs.path.dirname(bin) orelse return error.NativeSelectionFailed;
    const files = try ctx.a.dupe([]const u8, &.{
        resolved_driver,                                               "/usr/bin/xcrun",                                           clang, linker,
        try std.fs.path.join(ctx.a, &.{ usr, "lib", "libLTO.dylib" }), try std.fs.path.join(ctx.a, &.{ sdk, "SDKSettings.json" }),
    });
    var h = cache.Hash.init(.{});
    cache.field(&h, "apple-native-selection-v1");
    cache.field(&h, driver);
    cache.field(&h, clang);
    cache.field(&h, linker);
    cache.field(&h, default_sdk);
    cache.field(&h, selected_sdk);
    cache.field(&h, sdk);
    cache.field(&h, resource);
    cache.field(&h, try identity.nativeFiles(ctx, files));
    return .{ .driver = driver, .clang = clang, .linker = linker, .sdk = sdk, .resource_dir = resource, .files = files, .hash = try cache.finish(ctx.a, &h) };
}

test "driver plans require complete bounded quoted commands" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const header = "Apple clang version 21\nTarget: arm64-apple-darwin\nThread model: posix\nInstalledDir: /tools/bin\n";
    const frontend = " \"/tools/bin/clang\" \"-cc1\" \"-resource-dir\" \"/tools/lib/clang/21\" \"-x\" \"c\" \"/dev/null\"\n";
    const linker = " \"/tools/bin/ld\" \"-o\" \"/dev/null\"\n";
    const selected = try parsePlan(a, header ++ frontend ++ linker);
    try std.testing.expectEqualStrings("/tools/bin/clang", selected.clang);
    try std.testing.expectEqualStrings("/tools/bin/ld", selected.linker);
    try std.testing.expectEqualStrings("/tools/lib/clang/21", selected.resource);
    try std.testing.expectError(error.UnsupportedDriverPlan, parsePlan(a, header ++ frontend));
    try std.testing.expectError(error.UnsupportedDriverPlan, parsePlan(a, header ++ frontend ++ linker ++ linker));
    try std.testing.expectError(error.UnsupportedNativeConfiguration, parsePlan(a, header ++ "Configuration file: /tmp/clang.cfg\n" ++ frontend ++ linker));
    try std.testing.expectError(error.UnsupportedDriverPlan, arguments(a, "\"unterminated"));
    try std.testing.expectError(error.UnsupportedDriverPlan, arguments(a, "\"a\"trailing"));
    const escaped = try arguments(a, "\"/path with spaces/a\\\"b\\\\c\"");
    try std.testing.expectEqualStrings("/path with spaces/a\"b\\c", escaped[0]);
}
