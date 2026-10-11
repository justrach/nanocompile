const std = @import("std");
const cache = @import("cache");

pub fn main(init: std.process.Init) !void {
    const a = init.arena.allocator();
    const args = try init.minimal.args.toSlice(a);
    if (args.len != 3) return error.ExpectedModeAndFile;
    if (!std.mem.eql(u8, args[1], "0") and !std.mem.eql(u8, args[1], "1") and !std.mem.eql(u8, args[1], "2"))
        return error.InvalidMode;
    try init.environ_map.put("NANOCOMPILE_BLOB_HASH_MODE", args[1]);
    try init.environ_map.put("NANOCOMPILE_TRACE", "1");
    var ctx = try cache.Context.init(a, init.io, init.environ_map);
    const start = std.Io.Clock.awake.now(ctx.io).nanoseconds;
    const hash = try ctx.digestBlob(args[2]);
    const elapsed = std.Io.Clock.awake.now(ctx.io).nanoseconds - start;
    try ctx.out(try std.json.Stringify.valueAlloc(a, .{ .hash = hash, .nanoseconds = elapsed }, .{}));
    try ctx.out("\n");
}
