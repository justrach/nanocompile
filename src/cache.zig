const std = @import("std");
const builtin = @import("builtin");
const c = struct {
    extern "c" fn open(path: [*:0]const u8, flags: c_int, ...) c_int;
    extern "c" fn close(fd: c_int) c_int;
    extern "c" fn write(fd: c_int, bytes: [*]const u8, len: usize) isize;
    extern "c" fn getpid() c_int;
    extern "c" fn flock(fd: c_int, operation: c_int) c_int;
    extern "c" fn clonefile(src: [*:0]const u8, dst: [*:0]const u8, flags: u32) c_int;
    extern "c" fn ioctl(fd: c_int, request: c_ulong, ...) c_int;
    const O_RDONLY = 0;
    const O_WRONLY = 1;
    const O_RDWR = 2;
    const O_CREAT = if (builtin.os.tag == .macos) 0x200 else 0x40;
    const O_EXCL = if (builtin.os.tag == .macos) 0x800 else 0x80;
    const O_APPEND = if (builtin.os.tag == .macos) 0x8 else 0x400;
    const O_CLOEXEC = if (builtin.os.tag == .macos) 0x1000000 else 0x80000;
    const LOCK_SH = 1;
    const LOCK_EX = 2;
    const LOCK_UN = 8;
    const FICLONE = 0x40049409;
};
const Dir = std.Io.Dir;
pub const Hash = std.crypto.hash.Blake3;

