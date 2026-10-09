//! Private cache-hit worker: copy beside an exported src/cache.zig/compiler.zig.
//! Entire content verification remains in the ordinary compiler/cache path.
const std = @import("std");
const cache = @import("cache.zig");
const compiler = @import("compiler.zig");
extern "c" fn nc_worker_listen(path: [*:0]const u8) c_int;
extern "c" fn nc_worker_accept(listener: c_int) c_int;
extern "c" fn nc_worker_read(fd: c_int, data: [*]u8, size: usize) c_int;
extern "c" fn nc_worker_reply_memory(fd: c_int, code: u8, out: ?[*]const u8, out_len: usize, err: ?[*]const u8, err_len: usize) c_int;
extern "c" fn chdir(path: [*:0]const u8) c_int;
const Request = struct { argv: []const []const u8, cwd: []const u8, env: []const [2][]const u8, observer: ?[]const u8 = null };

fn serve(init: std.process.Init, fd: c_int) !u8 {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var header: [4]u8 = undefined;
    if (nc_worker_read(fd, &header, 4) != 0) return error.InvalidFrame;
    const size = std.mem.readInt(u32, &header, .little);
    if (size == 0 or size > 1024 * 1024) return error.InvalidFrame;
    const payload = try a.alloc(u8, size);
    if (nc_worker_read(fd, payload.ptr, size) != 0) return error.InvalidFrame;
    const parsed = try std.json.parseFromSlice(Request, a, payload, .{});
    var stdout: std.ArrayList(u8) = .empty;
    var stderr: std.ArrayList(u8) = .empty;
    const code = executeRequest(init, a, parsed.value, &stdout, &stderr) catch 200;
    _ = nc_worker_reply_memory(fd, code, stdout.items.ptr, stdout.items.len, stderr.items.ptr, stderr.items.len);
    return code;
}

fn executeRequest(init: std.process.Init, a: std.mem.Allocator, req: Request, stdout: *std.ArrayList(u8), stderr: *std.ArrayList(u8)) !u8 {
    if (req.argv.len < 2 or req.argv.len > 4096 or req.env.len > 8192 or !std.fs.path.isAbsolute(req.cwd)) return 200;
    for (req.argv) |arg| if (std.mem.indexOfScalar(u8, arg, 0) != null) return 200;
    if (std.mem.indexOfScalar(u8, req.cwd, 0) != null) return 200;
    var env = std.process.Environ.Map.init(a);
    defer env.deinit();
    for (req.env) |pair| {
        if (pair[0].len == 0 or std.mem.indexOfScalar(u8, pair[0], '=') != null or
            std.mem.indexOfScalar(u8, pair[0], 0) != null or std.mem.indexOfScalar(u8, pair[1], 0) != null) return 200;
        try env.put(pair[0], pair[1]);
    }
    // One connection executes at a time in EACH worker process. All grouped
    // tasks and locks have completed/released before changing cwd again.
    const cwd = try a.dupeSentinel(u8, req.cwd, 0);
    if (chdir(cwd) != 0) return 200;
    var ctx = try cache.Context.init(a, init.io, &env);
    ctx.restore_only = true;
    if (req.observer) |observer| {
        if (!std.fs.path.isAbsolute(observer) or observer.len > 4096 or std.mem.indexOfScalar(u8, observer, 0) != null) return 200;
        ctx.producer_observer = observer;
    }
    ctx.stdout_capture = stdout;
    ctx.stderr_capture = stderr;
    const command = req.argv[1];
    const kind: compiler.Kind = if (std.mem.eql(u8, command, "zig")) .zig else .rust;
    var argv: std.ArrayList([]const u8) = .empty;
    const executable = if (std.mem.eql(u8, command, "zig") or std.mem.eql(u8, command, "rustc"))
        env.get(if (kind == .zig) "NANOCOMPILE_ZIG" else "NANOCOMPILE_RUSTC") orelse command
    else if (std.mem.eql(u8, std.fs.path.basename(command), "rustc")) command else return 200;
    try argv.append(a, executable);
    try argv.appendSlice(a, req.argv[2..]);
    return compiler.execute(&ctx, kind, argv.items);
}

pub fn main(init: std.process.Init) !void {
    if (@import("builtin").os.tag != .macos) @compileError("macOS experiment");
    const args = try init.minimal.args.toSlice(init.arena.allocator());
    if (args.len != 2) return error.ExpectedSocketPath;
    const path = try init.arena.allocator().dupeSentinel(u8, args[1], 0);
    const listener = nc_worker_listen(path);
    if (listener < 0) return error.CannotListen;
    defer _ = std.c.close(listener);
    while (true) {
        const fd = nc_worker_accept(listener);
        if (fd == -2) continue;
        if (fd < 0) return error.AcceptFailed;
        defer _ = std.c.close(fd);
        const code = serve(init, fd) catch blk: {
            _ = nc_worker_reply_memory(fd, 200, null, 0, null, 0);
            break :blk @as(u8, 200);
        };
        std.debug.print("restore worker result: {d}\n", .{code});
    }
}
