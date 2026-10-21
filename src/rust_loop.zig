//! Native rust-loop steps: catalog, spec generation, and the rustc gate.
//! A successful fast-check is never the commit or release signal.
const std = @import("std");
const builtin = @import("builtin");
const cache = @import("cache.zig");
const identity = @import("identity.zig");
const Dir = std.Io.Dir;

pub const schema: u32 = 1;
pub const fast_check = "fast-check";
pub const validate = "validate";
pub const stamp_dir = ".nanocompile-loop";
pub const charlie_thread = "https://x.com/charliermarsh/status/2112711387285758250";

const forbidden_validate = [_][]const u8{ "cranelift", "codegen-backend", "cg_clif", "cargo-clif", "rustd", "lust", "relax" };
const codegen_flags = [_][]const u8{ "codegen-units", "incremental", "linker", "link-arg", "debuginfo", "split-debuginfo", "strip" };
const source_roots = [_][]const u8{ "src", "tests", "examples", "benches" };
const config_files = [_][]const u8{ "Cargo.toml", "Cargo.lock", "rust-toolchain", "rust-toolchain.toml", "build.rs", ".cargo/config.toml", ".cargo/config" };

const CatalogItem = struct {
    id: []const u8,
    role: []const u8 = "recommendation",
    title: []const u8,
    command: []const []const u8 = &.{},
    verified: []const u8 = "",
    url: ?[]const u8 = null,
    nightly: ?bool = null,
    thread: ?[]const u8 = null,
    public_repo_verified: ?bool = null,
    open_source: ?bool = null,
};
const Catalog = struct {
    schema: u32 = schema,
    attribution: []const u8 = charlie_thread,
    usable_now: []const CatalogItem,
    experimental: []const CatalogItem,
    required_tasks: []const []const u8,
};
const Task = struct {
    name: []const u8,
    cwd: []const u8 = ".",
    command: []const []const u8,
    inputs: []const []const u8,
    outputs: []const []const u8,
    depends_on: []const []const u8 = &.{},
    tool_resources: []const []const u8 = &.{},
};
const Spec = struct { schema: u32 = 1, tasks: []const Task };

