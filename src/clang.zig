//! Explicit Apple Clang CAS adapter. Build scripts remain live; Clang owns keys,
//! input discovery and replay. Inline scanning can change debug representation.
const std = @import("std");
const builtin = @import("builtin");
const cache = @import("cache.zig");
const identity = @import("identity.zig");

fn code(term: std.process.Child.Term) u8 {
    return switch (term) {
        .exited => |v| v,
        .signal => |v| @intCast(@min(255, 128 + @as(u32, @backingInt(v)))),
        else => 1,
    };
}
fn run(ctx: *cache.Context, argv: []const []const u8) !u8 {
    var child = try std.process.spawn(ctx.io, .{ .argv = argv, .environ_map = ctx.env });
    return code(try child.wait(ctx.io));
}
fn enabled(ctx: *cache.Context, name: []const u8) bool {
    return if (ctx.env.get(name)) |v| std.mem.eql(u8, v, "1") else false;
}
fn selected(ctx: *cache.Context) ![]const u8 {
    if (ctx.env.get("NANOCOMPILE_CLANG")) |tool| return identity.selectedExecutable(ctx, tool);
    if (builtin.os.tag != .macos) return "clang";
    const result = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ "xcrun", "--find", "clang" }, .environ_map = ctx.env });
    if (code(result.term) != 0) return error.ClangSelectionFailed;
    const path = std.mem.trim(u8, result.stdout, "\r\n ");
    if (!std.fs.path.isAbsolute(path)) return error.InvalidClangSelection;
    return identity.selectedExecutable(ctx, path);
}
fn compileOnly(args: []const []const u8) bool {
    var compile = false;
    var arches: usize = 0;
    for (args, 0..) |arg, i| {
        if (std.mem.eql(u8, arg, "-c")) compile = true;
        if (std.mem.eql(u8, arg, "-arch")) arches += 1;
        for ([_][]const u8{ "-E", "-S", "-M", "-MM", "-###", "--version", "-v", "-cc1", "-cc1as", "-" }) |probe|
            if (std.mem.eql(u8, arg, probe)) return false;
        // Response files and caller-owned CAS/scanner settings retain Clang's
        // own command unmodified. This command does not rewrite those policies.
        if (std.mem.eql(u8, arg, "/dev/stdin") or std.mem.startsWith(u8, arg, "/dev/fd/") or std.mem.startsWith(u8, arg, "/proc/self/fd/") or std.mem.startsWith(u8, arg, "@") or std.mem.startsWith(u8, arg, "-fcas") or
            std.mem.startsWith(u8, arg, "-fcache") or std.mem.startsWith(u8, arg, "-fdepscan")) return false;
        const target = if (std.mem.startsWith(u8, arg, "--target=")) arg[9..] else if ((std.mem.eql(u8, arg, "--target") or std.mem.eql(u8, arg, "-target")) and i + 1 < args.len) args[i + 1] else null;
        if (target) |t| if (std.mem.indexOf(u8, t, "apple-macos") == null and std.mem.indexOf(u8, t, "apple-darwin") == null) return false;
    }
    return compile and arches <= 1;
}
fn hasSysroot(args: []const []const u8) bool {
    for (args) |arg| if (std.mem.startsWith(u8, arg, "-isysroot") or std.mem.eql(u8, arg, "--sysroot") or std.mem.startsWith(u8, arg, "--sysroot=")) return true;
    return false;
}
fn sdk(ctx: *cache.Context) ![]const u8 {
    if (ctx.env.get("SDKROOT")) |root| if (root.len != 0) return root;
    const result = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ "xcrun", "--sdk", "macosx", "--show-sdk-path" }, .environ_map = ctx.env });
    if (code(result.term) != 0) return error.ClangSDKSelectionFailed;
    const root = std.mem.trim(u8, result.stdout, "\r\n ");
    if (!std.fs.path.isAbsolute(root)) return error.InvalidClangSDK;
    return root;
}
// Experimental overlap: SDK query buffers never share the caller's arena.
const SdkQuery = struct {
    result: ?std.process.RunResult = null,
    failure: ?anyerror = null,

    fn run(q: *SdkQuery, io: std.Io, env: *const std.process.Environ.Map) void {
        q.result = std.process.run(std.heap.page_allocator, io, .{ .argv = &.{ "xcrun", "--sdk", "macosx", "--show-sdk-path" }, .environ_map = env }) catch |err| {
            q.failure = err;
            return;
        };
    }
    fn deinit(q: *SdkQuery) void {
        if (q.result) |r| {
            std.heap.page_allocator.free(r.stdout);
            std.heap.page_allocator.free(r.stderr);
        }
    }
    fn value(q: *SdkQuery) ![]const u8 {
        if (q.failure) |err| return err;
        const result = q.result orelse return error.ClangSDKSelectionFailed;
        if (code(result.term) != 0) return error.ClangSDKSelectionFailed;
        const root = std.mem.trim(u8, result.stdout, "\r\n ");
        if (!std.fs.path.isAbsolute(root)) return error.InvalidClangSDK;
        return root;
    }
};

