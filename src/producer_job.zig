//! Private output ownership for future proc-macro producer discovery.
//! Callers must hold the cache maintenance lock and permit only this compiler
//! job to write into `out`. Resolve inputs while rustc scratch files still live.
const std = @import("std");
const cache = @import("cache.zig");
const Dir = std.Io.Dir;

pub const Job = struct {
    root: []const u8,
    out: []const u8,
    canonical_out: []const u8,
    capture_id: []const u8,
    alias: ?[]const u8 = null,
    alias_target: ?[]const u8 = null,

    pub fn create(ctx: *cache.Context) !Job {
        const parent = try ctx.path(&.{"producer-jobs"});
        try Dir.cwd().createDirPath(ctx.io, parent);
        var random: [16]u8 = undefined;
        // Exclusive mkdir prevents adopting another job's existing outputs.
        for (0..8) |_| {
            try std.Io.randomSecure(ctx.io, &random);
            const id = try ctx.a.dupe(u8, &std.fmt.bytesToHex(random, .lower));
            const root = try std.fs.path.join(ctx.a, &.{ parent, id });
            Dir.cwd().createDir(ctx.io, root, .fromMode(0o700)) catch |err| switch (err) {
                error.PathAlreadyExists => continue,
                else => return err,
            };
            errdefer Dir.cwd().deleteTree(ctx.io, root) catch {};
            const out = try std.fs.path.join(ctx.a, &.{ root, "out" });
            try Dir.cwd().createDir(ctx.io, out, .fromMode(0o700));
            return .{ .root = root, .out = out, .capture_id = id, .canonical_out = try Dir.cwd().realPathFileAlloc(ctx.io, out, ctx.a) };
        }
        return error.JobCollision;
    }

    /// Caller holds key and output locks. Never adopt an existing alias: even
    /// stale links belong to another job. Only lexical spelling is stable;
    /// physical ownership remains a freshly created exclusive directory.
    pub fn acquireAlias(self: *Job, ctx: *cache.Context, key: []const u8) !void {
        if (self.alias != null or key.len != 64) return error.InvalidJobAlias;
        for (key) |c| if (!std.ascii.isHex(c)) return error.InvalidJobAlias;
        const parent = try ctx.path(&.{"producer-aliases"});
        try Dir.cwd().createDirPath(ctx.io, parent);
        const dir = try Dir.cwd().openDir(ctx.io, parent, .{});
        defer dir.close(ctx.io);
        try dir.setPermissions(ctx.io, .fromMode(0o700));
        const alias = try std.fs.path.join(ctx.a, &.{ parent, key });
        const target = try Dir.cwd().realPathFileAlloc(ctx.io, self.root, ctx.a);
        const out = try std.fs.path.join(ctx.a, &.{ alias, "out" });
        try Dir.cwd().symLink(ctx.io, target, alias, .{});
        self.alias = alias;
        self.alias_target = target;
        self.out = out;
    }

    pub fn validateAlias(self: Job, ctx: *cache.Context) !void {
        if (self.alias) |alias| {
            var buffer: [std.fs.max_path_bytes]u8 = undefined;
            const n = try Dir.cwd().readLink(ctx.io, alias, &buffer);
            if (!std.mem.eql(u8, buffer[0..n], self.alias_target.?)) return error.JobAliasChanged;
            const canonical = try Dir.cwd().realPathFileAlloc(ctx.io, self.out, ctx.a);
            if (!std.mem.eql(u8, canonical, self.canonical_out)) return error.JobAliasChanged;
        }
    }

    pub fn cleanup(self: Job, ctx: *cache.Context) !void {
        // Release lexical aliases even when physical diagnostics are retained.
        // A retargeted link is foreign; do not delete it or follow it.
        if (self.alias) |alias| {
            var buffer: [std.fs.max_path_bytes]u8 = undefined;
            const n = Dir.cwd().readLink(ctx.io, alias, &buffer) catch 0;
            if (std.mem.eql(u8, buffer[0..n], self.alias_target.?))
                try Dir.cwd().deleteFile(ctx.io, alias);
        }
        if (std.mem.eql(u8, ctx.env.get("NANOCOMPILE_RETAIN_PRODUCER_JOBS") orelse "", "1")) {
            ctx.trace("diagnostic: retaining private producer job");
            return;
        }
        try Dir.cwd().deleteTree(ctx.io, self.root);
    }

    /// Native linker argv[0] selects sibling observer.json. No generated shell
    /// script or environment-variable injection is needed by the compiler.
    pub fn installObserver(self: Job, ctx: *cache.Context, binary: []const u8, config: []const u8) ![]const u8 {
        if (!std.fs.path.isAbsolute(binary)) return error.InvalidLinkObserver;
        const executable = try Dir.cwd().statFile(ctx.io, binary, .{});
        if (executable.kind != .file or executable.permissions.toMode() & 0o111 == 0) return error.InvalidLinkObserver;
        const path = try std.fs.path.join(ctx.a, &.{ self.root, "nanocompile-internal-linker" });
        try ctx.atomic(try std.fs.path.join(ctx.a, &.{ self.root, "observer.json" }), config);
        try Dir.cwd().symLink(ctx.io, binary, path, .{});
        return path;
    }

    pub const Input = struct { lexical: []const u8, path: []const u8, owned: bool };

    pub fn ownsPaths(self: Job, lexical: []const u8, canonical: []const u8) bool {
        return within(self.out, lexical) and within(self.canonical_out, canonical);
    }

    pub fn classify(self: Job, ctx: *cache.Context, input: []const u8) !Input {
        const lexical = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, input });
        const canonical = try Dir.cwd().realPathFileAlloc(ctx.io, lexical, ctx.a);
        if ((try Dir.cwd().statFile(ctx.io, canonical, .{})).kind != .file)
            return error.NotRegularFile;
        // A symlink into or out of the private output directory never gains
        // ownership merely through one of its spellings. No suffix heuristic.
        return .{ .lexical = lexical, .path = canonical, .owned = self.ownsPaths(lexical, canonical) };
    }
};

