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

fn livePlan(ctx: *cache.Context, driver: []const u8) !DriverPlan {
    const result = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ driver, "-v", "-###", "-x", "c", "/dev/null", "-o", "/dev/null" }, .environ_map = ctx.env });
    if (std.mem.indexOf(u8, result.stdout, "Configuration file:") != null or std.mem.indexOf(u8, result.stderr, "Configuration file:") != null) return error.UnsupportedNativeConfiguration;
    switch (result.term) {
        .exited => |code| if (code != 0) return error.UnsupportedDriverPlan,
        else => return error.UnsupportedDriverPlan,
    }
    if (result.stdout.len != 0) return error.UnsupportedDriverPlan;
    return parsePlan(ctx.a, result.stderr);
}

pub fn apple(ctx: *cache.Context, driver: []const u8) !Selection {
    if (builtin.os.tag != .macos) return error.UnsupportedNativeSelection;
    for ([_][]const u8{ "CCC_OVERRIDE_OPTIONS", "CCC_ADD_ARGS", "DYLD_INSERT_LIBRARIES", "LD_PRELOAD" }) |key|
        if (ctx.env.get(key) != null) return error.UnsupportedNativeConfiguration;
    // Only Apple's default dispatch shim is covered initially. Other native
    // drivers, target/linker overrides and SDK flags need their own selection.
    const resolved_driver = try real(ctx, driver);
    if (!std.mem.eql(u8, resolved_driver, "/usr/bin/clang") and
        !std.mem.eql(u8, resolved_driver, "/usr/bin/cc")) return error.UnsupportedNativeSelection;
    const plan = livePlan(ctx, driver) catch |err| switch (err) {
        error.UnsupportedNativeConfiguration => return err,
        else => null,
    };
    const clang = try real(ctx, try query(ctx, &.{ "/usr/bin/xcrun", "--find", "clang" }));
    const linker = try real(ctx, if (plan) |selected| selected.linker else try query(ctx, &.{ driver, "-print-prog-name=ld" }));
    const xcrun_linker = try real(ctx, try query(ctx, &.{ "/usr/bin/xcrun", "--find", "ld" }));
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
    const default_sdk = try query(ctx, &.{ "/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path" });
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
