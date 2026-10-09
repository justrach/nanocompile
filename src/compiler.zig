const std = @import("std");
const cache = @import("cache.zig");
const identity = @import("identity.zig");
const Dir = std.Io.Dir;
pub const Kind = enum { rust, zig };
const Plan = struct {
    source: []const u8,
    outputs: []const []const u8,
    dependencies: []const []const u8,
    dep_info: ?[]const u8 = null,
    library_dirs: []const []const u8 = &.{},
};
const Module = struct { name: []const u8, source: []const u8 };

fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

fn absolute(ctx: *cache.Context, path: []const u8) ![]const u8 {
    return std.fs.path.resolve(ctx.a, &.{ ctx.cwd, path });
}

fn addUnique(ctx: *cache.Context, list: *std.ArrayList([]const u8), path: []const u8) !void {
    const abs = try absolute(ctx, path);
    for (list.items) |item| if (eq(item, abs)) return;
    try list.append(ctx.a, abs);
}

fn option(argv: []const []const u8, index: *usize, name: []const u8) !?[]const u8 {
    const arg = argv[index.*];
    if (eq(arg, name)) {
        index.* += 1;
        if (index.* >= argv.len) return error.MissingValue;
        return argv[index.*];
    }
    if (std.mem.startsWith(u8, arg, name) and arg.len > name.len and arg[name.len] == '=')
        return arg[name.len + 1 ..];
    return null;
}

