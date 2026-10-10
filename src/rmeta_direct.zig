//! Experimental exact-version Rust dependency decoder; unknown records refuse.
const std = @import("std");
const Error = error{UnsupportedNativeMetadata, HiddenNativeLinkInput};
const version = "rustc 1.97.1 (8bab26f4f 2026-07-14)";
const Reader = struct {
    bytes: []const u8,
    pos: usize = 0,

    fn take(self: *Reader, count: usize) Error![]const u8 {
        if (self.pos > self.bytes.len or count > self.bytes.len - self.pos) return error.UnsupportedNativeMetadata;
        const value = self.bytes[self.pos..][0..count];
        self.pos += count;
        return value;
    }
    fn byte(self: *Reader) Error!u8 {
        return (try self.take(1))[0];
    }
    fn integer(self: *Reader) Error!usize {
        var value: u64 = 0;
        var shift: u7 = 0;
        while (shift < 64) : (shift += 7) {
            const b = try self.byte();
            if (shift == 63 and b > 1) return error.UnsupportedNativeMetadata;
            value |= @as(u64, b & 127) << @intCast(shift);
            if (b < 128) return std.math.cast(usize, value) orelse error.UnsupportedNativeMetadata;
        }
        return error.UnsupportedNativeMetadata;
    }
    fn string(self: *Reader) Error![]const u8 {
        const text = try self.take(try self.integer());
        if (try self.byte() != 0xc1 or !std.unicode.utf8ValidateSlice(text)) return error.UnsupportedNativeMetadata;
        return text;
    }
    fn boolean(self: *Reader) Error!bool {
        return switch (try self.byte()) {
            0 => false,
            1 => true,
            else => error.UnsupportedNativeMetadata,
        };
    }
    fn optionBool(self: *Reader) Error!void {
        if (try self.boolean()) _ = try self.boolean();
    }
    fn symbol(self: *Reader) Error!?[]const u8 {
        return switch (try self.byte()) {
            0 => try self.string(),
            1 => blk: {
                var other: Reader = .{ .bytes = self.bytes, .pos = try self.integer() };
                break :blk try other.string();
            },
            2 => switch (try self.integer()) {
                    296 => "alloc",
                    629 => "core",
                    1876 => "std",
                    556 => "compiler_builtins",
                    2102 => "unwind",
                    1366 => "panic_abort",
                    1405 => "panic_unwind",
                    1943 => "test",
                    1469 => "proc_macro",
                    1060 => "libc",
                    else => return error.UnsupportedNativeMetadata,
            },
            else => error.UnsupportedNativeMetadata,
        };
    }
};
pub const Root = struct { name: []const u8, hash: []const u8, triple: []const u8, proc_macro: bool };
pub const Crate = struct { name: []const u8, hash: []const u8, proc_macro: bool };
pub const Graph = struct { root: Root, dependencies: []const Crate };

fn nameValid(text: []const u8) !void {
    if (text.len == 0) return error.UnsupportedNativeMetadata;
    for (text) |ch| if (!std.ascii.isAlphanumeric(ch) and ch != '_' and ch != '-') return error.UnsupportedNativeMetadata;
}