pub const Context = struct {
    a: std.mem.Allocator,
    io: std.Io,
    env: *std.process.Environ.Map,
    root: []const u8,
    cwd: []const u8,
    compiler_identity: ?[]const u8 = null,

    pub fn init(a: std.mem.Allocator, io: std.Io, env: *std.process.Environ.Map) !Context {
        const root = env.get("NANOCOMPILE_DIR") orelse try std.fs.path.join(a, &.{
            env.get("XDG_CACHE_HOME") orelse try std.fs.path.join(a, &.{ env.get("HOME") orelse return error.NoHome, ".cache" }),
            "nanocompile",
        });
        const cwd = try std.process.currentPathAlloc(io, a);
        return .{ .a = a, .io = io, .env = env, .root = try std.fs.path.resolve(a, &.{ cwd, root }), .cwd = cwd };
    }

    pub fn path(self: *Context, parts: []const []const u8) ![]const u8 {
        var all: std.ArrayList([]const u8) = .empty;
        try all.append(self.a, self.root);
        try all.appendSlice(self.a, parts);
        return std.fs.path.join(self.a, all.items);
    }

    pub fn prepare(self: *Context) !void {
        for ([_][]const u8{ "entries", "blobs", "locks" }) |sub|
            try Dir.cwd().createDirPath(self.io, try self.path(&.{sub}));
    }

    pub fn out(self: *Context, bytes: []const u8) !void {
        try std.Io.File.stdout().writeStreamingAll(self.io, bytes);
    }

    pub fn trace(self: *Context, reason: []const u8) void {
        if (self.env.get("NANOCOMPILE_TRACE")) |v| {
            if (std.mem.eql(u8, v, "1")) std.debug.print("nanocompile: {s}\n", .{reason});
        }
    }

    pub fn read(self: *Context, path_: []const u8) ![]u8 {
        return Dir.cwd().readFileAlloc(self.io, path_, self.a, .limited(64 * 1024 * 1024));
    }

    pub fn digest(self: *Context, path_: []const u8) ![]const u8 {
        const file = try Dir.cwd().openFile(self.io, path_, .{});
        defer file.close(self.io);
        if ((try file.stat(self.io)).kind != .file) return error.NotRegularFile;
        var h = Hash.init(.{});
        var buffer: [64 * 1024]u8 = undefined;
        var reader = file.reader(self.io, &buffer);
        var block: [64 * 1024]u8 = undefined;
        while (true) {
            const n = try reader.interface.readSliceShort(&block);
            if (n == 0) break;
            h.update(block[0..n]);
        }
        return finish(self.a, &h);
    }

    pub fn libraryNames(self: *Context, path_: []const u8, outputs: []const []const u8) ![]const []const u8 {
        var dir = try Dir.cwd().openDir(self.io, path_, .{ .iterate = true });
        defer dir.close(self.io);
        var iterator = dir.iterate();
        var names: std.ArrayList([]const u8) = .empty;
        while (try iterator.next(self.io)) |entry| {
            if (!std.mem.endsWith(u8, entry.name, ".rlib") and !std.mem.endsWith(u8, entry.name, ".rmeta") and !std.mem.endsWith(u8, entry.name, ".dylib") and !std.mem.endsWith(u8, entry.name, ".so")) continue;
            const full = try std.fs.path.join(self.a, &.{ path_, entry.name });
            var ignored = false;
            for (outputs) |out_| if (std.mem.eql(u8, full, out_)) {
                ignored = true;
                break;
            };
            if (!ignored) try names.append(self.a, try std.fmt.allocPrint(self.a, "{s}:{s}", .{ entry.name, @tagName(entry.kind) }));
        }
        std.mem.sort([]const u8, names.items, {}, struct {
            fn less(_: void, a: []const u8, b: []const u8) bool {
                return std.mem.order(u8, a, b) == .lt;
            }
        }.less);
        return names.items;
    }

    pub fn libraryDigest(self: *Context, path_: []const u8, prefix: []const u8, outputs: []const []const u8) ![]const u8 {
        return prefixDigest(self.a, try self.libraryNames(path_, outputs), prefix);
    }

    pub fn directoryDigest(self: *Context, path_: []const u8, libraries: bool, outputs: []const []const u8) ![]const u8 {
        return self.membersDigest(path_, libraries, false, outputs);
    }

    pub fn nativeDirectoryDigest(self: *Context, path_: []const u8) ![]const u8 {
        return self.membersDigest(path_, false, true, &.{});
    }

    fn membersDigest(self: *Context, path_: []const u8, libraries: bool, all_members: bool, outputs: []const []const u8) ![]const u8 {
        var dir = try Dir.cwd().openDir(self.io, path_, .{ .iterate = true });
        defer dir.close(self.io);
        var iterator = dir.iterate();
        var names: std.ArrayList([]const u8) = .empty;
        while (try iterator.next(self.io)) |entry| {
            if (libraries) {
                const relevant = std.mem.endsWith(u8, entry.name, ".rlib") or std.mem.endsWith(u8, entry.name, ".rmeta") or std.mem.endsWith(u8, entry.name, ".dylib") or std.mem.endsWith(u8, entry.name, ".so");
                if (!relevant) continue;
                const full = try std.fs.path.join(self.a, &.{ path_, entry.name });
                var ignored = false;
                for (outputs) |out_| if (std.mem.eql(u8, full, out_)) {
                    ignored = true;
                    break;
                };
                if (ignored) continue;
            }
            // Rust's file-vs-directory module resolution observes these names.
            if (all_members or libraries or entry.kind == .directory or std.mem.endsWith(u8, entry.name, ".rs"))
                try names.append(self.a, try std.fmt.allocPrint(self.a, "{s}:{s}", .{ entry.name, @tagName(entry.kind) }));
        }
        std.mem.sort([]const u8, names.items, {}, struct {
            fn less(_: void, a: []const u8, b: []const u8) bool {
                return std.mem.order(u8, a, b) == .lt;
            }
        }.less);
        var h = Hash.init(.{});
        for (names.items) |name| field(&h, name);
        return finish(self.a, &h);
    }

    pub fn atomic(self: *Context, path_: []const u8, bytes: []const u8) !void {
        var file = try Dir.cwd().createFileAtomic(self.io, path_, .{ .make_path = true, .replace = true, .permissions = .fromMode(0o600) });
        defer file.deinit(self.io);
        try file.file.writeStreamingAll(self.io, bytes);
        try file.replace(self.io);
    }

    pub fn event(self: *Context, name: []const u8) void {
        const path_ = self.path(&.{"events"}) catch return;
        const z = self.a.dupeSentinel(u8, path_, 0) catch return;
        const fd = c.open(z, c.O_WRONLY | c.O_CREAT | c.O_APPEND | c.O_CLOEXEC, @as(c_uint, 0o600));
        if (fd < 0) return;
        defer _ = c.close(fd);
        const line = std.fmt.allocPrint(self.a, "{s}\n", .{name}) catch return;
        _ = c.write(fd, line.ptr, line.len);
    }
};

pub const Lock = struct {
    fd: c_int,
    pub fn acquire(ctx: *Context, name: []const u8, exclusive: bool) !Lock {
        const z = try ctx.a.dupeSentinel(u8, try ctx.path(&.{ "locks", name }), 0);
        const fd = c.open(z, c.O_RDWR | c.O_CREAT | c.O_CLOEXEC, @as(c_uint, 0o600));
        if (fd < 0) return error.LockOpenFailed;
        errdefer _ = c.close(fd);
        if (c.flock(fd, if (exclusive) c.LOCK_EX else c.LOCK_SH) != 0) return error.LockFailed;
        return .{ .fd = fd };
    }
    pub fn release(self: Lock) void {
        _ = c.flock(self.fd, c.LOCK_UN);
        _ = c.close(self.fd);
    }
};

pub fn field(h: *Hash, value: []const u8) void {
    var size: [8]u8 = undefined;
    std.mem.writeInt(u64, &size, value.len, .little);
    h.update(&size);
    h.update(value);
}

