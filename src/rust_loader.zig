//! Narrow proof that stock Darwin rustc's startup libraries do not use fallback
//! search. Only the direct installation and ordinary system load paths qualify.
const std = @import("std");
const cache = @import("cache.zig");
const builtin = @import("builtin");
const Dir = std.Io.Dir;

fn word(bytes: []const u8, offset: usize) !u32 {
    if (offset > bytes.len or bytes.len - offset < 4) return error.InvalidMachO;
    return std.mem.readInt(u32, bytes[offset..][0..4], .little);
}
fn string(bytes: []const u8, offset: usize) ![]const u8 {
    if (offset >= bytes.len) return error.InvalidMachO;
    const end = std.mem.indexOfScalar(u8, bytes[offset..], 0) orelse return error.InvalidMachO;
    return bytes[offset..][0..end];
}
fn header(ctx: *cache.Context, path: []const u8) ![]const u8 {
    const file = try Dir.cwd().openFile(ctx.io, path, .{});
    defer file.close(ctx.io);
    if ((try file.stat(ctx.io)).kind != .file) return error.InvalidMachO;
    var reader = file.reader(ctx.io, &.{});
    var fixed: [32]u8 = undefined;
    try reader.interface.readSliceAll(&fixed);
    if (try word(&fixed, 0) != 0xfeedfacf) return error.InvalidMachO;
    const size = try word(&fixed, 20);
    if (size > 65536) return error.InvalidMachO;
    const result = try ctx.a.alloc(u8, 32 + size);
    @memcpy(result[0..32], &fixed);
    try reader.interface.readSliceAll(result[32..]);
    return result;
}
fn loads(bytes: []const u8, executable: bool) !?[]const u8 {
    if (bytes.len < 32 or try word(bytes, 0) != 0xfeedfacf) return error.InvalidMachO;
    if (try word(bytes, 12) != (if (executable) @as(u32, 2) else @as(u32, 6))) return error.InvalidMachO;
    const count = try word(bytes, 16);
    const size = try word(bytes, 20);
    if (size != bytes.len - 32) return error.InvalidMachO;
    var offset: usize = 32;
    var driver: ?[]const u8 = null;
    var rpaths: usize = 0;
    for (0..count) |_| {
        const cmd = try word(bytes, offset);
        const length = try word(bytes, offset + 4);
        if (length < 8 or length > bytes.len - offset) return error.InvalidMachO;
        const command = bytes[offset..][0..length];
        switch (cmd) {
            0xc => {
                if (length < 24) return error.InvalidMachO;
                const name_offset = try word(command, 8);
                if (name_offset < 24) return error.InvalidMachO;
                const value = try string(command, name_offset);
                if (std.mem.startsWith(u8, value, "/usr/lib/") or std.mem.startsWith(u8, value, "/System/Library/")) {
                    if (std.mem.indexOf(u8, value, "/../") != null) return error.InvalidMachO;
                } else if (executable and driver == null and std.mem.startsWith(u8, value, "@rpath/librustc_driver-") and std.mem.endsWith(u8, value, ".dylib") and std.mem.indexOfScalar(u8, value[7..], '/') == null) {
                    driver = value[7..];
                } else return error.UnprovenLoadPath;
            },
            0x8000001c => {
                const name_offset = try word(command, 8);
                if (name_offset < 12) return error.InvalidMachO;
                if (!std.mem.eql(u8, try string(command, name_offset), "@loader_path/../lib")) return error.UnprovenLoadPath;
                rpaths += 1;
            },
            0x80000018, 0x8000001f, 0x20, 0x80000023 => return error.UnprovenLoadPath,
            else => {},
        }
        offset += length;
    }
    if (offset != bytes.len or rpaths > 1 or (executable and (rpaths != 1 or driver == null))) return error.UnprovenLoadPath;
    return driver;
}

pub fn allowsFallback(ctx: *cache.Context, compiler: []const u8, sysroot: []const u8) !bool {
    if (builtin.os.tag != .macos) return false;
    for (ctx.env.keys()) |name| {
        if (std.mem.eql(u8, name, "DYLD_FALLBACK_LIBRARY_PATH")) continue;
        if (std.mem.startsWith(u8, name, "DYLD_") or std.mem.startsWith(u8, name, "LD_")) return false;
    }
    const installed = try std.fs.path.join(ctx.a, &.{ sysroot, "bin", "rustc" });
    if (!std.mem.eql(u8, compiler, installed)) return false;
    const driver = (try loads(try header(ctx, compiler), true)) orelse return false;
    const path = try std.fs.path.join(ctx.a, &.{ sysroot, "lib", driver });
    // The matching file is part of rustResources' ordinary content fingerprint
    // and stamp revalidation. External symlinked implementations do not qualify.
    if (!std.mem.eql(u8, path, try Dir.cwd().realPathFileAlloc(ctx.io, path, ctx.a))) return false;
    _ = try loads(try header(ctx, path), false);
    return true;
}

test "malformed and unsupported loader headers refuse reuse" {
    try std.testing.expectError(error.InvalidMachO, loads("short", true));
    var header_bytes: [32]u8 = @splat(0);
    std.mem.writeInt(u32, header_bytes[0..4], 0xfeedfacf, .little);
    std.mem.writeInt(u32, header_bytes[12..16], 2, .little);
    try std.testing.expectError(error.UnprovenLoadPath, loads(&header_bytes, true));
    header_bytes[0] = 0;
    try std.testing.expectError(error.InvalidMachO, loads(&header_bytes, true));
}
