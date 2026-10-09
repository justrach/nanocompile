//! An exact-version reader for native libraries recorded in completed Rust
//! metadata. Private format changes and unsupported records retain refusal.
const std = @import("std");
const metadata = @import("rust_metadata.zig");
const Error = error{ UnsupportedNativeMetadata, HiddenNativeLinkInput };
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
            2 => blk: {
                if (try self.integer() > std.math.maxInt(u32)) return error.UnsupportedNativeMetadata;
                break :blk null; // Pinned rustc's predefined symbol table.
            },
            else => error.UnsupportedNativeMetadata,
        };
    }
};

/// Only ordinary rmeta is accepted. The caller obtains `expected` from rustc's
/// independent reader for the very same content-checked completed artifact.
pub fn dynamicOnly(input: []const u8, expected: metadata.Root) Error!void {
    const end = "rust-end-file";
    if (input.len < 29 or !std.mem.startsWith(u8, input, "rust\x00\x00\x00\x0a") or !std.mem.endsWith(u8, input, end)) return error.UnsupportedNativeMetadata;
    const bytes = input[0 .. input.len - end.len];
    var header: Reader = .{ .bytes = bytes, .pos = 16 };
    if (!std.mem.eql(u8, try header.string(), version)) return error.UnsupportedNativeMetadata;
    const root = std.math.cast(usize, std.mem.readInt(u64, bytes[8..16], .little)) orelse return error.UnsupportedNativeMetadata;
    if (root < header.pos or root >= bytes.len) return error.UnsupportedNativeMetadata;
    var r: Reader = .{ .bytes = bytes, .pos = root };
    if (try r.byte() != 0) return error.UnsupportedNativeMetadata; // Custom JSON target.
    const triple = try r.string();
    if (!std.mem.eql(u8, triple, expected.triple) or expected.proc_macro) return error.UnsupportedNativeMetadata;
    if (!std.mem.endsWith(u8, triple, "-apple-darwin") and !std.mem.endsWith(u8, triple, "-unknown-linux-gnu") and !std.mem.endsWith(u8, triple, "-unknown-linux-musl")) return error.UnsupportedNativeMetadata;
    const hash = std.mem.readInt(u128, (try r.take(16))[0..16], .little);
    const expected_hash = std.fmt.parseInt(u128, expected.hash, 16) catch return error.UnsupportedNativeMetadata;
    if (hash != expected_hash) return error.UnsupportedNativeMetadata;
    const name = try r.symbol();
    if (try r.boolean() or try r.boolean()) return error.UnsupportedNativeMetadata; // Macro/stub.
    const extra = try r.string();
    if (!std.mem.endsWith(u8, expected.name, extra)) return error.UnsupportedNativeMetadata;
    if (name) |text| {
        if (!std.mem.eql(u8, text, expected.name[0 .. expected.name.len - extra.len])) return error.UnsupportedNativeMetadata;
    }
    _ = try r.take(8); // StableCrateId.
    if (try r.boolean()) if (try r.byte() > 1) return error.UnsupportedNativeMetadata;
    if (try r.byte() > 1 or try r.byte() > 4) return error.UnsupportedNativeMetadata;
    for (0..4) |_| _ = try r.boolean();
    var previous: ?usize = null;
    var count: usize = 0;
    var position: usize = 0;
    // Nine preceding lazy arrays, then native_libraries. Empty arrays have no
    // pointer; first nonempty pointer is backward, subsequent ones forward.
    for (0..10) |_| {
        count = try r.integer();
        if (count != 0) {
            const distance = try r.integer();
            position = if (previous) |p| std.math.add(usize, p, distance) catch return error.UnsupportedNativeMetadata else std.math.sub(usize, root, distance) catch return error.UnsupportedNativeMetadata;
            if (position < header.pos or position >= root) return error.UnsupportedNativeMetadata;
            previous = position;
        }
    }
    if (count > 128) return error.UnsupportedNativeMetadata;
    var native: Reader = .{ .bytes = bytes[0..root], .pos = position };
    for (0..count) |_| {
        switch (try native.byte()) {
            1, 3 => try native.optionBool(), // Dylib / framework.
            6 => {}, // Unspecified means the compiler's default dynamic kind.
            else => return error.HiddenNativeLinkInput,
        }
        _ = try native.symbol();
        if (try native.boolean()) return error.HiddenNativeLinkInput; // Bundled filename.
        if (try native.boolean()) return error.UnsupportedNativeMetadata; // CfgEntry.
        if (try native.boolean()) {
            _ = try native.integer(); // CrateNum.
            _ = try native.integer(); // DefIndex.
        }
        try native.optionBool(); // Verbatim name.
        if (try native.integer() != 0) return error.HiddenNativeLinkInput; // DLL imports.
    }
}

test "native metadata refuses unknown and truncated formats" {
    const root: metadata.Root = .{ .name = "test", .hash = "00000000000000000000000000000000", .triple = "aarch64-apple-darwin", .proc_macro = false };
    try std.testing.expectError(error.UnsupportedNativeMetadata, dynamicOnly("", root));
    try std.testing.expectError(error.UnsupportedNativeMetadata, dynamicOnly("rust\x00\x00\x00\x0a00000000rust-end-file", root));
    var reader: Reader = .{ .bytes = &.{ 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x02 } };
    try std.testing.expectError(error.UnsupportedNativeMetadata, reader.integer());
}