pub fn finish(a: std.mem.Allocator, h: *Hash) ![]const u8 {
    var bytes: [32]u8 = undefined;
    h.final(&bytes);
    return a.dupe(u8, &std.fmt.bytesToHex(bytes, .lower));
}

pub fn validHash(hash: []const u8) bool {
    if (hash.len != 64) return false;
    for (hash) |ch| if (!std.ascii.isDigit(ch) and !(ch >= 'a' and ch <= 'f')) return false;
    return true;
}

pub fn seal(ctx: *Context, bytes: []const u8) ![]const u8 {
    var hash = Hash.init(.{});
    hash.update(bytes);
    return std.fmt.allocPrint(ctx.a, "{s}\n{s}", .{ try finish(ctx.a, &hash), bytes });
}

pub fn unseal(ctx: *Context, bytes: []const u8) ![]const u8 {
    if (bytes.len < 65 or bytes[64] != '\n' or !validHash(bytes[0..64])) return error.InvalidEntry;
    var hash = Hash.init(.{});
    hash.update(bytes[65..]);
    if (!std.mem.eql(u8, try finish(ctx.a, &hash), bytes[0..64])) return error.InvalidEntry;
    return bytes[65..];
}

pub const Dependency = struct { path: []const u8, hash: []const u8, directory: bool = false, libraries: bool = false, library_prefix: ?[]const u8 = null, all_members: bool = false, missing: ?bool = null, symlink_target: ?[]const u8 = null };

pub fn symlinkDependency(ctx: *Context, path_: []const u8) !Dependency {
    const path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, path_ });
    if ((try Dir.cwd().statFile(ctx.io, path, .{ .follow_symlinks = false })).kind != .sym_link) return error.NotSymbolicLink;
    var buffer: [std.fs.max_path_bytes]u8 = undefined;
    const target = try ctx.a.dupe(u8, buffer[0..try Dir.cwd().readLink(ctx.io, path, &buffer)]);
    return .{ .path = path, .hash = try symlinkHash(ctx, path, target), .symlink_target = target };
}

fn symlinkHash(ctx: *Context, path: []const u8, target: []const u8) ![]const u8 {
    var h = Hash.init(.{});
    field(&h, "nanocompile-link-target-v1");
    field(&h, path);
    field(&h, target);
    return finish(ctx.a, &h);
}

fn symlinkValid(ctx: *Context, dep: Dependency) !bool {
    const target = dep.symlink_target orelse return false;
    if (target.len == 0 or dep.missing != null or dep.directory or dep.libraries or dep.all_members or
        dep.library_prefix != null or !std.fs.path.isAbsolute(dep.path)) return false;
    if (!std.mem.eql(u8, dep.hash, try symlinkHash(ctx, dep.path, target))) return false;
    if ((try Dir.cwd().statFile(ctx.io, dep.path, .{ .follow_symlinks = false })).kind != .sym_link) return false;
    var buffer: [std.fs.max_path_bytes]u8 = undefined;
    return std.mem.eql(u8, target, buffer[0..try Dir.cwd().readLink(ctx.io, dep.path, &buffer)]);
}

/// Negative linker lookups are inputs too. A later successful lookup must
/// invalidate restoration. Never treat access errors as evidence of absence.
pub fn missingDependency(ctx: *Context, path_: []const u8) !Dependency {
    const path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, path_ });
    if (!try absent(ctx, path)) return error.InputAlreadyExists;
    return .{ .path = path, .hash = try absentHash(ctx, path), .missing = true };
}

fn absentHash(ctx: *Context, path_: []const u8) ![]const u8 {
    var hash = Hash.init(.{});
    field(&hash, "nanocompile-absent-link-input-v1");
    field(&hash, path_);
    return finish(ctx.a, &hash);
}

fn absent(ctx: *Context, path_: []const u8) !bool {
    _ = Dir.cwd().statFile(ctx.io, path_, .{}) catch |err| switch (err) {
        error.FileNotFound, error.NotDir => return true,
        else => return err,
    };
    return false;
}

fn missingValid(ctx: *Context, dep: Dependency) !bool {
    if (dep.missing != true or dep.symlink_target != null or dep.directory or dep.libraries or dep.all_members or dep.library_prefix != null or !std.fs.path.isAbsolute(dep.path)) return false;
    if (!std.mem.eql(u8, dep.hash, try absentHash(ctx, dep.path))) return false;
    return absent(ctx, dep.path);
}
pub const Output = struct { path: []const u8, hash: []const u8, mode: u32 };
const entry_schema = 5;
pub const ArtifactInfo = struct { namespace: []const u8, key: []const u8, metadata: []const u8 };
pub const Entry = struct {
    artifact: ?ArtifactInfo = null,
    schema: u32 = entry_schema,
    dependencies: []const Dependency,
    outputs: []const Output,
    stdout: []const u8,
    stderr: []const u8,
};