fn rustPlan(ctx: *cache.Context, argv: []const []const u8) !Plan {
    var source: ?[]const u8 = null;
    var name: ?[]const u8 = null;
    var crate_type: ?[]const u8 = null;
    var emit: ?[]const u8 = null;
    var out_dir: ?[]const u8 = null;
    var suffix: []const u8 = "";
    var split_debug: []const u8 = "off";
    var inputs: std.ArrayList([]const u8) = .empty;
    var search_dirs: std.ArrayList([]const u8) = .empty;
    var i: usize = 1;
    while (i < argv.len) : (i += 1) {
        const arg = argv[i];
        if (try option(argv, &i, "--crate-name")) |v| {
            name = v;
            continue;
        }
        if (try option(argv, &i, "--crate-type")) |v| {
            crate_type = v;
            continue;
        }
        if (try option(argv, &i, "--emit")) |v| {
            emit = v;
            continue;
        }
        if (try option(argv, &i, "--out-dir")) |v| {
            out_dir = v;
            continue;
        }
        if (try option(argv, &i, "--extern")) |v| {
            const split = std.mem.indexOfScalar(u8, v, '=') orelse return error.UntrackedExtern;
            const path = v[split + 1 ..];
            if (!std.mem.endsWith(u8, path, ".rlib") and !std.mem.endsWith(u8, path, ".rmeta")) return error.ProceduralMacro;
            try addUnique(ctx, &inputs, path);
            continue;
        }
        if (eq(arg, "-L") or std.mem.startsWith(u8, arg, "-L")) {
            const v = if (eq(arg, "-L")) blk: {
                i += 1;
                if (i == argv.len) return error.MissingValue;
                break :blk argv[i];
            } else arg[2..];
            if (!std.mem.startsWith(u8, v, "dependency=")) return error.NativeSearchPath;
            try addUnique(ctx, &search_dirs, v[11..]);
            continue;
        }
        if (eq(arg, "-C") or std.mem.startsWith(u8, arg, "-C")) {
            const v = if (eq(arg, "-C")) blk: {
                i += 1;
                if (i == argv.len) return error.MissingValue;
                break :blk argv[i];
            } else arg[2..];
            const split = std.mem.indexOfScalar(u8, v, '=') orelse v.len;
            const key = v[0..split];
            if (eq(key, "extra-filename")) {
                suffix = v[@min(split + 1, v.len)..];
                continue;
            }
            if (eq(key, "split-debuginfo")) {
                split_debug = v[@min(split + 1, v.len)..];
                continue;
            }
            const safe = [_][]const u8{ "opt-level", "debuginfo", "debug-assertions", "overflow-checks", "panic", "codegen-units", "metadata", "embed-bitcode", "lto", "target-cpu", "target-feature", "strip", "relocation-model", "force-frame-pointers", "symbol-mangling-version" };
            var accepted = false;
            for (safe) |s| if (eq(s, key)) {
                accepted = true;
                break;
            };
            if (!accepted) return error.UntrackedCodegenOption;
            continue;
        }
        const safe = [_][]const u8{ "--edition", "--cap-lints", "--error-format", "--json", "--diagnostic-width", "--color", "--cfg", "--check-cfg", "--remap-path-prefix", "--target" };
        var accepted = false;
        for (safe) |s| if (try option(argv, &i, s)) |v| {
            if (eq(s, "--target") and (std.mem.endsWith(u8, v, ".json") or std.mem.indexOfScalar(u8, v, '/') != null)) return error.CustomTarget;
            accepted = true;
            break;
        };
        if (accepted) continue;
        if (std.mem.startsWith(u8, arg, "-")) return error.UnsupportedRustOption;
        if (source != null or !std.mem.endsWith(u8, arg, ".rs")) return error.UnsupportedSource;
        source = arg;
    }
    const ct = crate_type orelse return error.NoCrateType;
    if (!eq(ct, "rlib") and !eq(ct, "lib")) return error.UnsupportedCrateType;
    const crate = name orelse return error.NoCrateName;
    if (crate.len == 0 or std.mem.indexOfAny(u8, crate, "/\\\n") != null or std.mem.indexOfAny(u8, suffix, "/\\\n") != null) return error.InvalidOutputName;
    const src = try absolute(ctx, source orelse return error.NoSource);
    try addUnique(ctx, &inputs, src);
    const dir = out_dir orelse return error.NoOutputDirectory;
    if (!eq(split_debug, "off") and std.mem.indexOf(u8, emit orelse "", "link") != null) return error.SplitDebugSidecars;
    var outputs: std.ArrayList([]const u8) = .empty;
    var dep_info: ?[]const u8 = null;
    var emissions = std.mem.splitScalar(u8, emit orelse return error.NoEmit, ',');
    while (emissions.next()) |e| {
        const filename = if (eq(e, "dep-info"))
            try std.fmt.allocPrint(ctx.a, "{s}{s}.d", .{ crate, suffix })
        else if (eq(e, "metadata"))
            try std.fmt.allocPrint(ctx.a, "lib{s}{s}.rmeta", .{ crate, suffix })
        else if (eq(e, "link"))
            try std.fmt.allocPrint(ctx.a, "lib{s}{s}.rlib", .{ crate, suffix })
        else
            return error.UnsupportedEmission;
        const path = try absolute(ctx, try std.fs.path.join(ctx.a, &.{ dir, filename }));
        for (outputs.items) |existing| if (eq(existing, path)) return error.DuplicateEmission;
        try outputs.append(ctx.a, path);
        if (eq(e, "dep-info")) dep_info = path;
    }
    if (dep_info == null) return error.NoDependencyInfo;
    for (search_dirs.items) |path| {
        var dir_ = try Dir.cwd().openDir(ctx.io, path, .{ .iterate = true });
        defer dir_.close(ctx.io);
        var iterator = dir_.iterate();
        while (try iterator.next(ctx.io)) |entry| {
            // Reexported proc macros can be loaded transitively from an rlib.
            if (std.mem.endsWith(u8, entry.name, ".so") or std.mem.endsWith(u8, entry.name, ".dylib")) return error.ProceduralMacroSearchPath;
            if (!std.mem.endsWith(u8, entry.name, ".rlib") and !std.mem.endsWith(u8, entry.name, ".rmeta")) continue;
            const full = try absolute(ctx, try std.fs.path.join(ctx.a, &.{ path, entry.name }));
            var own_output = false;
            for (outputs.items) |out| if (eq(out, full)) {
                own_output = true;
                break;
            };
            if (!own_output) try addUnique(ctx, &inputs, full);
        }
    }
    return .{ .source = src, .outputs = outputs.items, .dependencies = inputs.items, .dep_info = dep_info, .library_dirs = search_dirs.items };
}

