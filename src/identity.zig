//! Toolchains are fingerprinted by content once. Their identity is memoized
//! behind inode/size/mtime/ctime checks and directory membership checks.
//! Source dependencies and stored outputs never use this metadata shortcut.
const std = @import("std");
const cache = @import("cache.zig");
const Dir = std.Io.Dir;
const Stamp = struct {
    path: []const u8,
    exists: bool,
    inode: u64 = 0,
    size: u64 = 0,
    mtime: i96 = 0,
    ctime: i96 = 0,
    kind: std.Io.File.Kind = .unknown,
};
const Memo = struct { schema: u32 = 8, locations: ?cache.RustLocations = null, hash: []const u8, decoder_hash: []const u8, stamps: []const Stamp };

fn rememberEpoch(ctx: *cache.Context, payload: []const u8) !void {
    var h = cache.Hash.init(.{});
    cache.field(&h, "installed-file-state-v1");
    cache.field(&h, payload);
    ctx.compiler_epoch = try cache.finish(ctx.a, &h);
}

fn stamp(ctx: *cache.Context, path: []const u8) !Stamp {
    const st = Dir.cwd().statFile(ctx.io, path, .{}) catch |err| switch (err) {
        error.FileNotFound => return .{ .path = path, .exists = false },
        else => return err,
    };
    return .{ .path = path, .exists = true, .inode = @intCast(st.inode), .size = st.size, .mtime = st.mtime.nanoseconds, .ctime = st.ctime.nanoseconds, .kind = st.kind };
}

fn equal(a: Stamp, b: Stamp) bool {
    return a.exists == b.exists and a.inode == b.inode and a.size == b.size and a.mtime == b.mtime and a.ctime == b.ctime and a.kind == b.kind;
}

fn resolveExecutable(ctx: *cache.Context, arg: []const u8) ![]const u8 {
    if (std.mem.indexOfScalar(u8, arg, '/') != null)
        return Dir.cwd().realPathFileAlloc(ctx.io, arg, ctx.a);
    var paths = std.mem.splitScalar(u8, ctx.env.get("PATH") orelse "", ':');
    while (paths.next()) |dir| {
        const candidate = try std.fs.path.join(ctx.a, &.{ if (dir.len == 0) "." else dir, arg });
        const real = Dir.cwd().realPathFileAlloc(ctx.io, candidate, ctx.a) catch continue;
        const st = try Dir.cwd().statFile(ctx.io, real, .{});
        if (st.kind == .file and st.permissions.toMode() & 0o111 != 0) return real;
    }
    return error.CompilerNotFound;
}

pub fn selectedExecutable(ctx: *cache.Context, arg: []const u8) ![]const u8 {
    return resolveExecutable(ctx, arg);
}

fn add(ctx: *cache.Context, stamps: *std.ArrayList(Stamp), path: []const u8) !void {
    for (stamps.items) |s| if (std.mem.eql(u8, s.path, path)) return;
    try stamps.append(ctx.a, try stamp(ctx, path));
}

fn tree(ctx: *cache.Context, stamps: *std.ArrayList(Stamp), root: []const u8) !void {
    try add(ctx, stamps, root);
    var dir = Dir.cwd().openDir(ctx.io, root, .{ .iterate = true }) catch |err| {
        ctx.trace(try std.fmt.allocPrint(ctx.a, "toolchain resource unavailable: {s} ({s})", .{ root, @errorName(err) }));
        return err;
    };
    defer dir.close(ctx.io);
    var walker = try dir.walk(ctx.a);
    defer walker.deinit();
    while (try walker.next(ctx.io)) |entry| {
        if (entry.kind != .file and entry.kind != .directory and entry.kind != .sym_link) continue;
        try add(ctx, stamps, try std.fs.path.join(ctx.a, &.{ root, entry.path }));
        if (entry.kind == .sym_link) {
            const path = try std.fs.path.join(ctx.a, &.{ root, entry.path });
            const current = try stamp(ctx, path);
            // Do not silently omit inputs inside linked resource directories.
            if (current.kind == .directory) return error.LinkedToolchainDirectory;
        }
    }
}

