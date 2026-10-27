//! File-granular opaque artifacts: one sealed entry owns every blob reference.
//! Callers discover coherent inputs and publish restored staging trees themselves.
const std = @import("std");
const cache = @import("cache.zig");
const Dir = std.Io.Dir;
const max_members = 100000;
const max_bytes: u64 = 1024 * 1024 * 1024;
const Source = struct { path: []const u8, source: []const u8 };
const Inventory = struct { schema: u32, directories: []const []const u8, files: []const Source };
const Metadata = struct { version: u32, directories: []const []const u8, metadata: []const u8 };

fn identity(ctx: *cache.Context, namespace: []const u8, key: []const u8) ![]const u8 {
    _ = try cache.artifactKey(ctx, namespace, key); // Preserve identity length limits.
    var hash = cache.Hash.init(.{});
    cache.field(&hash, "nanocompile-opaque-artifact-files-v1");
    cache.field(&hash, namespace);
    cache.field(&hash, key);
    return cache.finish(ctx.a, &hash);
}

fn blob(ctx: *cache.Context, hash: []const u8) ![]const u8 {
    if (!cache.validHash(hash)) return error.InvalidArtifactFiles;
    return ctx.path(&.{ "blobs", hash[0..2], hash });
}

fn validName(name: []const u8) bool {
    if (name.len == 0 or name.len > 4096 or std.fs.path.isAbsolute(name) or
        std.mem.indexOfAny(u8, name, "\\:\x00<>\"|?*") != null) return false;
    // Logical names are portable ASCII, avoiding Unicode/case-normalization
    // aliases on case-insensitive filesystems. Source paths remain unrestricted.
    for (name) |ch| if (ch < 0x20 or ch >= 0x7f) return false;
    var parts = std.mem.splitScalar(u8, name, '/');
    while (parts.next()) |part| {
        if (part.len == 0 or std.mem.eql(u8, part, ".") or std.mem.eql(u8, part, "..") or
            part[part.len - 1] == '.' or part[part.len - 1] == ' ') return false;
        const stem = part[0 .. std.mem.indexOfScalar(u8, part, '.') orelse part.len];
        for ([_][]const u8{ "con", "prn", "aux", "nul", "conin$", "conout$" }) |reserved|
            if (std.ascii.eqlIgnoreCase(stem, reserved)) return false;
        if (stem.len == 4 and stem[3] >= '1' and stem[3] <= '9' and
            (std.ascii.eqlIgnoreCase(stem[0..3], "com") or std.ascii.eqlIgnoreCase(stem[0..3], "lpt"))) return false;
    }
    return true;
}

fn lower(ctx: *cache.Context, name: []const u8) ![]const u8 {
    const result = try ctx.a.dupe(u8, name);
    for (result) |*ch| ch.* = std.ascii.toLower(ch.*);
    return result;
}

fn validateNames(ctx: *cache.Context, directories: []const []const u8, files: []const []const u8) !void {
    if (directories.len +| files.len == 0 or directories.len +| files.len > max_members) return error.InvalidArtifactFiles;
    var all: std.StringHashMapUnmanaged(void) = .empty;
    defer all.deinit(ctx.a);
    var dirs: std.StringHashMapUnmanaged(void) = .empty;
    defer dirs.deinit(ctx.a);
    for (directories) |name| {
        if (!validName(name)) return error.InvalidArtifactFiles;
        if ((try all.getOrPut(ctx.a, try lower(ctx, name))).found_existing) return error.InvalidArtifactFiles;
        try dirs.put(ctx.a, name, {});
    }
    for (files) |name| {
        if (!validName(name)) return error.InvalidArtifactFiles;
        if ((try all.getOrPut(ctx.a, try lower(ctx, name))).found_existing) return error.InvalidArtifactFiles;
    }
    for ([_][]const []const u8{ directories, files }) |names| for (names) |name| {
        var parent = name;
        while (std.mem.lastIndexOfScalar(u8, parent, '/')) |index| {
            parent = parent[0..index];
            if (!dirs.contains(parent)) return error.InvalidArtifactFiles;
        }
    };
}