fn parseEntry(ctx: *Context, bytes: []const u8) !Entry {
    const parsed = try std.json.parseFromSlice(Entry, ctx.a, try unseal(ctx, bytes), .{ .allocate = .alloc_always });
    return parsed.value;
}

fn blobPath(ctx: *Context, hash: []const u8) ![]const u8 {
    if (!validHash(hash)) return error.InvalidHash;
    return ctx.path(&.{ "blobs", hash[0..2], hash });
}

// Never hardlink: a later linker, strip, or user write must not mutate the cache.
pub fn materialize(ctx: *Context, source: []const u8, destination: []const u8, mode: u32) !void {
    try Dir.cwd().createDirPath(ctx.io, std.fs.path.dirname(destination) orelse ".");
    const temp = try std.fmt.allocPrint(ctx.a, "{s}.nano-{d}", .{ destination, c.getpid() });
    defer Dir.cwd().deleteFile(ctx.io, temp) catch {};
    Dir.cwd().deleteFile(ctx.io, temp) catch {};
    const src_z = try ctx.a.dupeSentinel(u8, source, 0);
    const dst_z = try ctx.a.dupeSentinel(u8, temp, 0);
    const cloned = if (builtin.os.tag == .macos)
        c.clonefile(src_z, dst_z, 0) == 0
    else blk: {
        const src = c.open(src_z, c.O_RDONLY | c.O_CLOEXEC);
        if (src < 0) break :blk false;
        defer _ = c.close(src);
        const dst = c.open(dst_z, c.O_WRONLY | c.O_CREAT | c.O_EXCL | c.O_CLOEXEC, @as(c_uint, 0o600));
        if (dst < 0) break :blk false;
        defer _ = c.close(dst);
        break :blk c.ioctl(dst, c.FICLONE, src) == 0;
    };
    if (!cloned) {
        Dir.cwd().deleteFile(ctx.io, temp) catch {};
        try Dir.cwd().copyFile(source, .cwd(), temp, ctx.io, .{});
    }
    const file = try Dir.cwd().openFile(ctx.io, temp, .{ .mode = .read_write });
    defer file.close(ctx.io);
    try file.setPermissions(ctx.io, .fromMode(@intCast(mode & 0o777)));
    try Dir.cwd().rename(temp, .cwd(), destination, ctx.io);
}

pub fn putFile(ctx: *Context, source: []const u8) ![]const u8 {
    const hash = try ctx.digest(source);
    const destination = try blobPath(ctx, hash);
    const existing = ctx.digest(destination) catch "";
    if (!std.mem.eql(u8, hash, existing)) try materialize(ctx, source, destination, 0o600);
    return hash;
}

fn putBytes(ctx: *Context, bytes: []const u8) ![]const u8 {
    var h = Hash.init(.{});
    h.update(bytes);
    const hash = try finish(ctx.a, &h);
    try ctx.atomic(try blobPath(ctx, hash), bytes);
    return hash;
}

pub fn store(ctx: *Context, key: []const u8, dependencies: []const Dependency, output_paths: []const []const u8, stdout: []const u8, stderr: []const u8) !void {
    for (dependencies) |dep| if (dep.missing != null and !try missingValid(ctx, dep)) return error.InvalidMissingDependency;
    for (dependencies) |dep| if (dep.symlink_target != null and !try symlinkValid(ctx, dep)) return error.InvalidSymlinkDependency;
    var outputs: std.ArrayList(Output) = .empty;
    for (output_paths) |path_| {
        const st = try Dir.cwd().statFile(ctx.io, path_, .{});
        if (st.kind != .file) return error.NotRegularFile;
        try outputs.append(ctx.a, .{ .path = path_, .hash = try putFile(ctx, path_), .mode = @intCast(st.permissions.toMode()) });
    }
    const entry: Entry = .{
        .dependencies = dependencies,
        .outputs = outputs.items,
        .stdout = try putBytes(ctx, stdout),
        .stderr = try putBytes(ctx, stderr),
    };
    const bytes = try std.json.Stringify.valueAlloc(ctx.a, entry, .{ .emit_null_optional_fields = false });
    try ctx.atomic(try ctx.path(&.{ "entries", key }), try seal(ctx, bytes));
}

/// Opaque task artifacts share sealed entries, CAS blobs, GC and R2 transport.
/// Task input discovery and archive extraction belong to the calling build tool.
pub fn artifactKey(ctx: *Context, namespace: []const u8, key: []const u8) ![]const u8 {
    if (namespace.len == 0 or namespace.len > 1024 or key.len == 0 or key.len > 1024) return error.InvalidArtifactIdentity;
    var h = Hash.init(.{});
    field(&h, "nanocompile-opaque-artifact-v1");
    field(&h, namespace);
    field(&h, key);
    return finish(ctx.a, &h);
}

