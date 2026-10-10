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

    pub fn cleanup(self: Job, ctx: *cache.Context) !void {
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
