//! Explicit, ordered whole-task contracts. Input discovery belongs to the caller.
const std = @import("std");
const builtin = @import("builtin");
const cache = @import("cache.zig");
const identity = @import("identity.zig");
const Dir = std.Io.Dir;
const Task = struct { name: []const u8, cwd: []const u8 = ".", command: []const []const u8, inputs: []const []const u8, outputs: []const []const u8, depends_on: []const []const u8 = &.{}, tool_resources: []const []const u8 = &.{} };
const Spec = struct { schema: u32 = 1, tasks: []const Task };
fn less(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.order(u8, a, b) == .lt;
}
fn records(ctx: *cache.Context, spec_path: []const u8, task: Task) ![]const cache.Dependency {
    var result: std.ArrayList(cache.Dependency) = .empty;
    try result.append(ctx.a, .{ .path = spec_path, .hash = (try ctx.checkedDigest(spec_path)).hash });
    for (task.inputs) |input| {
        const path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, input });
        try result.append(ctx.a, .{ .path = path, .hash = (try ctx.checkedDigest(path)).hash });
    }
    return result.items;
}
fn taskKey(ctx: *cache.Context, task: Task, argv: []const []const u8, deps: []const cache.Dependency) ![]const u8 {
    var h = cache.Hash.init(.{});
    cache.field(&h, "nanocompile-declared-task-v1");
    cache.field(&h, task.name);
    cache.field(&h, ctx.cwd);
    cache.field(&h, @tagName(builtin.os.tag));
    const host = try std.zig.system.resolveTargetQuery(ctx.io, .{});
    cache.field(&h, @tagName(host.cpu.arch));
    cache.field(&h, host.cpu.model.name);
    cache.field(&h, std.mem.asBytes(&host.cpu.features.ints));
    cache.field(&h, try std.fmt.allocPrint(ctx.a, "{any}", .{host.os}));
    // Commands name trusted installed tools. All other runtime resources/files
    // and child tools belong in the explicit input contract.
    cache.field(&h, try identity.installedFileDigest(ctx, argv[0]));
    for (task.tool_resources) |resource| {
        const path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, resource });
        cache.field(&h, try identity.nativeFiles(ctx, &.{path}));
    }

    for (argv) |arg| cache.field(&h, arg);
    const keys = try ctx.a.dupe([]const u8, ctx.env.keys());
    std.mem.sort([]const u8, keys, {}, less);
    for (keys) |name| {
        cache.field(&h, name);
        cache.field(&h, ctx.env.get(name).?);
    }
    for (deps) |dep| {
        cache.field(&h, dep.path);
        cache.field(&h, dep.hash);
    }
    for (task.outputs) |out| cache.field(&h, out);
    return cache.finish(ctx.a, &h);
}
fn executeOne(ctx: *cache.Context, spec_path: []const u8, task: Task) !u8 {
    if (task.command.len == 0 or task.outputs.len == 0 or task.inputs.len == 0) return error.InvalidTask;
    var argv = try ctx.a.dupe([]const u8, task.command);
    argv[0] = try identity.selectedExecutable(ctx, argv[0]);
    var outputs: std.ArrayList([]const u8) = .empty;
    for (task.outputs) |out| {
        const path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, out });
        for (outputs.items) |existing| if (std.mem.eql(u8, path, existing)) return error.DuplicateOutput;
        try outputs.append(ctx.a, path);
    }
    const before = try records(ctx, spec_path, task);
    for (before) |input| for (outputs.items) |out| if (std.mem.eql(u8, input.path, out)) return error.OverlappingOutput;
    const key = try taskKey(ctx, task, argv, before);
    const flight = try cache.Lock.acquire(ctx, key, true);
    defer flight.release();
    const sorted = try ctx.a.dupe([]const u8, outputs.items);
    std.mem.sort([]const u8, sorted, {}, less);
    var locks: std.ArrayList(cache.Lock) = .empty;
    defer for (locks.items) |held| held.release();
    for (sorted) |out| {
        var h = cache.Hash.init(.{});
        cache.field(&h, out);
        try locks.append(ctx.a, try cache.Lock.acquire(ctx, try std.fmt.allocPrint(ctx.a, "output-{s}", .{try cache.finish(ctx.a, &h)}), true));
    }
    const disabled = std.mem.eql(u8, ctx.env.get("NANOCOMPILE_DISABLE") orelse "", "1");
    if (!disabled and (cache.restore(ctx, key, outputs.items) catch false)) {
        ctx.event("task_hit");
        return 0;
    }
    const result = try std.process.run(ctx.a, ctx.io, .{ .argv = argv, .cwd = .{ .path = ctx.cwd }, .environ_map = ctx.env });
    try ctx.out(result.stdout);
    try std.Io.File.stderr().writeStreamingAll(ctx.io, result.stderr);
    const status: u8 = switch (result.term) {
        .exited => |v| v,
        .signal => |v| @intCast(@min(255, 128 + @as(u32, @backingInt(v)))),
        else => 1,
    };
    if (status != 0) {
        ctx.event("task_failed");
        return status;
    }
    if (disabled) {
        ctx.event("task_bypass");
        return 0;
    }
    ctx.event("task_miss");
    const after = records(ctx, spec_path, task) catch return 0;
    if (!std.mem.eql(u8, key, try taskKey(ctx, task, argv, after))) return 0;
    try cache.store(ctx, key, after, outputs.items, result.stdout, result.stderr);
    return 0;
}
pub fn execute(ctx: *cache.Context, filename: []const u8) !u8 {
    const spec_path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, filename });
    const spec_bytes = try ctx.read(spec_path);
    const parsed = try std.json.parseFromSlice(Spec, ctx.a, spec_bytes, .{ .allocate = .alloc_always });
    const spec = parsed.value;
    if (spec.schema != 1 or spec.tasks.len == 0 or spec.tasks.len > 1024) return error.InvalidTaskSpec;
    // Validate the complete graph before executing anything. Only dependencies
    // earlier in this explicit order are accepted; cycles/forward refs refuse.
    var names: std.StringHashMapUnmanaged(void) = .empty;
    for (spec.tasks) |task| {
        if (task.name.len == 0 or names.contains(task.name) or task.command.len == 0 or task.inputs.len == 0 or task.outputs.len == 0) return error.InvalidTaskGraph;
        for (task.depends_on) |dep| if (!names.contains(dep)) return error.InvalidTaskGraph;
        try names.put(ctx.a, task.name, {});
    }
    try ctx.prepare();
    const maintenance = try cache.Lock.acquire(ctx, "maintenance", false);
    defer maintenance.release();
    for (spec.tasks) |task| {
        // Re-read the contract: changes during an earlier task do not silently
        // execute or cache an already-parsed stale graph.
        if (!std.mem.eql(u8, spec_bytes, try ctx.read(spec_path))) return error.TaskSpecChanged;
        var local = ctx.*;
        local.cwd = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, task.cwd });
        const status = try executeOne(&local, spec_path, task);
        if (status != 0) return status;
    }
    return 0;
}
