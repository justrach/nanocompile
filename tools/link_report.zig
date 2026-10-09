//! Inspect a native link report using nanocompile's strict Zig parser.
const std = @import("std");
const deps = @import("link_dependencies");
pub fn main(init: std.process.Init) !void {
    const a = init.arena.allocator();
    const args = try init.minimal.args.toSlice(a);
    if (args.len != 3) return error.ExpectedFormatAndReportPath;
    const format = std.meta.stringToEnum(deps.Format, args[1]) orelse return error.UnsupportedFormat;
    const bytes = try std.Io.Dir.cwd().readFileAlloc(init.io, args[2], a, .limited(64 * 1024 * 1024));
    const report = try deps.parse(a, bytes, format);
    const json = try std.json.Stringify.valueAlloc(a, report, .{});
    try std.Io.File.stdout().writeStreamingAll(init.io, json);
    try std.Io.File.stdout().writeStreamingAll(init.io, "\n");
}
