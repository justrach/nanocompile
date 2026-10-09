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

pub fn apple(ctx: *cache.Context, driver: []const u8) !Selection {
    if (builtin.os.tag != .macos) return error.UnsupportedNativeSelection;
    for ([_][]const u8{ "CCC_OVERRIDE_OPTIONS", "CCC_ADD_ARGS", "DYLD_INSERT_LIBRARIES", "LD_PRELOAD" }) |key|
        if (ctx.env.get(key) != null) return error.UnsupportedNativeConfiguration;
    // Only Apple's default dispatch shim is covered initially. Other native
    // drivers, target/linker overrides and SDK flags need their own selection.
    const resolved_driver = try real(ctx, driver);
    if (!std.mem.eql(u8, resolved_driver, "/usr/bin/clang") and
        !std.mem.eql(u8, resolved_driver, "/usr/bin/cc")) return error.UnsupportedNativeSelection;
    const clang = try real(ctx, try query(ctx, &.{ "/usr/bin/xcrun", "--find", "clang" }));
    const linker = try real(ctx, try query(ctx, &.{ driver, "-print-prog-name=ld" }));
    const xcrun_linker = try real(ctx, try query(ctx, &.{ "/usr/bin/xcrun", "--find", "ld" }));
    if (!std.mem.eql(u8, linker, xcrun_linker)) return error.NativeSelectionFailed;
    const resource = try real(ctx, try query(ctx, &.{ driver, "-print-resource-dir" }));
    const verbose = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ driver, "-v", "--version" }, .environ_map = ctx.env });
    switch (verbose.term) {
        .exited => |code| if (code != 0) return error.NativeSelectionFailed,
        else => return error.NativeSelectionFailed,
    }
    if (std.mem.indexOf(u8, verbose.stdout, "Configuration file:") != null or
        std.mem.indexOf(u8, verbose.stderr, "Configuration file:") != null) return error.UnsupportedNativeConfiguration;
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