fn zigPlan(ctx: *cache.Context, argv: []const []const u8) !Plan {
    if (argv.len < 3) return error.NotCompilation;
    if (!eq(argv[1], "build-exe") and !eq(argv[1], "build-obj") and !eq(argv[1], "build-lib")) return error.UnsupportedZigCommand;
    var source: ?[]const u8 = null;
    var output: ?[]const u8 = null;
    var modules: std.ArrayList(Module) = .empty;
    var i: usize = 2;
    while (i < argv.len) : (i += 1) {
        const arg = argv[i];
        if (std.mem.startsWith(u8, arg, "-M")) {
            const split = std.mem.indexOfScalar(u8, arg, '=') orelse return error.NoModuleSource;
            const name = arg[2..split];
            if (name.len == 0 or split + 1 == arg.len) return error.NoModuleSource;
            for (modules.items) |m| if (eq(m.name, name)) return error.DuplicateModule;
            const path = try absolute(ctx, arg[split + 1 ..]);
            try modules.append(ctx.a, .{ .name = name, .source = path });
            if (source == null) source = path;
            continue;
        }
        if (eq(arg, "--dep")) {
            i += 1;
            if (i == argv.len) return error.MissingValue;
            if (std.mem.indexOfScalar(u8, argv[i], '=') != null) return error.ModuleAlias;
            continue;
        }
        if (std.mem.startsWith(u8, arg, "-femit-bin=")) {
            output = arg[11..];
            continue;
        }
        if (eq(arg, "-O") or eq(arg, "-target") or eq(arg, "-mcpu") or eq(arg, "--name")) {
            i += 1;
            if (i == argv.len) return error.MissingValue;
            if (eq(arg, "-target") and (std.mem.indexOf(u8, argv[i], "windows") != null or std.mem.indexOf(u8, argv[i], "uefi") != null)) return error.UnsupportedZigTarget;
            continue;
        }
        if (std.mem.startsWith(u8, arg, "-O") or std.mem.startsWith(u8, arg, "-mcpu=")) continue;
        const safe = [_][]const u8{ "-fstrip", "-fno-strip", "-fsingle-threaded", "-fno-single-threaded", "-fPIC", "-fno-PIC", "-fPIE", "-fno-PIE", "-fomit-frame-pointer", "-fno-omit-frame-pointer", "-fllvm", "-fno-llvm", "-flld", "-fno-lld", "-fno-emit-implib", "-static", "-dynamic" };
        var accepted = false;
        for (safe) |s| if (eq(s, arg)) {
            accepted = true;
            break;
        };
        if (accepted) continue;
        if (std.mem.startsWith(u8, arg, "-")) return error.UnsupportedZigOption;
        if (source != null or !std.mem.endsWith(u8, arg, ".zig")) return error.UnsupportedSource;
        source = arg;
    }
    const src = try absolute(ctx, source orelse return error.NoSource);
    const out = try absolute(ctx, output orelse return error.NoExplicitOutput);
    var has_root = false;
    for (modules.items) |m| if (eq(m.name, "root")) {
        has_root = true;
        break;
    };
    if (!has_root) try modules.append(ctx.a, .{ .name = "root", .source = src });
    // Shared/dynamic libraries have platform-specific extra outputs. Defer them.
    for (argv) |arg| if (eq(arg, "-dynamic")) return error.DynamicLibrary;
    var deps: std.ArrayList([]const u8) = .empty;
    try zigDependencies(ctx, src, modules.items, &deps);
    for (modules.items) |m| try zigDependencies(ctx, m.source, modules.items, &deps);
    if (std.mem.indexOf(u8, src, ctx.root) == 0 or eq(src, out)) return error.OverlappingOutput;
    return .{ .source = src, .outputs = try ctx.a.dupe([]const u8, &.{out}), .dependencies = deps.items };
}

fn within(root: []const u8, path: []const u8) bool {
    return eq(root, path) or (std.mem.startsWith(u8, path, root) and path.len > root.len and path[root.len] == '/');
}