pub const usable_now = [_]CatalogItem{
    .{ .id = "fast-check", .role = "task", .title = "Skip codegen on the edit path", .command = &.{ "cargo", "check" }, .verified = "cargo check --help; rustc emits metadata only" },
    .{ .id = "validate", .role = "task", .title = "Real rustc test/build gate", .command = &.{ "cargo", "test" }, .verified = "cargo test runs rustc with the default LLVM backend" },
    .{ .id = "nanocompile-wrapper", .title = "Cache eligible rustc invocations", .command = &.{ "RUSTC_WRAPPER=nanocompile", "CARGO_INCREMENTAL=0", "cargo", "check" }, .verified = "README RUSTC_WRAPPER protocol; incremental compilations are ineligible" },
    .{ .id = "rust-analyzer", .title = "Editor diagnostics from rust-analyzer", .command = &.{"rust-analyzer"}, .verified = "https://rust-analyzer.github.io/", .url = "https://rust-analyzer.github.io/" },
    .{ .id = "bacon", .title = "Persistent cargo check/test watcher", .command = &.{"bacon"}, .verified = "https://github.com/Canop/bacon", .url = "https://github.com/Canop/bacon" },
    .{ .id = "cranelift-dev", .title = "Cranelift codegen for nightly dev builds", .command = &.{ "rustup", "component", "add", "rustc-codegen-cranelift-preview", "--toolchain", "nightly" }, .verified = "https://doc.rust-lang.org/cargo/guide/build-performance.html", .url = "https://github.com/rust-lang/rustc_codegen_cranelift", .nightly = true },
    .{ .id = "fast-linker", .title = "Faster linker for cargo build", .command = &.{ "rustc", "-C", "link-arg=-fuse-ld=lld" }, .verified = "rustc -C help (link-arg, linker); rust-lld in the sysroot; mold in the Cargo book", .url = "https://doc.rust-lang.org/cargo/guide/build-performance.html" },
    .{ .id = "sccache", .title = "Shared compile cache for C or as an alternate rustc wrapper", .command = &.{"sccache"}, .verified = "https://github.com/mozilla/sccache", .url = "https://github.com/mozilla/sccache" },
    .{ .id = "crate-shape", .title = "Split crates and keep codegen-units parallel", .command = &.{ "rustc", "-C", "codegen-units=256" }, .verified = "rustc -C help lists codegen-units" },
    .{ .id = "hot-reload", .title = "Hot-reload a dylib or a Dioxus app", .command = &.{"hot-lib-reloader"}, .verified = "https://github.com/rksm/hot-lib-reloader-rs; DioxusLabs/dioxus subsecond", .url = "https://github.com/rksm/hot-lib-reloader-rs" },
    .{ .id = "disk-hygiene", .title = "Bound target and cache disk use", .command = &.{ "nanocompile", "gc" }, .verified = "nanocompile gc; cargo clean; profile.dev debug = line-tables-only", .url = "https://doc.rust-lang.org/cargo/guide/build-performance.html" },
};
pub const experimental = [_]CatalogItem{
    .{ .id = "rustd", .title = "rustd (Jon Kelley / Dioxus Labs)", .verified = "DioxusLabs/rustd README", .url = "https://github.com/DioxusLabs/rustd", .thread = "https://x.com/jkelleyrtp/status/2110433801071689733" },
    .{ .id = "relax", .title = "Relax (Rik Arends)", .verified = "Charlie Marsh thread", .url = "https://x.com/rikarends/status/2112212283934077190", .thread = "https://x.com/charliermarsh/status/2112711399512092895", .public_repo_verified = false },
    .{ .id = "lust", .title = "Lust (Theo)", .verified = "t3dotgg/lust-lang README", .url = "https://github.com/t3dotgg/lust-lang", .thread = "https://x.com/theo/status/2112366051623375234" },
    .{ .id = "astral-fork", .title = "Astral rustc/cargo/rustfmt/clippy fork", .verified = "Charlie Marsh thread", .url = "https://x.com/charliermarsh/status/2112711411830804544", .open_source = false },
    .{ .id = "upstream-perf", .title = "Rust project compiler performance optimizations", .verified = "Rust Project Goals 2026", .url = "https://goals.rust-lang.org/2026/compiler-performance-optimization.html", .thread = "https://x.com/charliermarsh/status/2112711419334635917" },
};

fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

fn contains(hay: []const u8, needle: []const u8) bool {
    if (needle.len == 0 or hay.len < needle.len) return false;
    var i: usize = 0;
    while (i + needle.len <= hay.len) : (i += 1) {
        if (std.ascii.eqlIgnoreCase(hay[i .. i + needle.len], needle)) return true;
    }
    return false;
}

pub fn forbiddenToken(values: []const []const u8) ?[]const u8 {
    for (values) |value| {
        for (forbidden_validate) |banned| if (contains(value, banned)) return banned;
    }
    return null;
}

fn fail(ctx: *cache.Context, message: []const u8) !void {
    try std.Io.File.stderr().writeStreamingAll(ctx.io, "rust-loop: ");
    try std.Io.File.stderr().writeStreamingAll(ctx.io, message);
    try std.Io.File.stderr().writeStreamingAll(ctx.io, "\n");
}

fn hasName(tasks: []const Task, end: usize, name: []const u8) bool {
    for (tasks[0..end]) |task| if (eq(task.name, name)) return true;
    return false;
}

