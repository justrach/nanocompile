//! Shared-store setup for one main checkout plus N agent worktrees.
//! `nanocompile worktree init` writes the general (train-frozen) config, not
//! per-repo knobs. Each worktree keeps its own `target/`; one NANOCOMPILE_DIR
//! restores anything main or a sibling already compiled.
const std = @import("std");
const builtin = @import("builtin");
const cache = @import("cache.zig");
const Dir = std.Io.Dir;

fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

const begin_mark = "# BEGIN nanocompile worktree";
const end_mark = "# END nanocompile worktree";

pub const GeneralFlag = struct { name: []const u8, value: []const u8 };
/// Frozen general defaults from the axum+ripgrep agent-worktree hill-climb.
/// Prefer these over per-repo tuning. See docs/agent-worktrees.md.
pub const general_flags = [_]GeneralFlag{
    .{ .name = "NANOCOMPILE_ALLOW_INCREMENTAL", .value = "1" },
    .{ .name = "CARGO_INCREMENTAL", .value = "0" },
    .{ .name = "NANOCOMPILE_HARDLINK_TARGET", .value = "1" },
    .{ .name = "NANOCOMPILE_NO_VARIANTS", .value = "1" },
    .{ .name = "NANOCOMPILE_PROC_MACROS", .value = "reported" },
    .{ .name = "NANOCOMPILE_PROC_MACRO_PRODUCERS", .value = "1" },
    .{ .name = "NANOCOMPILE_EXECUTABLE_PRODUCERS", .value = "1" },
    .{ .name = "NANOCOMPILE_REMAP_PATHS", .value = "1" },
};

pub fn renderConfig(allocator: std.mem.Allocator, wrapper: []const u8, store: []const u8) ![]const u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    try out.appendSlice(allocator, begin_mark);
    try out.appendSlice(allocator, "\n# Shared compiler store for agent worktrees. Do not per-repo tune.\n[build]\nrustc-wrapper = ");
    try appendTomlString(&out, allocator, wrapper);
    try out.appendSlice(allocator, "\n\n[env]\nNANOCOMPILE_DIR = { value = ");
    try appendTomlString(&out, allocator, store);
    try out.appendSlice(allocator, ", force = true }\n");
    for (general_flags) |flag| {
        try out.appendSlice(allocator, flag.name);
        try out.appendSlice(allocator, " = { value = ");
        try appendTomlString(&out, allocator, flag.value);
        try out.appendSlice(allocator, ", force = true }\n");
    }
    try out.appendSlice(allocator, end_mark);
    try out.appendSlice(allocator, "\n");
    return out.toOwnedSlice(allocator);
}

fn appendTomlString(out: *std.ArrayList(u8), allocator: std.mem.Allocator, value: []const u8) !void {
    try out.append(allocator, '"');
    for (value) |ch| {
        if (ch == '"' or ch == '\\') try out.append(allocator, '\\');
        try out.append(allocator, ch);
    }
    try out.append(allocator, '"');
}

fn mergeConfig(allocator: std.mem.Allocator, existing: []const u8, block: []const u8) ![]const u8 {
    if (std.mem.indexOf(u8, existing, begin_mark)) |start| {
        const after = if (std.mem.indexOf(u8, existing[start..], end_mark)) |rel|
            start + rel + end_mark.len
        else
            existing.len;
        const skip_nl: usize = if (after < existing.len and existing[after] == '\n') 1 else 0;
        return std.fmt.allocPrint(allocator, "{s}{s}{s}", .{ existing[0..start], block, existing[after + skip_nl ..] });
    }
    if (existing.len == 0) return allocator.dupe(u8, block);
    const sep = if (existing[existing.len - 1] == '\n') "" else "\n";
    return std.fmt.allocPrint(allocator, "{s}{s}{s}", .{ existing, sep, block });
}

fn generalStore(ctx: *cache.Context) ![]const u8 {
    // Ignore a leftover NANOCOMPILE_DIR from a bench; ship the user-default store.
    if (ctx.env.get("NANOCOMPILE_WORKTREE_STORE")) |explicit|
        return std.fs.path.resolve(ctx.a, &.{ ctx.cwd, explicit });
    const base = if (builtin.os.tag == .windows)
        ctx.env.get("LOCALAPPDATA") orelse try std.fs.path.join(ctx.a, &.{ ctx.env.get("USERPROFILE") orelse ctx.env.get("HOME") orelse return error.NoHome, ".cache" })
    else
        ctx.env.get("XDG_CACHE_HOME") orelse try std.fs.path.join(ctx.a, &.{ ctx.env.get("HOME") orelse return error.NoHome, ".cache" });
    return std.fs.path.join(ctx.a, &.{ base, "nanocompile" });
}

