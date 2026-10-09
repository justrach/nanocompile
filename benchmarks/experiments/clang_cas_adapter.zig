//! Private Cargo native-compiler experiment. Clang owns dependency scanning/replay.
const std = @import("std");
const config = @import("config");

fn compileOnly(args: []const [:0]const u8) bool {
    var compile = false;
    for (args) |arg| {
        if (std.mem.eql(u8, arg, "-c")) compile = true;
        for ([_][]const u8{ "-E", "-S", "-M", "-MM", "-###", "--version", "-v", "-cc1", "-cc1as", "-" }) |probe|
            if (std.mem.eql(u8, arg, probe)) return false;
    }
    return compile;
}

pub fn main(init: std.process.Init) !void {
    const a = init.arena.allocator();
    const args = try init.minimal.args.toSlice(a);
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.append(a, config.clang);
    var explicit_sysroot = false;
    for (args[1..]) |arg| {
        if (std.mem.eql(u8, arg, "-isysroot") or std.mem.eql(u8, arg, "--sysroot") or
            std.mem.startsWith(u8, arg, "--sysroot=") or std.mem.startsWith(u8, arg, "-isysroot=")) explicit_sysroot = true;
    }
    if (!explicit_sysroot) {
        const sdk = init.environ_map.get("SDKROOT") orelse config.sdk;
        try argv.appendSlice(a, &.{ "-isysroot", sdk });
    }
    if (compileOnly(args[1..])) {
        // Keep the diagnostic option identical in both controls. Its reported
        // hit/miss proves service use without a separate capture process.
        try argv.append(a, "-Rcompile-job-cache");
        if (init.environ_map.get("NANOCOMPILE_CLANG_CAS")) |cas| {
            if (!std.fs.path.isAbsolute(cas)) return error.CASRequiresAbsolutePath;
            try argv.appendSlice(a, &.{ "-fdepscan=inline", "-Xclang", "-fcas-path", "-Xclang", cas, "-Xclang", "-fcache-compile-job" });
            if (!config.enabled) try argv.appendSlice(a, &.{ "-Xclang", "-fcache-disable-replay" });
        }
    }
    try argv.appendSlice(a, args[1..]);
    if (compileOnly(args[1..])) {
        const result = try std.process.run(a, init.io, .{ .argv = argv.items, .environ_map = init.environ_map, .stdout_limit = .limited(64 * 1024 * 1024), .stderr_limit = .limited(64 * 1024 * 1024) });
        try std.Io.File.stdout().writeStreamingAll(init.io, result.stdout);
        try std.Io.File.stderr().writeStreamingAll(init.io, result.stderr);
        if (init.environ_map.get("NANOCOMPILE_CLANG_EVENTS")) |events| {
            const path = try std.fmt.allocPrint(a, "{s}/{d}-{d}.json", .{ events, std.c.getpid(), std.Io.Clock.awake.now(init.io).nanoseconds });
            const file = try std.Io.Dir.cwd().createFile(init.io, path, .{ .exclusive = true });
            defer file.close(init.io);
            const json = try std.json.Stringify.valueAlloc(a, .{
                .replay_enabled = config.enabled,
                .hit = std.mem.indexOf(u8, result.stderr, "remark: compile job cache hit") != null,
                .miss = std.mem.indexOf(u8, result.stderr, "remark: compile job cache miss") != null,
                .skipped = std.mem.indexOf(u8, result.stderr, "remark: compile job cache skipped") != null,
                .exit_code = code(result.term),
            }, .{});
            try file.writeStreamingAll(init.io, json);
        }
        std.process.exit(code(result.term));
    }
    var child = try std.process.spawn(init.io, .{ .argv = argv.items, .environ_map = init.environ_map });
    std.process.exit(code(try child.wait(init.io)));
}

fn code(term: std.process.Child.Term) u8 {
    return switch (term) {
        .exited => |v| v,
        .signal => |v| @intCast(@min(255, 128 + @as(u32, @backingInt(v)))),
        else => 1,
    };
}
