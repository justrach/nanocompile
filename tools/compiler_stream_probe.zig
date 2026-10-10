const std = @import("std");
const stream = @import("compiler_stream");
pub fn main(init: std.process.Init) void {
    const a = init.arena.allocator();
    const args = init.minimal.args.toSlice(a) catch std.process.exit(1);
    var ctx = stream.Context.init(a, init.io, init.environ_map) catch std.process.exit(1);
    const result = stream.run(&ctx, args[1..]) catch |err| {
        std.debug.print("probe: {s}\n", .{@errorName(err)});
        std.process.exit(1);
    };
    if (ctx.env.get("PROBE_CAPTURE_OUT")) |path| std.Io.Dir.cwd().writeFile(ctx.io, .{ .sub_path = path, .data = result.stdout }) catch std.process.exit(1);
    if (ctx.env.get("PROBE_CAPTURE_ERR")) |path| std.Io.Dir.cwd().writeFile(ctx.io, .{ .sub_path = path, .data = result.stderr }) catch std.process.exit(1);
    std.process.exit(switch (result.term) {
        .exited => |v| v,
        .signal => |v| @intCast(@min(255, 128 + @as(u32, @backingInt(v)))),
        else => 1,
    });
}