pub fn decode(a: std.mem.Allocator, input: []const u8) !Graph {
    const end = "rust-end-file";
    if (input.len < 29 or !std.mem.startsWith(u8, input, "rust\x00\x00\x00\x0a") or !std.mem.endsWith(u8, input, end)) return error.UnsupportedNativeMetadata;
    const bytes = input[0 .. input.len - end.len];
    var header: Reader = .{ .bytes = bytes, .pos = 16 };
    if (!std.mem.eql(u8, try header.string(), version)) return error.UnsupportedNativeMetadata;
    const root_pos = std.math.cast(usize, std.mem.readInt(u64, bytes[8..16], .little)) orelse return error.UnsupportedNativeMetadata;
    if (root_pos < header.pos or root_pos >= bytes.len) return error.UnsupportedNativeMetadata;
    var r: Reader = .{ .bytes = bytes, .pos = root_pos };
    if (try r.byte() != 0) return error.UnsupportedNativeMetadata;
    const triple = try r.string();
    const hash = std.mem.readInt(u128, (try r.take(16))[0..16], .little);
    const name = (try r.symbol()) orelse return error.UnsupportedNativeMetadata;
    const proc_macro = try r.boolean();
    if (proc_macro or try r.boolean()) return error.UnsupportedNativeMetadata;
    const extra = try r.string();
    const full_name = try std.mem.concat(a, u8, &.{ name, extra });
    try nameValid(full_name);
    _ = try r.take(8);
    if (try r.boolean()) if (try r.byte() > 1) return error.UnsupportedNativeMetadata;
    if (try r.byte() > 1 or try r.byte() > 4) return error.UnsupportedNativeMetadata;
    for (0..4) |_| _ = try r.boolean();
    var previous: ?usize = null;
    var count: usize = 0;
    var position: usize = 0;
    // extern implementable items, then crate_deps; preserve lazy pointer state.
    for (0..2) |_| {
        count = try r.integer();
        if (count != 0) {
            const distance = try r.integer();
            position = if (previous) |p| std.math.add(usize, p, distance) catch return error.UnsupportedNativeMetadata else std.math.sub(usize, root_pos, distance) catch return error.UnsupportedNativeMetadata;
            if (position < header.pos or position >= root_pos) return error.UnsupportedNativeMetadata;
            previous = position;
        }
    }
    if (count > 65536) return error.UnsupportedNativeMetadata;
    var dependencies: std.ArrayList(Crate) = .empty;
    var d: Reader = .{ .bytes = bytes[0..root_pos], .pos = position };
    for (0..count) |_| {
        const dep_name = (try d.symbol()) orelse return error.UnsupportedNativeMetadata;
        const dep_hash = std.mem.readInt(u128, (try d.take(16))[0..16], .little);
        if (try d.boolean()) _ = try d.take(16);
        const kind = try d.byte();
        if (kind > 2) return error.UnsupportedNativeMetadata;
        const dep_extra = try d.string();
        _ = try d.boolean();
        const dep_full = try std.mem.concat(a, u8, &.{ dep_name, dep_extra });
        try nameValid(dep_full);
        try dependencies.append(a, .{ .name = dep_full, .hash = try std.fmt.allocPrint(a, "{x:0>32}", .{dep_hash}), .proc_macro = kind == 0 });
    }
    return .{ .root = .{ .name = full_name, .hash = try std.fmt.allocPrint(a, "{x:0>32}", .{hash}), .triple = triple, .proc_macro = proc_macro }, .dependencies = dependencies.items };
}

pub fn main(init: std.process.Init) !void {
    const a = init.arena.allocator();
    const args = try init.minimal.args.toSlice(a);
    const Row = struct { file: []const u8, graph: ?Graph = null, failure: ?[]const u8 = null };
    var rows: std.ArrayList(Row) = .empty;
    for (args[1..]) |path| {
        const input = try @import("cache.zig").readMetadata(init.io, a, path);
        const graph = decode(a, input) catch |err| {
            try rows.append(a, .{ .file = path, .failure = @errorName(err) });
            continue;
        };
        try rows.append(a, .{ .file = path, .graph = graph });
    }
    const output = try std.json.Stringify.valueAlloc(a, rows.items, .{});
    try std.Io.File.stdout().writeStreamingAll(init.io, output);
}

test "unknown and truncated metadata refuses" {
    try std.testing.expectError(error.UnsupportedNativeMetadata, decode(std.testing.allocator, ""));
    try std.testing.expectError(error.UnsupportedNativeMetadata, decode(std.testing.allocator, "rust\x00\x00\x00\x0a00000000rust-end-file"));
}