fn zigDependencies(ctx: *cache.Context, source: []const u8, modules: []const Module, deps: *std.ArrayList([]const u8)) anyerror!void {
    for (deps.items) |dep| if (eq(dep, source)) return;
    if (deps.items.len > 10000) return error.TooManyDependencies;
    try addUnique(ctx, deps, source);
    const bytes = try ctx.read(source);
    var tokenizer = std.zig.Tokenizer.init(try ctx.a.dupeSentinel(u8, bytes, 0));
    while (true) {
        const token = tokenizer.next();
        if (token.tag == .eof) break;
        if (token.tag != .builtin) continue;
        const name = bytes[token.loc.start..token.loc.end];
        if (eq(name, "@cImport")) return error.CImport;
        if (!eq(name, "@import") and !eq(name, "@embedFile")) continue;
        if (tokenizer.next().tag != .l_paren) return error.DynamicZigDependency;
        const str = tokenizer.next();
        if (str.tag != .string_literal or tokenizer.next().tag != .r_paren) return error.DynamicZigDependency;
        const value = bytes[str.loc.start + 1 .. str.loc.end - 1];
        if (std.mem.indexOfScalar(u8, value, '\\') != null) return error.EscapedZigDependency;
        if (eq(name, "@import")) {
            var found = false;
            for (modules) |m| if (eq(m.name, value)) {
                try zigDependencies(ctx, m.source, modules, deps);
                found = true;
                break;
            };
            if (found or eq(value, "std") or eq(value, "builtin")) continue;
        }
        const path = try std.fs.path.resolve(ctx.a, &.{ std.fs.path.dirname(source).?, value });
        if (eq(name, "@import")) {
            try zigDependencies(ctx, path, modules, deps);
        } else {
            try addUnique(ctx, deps, path);
        }
    }
}

// rustc writes make-style dep-info. Parse all prerequisite lines, honoring
// escaped whitespace, escaped backslashes and continued physical lines.
pub fn parseDepInfo(a: std.mem.Allocator, bytes: []const u8) ![]const []const u8 {
    var result: std.ArrayList([]const u8) = .empty;
    var token: std.ArrayList(u8) = .empty;
    var prerequisites = false;
    var i: usize = 0;
    while (i < bytes.len) : (i += 1) {
        const ch = bytes[i];
        if (ch == '\\' and i + 1 < bytes.len) {
            i += 1;
            if (bytes[i] == '\n') continue;
            if (prerequisites) try token.append(a, bytes[i]);
            continue;
        }
        if (ch == '\n' or ch == '\r' or (prerequisites and (ch == ' ' or ch == '\t'))) {
            if (token.items.len > 0) {
                try result.append(a, try a.dupe(u8, token.items));
                token.clearRetainingCapacity();
            }
            if (ch == '\n') prerequisites = false;
            continue;
        }
        if (!prerequisites) {
            if (ch == ':' and i + 1 < bytes.len and (bytes[i + 1] == ' ' or bytes[i + 1] == '\t')) prerequisites = true;
            continue;
        }
        try token.append(a, ch);
    }
    if (token.items.len > 0) try result.append(a, try a.dupe(u8, token.items));
    return result.items;
}

fn dependencyRecords(ctx: *cache.Context, paths: []const []const u8) ![]const cache.Dependency {
    var deps: std.ArrayList(cache.Dependency) = .empty;
    for (paths) |path| try deps.append(ctx.a, .{ .path = path, .hash = try ctx.digest(path) });
    return deps.items;
}

fn hiddenNativeLink(bytes: []const u8) bool {
    var offset: usize = 0;
    while (std.mem.indexOfPos(u8, bytes, offset, "link")) |pos| {
        offset = pos + 4;
        if (pos > 0 and (std.ascii.isAlphanumeric(bytes[pos - 1]) or bytes[pos - 1] == '_')) continue;
        var i = offset;
        while (i < bytes.len) {
            if (std.ascii.isWhitespace(bytes[i])) {
                i += 1;
                continue;
            }
            if (i + 1 < bytes.len and bytes[i] == '/' and bytes[i + 1] == '/') {
                i = std.mem.indexOfScalarPos(u8, bytes, i, '\n') orelse bytes.len;
                continue;
            }
            if (i + 1 < bytes.len and bytes[i] == '/' and bytes[i + 1] == '*') {
                i += 2;
                var depth: usize = 1;
                while (i + 1 < bytes.len and depth > 0) {
                    if (bytes[i] == '/' and bytes[i + 1] == '*') {
                        depth += 1;
                        i += 2;
                    } else if (bytes[i] == '*' and bytes[i + 1] == '/') {
                        depth -= 1;
                        i += 2;
                    } else i += 1;
                }
                continue;
            }
            break;
        }
        // Conservative: this may also decline a user function named link.
        if (i < bytes.len and bytes[i] == '(') return true;
    }
    return false;
}