pub fn checkSpec(spec: Spec) !void {
    if (spec.schema != 1 or spec.tasks.len == 0) return error.InvalidRustLoopSpec;
    var fast_index: ?usize = null;
    var validate_index: ?usize = null;
    for (spec.tasks, 0..) |task, index| {
        if (task.name.len == 0 or task.command.len == 0 or task.inputs.len == 0 or task.outputs.len == 0)
            return error.InvalidRustLoopSpec;
        if (hasName(spec.tasks, index, task.name)) return error.InvalidRustLoopSpec;
        for (task.depends_on) |dep| if (!hasName(spec.tasks, index, dep)) return error.InvalidRustLoopSpec;
        if (eq(task.name, fast_check)) fast_index = index;
        if (eq(task.name, validate)) validate_index = index;
    }
    const fast_i = fast_index orelse return error.MissingFastCheck;
    const validate_i = validate_index orelse return error.MissingValidate;
    if (fast_i > validate_i) return error.ValidateBeforeFastCheck;
    const validate_task = spec.tasks[validate_i];
    var has_dep = false;
    for (validate_task.depends_on) |dep| if (eq(dep, fast_check)) {
        has_dep = true;
    };
    if (!has_dep) return error.ValidateMissingDependency;
    if (forbiddenToken(validate_task.command) != null) return error.ExperimentalValidate;
    var has_check = false;
    for (spec.tasks[fast_i].command) |part| if (eq(part, "check")) {
        has_check = true;
    };
    var has_test = false;
    for (validate_task.command) |part| if (eq(part, "test")) {
        has_test = true;
    };
    if (!has_check) return error.FastCheckMustUseCargoCheck;
    if (!has_test) return error.ValidateMustUseCargoTest;
}

test "rust-loop spec requires validate after fast-check" {
    const good = Spec{ .tasks = &.{
        .{ .name = fast_check, .command = &.{ "cargo", "check" }, .inputs = &.{"src/lib.rs"}, .outputs = &.{"a"} },
        .{ .name = validate, .command = &.{ "cargo", "test" }, .inputs = &.{"src/lib.rs"}, .outputs = &.{"b"}, .depends_on = &.{fast_check} },
    } };
    try checkSpec(good);
    try std.testing.expectError(error.MissingValidate, checkSpec(.{ .tasks = good.tasks[0..1] }));
    const swapped = Spec{ .tasks = &.{
        .{ .name = validate, .command = &.{ "cargo", "test" }, .inputs = &.{"src/lib.rs"}, .outputs = &.{"b"} },
        .{ .name = fast_check, .command = &.{ "cargo", "check" }, .inputs = &.{"src/lib.rs"}, .outputs = &.{"a"}, .depends_on = &.{validate} },
    } };
    try std.testing.expectError(error.ValidateBeforeFastCheck, checkSpec(swapped));
    const cranelift = Spec{ .tasks = &.{
        good.tasks[0],
        .{ .name = validate, .command = &.{ "cargo", "test", "-Zcodegen-backend" }, .inputs = &.{"src/lib.rs"}, .outputs = &.{"b"}, .depends_on = &.{fast_check} },
    } };
    try std.testing.expectError(error.ExperimentalValidate, checkSpec(cranelift));
}

pub fn workspaceMembers(allocator: std.mem.Allocator, text: []const u8) ![]const []const u8 {
    var found: std.ArrayList([]const u8) = .empty;
    errdefer {
        for (found.items) |item| allocator.free(item);
        found.deinit(allocator);
    }
    var section: []const u8 = "";
    var collecting = false;
    var lines = std.mem.splitScalar(u8, text, '\n');
    while (lines.next()) |raw| {
        const hash = std.mem.indexOfScalar(u8, raw, '#') orelse raw.len;
        const line = std.mem.trim(u8, raw[0..hash], " \t\r");
        if (line.len == 0) continue;
        if (line[0] == '[' and line[line.len - 1] == ']') {
            section = std.mem.trim(u8, line[1 .. line.len - 1], " ");
            collecting = false;
            continue;
        }
        if (!eq(section, "workspace")) continue;
        var rest = line;
        if (std.mem.startsWith(u8, line, "members")) {
            collecting = true;
            rest = if (std.mem.indexOfScalar(u8, line, '=')) |eq_at| std.mem.trim(u8, line[eq_at + 1 ..], " \t") else "";
        }
        if (!collecting) continue;
        if (rest.len > 0 and rest[0] == '[') rest = rest[1..];
        const done = std.mem.indexOfScalar(u8, rest, ']') != null;
        if (std.mem.indexOfScalar(u8, rest, ']')) |end| rest = rest[0..end];
        var parts = std.mem.splitScalar(u8, rest, ',');
        while (parts.next()) |part| {
            const item = std.mem.trim(u8, part, " \t\"'");
            if (item.len > 0) try found.append(allocator, try allocator.dupe(u8, item));
        }
        if (done) collecting = false;
    }
    return found.toOwnedSlice(allocator);
}

