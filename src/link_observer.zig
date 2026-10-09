//! Private final-link observer used by producer discovery. It inherits the
//! original environment and delegates to the explicitly selected driver.
//! Parent-side driver/SDK identity and scratch ownership remain separate gates.
const std = @import("std");
const cache = @import("cache.zig");
const deps = @import("link_dependencies.zig");

pub const Config = struct {
    driver: []const u8,
    format: deps.Format,
    report: []const u8,
    invocation: []const u8,
};

pub fn execute(ctx: *cache.Context, config_path: []const u8, args: []const []const u8) !u8 {
    if (!std.fs.path.isAbsolute(config_path) or args.len == 0) return error.InvalidLinkObserver;
    const bytes = try ctx.read(config_path);
    const parsed = try std.json.parseFromSlice(Config, ctx.a, bytes, .{ .allocate = .alloc_always });
    const config = parsed.value;
    for ([_][]const u8{ config.driver, config.report, config.invocation }) |path|
        if (!std.fs.path.isAbsolute(path)) return error.InvalidLinkObserver;
    if (std.mem.eql(u8, config.report, config.invocation) or std.mem.eql(u8, config_path, config.report) or
        std.mem.eql(u8, config_path, config.invocation)) return error.InvalidLinkObserver;
    var command: std.ArrayList([]const u8) = .empty;
    try command.append(ctx.a, config.driver);
    try command.appendSlice(ctx.a, args);
    // Separate driver arguments preserve paths containing commas or spaces.
    switch (config.format) {
        .darwin => try command.appendSlice(ctx.a, &.{ "-Xlinker", "-dependency_info", "-Xlinker", config.report }),
        .make => try command.appendSlice(ctx.a, &.{ "-Xlinker", try std.fmt.allocPrint(ctx.a, "--dependency-file={s}", .{config.report}) }),
    }
    const record = try std.json.Stringify.valueAlloc(ctx.a, .{ .cwd = ctx.cwd, .driver = config.driver, .args = args }, .{});
    try ctx.atomic(config.invocation, try cache.seal(ctx, record));
    var child = try std.process.spawn(ctx.io, .{ .argv = command.items, .environ_map = ctx.env });
    return switch (try child.wait(ctx.io)) {
        .exited => |code| code,
        .signal => |signal| @intCast(@min(255, 128 + @as(u32, @backingInt(signal)))),
        else => 1,
    };
}