pub fn storeArtifact(ctx: *Context, namespace: []const u8, key: []const u8, source: []const u8, metadata_: []const u8) !void {
    if (metadata_.len > 8192) return error.ArtifactMetadataTooLarge;
    _ = try std.json.parseFromSlice(std.json.Value, ctx.a, metadata_, .{});
    const entry: Entry = .{
        .artifact = .{ .namespace = namespace, .key = key, .metadata = metadata_ },
        .dependencies = &.{},
        .outputs = &.{.{ .path = "artifact", .hash = try putFile(ctx, source), .mode = 0o600 }},
        .stdout = try putBytes(ctx, ""),
        .stderr = try putBytes(ctx, ""),
    };
    const bytes = try std.json.Stringify.valueAlloc(ctx.a, entry, .{});
    try ctx.atomic(try ctx.path(&.{ "entries", try artifactKey(ctx, namespace, key) }), try seal(ctx, bytes));
}

pub fn fetchArtifact(ctx: *Context, namespace: []const u8, key: []const u8, destination: ?[]const u8) !bool {
    const identity = try artifactKey(ctx, namespace, key);
    const entry = parseEntry(ctx, ctx.read(try ctx.path(&.{ "entries", identity })) catch return false) catch return false;
    const info = entry.artifact orelse return false;
    if (entry.schema != entry_schema or entry.dependencies.len != 0 or entry.outputs.len != 1 or
        !std.mem.eql(u8, info.namespace, namespace) or !std.mem.eql(u8, info.key, key) or
        !std.mem.eql(u8, entry.outputs[0].path, "artifact")) return false;
    const source = blobPath(ctx, entry.outputs[0].hash) catch return false;
    const actual = ctx.digest(source) catch return false;
    if (!std.mem.eql(u8, actual, entry.outputs[0].hash)) return false;
    const st = try Dir.cwd().statFile(ctx.io, source, .{});
    if (destination) |out_| try materialize(ctx, source, out_, 0o600);
    const result = try std.json.Stringify.valueAlloc(ctx.a, .{ .hit = true, .bytes = st.size, .metadata = info.metadata }, .{});
    try ctx.out(result);
    try ctx.out("\n");
    return true;
}

pub fn restore(ctx: *Context, key: []const u8, allowed_outputs: []const []const u8) !bool {
    const bytes = ctx.read(try ctx.path(&.{ "entries", key })) catch return false;
    const entry = parseEntry(ctx, bytes) catch return false;
    if (entry.artifact != null or entry.schema != entry_schema or entry.outputs.len != allowed_outputs.len) return false;
    // One crate graph can record many prefixes in the same Cargo directory,
    // and explicit externs can also appear in the transitive graph. Reuse the
    // enumeration and content hashes only within this restore. No metadata
    // shortcut survives a compiler invocation or a before/after input check.
    var library_names: std.StringHashMapUnmanaged([]const []const u8) = .empty;
    defer library_names.deinit(ctx.a);
    var file_hashes: std.StringHashMapUnmanaged([]const u8) = .empty;
    defer file_hashes.deinit(ctx.a);
    for (entry.dependencies) |dep| {
        if (dep.symlink_target != null) {
            if (!(symlinkValid(ctx, dep) catch false)) return false;
            continue;
        }
        if (dep.missing != null) {
            if (!(missingValid(ctx, dep) catch false)) {
                ctx.trace("miss: negative lookup changed or unavailable");
                return false;
            }
            continue;
        }
        const hash = if (dep.library_prefix) |prefix| blk: {
            const slot = try library_names.getOrPut(ctx.a, dep.path);
            if (!slot.found_existing) slot.value_ptr.* = ctx.libraryNames(dep.path, allowed_outputs) catch return false;
            break :blk try prefixDigest(ctx.a, slot.value_ptr.*, prefix);
        } else if (dep.all_members)
            ctx.nativeDirectoryDigest(dep.path) catch return false
        else if (dep.directory)
            ctx.directoryDigest(dep.path, dep.libraries, allowed_outputs) catch return false
        else blk: {
            const slot = try file_hashes.getOrPut(ctx.a, dep.path);
            if (!slot.found_existing) slot.value_ptr.* = ctx.digest(dep.path) catch return false;
            break :blk slot.value_ptr.*;
        };
        if (!std.mem.eql(u8, hash, dep.hash)) {
            ctx.trace("miss: dependency content changed");
            return false;
        }
    }
    // Validate every blob and destination before writing any output.
    for (entry.outputs, allowed_outputs) |output, allowed| {
        if (!std.mem.eql(u8, output.path, allowed)) return false;
        const hash = ctx.digest(try blobPath(ctx, output.hash)) catch return false;
        if (!std.mem.eql(u8, hash, output.hash)) return false;
    }
    const stdout = ctx.read(try blobPath(ctx, entry.stdout)) catch return false;
    const stderr = ctx.read(try blobPath(ctx, entry.stderr)) catch return false;
    var h = Hash.init(.{});
    h.update(stdout);
    if (!std.mem.eql(u8, try finish(ctx.a, &h), entry.stdout)) return false;
    h = Hash.init(.{});
    h.update(stderr);
    if (!std.mem.eql(u8, try finish(ctx.a, &h), entry.stderr)) return false;
    for (entry.outputs) |output| try materialize(ctx, try blobPath(ctx, output.hash), output.path, output.mode);
    try ctx.out(stdout);
    try std.Io.File.stderr().writeStreamingAll(ctx.io, stderr);
    return true;
}