test "workspace members parse quoted arrays" {
    const members = try workspaceMembers(std.testing.allocator, "[workspace]\nmembers = [\"core\", \"app\"]\n");
    defer {
        for (members) |item| std.testing.allocator.free(item);
        std.testing.allocator.free(members);
    }
    try std.testing.expectEqual(@as(usize, 2), members.len);
    try std.testing.expectEqualStrings("core", members[0]);
    try std.testing.expectEqualStrings("app", members[1]);
}

fn existsKind(ctx: *cache.Context, path: []const u8, kind: std.Io.File.Kind) bool {
    const st = Dir.cwd().statFile(ctx.io, path, .{}) catch return false;
    return st.kind == kind;
}

fn walkFiles(ctx: *cache.Context, root: []const u8, directory: []const u8, into: *std.ArrayList([]const u8), seen: *std.StringHashMap(void)) !void {
    const folder = try std.fs.path.join(ctx.a, &.{ root, directory });
    var dir = Dir.cwd().openDir(ctx.io, folder, .{ .iterate = true }) catch return;
    defer dir.close(ctx.io);
    var walk = try dir.walk(ctx.a);
    defer walk.deinit();
    while (try walk.next(ctx.io)) |entry| {
        if (entry.kind != .file) continue;
        const rel = try posixJoin(ctx, &.{ directory, entry.path });
        if (seen.contains(rel)) continue;
        try seen.put(rel, {});
        try into.append(ctx.a, rel);
    }
}

fn posixJoin(ctx: *cache.Context, parts: []const []const u8) ![]const u8 {
    const joined = try std.fs.path.join(ctx.a, parts);
    if (builtin.os.tag != .windows) return joined;
    const copy = try ctx.a.dupe(u8, joined);
    for (copy) |*byte| {
        if (byte.* == '\\') byte.* = '/';
    }
    return copy;
}

fn less(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.order(u8, a, b) == .lt;
}

fn discoverInputs(ctx: *cache.Context, root: []const u8) ![]const []const u8 {
    var paths: std.ArrayList([]const u8) = .empty;
    var seen = std.StringHashMap(void).init(ctx.a);
    const cargo = try std.fs.path.join(ctx.a, &.{ root, "Cargo.toml" });
    if (!existsKind(ctx, cargo, .file)) return error.MissingCargoToml;
    var packages: std.ArrayList([]const u8) = .empty;
    try packages.append(ctx.a, root);
    const members = workspaceMembers(ctx.a, try ctx.read(cargo)) catch &.{};
    for (members) |member| try packages.append(ctx.a, try std.fs.path.join(ctx.a, &.{ root, member }));
    for (packages.items) |package| {
        if (!existsKind(ctx, package, .directory) and !eq(package, root)) continue;
        for (config_files) |name| {
            const path = try std.fs.path.join(ctx.a, &.{ package, name });
            if (!existsKind(ctx, path, .file)) continue;
            const rel = if (std.mem.startsWith(u8, path, root)) std.mem.trimStart(u8, path[root.len..], "/\\") else path;
            if (rel.len == 0 or seen.contains(rel)) continue;
            const stored = try posixJoin(ctx, &.{rel});
            try seen.put(stored, {});
            try paths.append(ctx.a, stored);
        }
        const rel_pkg = if (eq(package, root)) "" else std.mem.trimStart(u8, package[root.len..], "/\\");
        for (source_roots) |directory| {
            const rel_dir = if (rel_pkg.len == 0) directory else try posixJoin(ctx, &.{ rel_pkg, directory });
            try walkFiles(ctx, root, rel_dir, &paths, &seen);
        }
    }
    std.mem.sort([]const u8, paths.items, {}, less);
    return paths.items;
}