fn stampWorker(ctx: *cache.Context, stamps: []const Stamp, next: *std.atomic.Value(usize), valid: *std.atomic.Value(bool)) void {
    while (true) {
        const start = next.fetchAdd(32, .monotonic);
        if (start >= stamps.len) return;
        for (stamps[start..@min(start + 32, stamps.len)]) |expected| {
            const current = stamp(ctx, expected.path) catch {
                valid.store(false, .monotonic);
                continue;
            };
            if (!equal(current, expected)) valid.store(false, .monotonic);
        }
    }
}

fn validStamps(ctx: *cache.Context, stamps: []const Stamp, parallel: bool) bool {
    if (!parallel or stamps.len < 512) {
        for (stamps) |expected| if (!equal(expected, stamp(ctx, expected.path) catch return false)) return false;
        return true;
    }
    ctx.trace("toolchain: parallel Zig stamp validation");
    var next = std.atomic.Value(usize).init(0);
    var valid = std.atomic.Value(bool).init(true);
    var group: std.Io.Group = .init;
    defer group.cancel(ctx.io);
    for (0..3) |_| group.concurrent(ctx.io, stampWorker, .{ ctx, stamps, &next, &valid }) catch break;
    stampWorker(ctx, stamps, &next, &valid);
    group.await(ctx.io) catch return false;
    return valid.load(.monotonic);
}

fn readMemo(ctx: *cache.Context, path: []const u8, minimum_stamps: usize, is_zig: bool, physical: bool) ?[]const u8 {
    const bytes = ctx.read(path) catch return null;
    const payload = cache.unseal(ctx, bytes) catch return null;
    const parsed = std.json.parseFromSlice(Memo, ctx.a, payload, .{ .allocate = .alloc_always }) catch return null;
    const memo = parsed.value;
    if (memo.schema != 8 or !cache.validHash(memo.decoder_hash) or !cache.validHash(memo.hash) or memo.stamps.len < minimum_stamps) return null;
    if (!validStamps(ctx, memo.stamps, is_zig)) return null;
    rememberEpoch(ctx, payload) catch return null;
    ctx.compiler_decoder_identity = memo.decoder_hash;
    ctx.rust_locations = if (physical) memo.locations else null;
    return memo.hash;
}

// Selection memos intentionally differ across cwd/override chains. Share only
// installed Rust file digests between them, using the same trusted toolchain
// inode/size/mtime/ctime contract. Never use this for project dependencies.
const FileMemo = struct { schema: u32 = 1, stamp: Stamp, hash: []const u8 };

fn readFileMemo(ctx: *cache.Context, path: []const u8, expected: Stamp) ?[]const u8 {
    const payload = cache.unseal(ctx, ctx.read(path) catch return null) catch return null;
    const parsed = std.json.parseFromSlice(FileMemo, ctx.a, payload, .{ .allocate = .alloc_always }) catch return null;
    const memo = parsed.value;
    if (memo.schema != 1 or !cache.validHash(memo.hash) or !std.mem.eql(u8, expected.path, memo.stamp.path) or !equal(expected, memo.stamp)) return null;
    return memo.hash;
}

/// Installed compiler binaries share the existing content/stamp identity policy.
/// This is never used for source files or native output blobs.
pub fn installedFileDigest(ctx: *cache.Context, path: []const u8) ![]const u8 {
    return installedDigest(ctx, try stamp(ctx, path), "native-toolchain-file-v1");
}

const RustDigestJob = struct { hash: [64]u8 = undefined, err: ?anyerror = null };
fn rustDigestWorker(ctx: *cache.Context, stamps: []const Stamp, jobs: []RustDigestJob, next: *std.atomic.Value(usize)) void {
    while (true) {
        const i = next.fetchAdd(1, .monotonic);
        if (i >= stamps.len) return;
        const expected = stamps[i];
        if (!expected.exists or expected.kind != .file) continue;
        // Independent allocators keep concurrent memo reads, locks and atomic
        // writes away from the caller's non-threadsafe arena.
        var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
        defer arena.deinit();
        var local = ctx.*;
        local.a = arena.allocator();
        const hash = rustFileDigest(&local, expected) catch |err| {
            jobs[i].err = err;
            continue;
        };
        @memcpy(&jobs[i].hash, hash);
    }
}
fn parallelRustDigests(ctx: *cache.Context, stamps: []const Stamp) !?[]RustDigestJob {
    var count: usize = 0;
    var size: u64 = 0;
    for (stamps) |st| if (st.exists and st.kind == .file) {
        count += 1;
        size +|= st.size;
    };
    if (count < 16 or size < 8 * 1024 * 1024) return null;
    const jobs = try ctx.a.alloc(RustDigestJob, stamps.len);
    for (jobs) |*job| job.* = .{};
    var next: std.atomic.Value(usize) = .init(0);
    var group: std.Io.Group = .init;
    defer group.cancel(ctx.io);
    const workers = @min(@as(usize, 4), std.Thread.getCpuCount() catch 1);
    for (1..@max(workers, 1)) |_| group.concurrent(ctx.io, rustDigestWorker, .{ ctx, stamps, jobs, &next }) catch break;
    rustDigestWorker(ctx, stamps, jobs, &next);
    try group.await(ctx.io);
    return jobs;
}