fn within(root: []const u8, path: []const u8) bool {
    return path.len > root.len and std.mem.startsWith(u8, path, root) and path[root.len] == '/';
}

test "private jobs own only regular inputs beneath both output spellings" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    const cwd = try Dir.cwd().realPathFileAlloc(io, try std.fs.path.join(a, &.{ ".zig-cache", "tmp", &tmp.sub_path }), a);
    var env = std.process.Environ.Map.init(a);
    var ctx: cache.Context = .{ .a = a, .io = io, .env = &env, .root = try std.fs.path.join(a, &.{ cwd, "cache" }), .cwd = cwd };
    const first = try Job.create(&ctx);
    defer first.cleanup(&ctx) catch {};
    const second = try Job.create(&ctx);
    defer second.cleanup(&ctx) catch {};
    try std.testing.expect(!std.mem.eql(u8, first.capture_id, second.capture_id));
    var dir = try Dir.cwd().openDir(io, first.out, .{ .iterate = true });
    defer dir.close(io);
    var iterator = dir.iterate();
    try std.testing.expectEqual(null, try iterator.next(io));
    const generated = try std.fs.path.join(a, &.{ first.out, "scratch with spaces, no suffix" });
    try Dir.cwd().writeFile(io, .{ .sub_path = generated, .data = "generated" });
    try std.testing.expect((try first.classify(&ctx, generated)).owned);
    try tmp.dir.writeFile(io, .{ .sub_path = "foreign.o", .data = "persistent" });
    const foreign = try std.fs.path.join(a, &.{ cwd, "foreign.o" });
    try std.testing.expect(!(try first.classify(&ctx, foreign)).owned);
    try std.testing.expectError(error.InvalidLinkObserver, first.installObserver(&ctx, "relative-binary", "{}"));
    try std.testing.expectError(error.InvalidLinkObserver, first.installObserver(&ctx, foreign, "{}"));
    const executable = try Dir.cwd().openFile(io, foreign, .{});
    defer executable.close(io);
    try executable.setPermissions(io, .fromMode(0o700));
    const observer = try first.installObserver(&ctx, foreign, "observer fixture");
    try std.testing.expectEqualStrings(foreign, try Dir.cwd().realPathFileAlloc(io, observer, a));
    try std.testing.expectEqualStrings("observer fixture", try ctx.read(try std.fs.path.join(a, &.{ first.root, "observer.json" })));
    const linked = try std.fs.path.join(a, &.{ first.out, "linked.o" });
    try Dir.cwd().symLink(io, foreign, linked, .{});
    try std.testing.expect(!(try first.classify(&ctx, linked)).owned);
    const outside_alias = try std.fs.path.join(a, &.{ cwd, "outside-alias" });
    try Dir.cwd().symLink(io, generated, outside_alias, .{});
    try std.testing.expect(!(try first.classify(&ctx, outside_alias)).owned);
    try std.testing.expect(!within(first.out, try std.fmt.allocPrint(a, "{s}-sibling/file.o", .{first.out})));
    try std.testing.expectError(error.NotRegularFile, first.classify(&ctx, first.out));
    try std.testing.expectError(error.FileNotFound, first.classify(&ctx, "missing.o"));
}