fn specCommand(ctx: *cache.Context, self_exe: []const u8, step: []const u8, stamp: []const u8, target_dir: []const u8, offline: bool, wrapper: ?[]const u8, cargo_subcommand: []const u8) ![]const []const u8 {
    var command: std.ArrayList([]const u8) = .empty;
    try command.appendSlice(ctx.a, &.{ self_exe, "rust-loop", "run", "--step", step, "--stamp", stamp, "--target-dir", target_dir });
    if (offline) try command.append(ctx.a, "--offline");
    if (wrapper) |path| {
        try command.append(ctx.a, "--wrapper");
        try command.append(ctx.a, path);
    }
    try command.appendSlice(ctx.a, &.{ "--", "cargo", cargo_subcommand });
    return command.items;
}

fn buildSpec(ctx: *cache.Context, root: []const u8, self_exe: []const u8, offline: bool, wrapper: ?[]const u8, target_dir: []const u8) !Spec {
    const resolved_self = if (std.fs.path.isAbsolute(self_exe)) self_exe else identity.selectedExecutable(ctx, self_exe) catch self_exe;
    const inputs = try discoverInputs(ctx, root);
    const fast_stamp = stamp_dir ++ "/fast-check.ok";
    const validate_stamp = stamp_dir ++ "/validate.ok";
    var validate_inputs = try std.ArrayList([]const u8).initCapacity(ctx.a, inputs.len + 1);
    try validate_inputs.appendSlice(ctx.a, inputs);
    try validate_inputs.append(ctx.a, fast_stamp);
    var tools: []const []const u8 = &.{};
    if (wrapper != null) {
        var list: std.ArrayList([]const u8) = .empty;
        try list.append(ctx.a, try pathLookup(ctx, "cargo"));
        try list.append(ctx.a, try pathLookup(ctx, "rustc"));
        tools = list.items;
    }
    const tasks = try ctx.a.alloc(Task, 2);
    tasks[0] = .{
        .name = fast_check,
        .command = try specCommand(ctx, resolved_self, fast_check, fast_stamp, target_dir, offline, wrapper, "check"),
        .inputs = inputs,
        .outputs = try ctx.a.dupe([]const u8, &.{fast_stamp}),
        .tool_resources = tools,
    };
    tasks[1] = .{
        .name = validate,
        .depends_on = try ctx.a.dupe([]const u8, &.{fast_check}),
        .command = try specCommand(ctx, resolved_self, validate, validate_stamp, target_dir, offline, wrapper, "test"),
        .inputs = validate_inputs.items,
        .outputs = try ctx.a.dupe([]const u8, &.{validate_stamp}),
        .tool_resources = tools,
    };
    const spec = Spec{ .tasks = tasks };
    try checkSpec(spec);
    return spec;
}

fn writeFile(ctx: *cache.Context, path: []const u8, bytes: []const u8) !void {
    if (std.fs.path.dirname(path)) |dir| try Dir.cwd().createDirPath(ctx.io, dir);
    const file = try Dir.cwd().createFile(ctx.io, path, .{ .truncate = true });
    defer file.close(ctx.io);
    try file.writeStreamingAll(ctx.io, bytes);
}

fn resolveUnderCwd(ctx: *cache.Context, path: []const u8) ![]const u8 {
    if (std.fs.path.isAbsolute(path)) return path;
    return std.fs.path.resolve(ctx.a, &.{ ctx.cwd, path });
}

