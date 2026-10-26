//! Worktree orchestration uses the shipped Python helpers; Zig owns the CAS.
const std = @import("std");
const builtin = @import("builtin");
const cache = @import("cache.zig");

pub fn execute(ctx: *cache.Context, args: []const [:0]const u8) !u8 {
    if (builtin.os.tag == .windows) return error.UnsupportedPlatform;
    const executable = try std.process.executablePathAlloc(ctx.io, ctx.a);
    const directory = std.fs.path.dirname(executable) orelse return error.NoExecutableDirectory;
    const candidates = [_][]const u8{
        try std.fs.path.resolve(ctx.a, &.{ directory, "..", "share", "nanocompile", "worktree.py" }),
        try std.fs.path.join(ctx.a, &.{ directory, "tools", "worktree.py" }),
    };
    const helper = for (candidates) |candidate| {
        const info = std.Io.Dir.cwd().statFile(ctx.io, candidate, .{}) catch continue;
        if (info.kind == .file) break candidate;
    } else return error.WorktreeHelperNotInstalled;
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(ctx.a, &.{ ctx.env.get("NANOCOMPILE_PYTHON") orelse "python3", helper, "--nanocompile", executable, "--cache", ctx.root });
    for (args) |arg| try argv.append(ctx.a, arg);
    var child = try std.process.spawn(ctx.io, .{ .argv = argv.items, .environ_map = ctx.env });
    return switch (try child.wait(ctx.io)) {
        .exited => |value| value,
        .signal => |value| @intCast(@min(255, 128 + @as(u32, @backingInt(value)))),
        else => 1,
    };
}