fn rustFileDigest(ctx: *cache.Context, expected: Stamp) ![]const u8 {
    return installedDigest(ctx, expected, "rust-toolchain-file-v1");
}

fn installedDigest(ctx: *cache.Context, expected: Stamp, domain: []const u8) ![]const u8 {
    var h = cache.Hash.init(.{});
    cache.field(&h, domain);
    cache.field(&h, expected.path);
    const key = try cache.finish(ctx.a, &h);
    const path = try ctx.path(&.{ "toolchain-files", key });
    // Atomic sealed records permit an optimistic read. A per-file lock makes
    // concurrent first-use fingerprints share the expensive content hash.
    if (readFileMemo(ctx, path, expected)) |hash| return hash;
    const lock = try cache.Lock.acquire(ctx, try std.fmt.allocPrint(ctx.a, "toolchain-file-{s}", .{key}), true);
    defer lock.release();
    if (readFileMemo(ctx, path, expected)) |hash| return hash;
    const hash = try ctx.digest(expected.path);
    if (!equal(expected, try stamp(ctx, expected.path))) return error.ToolchainChanged;
    const bytes = try std.json.Stringify.valueAlloc(ctx.a, FileMemo{ .stamp = expected, .hash = hash }, .{});
    try ctx.atomic(path, try cache.seal(ctx, bytes));
    return hash;
}

/// Explicit installed-tool resources only. Never call for project inputs.
/// This uses the same trusted-installation metadata contract as rustc files.
pub fn nativeFiles(ctx: *cache.Context, paths: []const []const u8) ![]const u8 {
    var h = cache.Hash.init(.{});
    cache.field(&h, "native-toolchain-files-v1");
    var stamps: std.ArrayList(Stamp) = .empty;
    for (paths) |path| {
        if (!std.fs.path.isAbsolute(path)) return error.InvalidToolResource;
        const current = try stamp(ctx, path);
        if (!current.exists or current.kind != .file) return error.InvalidToolResource;
        try stamps.append(ctx.a, current);
    }
    for (stamps.items) |current| {
        cache.field(&h, current.path);
        cache.field(&h, try installedDigest(ctx, current, "native-toolchain-file-v1"));
    }
    for (stamps.items) |current| if (!equal(current, try stamp(ctx, current.path))) return error.ToolchainChanged;
    return cache.finish(ctx.a, &h);
}

fn rustResources(ctx: *cache.Context, stamps: *std.ArrayList(Stamp), root: []const u8) !void {
    try add(ctx, stamps, root);
    var dir = try Dir.cwd().openDir(ctx.io, root, .{ .iterate = true });
    defer dir.close(ctx.io);
    var iterator = dir.iterate();
    while (try iterator.next(ctx.io)) |entry| {
        const path = try std.fs.path.join(ctx.a, &.{ root, entry.name });
        if (entry.kind == .file or entry.kind == .sym_link) try add(ctx, stamps, path);
    }
    const rustlib = try std.fs.path.join(ctx.a, &.{ root, "rustlib" });
    try add(ctx, stamps, rustlib);
    var targets = try Dir.cwd().openDir(ctx.io, rustlib, .{ .iterate = true });
    defer targets.close(ctx.io);
    iterator = targets.iterate();
    while (try iterator.next(ctx.io)) |entry| {
        // src is used by build-std, which requires unsupported unstable flags.
        // etc contains debugger helpers, not ordinary rustc compilation inputs.
        if (entry.kind != .directory or std.mem.eql(u8, entry.name, "src") or std.mem.eql(u8, entry.name, "etc")) continue;
        try tree(ctx, stamps, try std.fs.path.join(ctx.a, &.{ rustlib, entry.name }));
    }
}

