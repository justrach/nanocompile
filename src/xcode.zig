//! Xcode's compiler-aware CAS remains responsible for Swift/Clang keys,
//! dependency discovery and replay. This opt-in command manages its location;
//! it never treats an app bundle as an opaque compiler-cache entry.
const std = @import("std");
const builtin = @import("builtin");
const cache = @import("cache.zig");

fn code(term: std.process.Child.Term) u8 {
    return switch (term) {
        .exited => |value| value,
        .signal => |value| @intCast(@min(255, 128 + @as(u32, @backingInt(value)))),
        else => 1,
    };
}

fn run(ctx: *cache.Context, argv: []const []const u8) !u8 {
    var child = try std.process.spawn(ctx.io, .{ .argv = argv, .environ_map = ctx.env });
    return code(try child.wait(ctx.io));
}

fn hasSetting(args: []const []const u8, setting: []const u8) bool {
    for (args) |arg| if (std.mem.startsWith(u8, arg, setting) and arg.len > setting.len and arg[setting.len] == '=') return true;
    return false;
}

fn informational(args: []const []const u8) bool {
    for (args) |arg| for ([_][]const u8{ "-version", "-help", "-list", "-showBuildSettings", "-showdestinations", "-showsdks", "-resolvePackageDependencies", "-exportArchive" }) |info| {
        if (std.mem.eql(u8, arg, info)) return true;
    };
    return false;
}

pub fn execute(ctx: *cache.Context, args: []const []const u8) !u8 {
    if (builtin.os.tag != .macos) return error.XcodeRequiresMacOS;
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.append(ctx.a, "xcodebuild");
    try argv.appendSlice(ctx.a, args);
    if (informational(args) or (if (ctx.env.get("NANOCOMPILE_DISABLE")) |v| std.mem.eql(u8, v, "1") else false)) return run(ctx, argv.items);
    var enabled: ?[]const u8 = null;
    for (args) |arg| if (std.mem.startsWith(u8, arg, "COMPILATION_CACHE_ENABLE_CACHING=")) {
        enabled = arg["COMPILATION_CACHE_ENABLE_CACHING=".len..];
    };
    if (enabled) |value| if (std.ascii.eqlIgnoreCase(value, "NO") or std.mem.eql(u8, value, "0")) return run(ctx, argv.items);
    // Explicit command-line settings win over this command's defaults.
    // Build products, project settings and signing retain Xcode's behavior.
    ctx.prepare() catch return run(ctx, argv.items);
    const maintenance = cache.Lock.acquire(ctx, "maintenance", false) catch return run(ctx, argv.items);
    defer maintenance.release();
    if (!hasSetting(args, "COMPILATION_CACHE_ENABLE_CACHING"))
        try argv.append(ctx.a, "COMPILATION_CACHE_ENABLE_CACHING=YES");
    if (!hasSetting(args, "COMPILATION_CACHE_CAS_PATH")) {
        const version = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ "xcodebuild", "-version" }, .environ_map = ctx.env });
        if (code(version.term) != 0) {
            try ctx.out(version.stdout);
            try std.Io.File.stderr().writeStreamingAll(ctx.io, version.stderr);
            return code(version.term);
        }
        var hash = cache.Hash.init(.{});
        cache.field(&hash, "native-xcode-cas-v1");
        cache.field(&hash, version.stdout);
        cache.field(&hash, @tagName(builtin.cpu.arch));
        cache.field(&hash, ctx.env.get("DEVELOPER_DIR") orelse "default");
        const root = try ctx.path(&.{ "xcode", try cache.finish(ctx.a, &hash) });
        try std.Io.Dir.cwd().createDirPath(ctx.io, root);
        const private = try std.Io.Dir.cwd().openDir(ctx.io, root, .{});
        defer private.close(ctx.io);
        try private.setPermissions(ctx.io, .fromMode(0o700));
        try argv.append(ctx.a, try std.fmt.allocPrint(ctx.a, "COMPILATION_CACHE_CAS_PATH={s}", .{root}));
    }
    if (!hasSetting(args, "COMPILATION_CACHE_KEEP_CAS_DIRECTORY"))
        try argv.append(ctx.a, "COMPILATION_CACHE_KEEP_CAS_DIRECTORY=YES");
    ctx.trace("Xcode native compilation cache; Swift/Clang keys and replay handled by Xcode");
    ctx.event("xcode_native_run");
    const result = try run(ctx, argv.items);
    if (result != 0) ctx.event("xcode_native_failed");
    return result;
}