fn pathLookup(ctx: *cache.Context, name: []const u8) ![]const u8 {
    // Keep rustup proxies as cargo/rustc. identity.selectedExecutable realpath's
    // them to rustup on Linux, which then treats `check` as `rustup check`.
    if (std.mem.indexOfScalar(u8, name, '/') != null) {
        if (std.fs.path.isAbsolute(name)) return name;
        return resolveUnderCwd(ctx, name);
    }
    var paths = std.mem.splitScalar(u8, ctx.env.get("PATH") orelse "", if (builtin.os.tag == .windows) ';' else ':');
    while (paths.next()) |dir| {
        const candidate = try std.fs.path.join(ctx.a, &.{ if (dir.len == 0) "." else dir, name });
        const st = Dir.cwd().statFile(ctx.io, candidate, .{}) catch continue;
        if (st.kind == .file) return candidate;
    }
    return error.CompilerNotFound;
}

fn runCargo(ctx: *cache.Context, step: []const u8, stamp: []const u8, target_dir: []const u8, offline: bool, wrapper: ?[]const u8, cargo_argv: []const []const u8) !u8 {
    if (!eq(step, fast_check) and !eq(step, validate)) {
        try fail(ctx, "unknown step");
        return 2;
    }
    if (cargo_argv.len == 0) {
        try fail(ctx, "missing cargo command after --");
        return 2;
    }
    if (eq(step, validate)) {
        if (forbiddenToken(cargo_argv)) |banned| {
            try fail(ctx, try std.fmt.allocPrint(ctx.a, "validate refuses {s}; the gate must be real rustc", .{banned}));
            return 2;
        }
        for (ctx.env.keys()) |name| {
            if (std.mem.endsWith(u8, name, "CODEGEN_BACKEND")) {
                if (contains(ctx.env.get(name) orelse "", "cranelift")) {
                    try fail(ctx, "validate refuses a cranelift codegen backend");
                    return 2;
                }
            }
        }
    }
    var environment = try ctx.env.clone(ctx.a);
    _ = environment.swapRemove("CARGO_PROFILE_DEV_CODEGEN_BACKEND");
    _ = environment.swapRemove("CARGO_PROFILE_TEST_CODEGEN_BACKEND");
    if (wrapper) |path| {
        try environment.put("RUSTC_WRAPPER", try resolveUnderCwd(ctx, path));
        try environment.put("CARGO_INCREMENTAL", "0");
    } else if (eq(step, validate)) {
        _ = environment.swapRemove("RUSTC_WRAPPER");
        _ = environment.swapRemove("RUSTC_WORKSPACE_WRAPPER");
    }
    try environment.put("CARGO_TARGET_DIR", try resolveUnderCwd(ctx, target_dir));
    if (environment.get("CARGO_TERM_COLOR") == null) try environment.put("CARGO_TERM_COLOR", "never");
    var argv = try ctx.a.dupe([]const u8, cargo_argv);
    argv[0] = try pathLookup(ctx, argv[0]);
    if (offline) {
        var has_offline = false;
        for (argv) |part| if (eq(part, "--offline")) {
            has_offline = true;
        };
        if (!has_offline) {
            var extra = try std.ArrayList([]const u8).initCapacity(ctx.a, argv.len + 1);
            try extra.appendSlice(ctx.a, argv);
            try extra.append(ctx.a, "--offline");
            argv = extra.items;
        }
    }
    const result = try std.process.run(ctx.a, ctx.io, .{
        .argv = argv,
        .cwd = .{ .path = ctx.cwd },
        .environ_map = &environment,
        .stdout_limit = .limited(64 * 1024 * 1024),
        .stderr_limit = .limited(64 * 1024 * 1024),
    });
    try ctx.out(result.stdout);
    try std.Io.File.stderr().writeStreamingAll(ctx.io, result.stderr);
    const status: u8 = switch (result.term) {
        .exited => |v| v,
        .signal => |v| @intCast(@min(255, 128 + @as(u32, @backingInt(v)))),
        else => 1,
    };
    if (status != 0) return status;
    try writeFile(ctx, try resolveUnderCwd(ctx, stamp), try std.fmt.allocPrint(ctx.a, "{s}\n", .{step}));
    return 0;
}

