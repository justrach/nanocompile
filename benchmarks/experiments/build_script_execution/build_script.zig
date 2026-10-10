//! Opt-in whole Cargo build-script execution under an explicit input contract.
const std = @import("std");
const cache = @import("cache.zig");
const identity = @import("identity.zig");
const Dir = std.Io.Dir;
const Contract = struct { package: []const u8, inputs: []const []const u8, tools: []const []const u8 = &.{}, installed_inputs: []const []const u8 = &.{}, apple_native: bool = false };
const Spec = struct { schema: u32 = 1, packages: []const Contract };
const Launch = struct { real: []const u8 };
const Receipt = struct { schema: u32 = 1, outputs: []const []const u8 };
fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}
fn less(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.order(u8, a, b) == .lt;
}
fn contract(ctx: *cache.Context) !Contract {
    const path = ctx.env.get("NANOCOMPILE_BUILD_SCRIPTS_FILE") orelse return error.NoContract;
    const parsed = try std.json.parseFromSlice(Spec, ctx.a, try ctx.read(path), .{ .allocate = .alloc_always });
    if (parsed.value.schema != 1) return error.InvalidContract;
    const name = ctx.env.get("CARGO_PKG_NAME") orelse return error.NoPackage;
    for (parsed.value.packages) |item| if (eq(item.package, name) and item.inputs.len > 0) return item;
    return error.NoContract;
}
const Snapshot = struct { records: []const cache.Dependency, epoch: []const u8 };
fn state(h: *cache.Hash, path: []const u8, st: std.Io.File.Stat) void {
    cache.field(h, path);
    cache.field(h, std.mem.asBytes(&st.inode));
    cache.field(h, std.mem.asBytes(&st.size));
    cache.field(h, std.mem.asBytes(&st.mtime.nanoseconds));
    cache.field(h, std.mem.asBytes(&st.ctime.nanoseconds));
}
fn snapshot(ctx: *cache.Context, roots: []const []const u8) !Snapshot {
    var records: std.ArrayList(cache.Dependency) = .empty;
    var epoch = cache.Hash.init(.{});
    for (roots) |root| {
        const path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, root });
        const st = Dir.cwd().statFile(ctx.io, path, .{ .follow_symlinks = false }) catch |err| switch (err) {
            error.FileNotFound => {
                try records.append(ctx.a, try cache.missingDependency(ctx, path));
                continue;
            },
            else => return err,
        };
        state(&epoch, path, st);
        switch (st.kind) {
            .file => try records.append(ctx.a, .{ .path = path, .hash = (try ctx.checkedDigest(path)).hash }),
            .directory => {
                try records.append(ctx.a, .{ .path = path, .hash = try ctx.nativeDirectoryDigest(path), .directory = true, .all_members = true });
                var dir = try Dir.cwd().openDir(ctx.io, path, .{ .iterate = true });
                defer dir.close(ctx.io);
                var walk = try dir.walk(ctx.a);
                defer walk.deinit();
                while (try walk.next(ctx.io)) |entry| {
                    if (records.items.len > 100000) return error.TooManyInputs;
                    const full = try std.fs.path.join(ctx.a, &.{ path, entry.path });
                    state(&epoch, full, try Dir.cwd().statFile(ctx.io, full, .{}));
                    if (entry.kind == .directory) try records.append(ctx.a, .{ .path = full, .hash = try ctx.nativeDirectoryDigest(full), .directory = true, .all_members = true }) else if (entry.kind == .file) try records.append(ctx.a, .{ .path = full, .hash = (try ctx.checkedDigest(full)).hash }) else return error.UnsupportedInputKind;
                }
            },
            else => return error.UnsupportedInputKind,
        }
    }
    return .{ .records = records.items, .epoch = try cache.finish(ctx.a, &epoch) };
}
fn material(ctx: *cache.Context, real: []const u8, argv: []const []const u8, item: Contract) ![]const u8 {
    var h = cache.Hash.init(.{});
    cache.field(&h, "nano-build-script-explicit-v2");
    if (ctx.env.get("OUT_DIR")) |out| cache.field(&h, try Dir.cwd().realPathFileAlloc(ctx.io, out, ctx.a));
    cache.field(&h, ctx.cwd);
    cache.field(&h, real);
    cache.field(&h, try ctx.digest(real));
    for (argv) |arg| cache.field(&h, arg);
    const spec = ctx.env.get("NANOCOMPILE_BUILD_SCRIPTS_FILE").?;
    cache.field(&h, try ctx.digest(spec));
    const names = try ctx.a.dupe([]const u8, ctx.env.keys());
    std.mem.sort([]const u8, names, {}, less);
    for (names) |name| {
        cache.field(&h, name);
        cache.field(&h, ctx.env.get(name).?);
    }
    if (ctx.env.get("RUSTC")) |rustc| cache.field(&h, try identity.fingerprint(ctx, false, rustc));
    for (item.tools) |tool| {
        const selected = try identity.selectedExecutable(ctx, tool);
        cache.field(&h, selected);
        cache.field(&h, try identity.installedFileDigest(ctx, selected));
    }
    for (item.installed_inputs) |path| cache.field(&h, try identity.installedTreeDigest(ctx, path));
    if (item.apple_native) {
        const selected = try @import("native_identity.zig").apple(ctx, try identity.selectedExecutable(ctx, "cc"));
        cache.field(&h, selected.hash);
        for ([_][]const u8{ try std.fs.path.join(ctx.a, &.{ selected.sdk, "usr", "include" }), try std.fs.path.join(ctx.a, &.{ selected.resource_dir, "include" }) }) |root|
            cache.field(&h, try identity.installedTreeDigest(ctx, root));
    }
    return cache.finish(ctx.a, &h);
}
fn empty(ctx: *cache.Context, root: []const u8) !bool {
    var dir = try Dir.cwd().openDir(ctx.io, root, .{ .iterate = true });
    defer dir.close(ctx.io);
    var it = dir.iterate();
    return try it.next(ctx.io) == null;
}
fn outputs(ctx: *cache.Context, root: []const u8) ![]const []const u8 {
    var paths: std.ArrayList([]const u8) = .empty;
    var dir = try Dir.cwd().openDir(ctx.io, root, .{ .iterate = true });
    defer dir.close(ctx.io);
    var walk = try dir.walk(ctx.a);
    defer walk.deinit();
    var size: u64 = 0;
    while (try walk.next(ctx.io)) |entry| {
        if (entry.kind == .directory) return error.UnsupportedOutput;
        if (entry.kind != .file or paths.items.len >= 50000) return error.UnsupportedOutput;
        const path = try std.fs.path.join(ctx.a, &.{ root, entry.path });
        size += (try Dir.cwd().statFile(ctx.io, path, .{})).size;
        if (size > 1024 * 1024 * 1024) return error.OutputTooLarge;
        try paths.append(ctx.a, path);
    }
    std.mem.sort([]const u8, paths.items, {}, less);
    return paths.items;
}
extern "c" fn fcntl(c_int, c_int, ...) c_int;
fn nullStdin(ctx: *cache.Context) bool {
    const null_file = Dir.cwd().openFile(ctx.io, "/dev/null", .{}) catch return false;
    defer null_file.close(ctx.io);
    var input: std.c.Stat = undefined;
    var expected: std.c.Stat = undefined;
    if (std.c.fstat(0, &input) != 0 or std.c.fstat(null_file.handle, &expected) != 0) return false;
    return input.dev == expected.dev and input.ino == expected.ino and input.rdev == expected.rdev and input.mode == expected.mode;
}
fn jobserver(ctx: *cache.Context) ![]const std.Io.File {
    var inherited: std.ArrayList(std.Io.File) = .empty;
    var flags = std.mem.tokenizeScalar(u8, ctx.env.get("CARGO_MAKEFLAGS") orelse "", ' ');
    while (flags.next()) |flag| if (std.mem.startsWith(u8, flag, "--jobserver-auth=")) {
        var ids = std.mem.splitScalar(u8, flag[17..], ',');
        while (ids.next()) |id| {
            const fd = std.fmt.parseInt(c_int, id, 10) catch continue;
            if (fd > 2 and fcntl(fd, 1) >= 0) try inherited.append(ctx.a, .{ .handle = fd, .flags = .{ .nonblocking = false } });
        }
    };
    return inherited.items;
}
fn run(ctx: *cache.Context, real: []const u8, args: []const []const u8) !std.process.RunResult {
    const job = try @import("producer_job.zig").Job.create(ctx);
    defer job.cleanup(ctx) catch {};
    const out = try std.fs.path.join(ctx.a, &.{ job.root, "stdout" });
    const err = try std.fs.path.join(ctx.a, &.{ job.root, "stderr" });
    const of = try Dir.cwd().createFile(ctx.io, out, .{});
    defer of.close(ctx.io);
    const ef = try Dir.cwd().createFile(ctx.io, err, .{});
    defer ef.close(ctx.io);
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.append(ctx.a, real);
    try argv.appendSlice(ctx.a, args);
    const inherited = try jobserver(ctx);
    var child = try std.process.spawn(ctx.io, .{ .argv = argv.items, .cwd = .{ .path = ctx.cwd }, .environ_map = ctx.env, .stdout = .{ .file = of }, .stderr = .{ .file = ef }, .inherit_files = inherited });
    const term = try child.wait(ctx.io);
    return .{ .term = term, .stdout = try ctx.read(out), .stderr = try ctx.read(err) };
}
fn replay(ctx: *cache.Context, result: std.process.RunResult) !u8 {
    try ctx.out(result.stdout);
    try std.Io.File.stderr().writeStreamingAll(ctx.io, result.stderr);
    return switch (result.term) {
        .exited => |v| v,
        .signal => |v| @intCast(@min(255, 128 + @as(u32, @backingInt(v)))),
        else => 1,
    };
}
fn passthrough(ctx: *cache.Context, real: []const u8, args: []const []const u8) !u8 {
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.append(ctx.a, real);
    try argv.appendSlice(ctx.a, args);
    var child = try std.process.spawn(ctx.io, .{ .argv = argv.items, .environ_map = ctx.env, .inherit_files = try jobserver(ctx) });
    return switch (try child.wait(ctx.io)) {
        .exited => |v| v,
        .signal => |v| @intCast(@min(255, 128 + @as(u32, @backingInt(v)))),
        else => 1,
    };
}
pub fn execute(ctx: *cache.Context, real: []const u8, args: []const []const u8) !u8 {
    ctx.prepare() catch return passthrough(ctx, real, args);
    const item = contract(ctx) catch return passthrough(ctx, real, args);
    if (eq(ctx.env.get("NANOCOMPILE_DISABLE") orelse "", "1")) return passthrough(ctx, real, args);
    if (!nullStdin(ctx)) {
        ctx.event("build_script_bypass");
        ctx.trace("build-script stdin is not /dev/null");
        return passthrough(ctx, real, args);
    }
    const requested_root = ctx.env.get("OUT_DIR") orelse return replay(ctx, try run(ctx, real, args));
    if (!std.fs.path.isAbsolute(requested_root)) return passthrough(ctx, real, args);
    const root = try Dir.cwd().realPathFileAlloc(ctx.io, requested_root, ctx.a);
    const maintenance = try cache.Lock.acquire(ctx, "maintenance", false);
    defer maintenance.release();
    var oh = cache.Hash.init(.{});
    cache.field(&oh, root);
    const flight = try cache.Lock.acquire(ctx, try std.fmt.allocPrint(ctx.a, "script-out-{s}", .{try cache.finish(ctx.a, &oh)}), true);
    defer flight.release();
    if (!try empty(ctx, root)) {
        ctx.trace("build-script output directory is not empty");
        ctx.event("build_script_bypass");
        return replay(ctx, try run(ctx, real, args));
    }
    var roots: std.ArrayList([]const u8) = .empty;
    try roots.appendSlice(ctx.a, item.inputs);
    try roots.appendSlice(ctx.a, &.{ real, ctx.env.get("NANOCOMPILE_BUILD_SCRIPTS_FILE").? });
    const before = snapshot(ctx, roots.items) catch |err| {
        ctx.trace(@errorName(err));
        ctx.event("build_script_bypass");
        return replay(ctx, try run(ctx, real, args));
    };
    for (before.records) |dep| if (eq(dep.path, root) or std.mem.startsWith(u8, dep.path, try std.fmt.allocPrint(ctx.a, "{s}/", .{root}))) return replay(ctx, try run(ctx, real, args));
    const base = material(ctx, real, args, item) catch |err| {
        ctx.trace(@errorName(err));
        ctx.event("build_script_bypass");
        return replay(ctx, try run(ctx, real, args));
    };
    var keyed = cache.Hash.init(.{});
    cache.field(&keyed, base);
    cache.field(&keyed, try std.json.Stringify.valueAlloc(ctx.a, before.records, .{}));
    const key = try cache.finish(ctx.a, &keyed);
    const index = try ctx.path(&.{ "build-script-receipts", key });
    if (ctx.read(index)) |bytes| restore: {
        const parsed = std.json.parseFromSlice(Receipt, ctx.a, cache.unseal(ctx, bytes) catch break :restore, .{ .allocate = .alloc_always }) catch break :restore;
        if (parsed.value.schema != 1 or parsed.value.outputs.len > 50000) break :restore;
        for (parsed.value.outputs) |path| {
            if (!std.mem.startsWith(u8, path, try std.fmt.allocPrint(ctx.a, "{s}/", .{root}))) break :restore;
            var parts = std.mem.splitScalar(u8, path[root.len + 1 ..], '/');
            while (parts.next()) |part| if (part.len == 0 or eq(part, "..") or eq(part, ".")) break :restore;
        }
        if (cache.restore(ctx, key, parsed.value.outputs) catch false) {
            ctx.event("build_script_hit");
            return 0;
        }
    } else |_| {}
    const result = try run(ctx, real, args);
    const code = try replay(ctx, result);
    if (code != 0) {
        ctx.event("build_script_failed");
        return code;
    }
    ctx.event("build_script_miss");
    const after = snapshot(ctx, roots.items) catch return 0;
    if (!eq(try std.json.Stringify.valueAlloc(ctx.a, before.records, .{}), try std.json.Stringify.valueAlloc(ctx.a, after.records, .{})) or !eq(before.epoch, after.epoch) or !eq(base, material(ctx, real, args, item) catch return 0)) return 0;
    const paths = outputs(ctx, root) catch return 0;
    try cache.store(ctx, key, after.records, paths, result.stdout, result.stderr);
    try ctx.atomic(index, try cache.seal(ctx, try std.json.Stringify.valueAlloc(ctx.a, Receipt{ .outputs = paths }, .{})));
    return 0;
}
// The explicit contract is checked at execution too, including disabled shims.
pub fn install(ctx: *cache.Context, argv: []const []const u8) !void {
    _ = contract(ctx) catch return;
    var name: ?[]const u8 = null;
    var dir: ?[]const u8 = null;
    var extra: []const u8 = "";
    for (argv, 0..) |arg, i| {
        if (eq(arg, "--crate-name") and i + 1 < argv.len) name = argv[i + 1];
        if (eq(arg, "--out-dir") and i + 1 < argv.len) dir = argv[i + 1];
        if (eq(arg, "-C") and i + 1 < argv.len and std.mem.startsWith(u8, argv[i + 1], "extra-filename=")) extra = argv[i + 1][15..];
    }
    if (!eq(name orelse return, "build_script_build")) return;
    const parent = dir orelse return;
    const path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, parent, try std.fmt.allocPrint(ctx.a, "build_script_build{s}", .{extra}) });
    const real = try std.fmt.allocPrint(ctx.a, "{s}.nano-real", .{path});
    const config = try std.fs.path.join(ctx.a, &.{ std.fs.path.dirname(path).?, "nano-build-script.json" });
    try Dir.cwd().rename(path, .cwd(), real, ctx.io);
    errdefer {
        Dir.cwd().rename(real, .cwd(), path, ctx.io) catch {};
        Dir.cwd().deleteFile(ctx.io, config) catch {};
    }
    try cache.materialize(ctx, try std.process.executablePathAlloc(ctx.io, ctx.a), path, 0o700);
    try ctx.atomic(config, try std.json.Stringify.valueAlloc(ctx.a, Launch{ .real = real }, .{}));
}
pub fn launch(ctx: *cache.Context, args: []const [:0]const u8) !?u8 {
    if (args.len == 0) return null;
    const name = std.fs.path.basename(args[0]);
    if (!eq(name, "build-script-build") and !std.mem.startsWith(u8, name, "build_script_build-")) return null;
    const path = try std.process.executablePathAlloc(ctx.io, ctx.a);
    const record = try std.fs.path.join(ctx.a, &.{ std.fs.path.dirname(path).?, "nano-build-script.json" });
    const parsed = try std.json.parseFromSlice(Launch, ctx.a, try ctx.read(record), .{ .allocate = .alloc_always });
    return try execute(ctx, parsed.value.real, args[1..]);
}

pub fn wantsInstall(ctx: *cache.Context, argv: []const []const u8) bool {
    if (ctx.env.get("NANOCOMPILE_BUILD_SCRIPTS_FILE") == null) return false;
    for (argv, 0..) |arg, i| if (eq(arg, "--crate-name") and i + 1 < argv.len and eq(argv[i + 1], "build_script_build")) {
        _ = contract(ctx) catch return false;
        return true;
    };
    return false;
}
pub fn installLockName(ctx: *cache.Context, argv: []const []const u8) ![]const u8 {
    var h = cache.Hash.init(.{});
    cache.field(&h, ctx.cwd);
    for (argv, 0..) |arg, i| if (eq(arg, "--out-dir") and i + 1 < argv.len) cache.field(&h, argv[i + 1]);
    return std.fmt.allocPrint(ctx.a, "script-install-{s}", .{try cache.finish(ctx.a, &h)});
}
