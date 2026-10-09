//! Convert a bound live linker capture into persistent cache dependencies.
//! Source snapshots, search membership, macro-input policy and tool selection
//! remain caller requirements; this is not a complete producer cache plan.
const std = @import("std");
const cache = @import("cache.zig");
const observer = @import("link_observer.zig");
const reports = @import("link_dependencies.zig");
const Dir = std.Io.Dir;

fn equal(a: Dir.Stat, b: Dir.Stat) bool {
    return a.inode == b.inode and a.size == b.size and a.kind == b.kind and
        a.mtime.nanoseconds == b.mtime.nanoseconds and a.ctime.nanoseconds == b.ctime.nanoseconds;
}

fn predate(st: Dir.Stat, started: i96) !void {
    if (st.mtime.nanoseconds >= started or st.ctime.nanoseconds >= started) return error.LinkInputChanged;
}

fn append(ctx: *cache.Context, records: *std.ArrayList(cache.Dependency), dep: cache.Dependency) !void {
    for (records.items) |old| {
        if (!std.mem.eql(u8, old.path, dep.path) or (old.symlink_target != null) != (dep.symlink_target != null) or
            (old.missing != null) != (dep.missing != null)) continue;
        if (!std.mem.eql(u8, old.hash, dep.hash)) return error.LinkInputChanged;
        return;
    }
    try records.append(ctx.a, dep);
}

fn links(ctx: *cache.Context, path: []const u8, started: i96, records: *std.ArrayList(cache.Dependency)) !void {
    var component: ?[]const u8 = path;
    while (component) |current| : (component = std.fs.path.dirname(current)) {
        const before = try Dir.cwd().statFile(ctx.io, current, .{ .follow_symlinks = false });
        if (before.kind != .sym_link) continue;
        try predate(before, started);
        const dep = try cache.symlinkDependency(ctx, current);
        if (!equal(before, try Dir.cwd().statFile(ctx.io, current, .{ .follow_symlinks = false }))) return error.LinkInputChanged;
        try append(ctx, records, dep);
    }
}

pub fn collect(ctx: *cache.Context, config: observer.Config, sealed: []const u8, started: i96) ![]const cache.Dependency {
    const invocation = try observer.parseInvocation(ctx, config, sealed);
    const link = invocation.link orelse return error.MissingOwnedLinkCapture;
    var records: std.ArrayList(cache.Dependency) = .empty;
    for (link.inputs) |input| {
        if (input.owned) continue;
        const resolved = try Dir.cwd().realPathFileAlloc(ctx.io, input.lexical, ctx.a);
        if (!std.mem.eql(u8, resolved, input.path)) return error.LinkInputChanged;
        const before = try Dir.cwd().statFile(ctx.io, input.path, .{});
        if (before.kind != .file) return error.NotRegularFile;
        try predate(before, started);
        try links(ctx, input.lexical, started, &records);
        const hash = try ctx.digest(input.path);
        if (std.mem.endsWith(u8, input.path, ".a") or std.mem.endsWith(u8, input.path, ".rlib")) {
            const file = try Dir.cwd().openFile(ctx.io, input.path, .{});
            defer file.close(ctx.io);
            var magic: [8]u8 = undefined;
            var reader = file.reader(ctx.io, &.{});
            const n = try reader.interface.readSliceShort(&magic);
            if (std.mem.eql(u8, magic[0..n], "!<thin>\n")) return error.ThinNativeArchive;
        }
        if (!std.mem.eql(u8, input.lexical, input.path) and !std.mem.eql(u8, hash, try ctx.digest(input.lexical))) return error.LinkInputChanged;
        if (!equal(before, try Dir.cwd().statFile(ctx.io, input.path, .{}))) return error.LinkInputChanged;
        if (!std.mem.eql(u8, input.path, try Dir.cwd().realPathFileAlloc(ctx.io, input.lexical, ctx.a))) return error.LinkInputChanged;
        try links(ctx, input.lexical, started, &records);
        try append(ctx, &records, .{ .path = input.path, .hash = hash });
        try append(ctx, &records, .{ .path = input.lexical, .hash = hash });
    }
    const report = try reports.parseForOutput(ctx.a, link.report, config.format, link.ownership.output);
    for (report.missing) |path| try append(ctx, &records, try cache.missingDependency(ctx, path));
    return records.items;
}