fn verifyFlags(ctx: *cache.Context) !u8 {
    const rustc = try pathLookup(ctx, "rustc");
    const cargo = try pathLookup(ctx, "cargo");
    const help = try std.process.run(ctx.a, ctx.io, .{
        .argv = &.{ rustc, "-C", "help" },
        .environ_map = ctx.env,
        .stdout_limit = .limited(64 * 1024 * 1024),
        .stderr_limit = .limited(64 * 1024 * 1024),
    });
    switch (help.term) {
        .exited => |code| if (code != 0) return error.RustcHelpFailed,
        else => return error.RustcHelpFailed,
    }
    for (codegen_flags) |flag| if (std.mem.indexOf(u8, help.stdout, flag) == null) return error.MissingCodegenFlag;
    const check = try std.process.run(ctx.a, ctx.io, .{
        .argv = &.{ cargo, "check", "--help" },
        .environ_map = ctx.env,
        .stdout_limit = .limited(64 * 1024 * 1024),
        .stderr_limit = .limited(64 * 1024 * 1024),
    });
    if (std.mem.indexOf(u8, check.stdout, "Check a local package") == null) return error.CargoCheckHelp;
    const test_help = try std.process.run(ctx.a, ctx.io, .{
        .argv = &.{ cargo, "test", "--help" },
        .environ_map = ctx.env,
        .stdout_limit = .limited(64 * 1024 * 1024),
        .stderr_limit = .limited(64 * 1024 * 1024),
    });
    if (!contains(test_help.stdout, "unit and integration tests") and !contains(test_help.stdout, "run the tests"))
        return error.CargoTestHelp;
    const sysroot = try std.process.run(ctx.a, ctx.io, .{
        .argv = &.{ rustc, "--print", "sysroot" },
        .environ_map = ctx.env,
        .stdout_limit = .limited(64 * 1024 * 1024),
        .stderr_limit = .limited(64 * 1024 * 1024),
    });
    const root = std.mem.trim(u8, sysroot.stdout, " \n\r\t");
    const lib = try std.fs.path.join(ctx.a, &.{ root, "lib", "rustlib" });
    var dir = Dir.cwd().openDir(ctx.io, lib, .{ .iterate = true }) catch return error.MissingRustLld;
    defer dir.close(ctx.io);
    var walk = try dir.walk(ctx.a);
    defer walk.deinit();
    var llds: std.ArrayList([]const u8) = .empty;
    while (try walk.next(ctx.io)) |entry| {
        if (entry.kind == .file and std.mem.indexOf(u8, entry.basename, "rust-lld") != null)
            try llds.append(ctx.a, try std.fs.path.join(ctx.a, &.{ lib, entry.path }));
    }
    if (llds.items.len == 0) return error.MissingRustLld;
    try ctx.out(try std.json.Stringify.valueAlloc(ctx.a, .{
        .rustc_codegen_flags = codegen_flags,
        .rust_lld = llds.items,
        .cargo_check = true,
        .cargo_test = true,
    }, .{ .whitespace = .indent_2 }));
    try ctx.out("\n");
    return 0;
}

const Parsed = struct {
    action: []const u8,
    manifest: []const u8 = "Cargo.toml",
    write: []const u8 = "-",
    wrapper: ?[]const u8 = null,
    target_dir: []const u8 = "target",
    stamp: ?[]const u8 = null,
    step: ?[]const u8 = null,
    spec: ?[]const u8 = null,
    offline: bool = false,
    cargo: []const []const u8 = &.{},
};