fn keyFor(ctx: *cache.Context, kind: Kind, argv: []const []const u8) ![]const u8 {
    var hash = cache.Hash.init(.{});
    cache.field(&hash, "nanocompile-v5");
    cache.field(&hash, @tagName(kind));
    cache.field(&hash, ctx.cwd);
    const host = std.zig.system.resolveTargetQuery(ctx.io, .{}) catch |err| {
        ctx.trace(try std.fmt.allocPrint(ctx.a, "host detection failed ({s})", .{@errorName(err)}));
        return err;
    };
    cache.field(&hash, @tagName(host.cpu.arch));
    cache.field(&hash, host.cpu.model.name);
    cache.field(&hash, std.mem.asBytes(&host.cpu.features.ints));
    cache.field(&hash, try std.fmt.allocPrint(ctx.a, "{any}", .{host.os}));
    for (argv) |arg| cache.field(&hash, arg);
    cache.field(&hash, try identity.fingerprint(ctx, kind == .zig, argv[0]));
    const keys = try ctx.a.dupe([]const u8, ctx.env.keys());
    std.mem.sort([]const u8, keys, {}, less);
    for (keys) |key| {
        cache.field(&hash, key);
        cache.field(&hash, ctx.env.get(key).?);
    }
    return cache.finish(ctx.a, &hash);
}

fn less(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.order(u8, a, b) == .lt;
}

fn exitCode(term: std.process.Child.Term) u8 {
    return switch (term) {
        .exited => |code| code,
        .signal => |signal| @intCast(@min(255, 128 + @as(u32, @backingInt(signal)))),
        else => 1,
    };
}

fn bypass(ctx: *cache.Context, argv: []const []const u8, reason: []const u8) !u8 {
    ctx.trace(reason);
    ctx.event("bypass");
    var child = try std.process.spawn(ctx.io, .{ .argv = argv, .environ_map = ctx.env });
    return exitCode(try child.wait(ctx.io));
}

pub fn execute(ctx: *cache.Context, kind: Kind, argv: []const []const u8) !u8 {
    if (ctx.env.get("NANOCOMPILE_DISABLE")) |v| if (eq(v, "1")) return bypass(ctx, argv, "bypass: disabled");
    const plan = (if (kind == .rust) rustPlan(ctx, argv) else zigPlan(ctx, argv)) catch |err|
        return bypass(ctx, argv, try std.fmt.allocPrint(ctx.a, "bypass: {s}", .{@errorName(err)}));
    ctx.prepare() catch return bypass(ctx, argv, "bypass: cache unavailable");
    const maintenance = cache.Lock.acquire(ctx, "maintenance", false) catch return bypass(ctx, argv, "bypass: cache lock unavailable");
    defer maintenance.release();
    const key = keyFor(ctx, kind, argv) catch |err| return bypass(ctx, argv, try std.fmt.allocPrint(ctx.a, "bypass: compiler identity unavailable ({s})", .{@errorName(err)}));
    const flight = cache.Lock.acquire(ctx, key, true) catch return bypass(ctx, argv, "bypass: key lock unavailable");
    defer flight.release();
    // Different argument sets can still write the same output. Serialize those
    // destinations too, otherwise one compile could store another's artifact.
    const destinations = try ctx.a.dupe([]const u8, plan.outputs);
    std.mem.sort([]const u8, destinations, {}, less);
    var output_locks: std.ArrayList(cache.Lock) = .empty;
    defer for (output_locks.items) |lock_| lock_.release();
    for (destinations) |destination| {
        var h = cache.Hash.init(.{});
        cache.field(&h, destination);
        const name = try std.fmt.allocPrint(ctx.a, "output-{s}", .{try cache.finish(ctx.a, &h)});
        const lock_ = cache.Lock.acquire(ctx, name, true) catch return bypass(ctx, argv, "bypass: output lock unavailable");
        try output_locks.append(ctx.a, lock_);
    }
    if (cache.restore(ctx, key, plan.outputs) catch false) {
        ctx.trace("hit");
        ctx.event("hit");
        return 0;
    }
    const before = dependencyRecords(ctx, plan.dependencies) catch return bypass(ctx, argv, "bypass: cannot fingerprint inputs");
    var directories: std.ArrayList(cache.Dependency) = .empty;
    for (plan.library_dirs) |dir| try directories.append(ctx.a, .{ .path = dir, .hash = try ctx.directoryDigest(dir, true, plan.outputs), .directory = true, .libraries = true });
    const started = std.Io.Clock.real.now(ctx.io).nanoseconds;
    ctx.trace("miss: compiling");
    const result = try std.process.run(ctx.a, ctx.io, .{ .argv = argv, .environ_map = ctx.env });
    try ctx.out(result.stdout);
    try std.Io.File.stderr().writeStreamingAll(ctx.io, result.stderr);
    const code = exitCode(result.term);
    if (code != 0) {
        ctx.event("failed");
        return code;
    }
    ctx.event("miss");
    save(ctx, key, plan, before, directories.items, started, result) catch |err| ctx.trace(try std.fmt.allocPrint(ctx.a, "uncached: {s}", .{@errorName(err)}));
    return 0;
}