fn nativeExecutable(ctx: *cache.Context, tool: []const u8) bool {
    const file = std.Io.Dir.cwd().openFile(ctx.io, tool, .{}) catch return false;
    defer file.close(ctx.io);
    var magic: [4]u8 = undefined;
    if ((file.readPositional(ctx.io, &.{&magic}, 0) catch return false) != 4) return false;
    for ([_][4]u8{ .{ 0xcf, 0xfa, 0xed, 0xfe }, .{ 0xce, 0xfa, 0xed, 0xfe }, .{ 0xfe, 0xed, 0xfa, 0xcf }, .{ 0xfe, 0xed, 0xfa, 0xce }, .{ 0xca, 0xfe, 0xba, 0xbe }, .{ 0xca, 0xfe, 0xba, 0xbf }, .{ 0xbe, 0xba, 0xfe, 0xca }, .{ 0xbf, 0xba, 0xfe, 0xca } }) |candidate|
        if (std.mem.eql(u8, &magic, &candidate)) return true;
    return false;
}
fn supports(ctx: *cache.Context, tool: []const u8, hash: []const u8) !bool {
    const memo = try ctx.path(&.{ "metadata", try std.fmt.allocPrint(ctx.a, "clang-cas-capability-{s}", .{hash}) });
    if (ctx.read(memo)) |bytes| {
        const payload = cache.unseal(ctx, bytes) catch "";
        if (std.mem.eql(u8, payload, "apple-clang-cas-v2")) return true;
        if (std.mem.eql(u8, payload, "apple-clang-cas-unsupported-v2")) return false;
    } else |_| {}
    const version = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ tool, "--version" }, .environ_map = ctx.env });
    if (code(version.term) != 0 or std.mem.indexOf(u8, version.stdout, "Apple clang version") == null) return false;
    const driver = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ tool, "--help-hidden" }, .environ_map = ctx.env });
    const frontend = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ tool, "-cc1", "--help" }, .environ_map = ctx.env });
    if (code(driver.term) != 0 or code(frontend.term) != 0 or
        std.mem.indexOf(u8, driver.stdout, "-fdepscan=") == null or
        std.mem.indexOf(u8, frontend.stdout, "-fcache-compile-job") == null or
        std.mem.indexOf(u8, frontend.stdout, "-fcas-path") == null) return false;
    // Some Apple releases advertise these flags without exposing usable driver
    // replay. Qualify the exact binary with a real compiler-owned hit once.
    const probe_lock = try cache.Lock.acquire(ctx, try std.fmt.allocPrint(ctx.a, "clang-capability-{s}", .{hash}), true);
    defer probe_lock.release();
    if (ctx.read(memo)) |bytes| {
        const payload = cache.unseal(ctx, bytes) catch "";
        if (std.mem.eql(u8, payload, "apple-clang-cas-v2")) return true;
        if (std.mem.eql(u8, payload, "apple-clang-cas-unsupported-v2")) return false;
    } else |_| {}
    const probe_root = try ctx.path(&.{ "metadata", try std.fmt.allocPrint(ctx.a, "clang-cas-probe-{s}", .{hash}) });
    try std.Io.Dir.cwd().createDirPath(ctx.io, probe_root);
    defer std.Io.Dir.cwd().deleteTree(ctx.io, probe_root) catch {};
    const source = try std.fs.path.join(ctx.a, &.{ probe_root, "probe.c" });
    const output = try std.fs.path.join(ctx.a, &.{ probe_root, "probe.o" });
    const cas_root = try std.fs.path.join(ctx.a, &.{ probe_root, "cas" });
    try ctx.atomic(source, "int nanocompile_capability_probe(void) { return 42; }\n");
    const command = &.{ tool, "-c", source, "-o", output, "-fdepscan=inline", "-Xclang", "-fcas-path", "-Xclang", cas_root, "-Xclang", "-fcache-compile-job", "-Rcompile-job-cache" };
    const cold = try std.process.run(ctx.a, ctx.io, .{ .argv = command, .environ_map = ctx.env });
    const warm = try std.process.run(ctx.a, ctx.io, .{ .argv = command, .environ_map = ctx.env });
    const usable = code(cold.term) == 0 and code(warm.term) == 0 and std.mem.indexOf(u8, warm.stderr, "remark: compile job cache hit") != null;
    try ctx.atomic(memo, try cache.seal(ctx, if (usable) "apple-clang-cas-v2" else "apple-clang-cas-unsupported-v2"));
    return usable;
}