// Byte-pinned stock installation, not a version-string
// heuristic. Unrecognized compilers/drivers keep contextual selection memos.
fn physicalStock(ctx: *cache.Context, real: []const u8) bool {
    if (@import("builtin").os.tag != .macos or @import("builtin").cpu.arch != .aarch64) return false;
    if (!std.mem.eql(u8, std.fs.path.basename(real), "rustc")) return false;
    const bin = std.fs.path.dirname(real) orelse return false;
    if (!std.mem.eql(u8, std.fs.path.basename(bin), "bin")) return false;
    const root = std.fs.path.dirname(bin) orelse return false;
    if (!std.mem.eql(u8, identityDigest(ctx, real) catch return false, "7057a29fe82d8bd41fbf4b9af4a58aebcc9642700d57b6bf0c08b1ca50b2d787")) return false;
    const driver = std.fs.path.join(ctx.a, &.{ root, "lib", "librustc_driver-e03ed1db822dfa4c.dylib" }) catch return false;
    if (!std.mem.eql(u8, identityDigest(ctx, driver) catch return false, "4ba56a4c5bdac7453efe3362e59224d279b5a17b5ca7d4917ec4fc86cb000a2f")) return false;
    return @import("rust_loader.zig").allowsFallback(ctx, real, root) catch false;
}
fn identityDigest(ctx: *cache.Context, path: []const u8) ![]const u8 {
    return installedDigest(ctx, try stamp(ctx, path), "rust-toolchain-file-v1");
}

