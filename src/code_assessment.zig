//! macOS assesses a Mach-O file the first time any process registers its code
//! signature for library validation, and caches the result on that file. Every
//! restore creates new files, so without help the first compiler to load a
//! restored proc-macro dylib waits for the assessment inside its frontend, one
//! dylib at a time. On a busy system policy service that is about 0.3 s per
//! dylib, on the build's critical path.
//!
//! `prewarm` starts the assessment as soon as the dylib is restored, in a
//! detached child that registers the signature and runs the library-validation
//! check. Nothing from the dylib is executed. The request does not wait for the
//! child. A compiler that loads the dylib later finds it already assessed.
//! NANOCOMPILE_PREWARM_CODE=0 disables it.
const std = @import("std");
const builtin = @import("builtin");
const cache = @import("cache.zig");

extern "c" fn fork() c_int;
extern "c" fn _exit(code: c_int) noreturn;
extern "c" fn open(path: [*:0]const u8, flags: c_int, ...) c_int;
extern "c" fn close(fd: c_int) c_int;
extern "c" fn dup2(old: c_int, new: c_int) c_int;
extern "c" fn pread(fd: c_int, buffer: [*]u8, size: usize, offset: i64) isize;
extern "c" fn fcntl(fd: c_int, command: c_int, ...) c_int;
extern "c" fn getdtablesize() c_int;

const F_ADDFILESIGS_RETURN = 97;
const F_CHECK_LV = 98;
const MH_MAGIC_64 = 0xfeedfacf;
const LC_CODE_SIGNATURE = 0x1d;

const FSignatures = extern struct {
    file_start: i64,
    blob_start: ?*anyopaque,
    blob_size: usize,
    fsignatures_size: usize = 0,
    cdhash: [20]u8 = @splat(0),
    hash_type: c_int = 0,
};

const CheckLibraryValidation = extern struct {
    file_start: i64,
    error_message_size: usize,
    error_message: ?*anyopaque,
};

pub fn prewarm(ctx: *cache.Context, paths: []const []const u8) void {
    if (builtin.os.tag != .macos) return;
    if (std.mem.eql(u8, ctx.env.get("NANOCOMPILE_PREWARM_CODE") orelse "1", "0")) return;
    // Paths are prepared before fork; the child only makes async-signal-safe calls.
    var names: [64][*:0]const u8 = undefined;
    var count: usize = 0;
    for (paths) |path| {
        if (count == names.len or !std.mem.endsWith(u8, path, ".dylib")) continue;
        names[count] = (ctx.a.dupeSentinel(u8, path, 0) catch return).ptr;
        count += 1;
    }
    if (count == 0) return;
    const pid = fork();
    if (pid != 0) return; // Parent (or failed fork): never wait.
    // The child must not hold Cargo's output pipes or the cache locks open.
    const null_fd = open("/dev/null", 2);
    if (null_fd >= 0) {
        _ = dup2(null_fd, 0);
        _ = dup2(null_fd, 1);
        _ = dup2(null_fd, 2);
    }
    var fd: c_int = 3;
    const limit = @min(getdtablesize(), 65536);
    while (fd < limit) : (fd += 1) _ = close(fd);
    for (names[0..count]) |name| assess(name);
    _exit(0);
}

fn assess(path: [*:0]const u8) void {
    const fd = open(path, 0);
    if (fd < 0) return;
    defer _ = close(fd);
    var header: [32]u8 align(8) = undefined;
    if (pread(fd, &header, header.len, 0) != header.len) return;
    if (std.mem.readInt(u32, header[0..4], .little) != MH_MAGIC_64) return;
    const ncmds = std.mem.readInt(u32, header[16..20], .little);
    const sizeofcmds = std.mem.readInt(u32, header[20..24], .little);
    var commands: [65536]u8 = undefined;
    if (sizeofcmds > commands.len) return;
    if (pread(fd, &commands, sizeofcmds, header.len) != sizeofcmds) return;
    var offset: usize = 0;
    var i: u32 = 0;
    while (i < ncmds and offset + 16 <= sizeofcmds) : (i += 1) {
        const cmd = std.mem.readInt(u32, commands[offset..][0..4], .little);
        const size = std.mem.readInt(u32, commands[offset + 4 ..][0..4], .little);
        if (size < 8) return;
        if (cmd == LC_CODE_SIGNATURE) {
            const data_offset = std.mem.readInt(u32, commands[offset + 8 ..][0..4], .little);
            const data_size = std.mem.readInt(u32, commands[offset + 12 ..][0..4], .little);
            var signatures: FSignatures = .{ .file_start = 0, .blob_start = @ptrFromInt(data_offset), .blob_size = data_size };
            if (fcntl(fd, F_ADDFILESIGS_RETURN, &signatures) != 0) return;
            var message: [256]u8 = undefined;
            var check: CheckLibraryValidation = .{ .file_start = 0, .error_message_size = message.len, .error_message = &message };
            _ = fcntl(fd, F_CHECK_LV, &check);
            return;
        }
        offset += size;
    }
}
