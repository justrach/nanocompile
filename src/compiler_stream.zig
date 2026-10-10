//! Stream real compiler notifications immediately while retaining replay bytes.
const std = @import("std");
const cache = @import("cache.zig");
pub const Context = cache.Context;

pub fn run(ctx: *cache.Context, argv: []const []const u8) !std.process.RunResult {
    var child = try std.process.spawn(ctx.io, .{ .argv = argv, .environ_map = ctx.env, .stdin = .ignore, .stdout = .pipe, .stderr = .pipe });
    defer child.kill(ctx.io);
    var buffers: std.Io.File.MultiReader.Buffer(2) = undefined;
    var reader: std.Io.File.MultiReader = undefined;
    reader.init(ctx.a, ctx.io, buffers.toStreams(), &.{ child.stdout.?, child.stderr.? });
    defer reader.deinit();
    var forwarded = [_]usize{ 0, 0 };
    while (true) {
        var ended = false;
        reader.fill(64, .none) catch |err| switch (err) {
            error.EndOfStream => ended = true,
            else => return err,
        };
        for (0..2) |index| {
            const bytes = reader.reader(index).buffered();
            const fresh = bytes[forwarded[index]..];
            if (index == 0) try ctx.out(fresh) else try std.Io.File.stderr().writeStreamingAll(ctx.io, fresh);
            forwarded[index] = bytes.len;
        }
        if (ended) break;
    }
    try reader.checkAnyError();
    const term = try child.wait(ctx.io);
    return .{ .term = term, .stdout = try reader.toOwnedSlice(0), .stderr = try reader.toOwnedSlice(1) };
}