fn save(ctx: *cache.Context, key: []const u8, plan: Plan, before: []const cache.Dependency, directories: []const cache.Dependency, started: i96, result: std.process.RunResult) !void {
    for (before) |dep| if (!eq(try ctx.digest(dep.path), dep.hash)) return error.InputChangedDuringCompilation;
    var paths: std.ArrayList([]const u8) = .empty;
    for (plan.dependencies) |path| try addUnique(ctx, &paths, path);
    if (plan.dep_info) |path| {
        const bytes = try ctx.read(path);
        for (try parseDepInfo(ctx.a, bytes)) |dep| try addUnique(ctx, &paths, dep);
    }
    // Outputs cannot be inputs, otherwise the next run could self-invalidate.
    for (paths.items) |dep| for (plan.outputs) |out| if (eq(dep, out)) return error.OverlappingOutput;
    var records: std.ArrayList(cache.Dependency) = .empty;
    var dirs: std.ArrayList([]const u8) = .empty;
    for (paths.items) |dep| {
        const st = try Dir.cwd().statFile(ctx.io, dep, .{});
        // Dependencies discovered after rustc finishes must predate its start.
        // ctime also catches writes followed by restoring the old mtime.
        if (st.mtime.nanoseconds >= started or st.ctime.nanoseconds >= started) return error.InputChangedDuringCompilation;
        if (plan.dep_info != null and std.mem.endsWith(u8, dep, ".rs") and hiddenNativeLink(try ctx.read(dep))) return error.HiddenNativeLinkInput;
        try records.append(ctx.a, .{ .path = dep, .hash = try ctx.digest(dep) });
        if (plan.dep_info != null and std.mem.endsWith(u8, dep, ".rs"))
            try addUnique(ctx, &dirs, std.fs.path.dirname(dep).?);
    }
    for (dirs.items) |dir| {
        const st = try Dir.cwd().statFile(ctx.io, dir, .{});
        if (st.mtime.nanoseconds >= started or st.ctime.nanoseconds >= started) return error.DirectoryChangedDuringCompilation;
        try records.append(ctx.a, .{ .path = dir, .hash = try ctx.directoryDigest(dir, false, plan.outputs), .directory = true });
    }
    for (directories) |dep| {
        if (!eq(dep.hash, try ctx.directoryDigest(dep.path, true, plan.outputs))) return error.LibraryDirectoryChangedDuringCompilation;
        try records.append(ctx.a, dep);
    }
    try cache.store(ctx, key, records.items, plan.outputs, result.stdout, result.stderr);
}

test "dep-info handles escaped paths and continuations" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const deps = try parseDepInfo(arena.allocator(), "out.rlib: src/lib.rs path\\ with\\ spaces.rs \\\n other.rs\n\nsrc/lib.rs:\n# env-dep:HELLO=world\n");
    try std.testing.expectEqual(@as(usize, 3), deps.len);
    try std.testing.expectEqualStrings("src/lib.rs", deps[0]);
    try std.testing.expectEqualStrings("path with spaces.rs", deps[1]);
    try std.testing.expectEqualStrings("other.rs", deps[2]);
}

test "native link attributes include comments and cfg_attr forms" {
    try std.testing.expect(hiddenNativeLink("#[link /* comment */ (name=\"native\")] extern {}"));
    try std.testing.expect(hiddenNativeLink("#[cfg_attr(unix, link(name=\"native\"))] extern {}"));
    try std.testing.expect(!hiddenNativeLink("pub fn linking_notes() {} #[link_name=\"symbol\"] extern {}"));
}
