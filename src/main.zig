const std = @import("std");
const builtin = @import("builtin");
const cache = @import("cache.zig");
const compiler = @import("compiler.zig");
const xcode = @import("xcode.zig");

comptime {
    if (builtin.os.tag != .macos and builtin.os.tag != .linux)
        @compileError("nanocompile currently supports macOS and Linux");
    if (!std.mem.eql(u8, builtin.zig_version_string, "0.17.0"))
        @compileError("build nanocompile with stable Zig 0.17.0");
}

const help =
    \\nanocompile 0.1.0 — shared Rust and Zig compilation cache
    \\Usage:
    \\  nanocompile zig build-exe|build-obj|build-lib FILE -femit-bin=OUTPUT [FLAGS]
    \\  nanocompile rustc [RUSTC FLAGS]
    \\  nanocompile xcodebuild [XCODE FLAGS]  use Xcode native Swift/Clang CAS (macOS)
    \\  RUSTC_WRAPPER=/absolute/path/nanocompile cargo build
    \\  nanocompile artifact put|get|head NAMESPACE KEY [FILE] [METADATA_JSON]
    \\  nanocompile stats | clear | doctor
    \\  nanocompile gc [MAX_BYTES]  remove orphan blobs and evict to a budget
    \\Environment:
    \\  NANOCOMPILE_DIR       cache directory (default: $XDG_CACHE_HOME/nanocompile)
    \\  NANOCOMPILE_TRACE=1   print cache decisions to stderr
    \\  NANOCOMPILE_DISABLE=1 run the compiler without caching
    \\  NANOCOMPILE_PROC_MACROS=reported  opt into compiler-reported macro inputs
    \\  NANOCOMPILE_EXTRA_INPUTS_FILE    JSON array declaring additional files
    \\  NANOCOMPILE_ZIG       Zig executable (default: zig)
    \\  NANOCOMPILE_RUSTC     rustc executable (default: rustc)
    \\Unsupported invocations transparently run the original compiler.
    \\
;

pub fn main(init: std.process.Init) void {
    const a = init.arena.allocator();
    const args = init.minimal.args.toSlice(a) catch std.process.exit(1);
    var ctx = cache.Context.init(a, init.io, init.environ_map) catch |err| {
        std.debug.print("nanocompile: {s}\n", .{@errorName(err)});
        std.process.exit(1);
    };
    const code = dispatch(&ctx, args) catch |err| blk: {
        std.debug.print("nanocompile: {s}\n", .{@errorName(err)});
        break :blk @as(u8, 1);
    };
    std.process.exit(code);
}

fn dispatch(ctx: *cache.Context, args: []const [:0]const u8) !u8 {
    if (args.len < 2 or std.mem.eql(u8, args[1], "--help") or std.mem.eql(u8, args[1], "help")) {
        try ctx.out(help);
        return 0;
    }
    const command = args[1];
    if (std.mem.eql(u8, command, "xcodebuild")) return xcode.execute(ctx, args[2..]);
    if (std.mem.eql(u8, command, "artifact")) {
        if (args.len < 5) return error.MissingArtifactArguments;
        const op = args[2];
        const namespace = args[3];
        const key = args[4];
        const put = std.mem.eql(u8, op, "put");
        const get = std.mem.eql(u8, op, "get");
        const head = std.mem.eql(u8, op, "head");
        if ((!put and !get and !head) or (put and (args.len < 6 or args.len > 7)) or
            (get and args.len != 6) or (head and args.len != 5)) return error.InvalidArtifactArguments;
        try ctx.prepare();
        const maintenance = try cache.Lock.acquire(ctx, "maintenance", false);
        defer maintenance.release();
        const lock = try cache.Lock.acquire(ctx, try cache.artifactKey(ctx, namespace, key), put);
        defer lock.release();
        if (put) {
            try cache.storeArtifact(ctx, namespace, key, args[5], if (args.len == 7) args[6] else "{}");
            try ctx.out("{\"stored\":true}\n");
            return 0;
        }
        if (try cache.fetchArtifact(ctx, namespace, key, if (get) args[5] else null)) return 0;
        try ctx.out("{\"hit\":false}\n");
        return 3;
    }
    if (std.mem.eql(u8, command, "--version")) {
        try ctx.out("nanocompile 0.1.0 (Zig 0.17.0)\n");
        return 0;
    }
    if (std.mem.eql(u8, command, "stats")) {
        try cache.stats(ctx);
        return 0;
    }
    if (std.mem.eql(u8, command, "clear")) {
        try cache.clear(ctx);
        return 0;
    }
    if (std.mem.eql(u8, command, "gc")) {
        const limit = if (args.len > 2) try std.fmt.parseInt(u64, args[2], 10) else 10 * 1024 * 1024 * 1024;
        try cache.gc(ctx, limit);
        return 0;
    }
    if (std.mem.eql(u8, command, "doctor")) {
        try ctx.out(try std.fmt.allocPrint(ctx.a, "cache: {s}\nplatform: {s}\nrestore: copy-on-write clone, falling back to independent copy\n", .{ ctx.root, @tagName(builtin.os.tag) }));
        try ctx.prepare();
        return 0;
    }
    var argv: std.ArrayList([]const u8) = .empty;
    const kind: compiler.Kind = if (std.mem.eql(u8, command, "zig")) .zig else .rust;
    if (std.mem.eql(u8, command, "zig") or std.mem.eql(u8, command, "rustc")) {
        try argv.append(ctx.a, ctx.env.get(if (kind == .zig) "NANOCOMPILE_ZIG" else "NANOCOMPILE_RUSTC") orelse command);
    } else {
        // Cargo's RUSTC_WRAPPER protocol supplies the compiler as argv[1].
        try argv.append(ctx.a, command);
    }
    for (args[2..]) |arg| try argv.append(ctx.a, arg);
    return compiler.execute(ctx, kind, argv.items);
}

test {
    _ = cache;
    _ = compiler;
    _ = @import("link_dependencies.zig");
}