pub fn execute(ctx: *cache.Context, args: []const []const u8) !u8 {
    const eligible = builtin.os.tag == .macos and compileOnly(args) and !enabled(ctx, "NANOCOMPILE_DISABLE");
    var sdk_query: SdkQuery = .{};
    defer sdk_query.deinit();
    var group: std.Io.Group = .init;
    defer group.cancel(ctx.io);
    const explicit_sdk = if (ctx.env.get("SDKROOT")) |value| value.len != 0 else false;
    const sdk_started = blk: {
        if (!eligible or hasSysroot(args) or ctx.env.get("NANOCOMPILE_CLANG") != null or explicit_sdk) break :blk false;
        group.concurrent(ctx.io, SdkQuery.run, .{ &sdk_query, ctx.io, ctx.env }) catch break :blk false;
        break :blk true;
    };
    const tool = try selected(ctx);
    var original: std.ArrayList([]const u8) = .empty;
    try original.append(ctx.a, tool);
    try original.appendSlice(ctx.a, args);
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.append(ctx.a, tool);
    // Probes, unsupported jobs and explicit disabling use inherited descriptors.
    if (!eligible) {
        return run(ctx, original.items);
    }
    // SDK and default compiler selection are queried live on every eligible job.
    // Clang scans included SDK/resource files; no source-content memo is added.
    const selected_sdk = if (hasSysroot(args)) "caller-sysroot" else if (sdk_started) blk: {
        group.await(ctx.io) catch return run(ctx, original.items);
        break :blk sdk_query.value() catch return run(ctx, original.items);
    } else sdk(ctx) catch {
        return run(ctx, original.items);
    };
    if (!nativeExecutable(ctx, tool) or (!hasSysroot(args) and !std.fs.path.isAbsolute(selected_sdk))) return run(ctx, original.items);
    ctx.prepare() catch {
        return run(ctx, original.items);
    };
    const maintenance = cache.Lock.acquire(ctx, "maintenance", false) catch {
        return run(ctx, original.items);
    };
    defer maintenance.release();
    const hash = identity.installedFileDigest(ctx, tool) catch {
        return run(ctx, original.items);
    };
    if (!(supports(ctx, tool, hash) catch false)) {
        ctx.trace("Clang CAS unavailable; compiler passthrough");
        return run(ctx, original.items);
    }
    if (!hasSysroot(args)) try argv.appendSlice(ctx.a, &.{ "-isysroot", selected_sdk });
    var h = cache.Hash.init(.{});
    cache.field(&h, "nanocompile-native-clang-v1");
    cache.field(&h, tool);
    cache.field(&h, hash);
    cache.field(&h, selected_sdk);
    cache.field(&h, @tagName(builtin.cpu.arch));
    const root = try ctx.path(&.{ "native-clang", try cache.finish(ctx.a, &h) });
    std.Io.Dir.cwd().createDirPath(ctx.io, root) catch return run(ctx, original.items);
    const private = std.Io.Dir.cwd().openDir(ctx.io, root, .{}) catch return run(ctx, original.items);
    defer private.close(ctx.io);
    private.setPermissions(ctx.io, .fromMode(0o700)) catch return run(ctx, original.items);
    try argv.appendSlice(ctx.a, &.{ "-fdepscan=inline", "-Xclang", "-fcas-path", "-Xclang", root, "-Xclang", "-fcache-compile-job" });
    const remarks = enabled(ctx, "NANOCOMPILE_CLANG_REMARKS");
    if (remarks) try argv.append(ctx.a, "-Rcompile-job-cache");
    try argv.appendSlice(ctx.a, args);
    ctx.event("clang_native_run");
    if (!remarks) {
        const result = try run(ctx, argv.items);
        if (result != 0) ctx.event("clang_native_failed");
        return result;
    }
    const result = try std.process.run(ctx.a, ctx.io, .{ .argv = argv.items, .environ_map = ctx.env, .stdout_limit = .limited(64 * 1024 * 1024), .stderr_limit = .limited(64 * 1024 * 1024) });
    try ctx.out(result.stdout);
    try std.Io.File.stderr().writeStreamingAll(ctx.io, result.stderr);
    if (std.mem.indexOf(u8, result.stderr, "remark: compile job cache hit") != null) ctx.event("clang_native_hit");
    if (std.mem.indexOf(u8, result.stderr, "remark: compile job cache miss") != null) ctx.event("clang_native_miss");
    if (code(result.term) != 0) ctx.event("clang_native_failed");
    return code(result.term);
}

test "Clang caching is explicit compile-only with inherited-input fallback" {
    try std.testing.expect(compileOnly(&.{ "-c", "x.c", "-o", "x.o" }));
    try std.testing.expect(compileOnly(&.{ "--target=arm64-apple-macosx", "-c", "x.S" }));
    for ([_][]const []const u8{ &.{ "-c", "-" }, &.{ "-c", "-E", "x.c" }, &.{"@args"}, &.{ "--target=x86_64-linux-gnu", "-c", "x.c" }, &.{ "-arch", "arm64", "-arch", "x86_64", "-c", "x.c" }, &.{ "-c", "-fcache-disable-replay", "x.c" } }) |args|
        try std.testing.expect(!compileOnly(args));
}