pub fn stats(ctx: *Context) !void {
    try ctx.prepare();
    const lock = try Lock.acquire(ctx, "maintenance", false);
    defer lock.release();
    const events = ctx.read(try ctx.path(&.{"events"})) catch "";
    var hit: usize = 0;
    var miss: usize = 0;
    var bypass: usize = 0;
    var failed: usize = 0;
    var xcode_runs: usize = 0;
    var xcode_failed: usize = 0;
    var it = std.mem.tokenizeScalar(u8, events, '\n');
    while (it.next()) |event| {
        if (std.mem.eql(u8, event, "hit")) hit += 1;
        if (std.mem.eql(u8, event, "miss")) miss += 1;
        if (std.mem.eql(u8, event, "bypass")) bypass += 1;
        if (std.mem.eql(u8, event, "failed")) failed += 1;
        if (std.mem.eql(u8, event, "xcode_native_run")) xcode_runs += 1;
        if (std.mem.eql(u8, event, "xcode_native_failed")) xcode_failed += 1;
    }
    var blobs: usize = 0;
    var size: u64 = 0;
    var dir = try Dir.cwd().openDir(ctx.io, try ctx.path(&.{"blobs"}), .{ .iterate = true });
    defer dir.close(ctx.io);
    var walk = try dir.walk(ctx.a);
    defer walk.deinit();
    while (try walk.next(ctx.io)) |item| if (item.kind == .file) {
        blobs += 1;
        size += (try item.dir.statFile(ctx.io, item.basename, .{})).size;
    };
    try ctx.out(try std.fmt.allocPrint(ctx.a, "hits: {d}\nmisses: {d}\nbypasses: {d}\nfailed compilations: {d}\nblobs: {d}\nlogical bytes: {d}\n", .{ hit, miss, bypass, failed, blobs, size }));
    try ctx.out(try std.fmt.allocPrint(ctx.a, "native Xcode invocations: {d}\nnative Xcode failures: {d}\n", .{ xcode_runs, xcode_failed }));
}

pub fn clear(ctx: *Context) !void {
    try ctx.prepare();
    const lock = try Lock.acquire(ctx, "maintenance", true);
    defer lock.release();
    for ([_][]const u8{ "entries", "blobs", "xcode", "metadata", "metadata-queries" }) |sub| {
        try Dir.cwd().deleteTree(ctx.io, try ctx.path(&.{sub}));
        try Dir.cwd().createDirPath(ctx.io, try ctx.path(&.{sub}));
    }
    Dir.cwd().deleteFile(ctx.io, try ctx.path(&.{"events"})) catch {};
    try ctx.out("cache cleared\n");
}