pub fn fingerprint(ctx: *cache.Context, is_zig: bool, executable: []const u8) ![]const u8 {
    const real = resolveExecutable(ctx, executable) catch |err| {
        ctx.trace(try std.fmt.allocPrint(ctx.a, "cannot resolve compiler: {s} ({s})", .{ executable, @errorName(err) }));
        return err;
    };
    {
        const file = try Dir.cwd().openFile(ctx.io, real, .{});
        defer file.close(ctx.io);
        var buffer: [4]u8 = undefined;
        var reader = file.reader(ctx.io, &.{});
        try reader.interface.readSliceAll(&buffer);
        const native_binary = std.mem.eql(u8, &buffer, "\x7fELF") or std.mem.eql(u8, &buffer, "\xcf\xfa\xed\xfe") or std.mem.eql(u8, &buffer, "\xce\xfa\xed\xfe") or std.mem.eql(u8, &buffer, "\xca\xfe\xba\xbe");
        if (!native_binary) return error.UnsupportedCompilerScript;
    }
    const physical = !is_zig and std.mem.eql(u8, executable, real) and physicalStock(ctx, real);
    if (physical) ctx.trace("toolchain: pinned physical installation memo");
    var selectors: std.ArrayList(Stamp) = .empty;
    try add(ctx, &selectors, real);
    // rustup's selection observes ancestor override files and global settings.
    // Missing override files are recorded too: adding one invalidates the memo.
    if (!is_zig and !physical) {
        const rustup = ctx.env.get("RUSTUP_HOME") orelse try std.fs.path.join(ctx.a, &.{ ctx.env.get("HOME") orelse "", ".rustup" });
        try add(ctx, &selectors, try std.fs.path.join(ctx.a, &.{ rustup, "settings.toml" }));
        try add(ctx, &selectors, try std.fs.path.join(ctx.a, &.{ rustup, "toolchains" }));
        var dir: ?[]const u8 = ctx.cwd;
        while (dir) |d| {
            try add(ctx, &selectors, try std.fs.path.join(ctx.a, &.{ d, "rust-toolchain" }));
            try add(ctx, &selectors, try std.fs.path.join(ctx.a, &.{ d, "rust-toolchain.toml" }));
            dir = std.fs.path.dirname(d);
        }
    }
    var h = cache.Hash.init(.{});
    cache.field(&h, if (physical) "toolchain-memo-v5-pinned-physical-1.97.1" else "toolchain-memo-v4");
    cache.field(&h, real);
    cache.field(&h, if (is_zig) "zig" else "rust");
    // Compilation keys include the entire environment. This memo includes
    // only toolchain-selection variables, so Cargo's per-crate package values
    // do not force another full toolchain content hash for every dependency.
    const keys = try ctx.a.dupe([]const u8, ctx.env.keys());
    std.mem.sort([]const u8, keys, {}, struct {
        fn less(_: void, a: []const u8, b: []const u8) bool {
            return std.mem.order(u8, a, b) == .lt;
        }
    }.less);
    for (keys) |key| {
        if (physical and std.mem.eql(u8, key, "DYLD_FALLBACK_LIBRARY_PATH")) continue;
        const selector = std.mem.startsWith(u8, key, "RUSTUP_") or std.mem.startsWith(u8, key, "ZIG_") or std.mem.startsWith(u8, key, "DYLD_") or std.mem.startsWith(u8, key, "LD_") or std.mem.eql(u8, key, "HOME") or std.mem.eql(u8, key, "PATH") or std.mem.eql(u8, key, "SDKROOT");
        if (!selector) continue;
        cache.field(&h, key);
        cache.field(&h, ctx.env.get(key).?);
    }
    for (selectors.items) |s| cache.field(&h, s.path);
    const key = try cache.finish(ctx.a, &h);
    try Dir.cwd().createDirPath(ctx.io, try ctx.path(&.{"toolchains"}));
    const lock_name = try std.fmt.allocPrint(ctx.a, "toolchain-{s}", .{key});
    const path = try ctx.path(&.{ "toolchains", key });
    {
        const shared = try cache.Lock.acquire(ctx, lock_name, false);
        defer shared.release();
        if (readMemo(ctx, path, selectors.items.len, is_zig, physical)) |hash| return hash;
    }
    const lock = try cache.Lock.acquire(ctx, lock_name, true);
    defer lock.release();
    if (readMemo(ctx, path, selectors.items.len, is_zig, physical)) |hash| return hash;
    const version = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ executable, if (is_zig) "version" else "-vV" }, .environ_map = ctx.env });
    switch (version.term) {
        .exited => |code| if (code != 0) return error.CompilerIdentityFailed,
        else => return error.CompilerIdentityFailed,
    }
    var locations: ?cache.RustLocations = null;
    var stamps: std.ArrayList(Stamp) = .empty;
    try stamps.appendSlice(ctx.a, selectors.items);
    if (is_zig) {
        const result = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ executable, "env" }, .environ_map = ctx.env });
        // Zig 0.17's `zig env` uses ZON; deserialize its public lib_dir field.
        const Env = struct { lib_dir: []const u8 };
        var diagnostics: std.zon.parse.Diagnostics = undefined;
        const parsed = try std.zon.parse.fromSlice(Env, .{ .gpa = ctx.a, .arena = ctx.a, .source = try ctx.a.dupeSentinel(u8, result.stdout, 0), .diagnostics = &diagnostics, .ignore_unknown_fields = true });
        try add(ctx, &stamps, parsed.lib_dir);
        // Eligible Zig invocations contain no C/C++ source, @cImport, libc
        // linking, or custom SDK options. Fingerprint their Zig resources,
        // rather than statting 19,000 unrelated platform headers on every hit.
        for ([_][]const u8{ "std", "compiler", "compiler_rt" }) |sub|
            try tree(ctx, &stamps, try std.fs.path.join(ctx.a, &.{ parsed.lib_dir, sub }));
        for ([_][]const u8{ "compiler_rt.zig", "ubsan_rt.zig" }) |sub|
            try add(ctx, &stamps, try std.fs.path.join(ctx.a, &.{ parsed.lib_dir, sub }));
        // Zig supplies Darwin's implicit libSystem link stubs itself.
        try tree(ctx, &stamps, try std.fs.path.join(ctx.a, &.{ parsed.lib_dir, "libc", "darwin" }));
    } else {
        const result = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ executable, "--print", "sysroot", "--print", "target-libdir" }, .environ_map = ctx.env });
        switch (result.term) {
            .exited => |code| if (code != 0) return error.CompilerIdentityFailed,
            else => return error.CompilerIdentityFailed,
        }
        var lines = std.mem.tokenizeAny(u8, result.stdout, "\r\n");
        const sysroot = lines.next() orelse return error.InvalidSysroot;
        const target_libdir = lines.next() orelse return error.InvalidSysroot;
        if (lines.next() != null or !std.fs.path.isAbsolute(sysroot) or !std.fs.path.isAbsolute(target_libdir)) return error.InvalidSysroot;
        const installed = try std.fs.path.join(ctx.a, &.{ sysroot, "bin", "rustc" });
        var loader_override = false;
        for (ctx.env.keys()) |name| if (std.mem.startsWith(u8, name, "LD_") or std.mem.startsWith(u8, name, "DYLD_")) {
            loader_override = true;
        };
        // Only the direct, canonical stock compiler may reuse these locations.
        // Proxies, aliases, explicit targets and loader overrides query live.
        const fallback_verified = @import("rust_loader.zig").allowsFallback(ctx, real, sysroot) catch false;
        if (physical and (!loader_override or fallback_verified) and std.mem.eql(u8, executable, real) and std.mem.eql(u8, real, installed) and
            std.mem.startsWith(u8, version.stdout, "rustc 1.97.1 (8bab26f4f 2026-07-14)\n"))
            locations = .{ .compiler = real, .sysroot = sysroot, .target_libdir = target_libdir, .fallback_verified = fallback_verified };
        try add(ctx, &stamps, target_libdir);
        try add(ctx, &stamps, try std.fs.path.join(ctx.a, &.{ sysroot, "bin", "rustc" }));
        rustResources(ctx, &stamps, try std.fs.path.join(ctx.a, &.{ sysroot, "lib" })) catch |err| {
            ctx.trace(try std.fmt.allocPrint(ctx.a, "Rust resources unavailable: {s} ({s})", .{ sysroot, @errorName(err) }));
            return err;
        };
    }
    h = cache.Hash.init(.{});
    cache.field(&h, version.stdout);
    cache.field(&h, version.stderr);
    var decoder = cache.Hash.init(.{});
    cache.field(&decoder, "metadata-decoder-selected-resources-v2");
    cache.field(&decoder, version.stdout);
    cache.field(&decoder, version.stderr);
    // Stable sorting makes the content identity independent of enumeration order.
    std.mem.sort(Stamp, stamps.items, {}, struct {
        fn less(_: void, a: Stamp, b: Stamp) bool {
            return std.mem.order(u8, a.path, b.path) == .lt;
        }
    }.less);
    const prefetched = if (is_zig) null else try parallelRustDigests(ctx, stamps.items);
    for (stamps.items, 0..) |s, i| {
        cache.field(&h, s.path);
        // Selection state stays in the complete fingerprint and all stamp
        // checks. Classification is scoped to the resolved compiler resources.
        var decoder_resource = s.exists;
        if (!is_zig and !std.mem.eql(u8, s.path, real)) {
            for (selectors.items) |selector| {
                if (std.mem.eql(u8, s.path, selector.path)) {
                    decoder_resource = false;
                    break;
                }
            }
        }
        if (decoder_resource) cache.field(&decoder, s.path);
        if (s.exists and s.kind == .file) {
            const digest = (if (prefetched) |jobs| blk: {
                if (jobs[i].err) |err| break :blk @as(anyerror![]const u8, err);
                break :blk @as(anyerror![]const u8, &jobs[i].hash);
            } else if (is_zig) ctx.digest(s.path) else rustFileDigest(ctx, s)) catch |err| {
                ctx.trace(try std.fmt.allocPrint(ctx.a, "toolchain file unavailable: {s} ({s})", .{ s.path, @errorName(err) }));
                return err;
            };
            cache.field(&h, digest);
            if (decoder_resource) cache.field(&decoder, digest);
        }
    }
    // A compiler update concurrent with fingerprinting is not a valid identity.
    for (stamps.items) |s| if (!equal(s, try stamp(ctx, s.path))) return error.ToolchainChanged;
    const hash = try cache.finish(ctx.a, &h);
    const decoder_hash = try cache.finish(ctx.a, &decoder);
    const bytes = try std.json.Stringify.valueAlloc(ctx.a, Memo{ .locations = locations, .hash = hash, .decoder_hash = decoder_hash, .stamps = stamps.items }, .{});
    try ctx.atomic(path, try cache.seal(ctx, bytes));
    try rememberEpoch(ctx, bytes);
    ctx.compiler_decoder_identity = decoder_hash;
    ctx.rust_locations = locations;
    return hash;
}