fn userMetadata(ctx: *cache.Context, bytes: []const u8) !void {
    if (bytes.len > 8192) return error.ArtifactMetadataTooLarge;
    _ = try std.json.parseFromSlice(std.json.Value, ctx.a, bytes, .{});
}

fn store(ctx: *cache.Context, namespace: []const u8, key: []const u8, specification: []const u8, metadata: []const u8) !void {
    try userMetadata(ctx, metadata);
    const parsed = try std.json.parseFromSlice(Inventory, ctx.a, try ctx.read(specification), .{ .allocate = .alloc_always });
    const inventory = parsed.value;
    if (inventory.schema != 1) return error.InvalidArtifactFiles;
    const names = try ctx.a.alloc([]const u8, inventory.files.len);
    for (names, inventory.files) |*name, source| name.* = source.path;
    try validateNames(ctx, inventory.directories, names);
    const states = try ctx.a.alloc(std.Io.File.Stat, inventory.files.len);
    const paths = try ctx.a.alloc([]const u8, inventory.files.len);
    var total: u64 = 0;
    for (inventory.files, paths, states) |source, *path, *state| {
        if (source.source.len == 0 or std.mem.indexOfScalar(u8, source.source, 0) != null) return error.InvalidArtifactFiles;
        path.* = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, source.source });
        state.* = try Dir.cwd().statFile(ctx.io, path.*, .{ .follow_symlinks = false });
        if (state.kind != .file) return error.NotRegularFile;
        total +|= state.size;
        if (total > max_bytes) return error.ArtifactFilesTooLarge;
    }
    // Fresh content validation remains part of every operation, including hits.
    var full = ctx.*;
    full.digest_memo = false;
    full.entry_digests = null;
    const outputs = try ctx.a.alloc(cache.Output, paths.len);
    for (outputs, inventory.files, paths) |*output, source, path|
        output.* = .{ .path = source.path, .hash = try cache.putFile(&full, path), .mode = 0o644 };
    // Reject mutation during collection, and verify the exact stored clones.
    for (outputs, paths, states) |output, path, before| {
        const after = try Dir.cwd().statFile(ctx.io, path, .{ .follow_symlinks = false });
        if (!cache.sameFileState(before, after) or
            !std.mem.eql(u8, output.hash, try full.digest(try blob(ctx, output.hash)))) return error.ArtifactFilesChanged;
    }
    const empty = try cache.putBytes(&full, "");
    const entry: cache.Entry = .{
        .artifact = .{ .namespace = namespace, .key = key, .metadata = try std.json.Stringify.valueAlloc(ctx.a, Metadata{
            .version = 1,
            .directories = inventory.directories,
            .metadata = metadata,
        }, .{}) },
        .dependencies = &.{},
        .outputs = outputs,
        .stdout = empty,
        .stderr = empty,
    };
    const bytes = try std.json.Stringify.valueAlloc(ctx.a, entry, .{});
    if (bytes.len > 64 * 1024 * 1024 - 65) return error.ArtifactFilesTooLarge;
    try ctx.atomic(try ctx.path(&.{ "entries", try identity(ctx, namespace, key) }), try cache.seal(ctx, bytes));
    try ctx.out(try std.json.Stringify.valueAlloc(ctx.a, .{ .stored = true, .bytes = total, .files = outputs.len, .directories = inventory.directories.len }, .{}));
    try ctx.out("\n");
}