/// Evict old entries to a logical-byte budget, retaining shared blobs until
/// their final referencing entry is gone. The maintenance lock excludes all
/// compiles, restores, and stats while the store's references are reconciled.
pub fn gc(ctx: *Context, limit: u64) !void {
    try ctx.prepare();
    const lock = try Lock.acquire(ctx, "maintenance", true);
    defer lock.release();
    const Candidate = struct { path: []const u8, entry: Entry, used: i96 };
    var candidates: std.ArrayList(Candidate) = .empty;
    var references: std.StringHashMap(usize) = .init(ctx.a);
    var sizes: std.StringHashMap(u64) = .init(ctx.a);
    var dir = try Dir.cwd().openDir(ctx.io, try ctx.path(&.{"entries"}), .{ .iterate = true });
    defer dir.close(ctx.io);
    var iterator = dir.iterate();
    while (try iterator.next(ctx.io)) |item| {
        if (item.kind != .file) continue;
        const path_ = try ctx.path(&.{ "entries", item.name });
        const st = try Dir.cwd().statFile(ctx.io, path_, .{});
        const bytes = try ctx.read(path_);
        const entry = parseEntry(ctx, bytes) catch {
            try Dir.cwd().deleteFile(ctx.io, path_);
            continue;
        };
        var hashes: std.ArrayList([]const u8) = .empty;
        try hashes.appendSlice(ctx.a, &.{ entry.stdout, entry.stderr });
        for (entry.outputs) |output| try hashes.append(ctx.a, output.hash);
        var valid = entry.schema == entry_schema;
        for (hashes.items) |hash| if (!validHash(hash)) {
            valid = false;
            break;
        };
        if (!valid) {
            try Dir.cwd().deleteFile(ctx.io, path_);
            continue;
        }
        for (hashes.items) |hash| {
            const ref = try references.getOrPut(hash);
            if (!ref.found_existing) ref.value_ptr.* = 0;
            ref.value_ptr.* += 1;
        }
        try candidates.append(ctx.a, .{ .path = path_, .entry = entry, .used = (st.atime orelse st.mtime).nanoseconds });
    }
    var blobs = try Dir.cwd().openDir(ctx.io, try ctx.path(&.{"blobs"}), .{ .iterate = true });
    defer blobs.close(ctx.io);
    var walk = try blobs.walk(ctx.a);
    defer walk.deinit();
    var total: u64 = 0;
    var freed: u64 = 0;
    while (try walk.next(ctx.io)) |item| {
        if (item.kind != .file) continue;
        const size = (try item.dir.statFile(ctx.io, item.basename, .{})).size;
        if (!references.contains(item.basename)) {
            try item.dir.deleteFile(ctx.io, item.basename);
            freed += size;
        } else {
            try sizes.put(try ctx.a.dupe(u8, item.basename), size);
            total += size;
        }
    }
    std.mem.sort(Candidate, candidates.items, {}, struct {
        fn less(_: void, a: Candidate, b: Candidate) bool {
            return a.used < b.used;
        }
    }.less);
    var evicted: usize = 0;
    for (candidates.items) |candidate| {
        if (total <= limit) break;
        try Dir.cwd().deleteFile(ctx.io, candidate.path);
        evicted += 1;
        var hashes: std.ArrayList([]const u8) = .empty;
        try hashes.appendSlice(ctx.a, &.{ candidate.entry.stdout, candidate.entry.stderr });
        for (candidate.entry.outputs) |out_| try hashes.append(ctx.a, out_.hash);
        for (hashes.items) |hash| {
            const ref = references.getPtr(hash).?;
            ref.* -= 1;
            if (ref.* == 0) {
                const size = sizes.get(hash) orelse 0;
                Dir.cwd().deleteFile(ctx.io, try blobPath(ctx, hash)) catch |err| switch (err) {
                    error.FileNotFound => {},
                    else => return err,
                };
                total -= size;
                freed += size;
            }
        }
    }
    try ctx.out(try std.fmt.allocPrint(ctx.a, "evicted entries: {d}\nfreed logical bytes: {d}\nremaining logical bytes: {d}\n", .{ evicted, freed, total }));
}

test "hash fields cannot collide through concatenation" {
    var left = Hash.init(.{});
    field(&left, "ab");
    field(&left, "c");
    var right = Hash.init(.{});
    field(&right, "a");
    field(&right, "bc");
    var l: [32]u8 = undefined;
    var r: [32]u8 = undefined;
    left.final(&l);
    right.final(&r);
    try std.testing.expect(!std.mem.eql(u8, &l, &r));
}

test "blob hashes reject traversal" {
    try std.testing.expect(!validHash("../entry"));
    try std.testing.expect(validHash("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"));
}

