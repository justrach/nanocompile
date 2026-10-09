//! Full-content file-read strategy probe; no production changes.
const std = @import("std");
const cache = @import("cache");
fn positional(ctx: *cache.Context, path: []const u8, comptime size: usize) ![]const u8 {
    const file = try std.Io.Dir.cwd().openFile(ctx.io, path, .{});
    defer file.close(ctx.io);
    if ((try file.stat(ctx.io)).kind != .file) return error.NotRegularFile;
    var h = cache.Hash.init(.{});
    var block: [size]u8 = undefined;
    var offset: u64 = 0;
    while (true) {
        const n = try file.readPositional(ctx.io, &.{&block}, offset);
        if (n == 0) break;
        h.update(block[0..n]);
        offset += n;
    }
    return cache.finish(ctx.a, &h);
}
pub fn main(init: std.process.Init) !void {
    const a = init.arena.allocator();
    const args = try init.minimal.args.toSlice(a);
    if (args.len != 3) return error.ExpectedModeAndFile;
    var ctx = try cache.Context.init(a, init.io, init.environ_map);
    const start = std.Io.Clock.awake.now(ctx.io).nanoseconds;
    const hash = if (std.mem.eql(u8, args[1], "accepted")) try ctx.digest(args[2]) else if (std.mem.eql(u8, args[1], "positional-4k")) try positional(&ctx, args[2], 4096) else if (std.mem.eql(u8, args[1], "positional-64k")) try positional(&ctx, args[2], 65536) else if (std.mem.eql(u8, args[1], "positional-256k")) try positional(&ctx, args[2], 262144) else if (std.mem.eql(u8, args[1], "positional-1m")) try positional(&ctx, args[2], 1048576) else return error.UnknownMode;
    const elapsed = std.Io.Clock.awake.now(ctx.io).nanoseconds - start;
    try ctx.out(try std.json.Stringify.valueAlloc(a, .{ .hash = hash, .nanoseconds = elapsed }, .{}));
    try ctx.out("\n");
}