fn fetch(ctx: *cache.Context, namespace: []const u8, key: []const u8, destination: ?[]const u8) !bool {
    const id = try identity(ctx, namespace, key);
    const bytes = ctx.read(try ctx.path(&.{ "entries", id })) catch return false;
    const parsed = std.json.parseFromSlice(cache.Entry, ctx.a, cache.unseal(ctx, bytes) catch return false, .{ .allocate = .alloc_always }) catch return false;
    const entry = parsed.value;
    const info = entry.artifact orelse return false;
    if (entry.schema != cache.entry_schema or entry.dependencies.len != 0 or
        !std.mem.eql(u8, info.namespace, namespace) or !std.mem.eql(u8, info.key, key)) return false;
    const meta = std.json.parseFromSlice(Metadata, ctx.a, info.metadata, .{ .allocate = .alloc_always }) catch return false;
    if (meta.value.version != 1) return false;
    userMetadata(ctx, meta.value.metadata) catch return false;
    const names = try ctx.a.alloc([]const u8, entry.outputs.len);
    for (names, entry.outputs) |*name, output| name.* = output.path;
    validateNames(ctx, meta.value.directories, names) catch return false;
    var full = ctx.*;
    full.digest_memo = false;
    full.entry_digests = null;
    for ([_][]const u8{ entry.stdout, entry.stderr }) |hash| {
        const path = blob(ctx, hash) catch return false;
        const state = Dir.cwd().statFile(ctx.io, path, .{ .follow_symlinks = false }) catch return false;
        if (state.kind != .file or state.size != 0 or !std.mem.eql(u8, hash, full.digest(path) catch return false)) return false;
    }
    var total: u64 = 0;
    for (entry.outputs) |output| {
        if (output.mode != 0o644) return false;
        const path = blob(ctx, output.hash) catch return false;
        const state = Dir.cwd().statFile(ctx.io, path, .{ .follow_symlinks = false }) catch return false;
        if (state.kind != .file) return false;
        total +|= state.size;
        if (total > max_bytes or !std.mem.eql(u8, output.hash, full.digest(path) catch return false)) return false;
    }
    if (destination) |out| {
        // All blobs/names are verified before creating anything. An absent,
        // caller-owned staging destination is required; never merge live trees.
        try Dir.cwd().createDir(ctx.io, out, .fromMode(0o700));
        errdefer Dir.cwd().deleteTree(ctx.io, out) catch {};
        for (meta.value.directories) |name| try Dir.cwd().createDirPath(ctx.io, try std.fs.path.join(ctx.a, &.{ out, name }));
        for (entry.outputs) |output| try cache.materializeKnown(&full, try blob(ctx, output.hash), try std.fs.path.join(ctx.a, &.{ out, output.path }), 0o644, output.hash);
    }
    cache.touchEntry(ctx, id);
    try ctx.out(try std.json.Stringify.valueAlloc(ctx.a, .{ .hit = true, .bytes = total, .files = entry.outputs.len, .directories = meta.value.directories.len, .metadata = meta.value.metadata }, .{}));
    try ctx.out("\n");
    return true;
}

pub fn execute(ctx: *cache.Context, args: []const [:0]const u8) !u8 {
    const put = args.len > 0 and std.mem.eql(u8, args[0], "put-files");
    const get = args.len > 0 and std.mem.eql(u8, args[0], "get-files");
    const head = args.len > 0 and std.mem.eql(u8, args[0], "head-files");
    if ((!put and !get and !head) or (put and (args.len < 4 or args.len > 5)) or
        (get and args.len != 4) or (head and args.len != 3)) return error.InvalidArtifactArguments;
    try ctx.prepare();
    const maintenance = try cache.Lock.acquire(ctx, "maintenance", false);
    defer maintenance.release();
    const lock = try cache.Lock.acquire(ctx, try identity(ctx, args[1], args[2]), put);
    defer lock.release();
    if (put) {
        try store(ctx, args[1], args[2], args[3], if (args.len == 5) args[4] else "{}");
        return 0;
    }
    if (try fetch(ctx, args[1], args[2], if (get) args[3] else null)) return 0;
    try ctx.out("{\"hit\":false}\n");
    return 3;
}