test "symlink guards reject retargeting before restoration writes" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    const cwd = try Dir.cwd().realPathFileAlloc(io, try std.fs.path.join(a, &.{ ".zig-cache", "tmp", &tmp.sub_path }), a);
    var env = std.process.Environ.Map.init(a);
    var ctx: Context = .{ .a = a, .io = io, .env = &env, .root = try std.fs.path.join(a, &.{ cwd, "cache" }), .cwd = cwd };
    try ctx.prepare();
    try tmp.dir.writeFile(io, .{ .sub_path = "first", .data = "same bytes" });
    try tmp.dir.writeFile(io, .{ .sub_path = "second", .data = "same bytes" });
    try tmp.dir.symLink(io, "first", "alias", .{});
    const dep = try symlinkDependency(&ctx, "alias");
    const output = try std.fs.path.join(a, &.{ cwd, "output" });
    try tmp.dir.writeFile(io, .{ .sub_path = "output", .data = "compiled" });
    const key = "123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0";
    try store(&ctx, key, &.{dep}, &.{output}, "", "");
    try tmp.dir.deleteFile(io, "output");
    try std.testing.expect(try restore(&ctx, key, &.{output}));
    try tmp.dir.deleteFile(io, "alias");
    try tmp.dir.symLink(io, "second", "alias", .{});
    try tmp.dir.writeFile(io, .{ .sub_path = "output", .data = "leave untouched" });
    try std.testing.expect(!try restore(&ctx, key, &.{output}));
    try std.testing.expectEqualStrings("leave untouched", try ctx.read(output));
    try std.testing.expectError(error.InvalidSymlinkDependency, store(&ctx, key, &.{dep}, &.{output}, "", ""));
    const changed = try symlinkDependency(&ctx, "alias");
    try std.testing.expect(!std.mem.eql(u8, changed.hash, dep.hash));
    var malformed = changed;
    malformed.directory = true;
    try std.testing.expectError(error.InvalidSymlinkDependency, store(&ctx, key, &.{malformed}, &.{output}, "", ""));
    malformed = changed;
    malformed.hash = key;
    try std.testing.expectError(error.InvalidSymlinkDependency, store(&ctx, key, &.{malformed}, &.{output}, "", ""));
    const ordinary = try std.json.Stringify.valueAlloc(a, Dependency{ .path = output, .hash = key }, .{ .emit_null_optional_fields = false });
    try std.testing.expect(std.mem.indexOf(u8, ordinary, "symlink_target") == null);
    try std.testing.expectError(error.NotSymbolicLink, symlinkDependency(&ctx, "first"));
}

test "negative linker lookups gate storage and restoration before writes" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    const relative = try std.fs.path.join(a, &.{ ".zig-cache", "tmp", &tmp.sub_path });
    const cwd = try Dir.cwd().realPathFileAlloc(io, relative, a);
    var env = std.process.Environ.Map.init(a);
    var ctx: Context = .{ .a = a, .io = io, .env = &env, .root = try std.fs.path.join(a, &.{ cwd, "cache" }), .cwd = cwd };
    try ctx.prepare();
    const output = try std.fs.path.join(a, &.{ cwd, "output" });
    const dep = try missingDependency(&ctx, "candidate.a");
    try tmp.dir.writeFile(io, .{ .sub_path = "output", .data = "compiled artifact" });
    const key = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    try store(&ctx, key, &.{dep}, &.{output}, "", "");
    try tmp.dir.deleteFile(io, "output");
    try std.testing.expect(try restore(&ctx, key, &.{output}));
    try std.testing.expectEqualStrings("compiled artifact", try ctx.read(output));
    // Appearance of a previously absent candidate cannot overwrite destinations.
    try tmp.dir.writeFile(io, .{ .sub_path = "candidate.a", .data = "new library" });
    try tmp.dir.writeFile(io, .{ .sub_path = "output", .data = "leave untouched" });
    try std.testing.expect(!try restore(&ctx, key, &.{output}));
    try std.testing.expectEqualStrings("leave untouched", try ctx.read(output));
    try std.testing.expectError(error.InputAlreadyExists, missingDependency(&ctx, dep.path));
    try std.testing.expectError(error.InvalidMissingDependency, store(&ctx, key, &.{dep}, &.{output}, "", ""));
    try tmp.dir.deleteFile(io, "candidate.a");
    try std.testing.expect(try restore(&ctx, key, &.{output}));
    // Malformed combinations cannot sneak past file-content validation.
    var malformed = dep;
    malformed.directory = true;
    try std.testing.expectError(error.InvalidMissingDependency, store(&ctx, key, &.{malformed}, &.{output}, "", ""));
    malformed = dep;
    malformed.hash = key;
    try std.testing.expectError(error.InvalidMissingDependency, store(&ctx, key, &.{malformed}, &.{output}, "", ""));
    malformed = dep;
    malformed.missing = false;
    try std.testing.expectError(error.InvalidMissingDependency, store(&ctx, key, &.{malformed}, &.{output}, "", ""));
    // Ordinary entries still omit the optional extension for older v5 readers.
    const ordinary: Dependency = .{ .path = "source.rs", .hash = key };
    const json = try std.json.Stringify.valueAlloc(a, ordinary, .{ .emit_null_optional_fields = false });
    try std.testing.expect(std.mem.indexOf(u8, json, "missing") == null);
}

// Names are sorted by libraryNames. Prefix matching deliberately follows rustc's
// over-inclusive library lookup, including alternate filenames and duplicates.
pub fn prefixDigest(a: std.mem.Allocator, names: []const []const u8, prefix: []const u8) ![]const u8 {
    var hash = Hash.init(.{});
    for (names) |name| if (std.mem.startsWith(u8, name, prefix)) field(&hash, name);
    return finish(a, &hash);
}