test "shared Rust toolchain digests reject corruption and preserved-mtime edits" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    const relative = try std.fs.path.join(a, &.{ ".zig-cache", "tmp", &tmp.sub_path });
    const cwd = try Dir.cwd().realPathFileAlloc(io, relative, a);
    var env = std.process.Environ.Map.init(a);
    var ctx: cache.Context = .{ .a = a, .io = io, .env = &env, .root = try std.fs.path.join(a, &.{ cwd, "cache" }), .cwd = cwd };
    try ctx.prepare();
    try tmp.dir.writeFile(io, .{ .sub_path = "resource", .data = "first_" });
    const input = try std.fs.path.join(a, &.{ cwd, "resource" });
    const before = try stamp(&ctx, input);
    const first = try rustFileDigest(&ctx, before);
    try std.testing.expectEqualStrings(try ctx.digest(input), first);
    try std.testing.expectEqualStrings(first, try rustFileDigest(&ctx, before));
    try tmp.dir.writeFile(io, .{ .sub_path = "resource", .data = "second" });
    const file = try tmp.dir.openFile(io, "resource", .{});
    defer file.close(io);
    try file.setTimestamps(io, .{ .modify_timestamp = .{ .new = .{ .nanoseconds = before.mtime } } });
    const after = try stamp(&ctx, input);
    try std.testing.expectEqual(before.mtime, after.mtime);
    try std.testing.expect(!equal(before, after));
    const second = try rustFileDigest(&ctx, after);
    try std.testing.expect(!std.mem.eql(u8, first, second));
    try std.testing.expectEqualStrings(try ctx.digest(input), second);
    var memos = try Dir.cwd().openDir(io, try ctx.path(&.{"toolchain-files"}), .{ .iterate = true });
    defer memos.close(io);
    var iterator = memos.iterate();
    const entry = (try iterator.next(io)).?;
    try memos.writeFile(io, .{ .sub_path = entry.name, .data = "corrupt" });
    try std.testing.expectEqualStrings(second, try rustFileDigest(&ctx, after));
}

