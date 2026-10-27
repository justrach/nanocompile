//! Explicit, ordered whole-task contracts. Input discovery belongs to the caller.
const std = @import("std");
const builtin = @import("builtin");
const cache = @import("cache.zig");
const identity = @import("identity.zig");
const Dir = std.Io.Dir;
const report_variable = "NANOCOMPILE_TASK_REPORT";
const HostIdentity = enum { native, platform };
const Relocatable = struct {
    // Required assertions, not inferred properties or a filesystem sandbox.
    path_independent: bool,
    resources_complete: bool,
    environment: []const []const u8,
};
const Task = struct { name: []const u8, cwd: []const u8 = ".", command: []const []const u8, inputs: []const []const u8, outputs: []const []const u8, depends_on: []const []const u8 = &.{}, tool_resources: []const []const u8 = &.{}, host_identity: HostIdentity = .native, relocatable: ?Relocatable = null };
const Spec = struct { schema: u32 = 1, tasks: []const Task };
const Timings = struct {
    input_hash_ns: i96 = 0,
    tool_identity_ns: i96 = 0,
    lock_wait_ns: i96 = 0,
    lookup_restore_ns: i96 = 0,
    lookup_ns: i96 = 0,
    restore_ns: i96 = 0,
    diagnostic_replay_ns: i96 = 0,
    total_ns: i96 = 0,
    child_ns: i96 = 0,
    revalidation_ns: i96 = 0,
    storage_ns: i96 = 0,
};
const TaskReport = struct {
    task_index: usize,
    outcome: []const u8 = "error",
    lookup: []const u8 = "not_attempted",
    storage: []const u8 = "not_attempted",
    exit_code: ?u8 = null,
    timings: Timings = .{},
    input_bytes_hashed: u64 = 0,
    revalidation_input_bytes_hashed: u64 = 0,
    restored_output_bytes: ?u64 = null,
    stored_output_bytes: ?u64 = null,
    output_bytes: ?u64 = null,
    child_stdout_bytes: u64 = 0,
    child_stderr_bytes: u64 = 0,
};
fn now(ctx: *cache.Context, enabled: bool) i96 {
    return if (enabled) std.Io.Clock.awake.now(ctx.io).nanoseconds else 0;
}
fn less(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.order(u8, a, b) == .lt;
}
fn isReportVariable(name: []const u8) bool {
    return if (builtin.os.tag == .windows) std.ascii.eqlIgnoreCase(name, report_variable) else std.mem.eql(u8, name, report_variable);
}
// Parallelize only independent full reads, never before/after validation or
// dependency order. Each worker owns its allocator and disables digest memos.
const InputJob = struct { path: []const u8, hash: [64]u8 = undefined, size: u64 = 0, failure: ?anyerror = null };
fn inputWorker(ctx: *const cache.Context, jobs: []InputJob, next: *std.atomic.Value(usize)) void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    var local = ctx.*;
    local.a = arena.allocator();
    local.digest_memo = false;
    local.entry_digests = null;
    while (true) {
        const index = next.fetchAdd(1, .monotonic);
        if (index >= jobs.len) return;
        _ = arena.reset(.retain_capacity);
        const digest = local.checkedDigest(jobs[index].path) catch |err| {
            jobs[index].failure = err;
            continue;
        };
        @memcpy(&jobs[index].hash, digest.hash);
        jobs[index].size = digest.state.size;
    }
}
fn records(ctx: *cache.Context, task: Task, bytes: *u64) ![]const cache.Dependency {
    // Tiny contracts retain the serial path. Larger sets use at most four
    // file workers; all hashes/errors join before key construction or execution.
    if (task.inputs.len >= 8) {
        const jobs = try ctx.a.alloc(InputJob, task.inputs.len);
        for (jobs, task.inputs) |*job, input| job.* = .{ .path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, input }) };
        var next: std.atomic.Value(usize) = .init(0);
        var group: std.Io.Group = .init;
        defer group.cancel(ctx.io);
        const workers = @min(@as(usize, 4), std.Thread.getCpuCount() catch 1);
        for (1..@max(workers, 1)) |_| group.concurrent(ctx.io, inputWorker, .{ ctx, jobs, &next }) catch break;
        inputWorker(ctx, jobs, &next);
        try group.await(ctx.io);
        const result = try ctx.a.alloc(cache.Dependency, jobs.len);
        for (result, jobs) |*dep, job| {
            if (job.failure) |err| return err;
            bytes.* +|= job.size;
            dep.* = .{ .path = job.path, .hash = try ctx.a.dupe(u8, &job.hash) };
        }
        return result;
    }
    var result: std.ArrayList(cache.Dependency) = .empty;
    for (task.inputs) |input| {
        const path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, input });
        // Declared inputs always receive complete content hashes, not persistent
        // metadata memo hits (including inputs larger than the memo threshold).
        const digest = try ctx.checkedDigest(path);
        bytes.* +|= digest.state.size;
        try result.append(ctx.a, .{ .path = path, .hash = digest.hash });
    }
    return result.items;
}
fn count(h: *cache.Hash, n: usize) void {
    var bytes: [8]u8 = undefined;
    std.mem.writeInt(u64, &bytes, @intCast(n), .little);
    cache.field(h, &bytes);
}
fn sequence(h: *cache.Hash, tag: []const u8, values: []const []const u8) void {
    cache.field(h, tag);
    count(h, values.len);
    for (values) |value| cache.field(h, value);
}
const Host = struct {
    os: std.Target.Os.Tag,
    arch: std.Target.Cpu.Arch,
    abi: std.Target.Abi,
    model: []const u8,
    features: []const u8,
    version: []const u8,
};
fn validateHost(mode: HostIdentity, os: std.Target.Os.Tag, arch: std.Target.Cpu.Arch) !void {
    if (mode == .platform and (os != .linux or arch != .x86_64)) return error.UnsupportedTaskHostIdentity;
}
fn hostFields(h: *cache.Hash, mode: HostIdentity, host: Host) void {
    switch (mode) {
        // Keep omitted/explicit-native keys identical to the existing domain.
        .native => sequence(h, "host", &.{ @tagName(host.os), @tagName(host.arch), host.model, host.features, host.version }),
        // Caller promises the entire task is independent of native CPU/kernel
        // selection. OS, architecture and ABI still partition portable entries.
        .platform => sequence(h, "host-platform-v1", &.{ @tagName(host.os), @tagName(host.arch), @tagName(host.abi) }),
    }
}
fn hostDigest(mode: HostIdentity, host: Host) [32]u8 {
    var h = cache.Hash.init(.{});
    hostFields(&h, mode, host);
    var bytes: [32]u8 = undefined;
    h.final(&bytes);
    return bytes;
}
test "task host identity retains native safeguards and opts into platform reuse" {
    const original: Host = .{ .os = .linux, .arch = .x86_64, .abi = .musl, .model = "cpu-a", .features = "features-a", .version = "kernel-a" };
    const native = hostDigest(.native, original);
    const portable = hostDigest(.platform, original);
    var prior = cache.Hash.init(.{});
    sequence(&prior, "host", &.{ "linux", "x86_64", "cpu-a", "features-a", "kernel-a" });
    var expected: [32]u8 = undefined;
    prior.final(&expected);
    try std.testing.expectEqualSlices(u8, &expected, &native);
    try std.testing.expect(!std.mem.eql(u8, &native, &portable));
    inline for (.{ "model", "features", "version" }) |field| {
        var changed = original;
        @field(changed, field) = "different";
        try std.testing.expect(!std.mem.eql(u8, &native, &hostDigest(.native, changed)));
        try std.testing.expectEqualSlices(u8, &portable, &hostDigest(.platform, changed));
    }
}
test "platform task host identity retains OS architecture and ABI partitions" {
    const original: Host = .{ .os = .linux, .arch = .x86_64, .abi = .musl, .model = "cpu", .features = "features", .version = "kernel" };
    const digest = hostDigest(.platform, original);
    var changed = original;
    changed.os = .macos;
    try std.testing.expect(!std.mem.eql(u8, &digest, &hostDigest(.platform, changed)));
    changed = original;
    changed.arch = .aarch64;
    try std.testing.expect(!std.mem.eql(u8, &digest, &hostDigest(.platform, changed)));
    changed = original;
    changed.abi = .gnu;
    try std.testing.expect(!std.mem.eql(u8, &digest, &hostDigest(.platform, changed)));
}
test "platform task host opt-in rejects unsupported hosts before execution" {
    try validateHost(.platform, .linux, .x86_64);
    try std.testing.expectError(error.UnsupportedTaskHostIdentity, validateHost(.platform, .linux, .aarch64));
    try std.testing.expectError(error.UnsupportedTaskHostIdentity, validateHost(.platform, .macos, .x86_64));
    try std.testing.expectError(error.UnsupportedTaskHostIdentity, validateHost(.platform, .windows, .x86_64));
    try validateHost(.native, .macos, .aarch64);
}
const Tools = struct { executable: []const u8, resources: []const []const u8 };
fn tools(ctx: *cache.Context, task: Task, argv: []const []const u8) !Tools {
    var resources: std.ArrayList([]const u8) = .empty;
    for (task.tool_resources) |resource| {
        const path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, resource });
        try resources.append(ctx.a, try identity.nativeFiles(ctx, &.{path}));
    }
    return .{ .executable = try identity.installedFileDigest(ctx, argv[0]), .resources = resources.items };
}
fn taskKey(ctx: *cache.Context, task: Task, argv: []const []const u8, deps: []const cache.Dependency, installed: Tools) ![]const u8 {
    var h = cache.Hash.init(.{});
    // A new namespace prevents reuse of the old raw-spec-dependent keys.
    cache.field(&h, if (task.relocatable != null) "nanocompile-relocatable-task-v1" else "nanocompile-declared-task-v2");
    sequence(&h, "task", &.{task.name});
    sequence(&h, "cwd", &.{if (task.relocatable != null) task.cwd else ctx.cwd});
    if (task.relocatable) |contract| sequence(&h, "declared_environment", contract.environment);
    const host = try std.zig.system.resolveTargetQuery(ctx.io, .{});
    hostFields(&h, task.host_identity, .{ .os = builtin.os.tag, .arch = host.cpu.arch, .abi = host.abi, .model = host.cpu.model.name, .features = std.mem.asBytes(&host.cpu.features.ints), .version = try std.fmt.allocPrint(ctx.a, "{any}", .{host.os}) });
    sequence(&h, "command", task.command);
    sequence(&h, "selected_command", argv);
    sequence(&h, "installed_executable", &.{installed.executable});
    sequence(&h, "tool_resources", task.tool_resources);
    sequence(&h, "tool_identities", installed.resources);
    sequence(&h, "depends_on", task.depends_on);
    sequence(&h, "inputs", task.inputs);
    cache.field(&h, "input_records");
    count(&h, deps.len);
    for (deps, task.inputs) |dep, input| {
        cache.field(&h, if (task.relocatable != null) input else dep.path);
        cache.field(&h, dep.hash);
    }
    sequence(&h, "outputs", task.outputs);
    const keys = try ctx.a.dupe([]const u8, ctx.env.keys());
    std.mem.sort([]const u8, keys, {}, less);
    cache.field(&h, "environment");
    count(&h, keys.len);
    for (keys) |name| {
        cache.field(&h, name);
        cache.field(&h, ctx.env.get(name).?);
    }
    return cache.finish(ctx.a, &h);
}
fn outputBytes(ctx: *cache.Context, outputs: []const []const u8) ?u64 {
    var bytes: u64 = 0;
    for (outputs) |out| bytes +|= (Dir.cwd().statFile(ctx.io, out, .{}) catch return null).size;
    return bytes;
}
fn executeOne(ctx: *cache.Context, workspace: []const u8, spec_path: []const u8, spec_bytes: []const u8, task: Task, report: *TaskReport, reporting: bool, disabled: bool) !u8 {
    const task_start = now(ctx, reporting);
    defer report.timings.total_ns = now(ctx, reporting) - task_start;
    try validateRelocatable(ctx, workspace, task);
    var argv = try ctx.a.dupe([]const u8, task.command);
    argv[0] = try identity.selectedExecutable(ctx, argv[0]);
    var outputs: std.ArrayList([]const u8) = .empty;
    for (task.outputs) |out| {
        const path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, out });
        if (std.mem.eql(u8, path, spec_path)) return error.OverlappingOutput;
        for (outputs.items) |existing| if (std.mem.eql(u8, path, existing)) return error.DuplicateOutput;
        try outputs.append(ctx.a, path);
    }
    var phase = now(ctx, reporting);
    const before = try records(ctx, task, &report.input_bytes_hashed);
    report.timings.input_hash_ns = now(ctx, reporting) - phase;
    for (before) |input| for (outputs.items) |out| if (std.mem.eql(u8, input.path, out)) return error.OverlappingOutput;
    phase = now(ctx, reporting);
    const installed = try tools(ctx, task, argv);
    report.timings.tool_identity_ns = now(ctx, reporting) - phase;
    const key = try taskKey(ctx, task, argv, before, installed);
    phase = now(ctx, reporting);
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
    report.timings.lock_wait_ns = now(ctx, reporting) - phase;
    if (!disabled) {
        phase = now(ctx, reporting);
        // Existence distinguishes absence from a rejected/unreadable entry; a
        // generic false restore result cannot establish corruption's cause.
        if (reporting) {
            const entry: ?std.Io.File.Stat = Dir.cwd().statFile(ctx.io, try ctx.path(&.{ "entries", key }), .{}) catch |err| blk: {
                report.lookup = if (err == error.FileNotFound) "entry_absent" else "entry_unusable";
                break :blk null;
            };
            _ = entry;
        }
        var restore_timings: cache.RestoreTimings = .{};
        // Relocatable keys freshly hash inputs and use logical output names;
        // strict keys additionally revalidate the entry's absolute dependencies.
        const streams = cache.restoreStagedTimed(ctx, key, if (task.relocatable != null) task.outputs else outputs.items, outputs.items, if (reporting) &restore_timings else null) catch null;
        report.timings.lookup_ns = restore_timings.lookup_ns;
        report.timings.restore_ns = restore_timings.restore_ns;
        const hit = if (streams) |saved| replayed: {
            const replay_start = now(ctx, reporting);
            defer report.timings.diagnostic_replay_ns = now(ctx, reporting) - replay_start;
            // Preserve each mode's existing diagnostic-write failure behavior.
            ctx.out(saved.stdout) catch |err| {
                if (task.relocatable != null) return err;
                break :replayed false;
            };
            std.Io.File.stderr().writeStreamingAll(ctx.io, saved.stderr) catch |err| {
                if (task.relocatable != null) return err;
                break :replayed false;
            };
            break :replayed true;
        } else false;
        report.timings.lookup_restore_ns = now(ctx, reporting) - phase;
        if (hit) {
            report.lookup = "hit";
            report.outcome = "hit";
            report.exit_code = 0;
            if (reporting) {
                report.restored_output_bytes = outputBytes(ctx, outputs.items);
                report.output_bytes = report.restored_output_bytes;
            }
            ctx.event("task_hit");
            return 0;
        }
        if (!std.mem.eql(u8, report.lookup, "entry_absent")) report.lookup = "entry_unusable";
    } else report.lookup = "disabled";
    phase = now(ctx, reporting);
    const result = try std.process.run(ctx.a, ctx.io, .{ .argv = argv, .cwd = .{ .path = ctx.cwd }, .environ_map = ctx.env });
    report.timings.child_ns = now(ctx, reporting) - phase;
    report.child_stdout_bytes = result.stdout.len;
    report.child_stderr_bytes = result.stderr.len;
    try ctx.out(result.stdout);
    try std.Io.File.stderr().writeStreamingAll(ctx.io, result.stderr);
    const status: u8 = switch (result.term) {
        .exited => |v| v,
        .signal => |v| @intCast(@min(255, 128 + @as(u32, @backingInt(v)))),
        else => 1,
    };
    report.exit_code = status;
    if (status != 0) {
        report.outcome = "failed";
        ctx.event("task_failed");
        return status;
    }
    if (reporting) report.output_bytes = outputBytes(ctx, outputs.items);
    if (disabled) {
        report.outcome = "bypass";
        ctx.event("task_bypass");
        return 0;
    }
    report.outcome = "miss";
    ctx.event("task_miss");
    const after = validation: {
        const validation_start = now(ctx, reporting);
        defer report.timings.revalidation_ns = now(ctx, reporting) - validation_start;
        report.storage = "revalidation_failed";
        // Raw bytes are a race guard, not a cache-key component. Even a harmless
        // formatting edit during execution must suppress publication.
        if (!std.mem.eql(u8, spec_bytes, ctx.read(spec_path) catch return 0)) {
            report.storage = "spec_changed";
            return 0;
        }
        validateRelocatable(ctx, workspace, task) catch return 0;
        const after = records(ctx, task, &report.revalidation_input_bytes_hashed) catch return 0;
        const after_tools = tools(ctx, task, argv) catch return 0;
        if (!std.mem.eql(u8, key, try taskKey(ctx, task, argv, after, after_tools))) {
            report.storage = "inputs_or_tools_changed";
            return 0;
        }
        // Re-read again after input/tool hashing, not merely immediately after child.
        if (!std.mem.eql(u8, spec_bytes, ctx.read(spec_path) catch return 0)) {
            report.storage = "spec_changed";
            return 0;
        }
        break :validation after;
    };
    phase = now(ctx, reporting);
    defer report.timings.storage_ns = now(ctx, reporting) - phase;
    report.storage = "error";
    if (task.relocatable != null) {
        try cache.storeNamedTask(ctx, key, task.outputs, outputs.items, result.stdout, result.stderr);
    } else try cache.store(ctx, key, after, outputs.items, result.stdout, result.stderr);
    report.storage = "stored";
    if (reporting) report.stored_output_bytes = outputBytes(ctx, outputs.items);
    return 0;
}
// Resolve existing symlink ancestors even for a destination that does not exist.
fn canonicalPath(ctx: *cache.Context, path: []const u8) ![]const u8 {
    return Dir.cwd().realPathFileAlloc(ctx.io, path, ctx.a) catch |err| switch (err) {
        error.FileNotFound => try std.fs.path.join(ctx.a, &.{ try canonicalPath(ctx, std.fs.path.dirname(path) orelse return err), std.fs.path.basename(path) }),
        else => return err,
    };
}
fn within(path: []const u8, protected: []const u8) bool {
    const equal = if (builtin.os.tag == .windows) std.ascii.eqlIgnoreCase(path, protected) else std.mem.eql(u8, path, protected);
    if (equal) return true;
    if (path.len <= protected.len) return false;
    const prefix = if (builtin.os.tag == .windows) std.ascii.eqlIgnoreCase(path[0..protected.len], protected) else std.mem.eql(u8, path[0..protected.len], protected);
    return prefix and std.fs.path.isSep(path[protected.len]);
}
fn relativePath(path: []const u8, allow_dot: bool) bool {
    if (allow_dot and std.mem.eql(u8, path, ".")) return true;
    if (path.len == 0 or std.fs.path.isAbsolute(path)) return false;
    var parts = std.mem.splitAny(u8, path, if (builtin.os.tag == .windows) "/\\" else "/");
    while (parts.next()) |part| {
        if (part.len == 0 or std.mem.eql(u8, part, ".") or std.mem.eql(u8, part, "..")) return false;
    }
    return true;
}
fn samePath(a: []const u8, b: []const u8) bool {
    return if (builtin.os.tag == .windows) std.ascii.eqlIgnoreCase(a, b) else std.mem.eql(u8, a, b);
}
fn validateRelocatable(ctx: *cache.Context, workspace: []const u8, task: Task) !void {
    const contract = task.relocatable orelse return;
    if (!contract.path_independent or !contract.resources_complete) return error.IncompleteRelocatableContract;
    if (!relativePath(task.cwd, true)) return error.InvalidRelocatablePath;
    if (!within(ctx.cwd, workspace) or !samePath(ctx.cwd, try canonicalPath(ctx, ctx.cwd))) return error.InvalidRelocatablePath;
    for ([_][]const []const u8{ task.inputs, task.outputs }) |paths| for (paths) |path| {
        if (!relativePath(path, false)) return error.InvalidRelocatablePath;
        const absolute = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, path });
        // Reject symlinked files/ancestors, including links inside the workspace:
        // link identity and path-sensitive resolution are not this contract.
        if (!within(absolute, workspace) or !samePath(absolute, try canonicalPath(ctx, absolute))) return error.InvalidRelocatablePath;
    };
    // Installed tools remain absolute and installation-sensitive. We relocate
    // checkout files only, never toolchains/SDKs or arbitrary command arguments.
    if (!std.fs.path.isAbsolute(task.command[0])) return error.InvalidRelocatableTool;
    if (within(try canonicalPath(ctx, task.command[0]), workspace)) return error.InvalidRelocatableTool;
    for (task.tool_resources) |resource| {
        if (!std.fs.path.isAbsolute(resource) or within(try canonicalPath(ctx, resource), workspace)) return error.InvalidRelocatableTool;
    }
    for (contract.environment, 0..) |name, index| {
        if (name.len == 0 or std.mem.indexOfAny(u8, name, "=\x00") != null or isReportVariable(name)) return error.InvalidRelocatableEnvironment;
        for (contract.environment[0..index]) |previous| if (samePath(name, previous)) return error.InvalidRelocatableEnvironment;
    }
}
fn writeReport(ctx: *cache.Context, destination: []const u8, spec_path: []const u8, spec: Spec, rows: []const TaskReport, maintenance_lock_ns: i96, setup_ns: i96, total_ns: i96) !void {
    const path = try canonicalPath(ctx, try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, destination }));
    if (within(path, try canonicalPath(ctx, spec_path))) return;
    // Reports are fresh files only, outside every declared contract resource.
    // Exclusive creation also refuses preexisting symlinks/hardlinks and makes
    // report failures observational: never replace task or unrelated files.
    for (spec.tasks) |task| {
        var local = ctx.*;
        local.cwd = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, task.cwd });
        for ([_][]const []const u8{ task.inputs, task.outputs, task.tool_resources }) |paths| for (paths) |protected| {
            if (within(path, try canonicalPath(ctx, try std.fs.path.resolve(ctx.a, &.{ local.cwd, protected })))) return;
        };
        if (within(path, try canonicalPath(ctx, try identity.selectedExecutable(&local, task.command[0])))) return;
    }
    const bytes = try std.json.Stringify.valueAlloc(ctx.a, .{ .schema = @as(u32, 1), .maintenance_lock_ns = maintenance_lock_ns, .setup_ns = setup_ns, .total_ns = total_ns, .tasks = rows }, .{});
    const file = try Dir.cwd().createFile(ctx.io, path, .{ .exclusive = true, .permissions = cache.permissions(0o600) });
    defer file.close(ctx.io);
    try file.writeStreamingAll(ctx.io, bytes);
    try file.writeStreamingAll(ctx.io, "\n");
}
pub fn execute(ctx: *cache.Context, filename: []const u8) !u8 {
    // Only this reporting control is excluded, in an invocation-local copy used
    // by both key construction and children. Never mutate the root environment.
    const destination = ctx.env.get(report_variable);
    const invocation_start = now(ctx, destination != null);
    var environment = std.process.Environ.Map.init(ctx.a);
    defer environment.deinit();
    for (ctx.env.keys()) |name| {
        if (!isReportVariable(name)) try environment.put(name, ctx.env.get(name).?);
    }
    var invocation = ctx.*;
    invocation.env = &environment;
    const local_ctx = &invocation;
    const spec_path = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, filename });
    const spec_bytes = try ctx.read(spec_path);
    const parsed = try std.json.parseFromSlice(Spec, ctx.a, spec_bytes, .{ .allocate = .alloc_always });
    const spec = parsed.value;
    if (spec.schema != 1 or spec.tasks.len == 0 or spec.tasks.len > 1024) return error.InvalidTaskSpec;
    // Validate the complete graph before executing anything. Only dependencies
    // earlier in this explicit order are accepted; cycles/forward refs refuse.
    var names: std.StringHashMapUnmanaged(void) = .empty;
    for (spec.tasks) |task| {
        try validateHost(task.host_identity, builtin.os.tag, builtin.cpu.arch);
        if (task.name.len == 0 or names.contains(task.name) or task.command.len == 0 or task.inputs.len == 0 or task.outputs.len == 0) return error.InvalidTaskGraph;
        for (task.depends_on) |dep| if (!names.contains(dep)) return error.InvalidTaskGraph;
        try names.put(ctx.a, task.name, {});
    }
    // Reject incomplete relocation contracts anywhere in the graph before
    // running any child. Repeat physical path checks at execution/storage.
    const workspace = try canonicalPath(local_ctx, ctx.cwd);
    for (spec.tasks) |task| {
        var local = invocation;
        local.cwd = try std.fs.path.resolve(ctx.a, &.{ workspace, task.cwd });
        try validateRelocatable(&local, workspace, task);
    }
    var rows: std.ArrayList(TaskReport) = .empty;
    var maintenance_lock_ns: i96 = 0;
    var setup_ns: i96 = 0;
    defer if (destination) |path| writeReport(local_ctx, path, spec_path, spec, rows.items, maintenance_lock_ns, setup_ns, now(local_ctx, true) - invocation_start) catch {};
    try local_ctx.prepare();
    const start = now(local_ctx, destination != null);
    const maintenance = try cache.Lock.acquire(local_ctx, "maintenance", false);
    defer maintenance.release();
    maintenance_lock_ns = now(local_ctx, destination != null) - start;
    setup_ns = now(local_ctx, destination != null) - invocation_start;
    for (spec.tasks, 0..) |task, index| {
        // Re-read the contract: changes during an earlier task do not silently
        // execute or cache an already-parsed stale graph.
        if (!std.mem.eql(u8, spec_bytes, try ctx.read(spec_path))) return error.TaskSpecChanged;
        var local = invocation;
        local.cwd = try std.fs.path.resolve(ctx.a, &.{ if (task.relocatable != null) workspace else ctx.cwd, task.cwd });
        var declared_environment = std.process.Environ.Map.init(ctx.a);
        defer declared_environment.deinit();
        if (task.relocatable) |contract| {
            for (contract.environment) |name| {
                if (environment.get(name)) |value| try declared_environment.put(name, value);
            }
            // Excluded variables are absent from the child, not merely its key.
            local.env = &declared_environment;
        }
        var row: TaskReport = .{ .task_index = index };
        const disabled = std.mem.eql(u8, environment.get("NANOCOMPILE_DISABLE") orelse "", "1");
        const status = executeOne(&local, workspace, spec_path, spec_bytes, task, &row, destination != null, disabled) catch |err| {
            if (destination != null) rows.append(ctx.a, row) catch {};
            return err;
        };
        if (destination != null) rows.append(ctx.a, row) catch {};
        if (status != 0) return status;
    }
    return 0;
}
