//! Metadata classification is content-addressed and compiler-scoped. It never
//! replaces content validation of Rust inputs. Toolchain files use the already
//! validated complete toolchain fingerprint, like the existing identity memo.
const std = @import("std");
const cache = @import("cache.zig");
const Dir = std.Io.Dir;

pub const Root = struct {
    name: []const u8,
    hash: []const u8,
    triple: []const u8,
    proc_macro: bool,

    pub fn matches(self: Root, name: []const u8, hash: []const u8, triple: []const u8, proc_macro: bool) bool {
        // Host proc-macro resolution differs under cross compilation. Only
        // narrow when the exact target and macro kind agree with the graph.
        return self.proc_macro == proc_macro and std.mem.eql(u8, self.name, name) and
            std.mem.eql(u8, self.hash, hash) and std.mem.eql(u8, self.triple, triple);
    }
};

pub fn validCrateHash(hash: []const u8) bool {
    if (hash.len != 32) return false;
    for (hash) |ch| if (!std.ascii.isHex(ch)) return false;
    return true;
}

pub fn parse(bytes: []const u8) !Root {
    if (!std.mem.startsWith(u8, bytes, "Crate info:\n")) return error.UnsupportedRustMetadata;
    var name: ?[]const u8 = null;
    var hash: ?[]const u8 = null;
    var triple: ?[]const u8 = null;
    var proc_macro: ?bool = null;
    var lines = std.mem.splitScalar(u8, bytes, '\n');
    while (lines.next()) |line| {
        if (std.mem.startsWith(u8, line, "=")) break;
        if (std.mem.startsWith(u8, line, "name ")) {
            if (name != null) return error.UnsupportedRustMetadata;
            name = line[5..];
        } else if (std.mem.startsWith(u8, line, "hash ")) {
            if (hash != null) return error.UnsupportedRustMetadata;
            var words = std.mem.tokenizeScalar(u8, line[5..], ' ');
            hash = words.next();
        } else if (std.mem.startsWith(u8, line, "triple ")) {
            if (triple != null) return error.UnsupportedRustMetadata;
            triple = line[7..];
        } else if (std.mem.startsWith(u8, line, "proc_macro ")) {
            if (proc_macro != null) return error.UnsupportedRustMetadata;
            proc_macro = if (std.mem.eql(u8, line[11..], "false")) false else if (std.mem.eql(u8, line[11..], "true")) true else return error.UnsupportedRustMetadata;
        }
    }
    const root: Root = .{ .name = name orelse return error.UnsupportedRustMetadata, .hash = hash orelse return error.UnsupportedRustMetadata, .triple = triple orelse return error.UnsupportedRustMetadata, .proc_macro = proc_macro orelse return error.UnsupportedRustMetadata };
    if (root.name.len == 0 or root.triple.len == 0 or !validCrateHash(root.hash)) return error.UnsupportedRustMetadata;
    for (root.name) |ch| if (!std.ascii.isAlphanumeric(ch) and ch != '_' and ch != '-') return error.UnsupportedRustMetadata;
    return root;
}