test "parallel installed stamp validation rejects edits and missing files" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    const cwd = try Dir.cwd().realPathFileAlloc(io, try std.fs.path.join(a, &.{ ".zig-cache", "tmp", &tmp.sub_path }), a);
    var env = std.process.Environ.Map.init(a);
    var ctx: cache.Context = .{ .a = a, .io = io, .env = &env, .root = cwd, .cwd = cwd };
    try tmp.dir.writeFile(io, .{ .sub_path = "resource", .data = "before" });
    const path = try std.fs.path.join(a, &.{ cwd, "resource" });
    const expected = try stamp(&ctx, path);
    const stamps = try a.alloc(Stamp, 512);
    @memset(stamps, expected);
    try std.testing.expect(validStamps(&ctx, stamps, true));
    try tmp.dir.writeFile(io, .{ .sub_path = "resource", .data = "after_" });
    const file = try tmp.dir.openFile(io, "resource", .{});
    defer file.close(io);
    try file.setTimestamps(io, .{ .modify_timestamp = .{ .new = .{ .nanoseconds = expected.mtime } } });
    try std.testing.expect(!validStamps(&ctx, stamps, true));
    try tmp.dir.deleteFile(io, "resource");
    try std.testing.expect(!validStamps(&ctx, stamps, true));
}