pub fn execute(ctx: *cache.Context, args: []const [:0]const u8, self_exe: []const u8) !u8 {
    if (args.len == 0 or eq(args[0], "help") or eq(args[0], "--help")) {
        try ctx.out(
            \\nanocompile worktree init [DIR]
            \\  Write .cargo/config.toml so every git worktree shares one nanocompile store.
            \\  Uses the general hill-climbed defaults (not per-repo knobs). Each worktree
            \\  keeps its own target/; only invalidated crates compile.
            \\nanocompile worktree dedup DIR...
            \\  Hardlink identical files across target directories (one inode per blob).
            \\nanocompile worktree seed SRC DST
            \\  Hardlink SRC/ into DST/ (immutable) so a new worktree reuses the
            \\  warm target instead of allocating a second copy of fingerprints.
            \\nanocompile worktree gc DIR...
            \\  Drop store blobs that no live target still materializes (working set).
            \\TypeScript: wrap checkers with the same store
            \\  nanocompile tsrs --noEmit --checkers 4
            \\  nanocompile tsc --noEmit
            \\  nanocompile tsgo --noEmit
            \\  nanocompile bun check
            \\
        );
        return 0;
    }
    if (eq(args[0], "seed")) {
        if (args.len < 3) return error.MissingValue;
        const src = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, args[1] });
        const dst = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, args[2] });
        const n = try cache.seedTree(ctx, src, dst);
        try ctx.out(try std.fmt.allocPrint(ctx.a, "seeded {d} files\n", .{n}));
        return 0;
    }
    if (eq(args[0], "dedup")) {
        if (args.len < 2) return error.MissingValue;
        var roots: std.ArrayList([]const u8) = .empty;
        for (args[1..]) |arg| try roots.append(ctx.a, try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, arg }));
        const n = try cache.dedupTrees(ctx, roots.items);
        try ctx.out(try std.fmt.allocPrint(ctx.a, "deduped {d} files\n", .{n}));
        return 0;
    }
    if (eq(args[0], "gc")) {
        if (args.len < 2) return error.MissingValue;
        var roots: std.ArrayList([]const u8) = .empty;
        for (args[1..]) |arg| try roots.append(ctx.a, try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, arg }));
        const n = try cache.gcWorkingSet(ctx, roots.items);
        try ctx.out(try std.fmt.allocPrint(ctx.a, "gc dropped {d}\n", .{n}));
        return 0;
    }
    if (!eq(args[0], "init")) return error.UnknownWorktreeCommand;
    const dest = if (args.len > 1 and !eq(args[1], "--store")) args[1] else ctx.cwd;
    var store_arg: ?[]const u8 = null;
    var i: usize = 1;
    while (i < args.len) : (i += 1) {
        if (eq(args[i], "--store") and i + 1 < args.len) {
            i += 1;
            store_arg = args[i];
        }
    }
    const root = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, dest });
    const cargo_dir = try std.fs.path.join(ctx.a, &.{ root, ".cargo" });
    const config_path = try std.fs.path.join(ctx.a, &.{ cargo_dir, "config.toml" });
    Dir.cwd().createDirPath(ctx.io, cargo_dir) catch {};
    const wrapper = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, self_exe });
    const store = store_arg orelse try generalStore(ctx);
    const block = try renderConfig(ctx.a, wrapper, store);
    const existing = ctx.read(config_path) catch "";
    const merged = try mergeConfig(ctx.a, existing, block);
    try ctx.atomic(config_path, merged);
    try ctx.out(try std.fmt.allocPrint(ctx.a, "wrote {s}\nstore {s}\nwrapper {s}\n", .{ config_path, store, wrapper }));
    return 0;
}

test "worktree init renders the general shared-store block" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const block = try renderConfig(a, "/opt/nanocompile", "/home/user/.cache/nanocompile");
    try std.testing.expect(std.mem.indexOf(u8, block, "NANOCOMPILE_BUILD_SCRIPT_CACHE") == null);
    try std.testing.expect(std.mem.indexOf(u8, block, "NANOCOMPILE_EXECUTABLE_PRODUCERS") != null);
    try std.testing.expect(std.mem.indexOf(u8, block, "NANOCOMPILE_HARDLINK_TARGET") != null);
    try std.testing.expect(std.mem.indexOf(u8, block, "NANOCOMPILE_NO_VARIANTS") != null);
    try std.testing.expect(std.mem.indexOf(u8, block, "NANOCOMPILE_REMAP_PATHS") != null);
    try std.testing.expect(std.mem.indexOf(u8, block, "CARGO_INCREMENTAL") != null);
    try std.testing.expect(std.mem.indexOf(u8, block, "force = true") != null);
    const merged = try mergeConfig(a, "[build]\njobs = 8\n", block);
    try std.testing.expect(std.mem.indexOf(u8, merged, "jobs = 8") != null);
    const again = try mergeConfig(a, merged, try renderConfig(a, "/opt/other", "/cache"));
    try std.testing.expectEqual(std.mem.count(u8, again, begin_mark), 1);
    try std.testing.expect(std.mem.indexOf(u8, again, "/opt/other") != null);
}