const Memo = struct { schema: u32 = 1, compiler: []const u8, identity: []const u8, root: Root };
pub const Resolver = struct {
    ctx: *cache.Context,
    compiler: []const u8,
    query_env: *std.process.Environ.Map,
    query_cwd: []const u8,
    roots: std.StringHashMapUnmanaged(?Root) = .empty,
    hashes: std.StringHashMapUnmanaged([]const u8) = .empty,

    pub fn digest(self: *Resolver, path: []const u8) ![]const u8 {
        if (self.hashes.get(path)) |hash| return hash;
        const hash = try self.ctx.digest(path);
        try self.hashes.put(self.ctx.a, path, hash);
        return hash;
    }

    fn location(self: *Resolver, identity: []const u8) ![]const u8 {
        var hash = cache.Hash.init(.{});
        cache.field(&hash, "rust-root-classification-v1");
        cache.field(&hash, self.ctx.compiler_identity orelse return error.NoCompilerIdentity);
        cache.field(&hash, identity);
        return self.ctx.path(&.{ "metadata", try cache.finish(self.ctx.a, &hash) });
    }

    fn write(self: *Resolver, identity: []const u8, root: Root) !void {
        const memo: Memo = .{ .compiler = self.ctx.compiler_identity orelse return error.NoCompilerIdentity, .identity = identity, .root = root };
        const bytes = try std.json.Stringify.valueAlloc(self.ctx.a, memo, .{});
        try self.ctx.atomic(try self.location(identity), try cache.seal(self.ctx, bytes));
    }

    pub fn remember(self: *Resolver, path: []const u8, root: Root) !void {
        const identity = try std.fmt.allocPrint(self.ctx.a, "content:{s}", .{try self.digest(path)});
        self.write(identity, root) catch {};
        try self.roots.put(self.ctx.a, path, root);
    }

    pub fn inspect(self: *Resolver, path: []const u8, toolchain_file: bool) !?Root {
        if (self.roots.get(path)) |root| return root;
        const identity = if (toolchain_file)
            try std.fmt.allocPrint(self.ctx.a, "toolchain:{s}", .{path})
        else
            try std.fmt.allocPrint(self.ctx.a, "content:{s}", .{try self.digest(path)});
        const location_ = try self.location(identity);
        if (self.ctx.read(location_)) |bytes| read: {
            const payload = cache.unseal(self.ctx, bytes) catch break :read;
            const parsed = std.json.parseFromSlice(Memo, self.ctx.a, payload, .{ .allocate = .alloc_always }) catch break :read;
            const memo = parsed.value;
            if (memo.schema != 1 or !std.mem.eql(u8, memo.compiler, self.ctx.compiler_identity.?) or !std.mem.eql(u8, memo.identity, identity) or !validCrateHash(memo.root.hash)) break :read;
            try self.roots.put(self.ctx.a, path, memo.root);
            return memo.root;
        } else |_| {}
        const before = try Dir.cwd().statFile(self.ctx.io, path, .{});
        const result = try std.process.run(self.ctx.a, self.ctx.io, .{ .argv = &.{ self.compiler, "-Zls=root", path }, .environ_map = self.query_env, .cwd = .{ .path = self.query_cwd } });
        const root = switch (result.term) {
            .exited => |code| if (code == 0) parse(result.stdout) catch null else null,
            else => null,
        };
        const after = try Dir.cwd().statFile(self.ctx.io, path, .{});
        if (before.inode != after.inode or before.size != after.size or before.mtime.nanoseconds != after.mtime.nanoseconds or before.ctime.nanoseconds != after.ctime.nanoseconds) return error.InputChangedDuringMetadataQuery;
        if (root) |value| self.write(identity, value) catch {};
        try self.roots.put(self.ctx.a, path, root);
        return root;
    }
};

test "root classifications require name hash target and ordinary crate" {
    const header = "Crate info:\nname dep-first\nhash 0123456789abcdef0123456789abcdef stable_crate_id other\nproc_macro false\ntriple aarch64-apple-darwin\n=External Dependencies=\n";
    const root = try parse(header);
    try std.testing.expect(root.matches("dep-first", "0123456789abcdef0123456789abcdef", "aarch64-apple-darwin", false));
    try std.testing.expect(!root.matches("dep-other", root.hash, root.triple, false));
    try std.testing.expect(!root.matches(root.name, "11111111111111111111111111111111", root.triple, false));
    try std.testing.expect(!root.matches(root.name, root.hash, "x86_64-unknown-linux-gnu", false));
    var macro = root;
    macro.proc_macro = true;
    try std.testing.expect(!macro.matches(root.name, root.hash, root.triple, false));
    try std.testing.expect(macro.matches(root.name, root.hash, root.triple, true));
    try std.testing.expectError(error.UnsupportedRustMetadata, parse("Crate info:\nname dep\n"));
}

pub fn readerCompiler(ctx: *cache.Context, arg: []const u8) ![]const u8 {
    // Keep the executable basename: canonicalizing a rustup rustc symlink to
    // rustup itself would change proxy dispatch. Relative PATH entries must
    // remain relative to the caller even when diagnostics use a private cwd.
    if (std.mem.indexOfScalar(u8, arg, '/') != null) return std.fs.path.resolve(ctx.a, &.{ ctx.cwd, arg });
    var paths = std.mem.splitScalar(u8, ctx.env.get("PATH") orelse "", ':');
    while (paths.next()) |dir| {
        const path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, dir, arg });
        const st = Dir.cwd().statFile(ctx.io, path, .{}) catch continue;
        if (st.kind == .file and st.permissions.toMode() & 0o111 != 0) return path;
    }
    return error.CompilerNotFound;
}