// Trusted installed directories use content fingerprints plus complete stamps.
// Mutable project trees must never use this memo.
const InstalledLink = struct { path: []const u8, resolved: []const u8, inode: u64, mtime: i96, ctime: i96 };
fn installedLink(ctx: *cache.Context, path: []const u8) !InstalledLink {
    const st = try Dir.cwd().statFile(ctx.io, path, .{ .follow_symlinks = false });
    if (st.kind != .sym_link) return error.LinkChanged;
    return .{ .path = path, .resolved = try Dir.cwd().realPathFileAlloc(ctx.io, path, ctx.a), .inode = @intCast(st.inode), .mtime = st.mtime.nanoseconds, .ctime = st.ctime.nanoseconds };
}
fn validLinks(ctx: *cache.Context, links: []const InstalledLink) bool {
    for (links) |expected| {
        const current = installedLink(ctx, expected.path) catch return false;
        if (current.inode != expected.inode or current.mtime != expected.mtime or current.ctime != expected.ctime or !std.mem.eql(u8, current.resolved, expected.resolved)) return false;
    }
    return true;
}
fn installedGraph(ctx: *cache.Context, stamps: *std.ArrayList(Stamp), links: *std.ArrayList(InstalledLink), seen: *std.StringHashMap(void), path: []const u8) !void {
    if (seen.contains(path)) return;
    if (seen.count() >= 100000) return error.TooManyInstalledInputs;
    try seen.put(path, {});
    const st = try Dir.cwd().statFile(ctx.io, path, .{ .follow_symlinks = false });
    if (st.kind == .sym_link) {
        const link = try installedLink(ctx, path);
        try links.append(ctx.a, link);
        return installedGraph(ctx, stamps, links, seen, link.resolved);
    }
    if (st.kind != .file and st.kind != .directory) return error.UnsupportedInstalledInput;
    try stamps.append(ctx.a, try stamp(ctx, path));
    if (st.kind == .directory) {
        var dir = try Dir.cwd().openDir(ctx.io, path, .{ .iterate = true });
        defer dir.close(ctx.io);
        var it = dir.iterate();
        while (try it.next(ctx.io)) |entry| try installedGraph(ctx, stamps, links, seen, try std.fs.path.join(ctx.a, &.{ path, entry.name }));
    }
}
pub fn installedTreeDigest(ctx: *cache.Context, root: []const u8) ![]const u8 {
    const TreeMemo = struct { schema: u32 = 2, hash: []const u8, stamps: []const Stamp, links: []const InstalledLink };
    const canonical = try Dir.cwd().realPathFileAlloc(ctx.io, root, ctx.a);
    var h = cache.Hash.init(.{});
    cache.field(&h, "installed-script-tree-v2");
    cache.field(&h, canonical);
    const key = try cache.finish(ctx.a, &h);
    const path = try ctx.path(&.{ "script-tools", key });
    const lock = try cache.Lock.acquire(ctx, try std.fmt.allocPrint(ctx.a, "script-tool-{s}", .{key}), true);
    defer lock.release();
    if (ctx.read(path)) |bytes| memo: {
        const payload = cache.unseal(ctx, bytes) catch break :memo;
        const parsed = std.json.parseFromSlice(TreeMemo, ctx.a, payload, .{ .allocate = .alloc_always }) catch break :memo;
        if (parsed.value.schema == 2 and cache.validHash(parsed.value.hash) and parsed.value.stamps.len > 0 and validLinks(ctx, parsed.value.links) and validStamps(ctx, parsed.value.stamps, false)) return parsed.value.hash;
    } else |_| {}
    var stamps: std.ArrayList(Stamp) = .empty;
    var links: std.ArrayList(InstalledLink) = .empty;
    var seen = std.StringHashMap(void).init(ctx.a);
    defer seen.deinit();
    try installedGraph(ctx, &stamps, &links, &seen, canonical);
    std.mem.sort(Stamp, stamps.items, {}, struct {
        fn less(_: void, a: Stamp, b: Stamp) bool {
            return std.mem.order(u8, a.path, b.path) == .lt;
        }
    }.less);
    std.mem.sort(InstalledLink, links.items, {}, struct {
        fn less(_: void, a: InstalledLink, b: InstalledLink) bool {
            return std.mem.order(u8, a.path, b.path) == .lt;
        }
    }.less);
    h = cache.Hash.init(.{});
    for (links.items) |link| {
        cache.field(&h, link.path);
        cache.field(&h, link.resolved);
    }
    for (stamps.items) |st| {
        cache.field(&h, st.path);
        cache.field(&h, @tagName(st.kind));
        // The whole-tree record already preserves every trusted-installation
        // stamp. Hash every initial byte directly; thousands of independent
        // file locks and persistent records add no validation to this record.
        if (st.kind == .file) cache.field(&h, try ctx.digest(st.path));
    }
    if (!validLinks(ctx, links.items) or !validStamps(ctx, stamps.items, false)) return error.ToolchainChanged;
    const digest = try cache.finish(ctx.a, &h);
    try ctx.atomic(path, try cache.seal(ctx, try std.json.Stringify.valueAlloc(ctx.a, TreeMemo{ .hash = digest, .stamps = stamps.items, .links = links.items }, .{})));
    return digest;
}