test "stable aliases never adopt foreign jobs and retained cleanup releases spelling" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    const cwd = try Dir.cwd().realPathFileAlloc(io, try std.fs.path.join(a, &.{ ".zig-cache", "tmp", &tmp.sub_path }), a);
    var env = std.process.Environ.Map.init(a);
    var ctx: cache.Context = .{ .a = a, .io = io, .env = &env, .root = try std.fs.path.join(a, &.{ cwd, "cache" }), .cwd = cwd };
    var first = try Job.create(&ctx);
    var second = try Job.create(&ctx);
    defer second.cleanup(&ctx) catch {};
    const key = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    try first.acquireAlias(&ctx, key);
    const spelling = first.out;
    try first.validateAlias(&ctx);
    try std.testing.expectError(error.PathAlreadyExists, second.acquireAlias(&ctx, key));
    try second.acquireAlias(&ctx, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb");
    const generated = try std.fs.path.join(a, &.{ first.out, "generated.o" });
    try Dir.cwd().writeFile(io, .{ .sub_path = generated, .data = "owned" });
    try std.testing.expect((try first.classify(&ctx, generated)).owned);
    try std.testing.expect(!(try second.classify(&ctx, generated)).owned);
    try env.put("NANOCOMPILE_RETAIN_PRODUCER_JOBS", "1");
    try first.cleanup(&ctx);
    try std.testing.expectError(error.FileNotFound, Dir.cwd().statFile(io, first.alias.?, .{ .follow_symlinks = false }));
    _ = try Dir.cwd().statFile(io, first.root, .{});
    var next = try Job.create(&ctx);
    try next.acquireAlias(&ctx, key);
    try std.testing.expectEqualStrings(spelling, next.out);
    try std.testing.expect(!std.mem.eql(u8, first.canonical_out, next.canonical_out));
    try Dir.cwd().deleteFile(io, next.alias.?);
    try Dir.cwd().symLink(io, second.alias_target.?, next.alias.?, .{});
    try std.testing.expectError(error.JobAliasChanged, next.validateAlias(&ctx));
    try Dir.cwd().writeFile(io, .{ .sub_path = try std.fs.path.join(a, &.{ second.out, "generated.o" }), .data = "foreign" });
    try std.testing.expect(!(try next.classify(&ctx, generated)).owned);
    try env.put("NANOCOMPILE_RETAIN_PRODUCER_JOBS", "0");
    try next.cleanup(&ctx);
    var buffer: [std.fs.max_path_bytes]u8 = undefined;
    const n = try Dir.cwd().readLink(io, next.alias.?, &buffer);
    try std.testing.expectEqualStrings(second.alias_target.?, buffer[0..n]);
    try first.cleanup(&ctx);
}
