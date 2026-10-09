const std = @import("std");
pub fn main(init: std.process.Init) !void {
    const a = init.arena.allocator();
    const args = try init.minimal.args.toSlice(a);
    const size = try std.fmt.parseInt(usize, args[2], 10);
    const file = try std.Io.Dir.cwd().openFile(init.io, args[1], .{});
    defer file.close(init.io);
    const block = try a.alloc(u8, size);
    const backing = try a.alloc(u8, if (args.len > 3) size else 0);
    var reader = file.reader(init.io, backing);
    var h = std.crypto.hash.Blake3.init(.{});
    while (true) {
        const n = try reader.interface.readSliceShort(block);
        if (n == 0) break;
        h.update(block[0..n]);
    }
    var output: [32]u8 = undefined;
    h.final(&output);
    const hex = std.fmt.bytesToHex(output, .lower);
    try std.Io.File.stdout().writeStreamingAll(init.io, &hex);
}
