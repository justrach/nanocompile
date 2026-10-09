//! Private streaming comparison against the pinned upstream BLAKE3 C backend.
//! Build instructions and provenance are recorded with the experiment report.
const std = @import("std");
const cache = @import("cache");
const c = @import("blake3");
extern "c" fn blake3_simd_degree() usize;

fn cDigest(ctx: *cache.Context, path: []const u8) ![]const u8 {
    const file = try std.Io.Dir.cwd().openFile(ctx.io, path, .{});
    defer file.close(ctx.io);
    if ((try file.stat(ctx.io)).kind != .file) return error.NotRegularFile;
    var h: c.blake3_hasher = undefined;
    c.blake3_hasher_init(&h);
    var buffer: [64 * 1024]u8 = undefined;
    var reader = file.reader(ctx.io, &buffer);
    var block: [64 * 1024]u8 = undefined;
    while (true) {
        const n = try reader.interface.readSliceShort(&block);
        if (n == 0) break;
        c.blake3_hasher_update(&h, block[0..n].ptr, n);
    }
    var bytes: [32]u8 = undefined;
    c.blake3_hasher_finalize(&h, &bytes, bytes.len);
    return ctx.a.dupe(u8, &std.fmt.bytesToHex(bytes, .lower));
}

pub fn main(init: std.process.Init) !void {
    const a = init.arena.allocator();
    const args = try init.minimal.args.toSlice(a);
    if (args.len != 3) return error.ExpectedModeAndFile;
    var ctx = try cache.Context.init(a, init.io, init.environ_map);
    const start = std.Io.Clock.awake.now(ctx.io).nanoseconds;
    const hash = if (std.mem.eql(u8, args[1], "zig"))
        try ctx.digest(args[2])
    else if (std.mem.eql(u8, args[1], "upstream"))
        try cDigest(&ctx, args[2])
    else
        return error.UnknownMode;
    const elapsed = std.Io.Clock.awake.now(ctx.io).nanoseconds - start;
    try ctx.out(try std.json.Stringify.valueAlloc(a, .{
        .hash = hash,
        .nanoseconds = elapsed,
        .upstream_version = std.mem.span(c.blake3_version()),
        .upstream_simd_degree = blake3_simd_degree(),
    }, .{}));
    try ctx.out("\n");
}