fn parseArgs(ctx: *cache.Context, args: []const [:0]const u8) !Parsed {
    if (args.len == 0) return error.MissingRustLoopAction;
    var parsed = Parsed{ .action = args[0] };
    var i: usize = 1;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (eq(arg, "--offline")) {
            parsed.offline = true;
        } else if (eq(arg, "--")) {
            const rest = args[i + 1 ..];
            const cargo = try ctx.a.alloc([]const u8, rest.len);
            for (rest, 0..) |part, index| cargo[index] = part;
            parsed.cargo = cargo;
            break;
        } else if (eq(arg, "--python")) {
            // Compatibility with the former Python helper; the native driver ignores it.
            if (i + 1 >= args.len) return error.InvalidRustLoopArgument;
            i += 1;
        } else if (i + 1 >= args.len) {
            if (eq(parsed.action, "check-spec") and parsed.spec == null) {
                parsed.spec = arg;
            } else return error.InvalidRustLoopArgument;
        } else if (eq(arg, "--manifest")) {
            i += 1;
            parsed.manifest = args[i];
        } else if (eq(arg, "--write")) {
            i += 1;
            parsed.write = args[i];
        } else if (eq(arg, "--wrapper")) {
            i += 1;
            parsed.wrapper = args[i];
        } else if (eq(arg, "--target-dir")) {
            i += 1;
            parsed.target_dir = args[i];
        } else if (eq(arg, "--stamp")) {
            i += 1;
            parsed.stamp = args[i];
        } else if (eq(arg, "--step")) {
            i += 1;
            parsed.step = args[i];
        } else if (eq(parsed.action, "check-spec") and parsed.spec == null) {
            parsed.spec = arg;
        } else return error.InvalidRustLoopArgument;
    }
    return parsed;
}

pub fn execute(ctx: *cache.Context, args: []const [:0]const u8, self_exe: []const u8) !u8 {
    const parsed = try parseArgs(ctx, args);
    if (eq(parsed.action, "list")) {
        try ctx.out(try std.json.Stringify.valueAlloc(ctx.a, Catalog{
            .usable_now = &usable_now,
            .experimental = &experimental,
            .required_tasks = &.{ fast_check, validate },
        }, .{ .whitespace = .indent_2, .emit_null_optional_fields = false }));
        try ctx.out("\n");
        return 0;
    }
    if (eq(parsed.action, "verify-flags")) return verifyFlags(ctx);
    if (eq(parsed.action, "check-spec")) {
        const path = parsed.spec orelse return error.MissingTaskSpec;
        const spec_path = try resolveUnderCwd(ctx, path);
        const spec = (try std.json.parseFromSlice(Spec, ctx.a, try ctx.read(spec_path), .{
            .allocate = .alloc_always,
            .ignore_unknown_fields = true,
        })).value;
        checkSpec(spec) catch |err| {
            try fail(ctx, @errorName(err));
            return 2;
        };
        try ctx.out(try std.fmt.allocPrint(ctx.a, "PASS: rust-loop specification keeps {s} before {s}\n", .{ fast_check, validate }));
        return 0;
    }
    if (eq(parsed.action, "spec")) {
        const manifest = try resolveUnderCwd(ctx, parsed.manifest);
        const root = std.fs.path.dirname(manifest) orelse ctx.cwd;
        const spec = buildSpec(ctx, root, self_exe, parsed.offline, parsed.wrapper, parsed.target_dir) catch |err| {
            try fail(ctx, @errorName(err));
            return 2;
        };
        const encoded = try std.json.Stringify.valueAlloc(ctx.a, spec, .{ .whitespace = .indent_2, .emit_null_optional_fields = false });
        if (eq(parsed.write, "-")) {
            try ctx.out(encoded);
            try ctx.out("\n");
        } else try writeFile(ctx, try resolveUnderCwd(ctx, parsed.write), try std.fmt.allocPrint(ctx.a, "{s}\n", .{encoded}));
        return 0;
    }
    if (eq(parsed.action, "run")) {
        const step = parsed.step orelse return error.MissingRustLoopStep;
        const stamp = parsed.stamp orelse return error.MissingRustLoopStamp;
        return runCargo(ctx, step, stamp, parsed.target_dir, parsed.offline, parsed.wrapper, parsed.cargo);
    }
    return error.UnknownRustLoopAction;
}
