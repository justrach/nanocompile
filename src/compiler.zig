const std = @import("std");
const cache = @import("cache.zig");
const identity = @import("identity.zig");
const rust_dependencies = @import("rust_dependencies.zig");
const builtin = @import("builtin");
const Dir = std.Io.Dir;
pub const Kind = enum { rust, zig };
const Plan = struct {
    source: []const u8,
    outputs: []const []const u8,
    dependencies: []const []const u8,
    dep_info: ?[]const u8 = null,
    library_dirs: []const []const u8 = &.{},
    native_dirs: []const []const u8 = &.{},
    configuration: ?cache.Dependency = null,
    producer: bool = false,
    producer_dylib: bool = false,
    linked_output: ?[]const u8 = null,
    out_dir: ?[]const u8 = null,
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
    var native_dirs: std.ArrayList([]const u8) = .empty;
    var configuration: ?cache.Dependency = null;
    var static_libraries: std.ArrayList([]const u8) = .empty;
    var builtin_macro = false;
    var debug_info: []const u8 = "0";
    var producer_unsafe_codegen = false;
    var target: ?[]const u8 = null;
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
            if (eq(v, "proc_macro") and eq(ctx.env.get("NANOCOMPILE_PROC_MACRO_PRODUCERS") orelse "", "1")) {
                builtin_macro = true;
                continue;
            }
            const split = std.mem.indexOfScalar(u8, v, '=') orelse return error.UntrackedExtern;
            const path = v[split + 1 ..];
            if (!std.mem.endsWith(u8, path, ".rlib") and !std.mem.endsWith(u8, path, ".rmeta")) {
                if (!rust_dependencies.reportedMacros(ctx) or (!std.mem.endsWith(u8, path, ".dylib") and !std.mem.endsWith(u8, path, ".so"))) return error.ProceduralMacro;
            }
            try addUnique(ctx, &inputs, path);
            continue;
        }
        if (eq(arg, "-L") or std.mem.startsWith(u8, arg, "-L")) {
            const v = if (eq(arg, "-L")) blk: {
                i += 1;
                if (i == argv.len) return error.MissingValue;
                break :blk argv[i];
            } else arg[2..];
            if (std.mem.startsWith(u8, v, "dependency=")) {
                try addUnique(ctx, &search_dirs, v[11..]);
            } else if (std.mem.startsWith(u8, v, "native=")) {
                try addUnique(ctx, &native_dirs, v[7..]);
            } else return error.NativeSearchPath;
            continue;
        }
        if ((try option(argv, &i, "-l")) orelse (if (std.mem.startsWith(u8, arg, "-l")) arg[2..] else null)) |v| {
            if (!std.mem.startsWith(u8, v, "static=")) return error.UnsupportedNativeLibrary;
            const library = v[7..];
            if (library.len == 0) return error.UnsupportedNativeLibrary;
            for (library) |ch| if (!std.ascii.isAlphanumeric(ch) and ch != '_' and ch != '-') return error.UnsupportedNativeLibrary;
            try static_libraries.append(ctx.a, library);
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
            if (eq(key, "debuginfo")) debug_info = v[@min(split + 1, v.len)..];
            for ([_][]const u8{ "lto", "linker-plugin-lto", "relocation-model" }) |unsupported| {
                if (eq(key, unsupported)) producer_unsafe_codegen = true;
            }
            if (eq(key, "extra-filename")) {
                suffix = v[@min(split + 1, v.len)..];
                continue;
            }
            if (eq(key, "split-debuginfo")) {
                split_debug = v[@min(split + 1, v.len)..];
                continue;
            }
            const safe = [_][]const u8{ "opt-level", "debuginfo", "debug-assertions", "overflow-checks", "panic", "codegen-units", "metadata", "embed-bitcode", "lto", "linker-plugin-lto", "prefer-dynamic", "target-cpu", "target-feature", "strip", "relocation-model", "force-frame-pointers", "symbol-mangling-version" };
            var accepted = false;
            for (safe) |s| if (eq(s, key)) {
                accepted = true;
                break;
            };
            if (!accepted) {
                ctx.trace(try std.fmt.allocPrint(ctx.a, "unsupported Rust codegen option: {s}", .{key}));
                return error.UntrackedCodegenOption;
            }
            continue;
        }
        const safe = [_][]const u8{ "--edition", "--cap-lints", "--error-format", "--json", "--diagnostic-width", "--color", "--cfg", "--check-cfg", "--remap-path-prefix", "--target", "--allow", "--warn", "--deny", "--forbid", "--force-warn", "-A", "-W", "-D", "-F" };
        var accepted = false;
        for (safe) |s| if (try option(argv, &i, s)) |v| {
            if (eq(s, "--target")) target = v;
            if (eq(s, "--target") and (std.mem.endsWith(u8, v, ".json") or std.mem.indexOfScalar(u8, v, '/') != null)) return error.CustomTarget;
            accepted = true;
            break;
        };
        if (accepted) continue;
        if (std.mem.startsWith(u8, arg, "-")) {
            ctx.trace(try std.fmt.allocPrint(ctx.a, "unsupported Rust option: {s}", .{arg}));
            return error.UnsupportedRustOption;
        }
        if (source != null or !std.mem.endsWith(u8, arg, ".rs")) return error.UnsupportedSource;
        source = arg;
    }
    const ct = crate_type orelse return error.NoCrateType;
    const producer_dylib = eq(ct, "proc-macro") and eq(ctx.env.get("NANOCOMPILE_PROC_MACRO_PRODUCERS") orelse "", "1");
    const executable = eq(ct, "bin") and eq(ctx.env.get("NANOCOMPILE_EXECUTABLE_PRODUCERS") orelse "", "1");
    const producer = producer_dylib or executable;
    if (!producer and !eq(ct, "rlib") and !eq(ct, "lib")) return error.UnsupportedCrateType;
    if (!producer_dylib and builtin_macro) return error.UntrackedExtern;
    if (producer and (builtin.os.tag != .macos or !eq(debug_info, "0") or producer_unsafe_codegen or target != null)) return error.UnsupportedProducerConfiguration;
    if (static_libraries.items.len != 0 and target != null) return error.UnsupportedNativeTarget;
    // Plain static libraries bundle archive members into the rlib. Require a
    // candidate in explicit native search paths; the complete directory/file
    // snapshot guards content changes and newly preferred candidates.
    for (static_libraries.items) |library| {
        const filename = try std.fmt.allocPrint(ctx.a, "lib{s}.a", .{library});
        var found = false;
        for (native_dirs.items) |path| {
            const candidate = try std.fs.path.join(ctx.a, &.{ path, filename });
            const st = Dir.cwd().statFile(ctx.io, candidate, .{}) catch |err| switch (err) {
                error.FileNotFound, error.NotDir => continue,
                else => return err,
            };
            if (st.kind != .file) return error.UnsupportedNativeLibrary;
            found = true;
            break;
        }
        if (!found) return error.UntrackedNativeLibrary;
    }
    const crate = name orelse return error.NoCrateName;
    if (crate.len == 0 or std.mem.indexOfAny(u8, crate, "/\\\n") != null or std.mem.indexOfAny(u8, suffix, "/\\\n") != null) return error.InvalidOutputName;
    const src = try absolute(ctx, source orelse return error.NoSource);
    try addUnique(ctx, &inputs, src);
    // An explicit global declaration applies to every consumer too, including
    // files a proc macro reads only while expanding another package.
    if (ctx.env.get("NANOCOMPILE_EXTRA_INPUTS_FILE")) |declaration| {
        const config = try absolute(ctx, declaration);
        try addUnique(ctx, &inputs, config);
        const bytes = try ctx.read(config);
        var config_hash = cache.Hash.init(.{});
        config_hash.update(bytes);
        configuration = .{ .path = config, .hash = try cache.finish(ctx.a, &config_hash) };
        const parsed = try std.json.parseFromSlice([]const []const u8, ctx.a, bytes, .{ .allocate = .alloc_always });
        for (parsed.value) |input| try addUnique(ctx, &inputs, try std.fs.path.resolve(ctx.a, &.{ std.fs.path.dirname(config).?, input }));
    }
    const dir = out_dir orelse return error.NoOutputDirectory;
    if (!eq(split_debug, "off") and std.mem.indexOf(u8, emit orelse "", "link") != null) return error.SplitDebugSidecars;
    var outputs: std.ArrayList([]const u8) = .empty;
    var dep_info: ?[]const u8 = null;
    var linked_output: ?[]const u8 = null;
    var emissions = std.mem.splitScalar(u8, emit orelse return error.NoEmit, ',');
    while (emissions.next()) |e| {
        if (executable and eq(e, "metadata")) return error.UnsupportedEmission;
        const filename = if (eq(e, "dep-info"))
            try std.fmt.allocPrint(ctx.a, "{s}{s}.d", .{ crate, suffix })
        else if (eq(e, "metadata"))
            try std.fmt.allocPrint(ctx.a, "lib{s}{s}.rmeta", .{ crate, suffix })
        else if (eq(e, "link"))
            if (executable) try std.fmt.allocPrint(ctx.a, "{s}{s}", .{ crate, suffix }) else try std.fmt.allocPrint(ctx.a, "lib{s}{s}{s}", .{ crate, suffix, if (producer_dylib) ".dylib" else ".rlib" })
        else
            return error.UnsupportedEmission;
        const path = try absolute(ctx, try std.fs.path.join(ctx.a, &.{ dir, filename }));
        for (outputs.items) |existing| if (eq(existing, path)) return error.DuplicateEmission;
        try outputs.append(ctx.a, path);
        if (eq(e, "dep-info")) dep_info = path;
        if (eq(e, "link")) linked_output = path;
    }
    if (dep_info == null) return error.NoDependencyInfo;
    if (producer and (std.mem.indexOfAny(u8, dir, "\r\n\t\"\\") != null or std.mem.indexOfAny(u8, ctx.root, "\r\n\t\"\\") != null or std.mem.indexOf(u8, dir, "//") != null)) return error.UnsupportedProducerPath;
    return .{ .source = src, .outputs = outputs.items, .dependencies = inputs.items, .dep_info = dep_info, .library_dirs = search_dirs.items, .native_dirs = native_dirs.items, .configuration = configuration, .producer = producer, .producer_dylib = producer_dylib, .linked_output = linked_output, .out_dir = dir };
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

// Skip Rust whitespace and nested comments. Token text in comments cannot be
// a link attribute; retain conservative handling of other ambiguous tokens.
fn skipRustTrivia(bytes: []const u8, start: usize) usize {
    var i = start;
    while (i < bytes.len) {
        if (std.ascii.isWhitespace(bytes[i])) {
            i += 1;
        } else if (std.mem.startsWith(u8, bytes[i..], "//")) {
            i = std.mem.indexOfScalarPos(u8, bytes, i, '\n') orelse bytes.len;
        } else if (std.mem.startsWith(u8, bytes[i..], "/*")) {
            i += 2;
            var depth: usize = 1;
            while (i < bytes.len and depth > 0) {
                if (std.mem.startsWith(u8, bytes[i..], "/*")) {
                    depth += 1;
                    i += 2;
                } else if (std.mem.startsWith(u8, bytes[i..], "*/")) {
                    depth -= 1;
                    i += 2;
                } else i += 1;
            }
        } else break;
    }
    return i;
}

fn rustLiteralEnd(bytes: []const u8, start: usize) ?usize {
    var i = start;
    if (bytes[i] == 'b' or bytes[i] == 'c') i += 1;
    if (i == bytes.len) return null;
    if (bytes[i] == 'r') {
        i += 1;
        const hashes_start = i;
        while (i < bytes.len and bytes[i] == '#') : (i += 1) {}
        const hashes = i - hashes_start;
        if (i == bytes.len or bytes[i] != '"') return null;
        i += 1;
        while (i < bytes.len) : (i += 1) {
            if (bytes[i] != '"') continue;
            var end = i + 1;
            while (end < bytes.len and end - i - 1 < hashes and bytes[end] == '#') : (end += 1) {}
            if (end - i - 1 == hashes) return end;
        }
        return bytes.len;
    }
    if (bytes[i] == '"') {
        i += 1;
        while (i < bytes.len) {
            if (bytes[i] == '"') return i + 1;
            i += if (bytes[i] == '\\' and i + 1 < bytes.len) @as(usize, 2) else 1;
        }
        return bytes.len;
    }
    if (bytes[i] != '\'' or i + 1 == bytes.len) return null;
    // A lifetime is not a character literal. Only consume a complete single
    // character (including escapes), avoiding quotes inside character tokens.
    i += 1;
    if (bytes[i] == '\\') {
        i += 1;
        if (i == bytes.len) return null;
        if (bytes[i] == 'u' and i + 1 < bytes.len and bytes[i + 1] == '{') {
            i = (std.mem.indexOfScalarPos(u8, bytes, i + 2, '}') orelse return null) + 1;
        } else if (bytes[i] == 'x') {
            i += 3;
        } else i += 1;
    } else i += std.unicode.utf8ByteSequenceLength(bytes[i]) catch return null;
    return if (i < bytes.len and bytes[i] == '\'') i + 1 else null;
}

fn hiddenNativeLink(bytes: []const u8) bool {
    var i: usize = 0;
    var previous: []const u8 = "";
    while (true) {
        i = skipRustTrivia(bytes, i);
        if (i == bytes.len) break;
        if (rustLiteralEnd(bytes, i)) |end| {
            i = end;
            previous = "literal";
            continue;
        }
        const start = i;
        if (std.ascii.isAlphanumeric(bytes[i]) or bytes[i] == '_') {
            i += 1;
            while (i < bytes.len and (std.ascii.isAlphanumeric(bytes[i]) or bytes[i] == '_')) : (i += 1) {}
        } else i += 1;
        const token = bytes[start..i];
        if (eq(token, "link") and !eq(previous, "fn") and !eq(previous, ".") and !eq(previous, ":")) {
            const next = skipRustTrivia(bytes, i);
            if (next < bytes.len and bytes[next] == '(') return true;
        }
        previous = token;
    }
    return false;
}

fn keyFor(ctx: *cache.Context, kind: Kind, argv: []const []const u8) ![]const u8 {
    var hash = cache.Hash.init(.{});
    cache.field(&hash, "nanocompile-v8");
    cache.field(&hash, @tagName(kind));
    if (kind == .rust) cache.field(&hash, "native-metadata-eligibility-v1");
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
    const toolchain = try identity.fingerprint(ctx, kind == .zig, argv[0]);
    ctx.compiler_identity = toolchain;
    cache.field(&hash, toolchain);
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

fn replacePath(ctx: *cache.Context, bytes: []const u8, old: []const u8, new: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    var cursor: usize = 0;
    while (std.mem.indexOfPos(u8, bytes, cursor, old)) |at| {
        try out.appendSlice(ctx.a, bytes[cursor..at]);
        try out.appendSlice(ctx.a, new);
        cursor = at + old.len;
    }
    try out.appendSlice(ctx.a, bytes[cursor..]);
    return out.items;
}

fn executeProducer(ctx: *cache.Context, plan: Plan, argv: []const []const u8) !u8 {
    const native_identity = @import("native_identity.zig");
    const observer = @import("link_observer.zig");
    ctx.prepare() catch return bypass(ctx, argv, "bypass: cache unavailable");
    const maintenance = cache.Lock.acquire(ctx, "maintenance", false) catch return bypass(ctx, argv, "bypass: producer cache lock unavailable");
    defer maintenance.release();
    const driver = identity.selectedExecutable(ctx, "cc") catch return bypass(ctx, argv, "bypass: producer driver unavailable");
    const selected = native_identity.apple(ctx, driver) catch return bypass(ctx, argv, "bypass: producer driver selection unsupported");
    const binary = std.process.executablePathAlloc(ctx.io, ctx.a) catch return bypass(ctx, argv, "bypass: producer observer unavailable");
    const base_key = keyFor(ctx, .rust, argv) catch return bypass(ctx, argv, "bypass: producer compiler identity unavailable");
    const compiler_epoch = ctx.compiler_epoch orelse return bypass(ctx, argv, "bypass: producer compiler state unavailable");
    const binary_hash = ctx.digest(binary) catch return bypass(ctx, argv, "bypass: producer observer cannot be fingerprinted");
    var h = cache.Hash.init(.{});
    cache.field(&h, "nanocompile-experimental-producer-v1");
    cache.field(&h, base_key);
    cache.field(&h, compiler_epoch);
    cache.field(&h, selected.hash);
    cache.field(&h, binary_hash);
    const key = try cache.finish(ctx.a, &h);
    const flight = cache.Lock.acquire(ctx, key, true) catch return bypass(ctx, argv, "bypass: producer key lock unavailable");
    defer flight.release();
    const destinations = try ctx.a.dupe([]const u8, plan.outputs);
    std.mem.sort([]const u8, destinations, {}, less);
    var locks: std.ArrayList(cache.Lock) = .empty;
    defer for (locks.items) |lock| lock.release();
    for (destinations) |path| {
        var hash = cache.Hash.init(.{});
        cache.field(&hash, path);
        const lock = cache.Lock.acquire(ctx, try std.fmt.allocPrint(ctx.a, "output-{s}", .{try cache.finish(ctx.a, &hash)}), true) catch return bypass(ctx, argv, "bypass: producer output lock unavailable");
        try locks.append(ctx.a, lock);
    }
    if (plan.configuration) |config| {
        if (!eq(config.hash, ctx.digest(config.path) catch return bypass(ctx, argv, "bypass: cannot read producer declaration")))
            return bypass(ctx, argv, "bypass: producer input declaration changed");
    }
    if (cache.restore(ctx, key, plan.outputs) catch false) {
        ctx.trace(if (plan.producer_dylib) "hit: proc-macro producer" else "hit: executable producer");
        ctx.event("hit");
        return 0;
    }
    var before: std.ArrayList(cache.Dependency) = .empty;
    try before.appendSlice(ctx.a, dependencyRecords(ctx, plan.dependencies) catch return bypass(ctx, argv, "bypass: producer inputs unavailable"));
    try before.appendSlice(ctx.a, rust_dependencies.nativeSnapshot(ctx, plan.native_dirs) catch return bypass(ctx, argv, "bypass: producer native search unsupported"));
    const directories = rust_dependencies.snapshot(ctx, plan.library_dirs, plan.outputs) catch return bypass(ctx, argv, "bypass: producer dependency lookup unavailable");
    const job = @import("producer_job.zig").Job.create(ctx) catch return bypass(ctx, argv, "bypass: producer staging unavailable");
    defer job.cleanup(ctx) catch {};
    const original = plan.linked_output orelse return bypass(ctx, argv, "bypass: producer needs link output");
    const output = try std.fs.path.join(ctx.a, &.{ job.out, std.fs.path.basename(original) });
    const config: observer.Config = .{ .driver = driver, .format = .darwin, .report = try std.fs.path.join(ctx.a, &.{ job.root, "link.deps" }), .invocation = try std.fs.path.join(ctx.a, &.{ job.root, "invocation" }), .capture_id = job.capture_id, .ownership = .{ .out = job.out, .canonical_out = job.canonical_out, .output = output } };
    const linker = job.installObserver(ctx, binary, try std.json.Stringify.valueAlloc(ctx.a, config, .{})) catch return bypass(ctx, argv, "bypass: producer observer installation unavailable");
    var command: std.ArrayList([]const u8) = .empty;
    var i: usize = 0;
    while (i < argv.len) : (i += 1) {
        if (eq(argv[i], "--out-dir")) {
            try command.appendSlice(ctx.a, &.{ "--out-dir", job.out });
            i += 1;
        } else if (std.mem.startsWith(u8, argv[i], "--out-dir=")) {
            try command.append(ctx.a, try std.fmt.allocPrint(ctx.a, "--out-dir={s}", .{job.out}));
        } else try command.append(ctx.a, argv[i]);
    }
    try command.appendSlice(ctx.a, &.{ "-C", try std.fmt.allocPrint(ctx.a, "linker={s}", .{linker}) });
    if (plan.producer_dylib) {
        const install_name = try std.fs.path.join(ctx.a, &.{ plan.out_dir.?, std.fs.path.basename(original) });
        for ([_][]const u8{ "-Xlinker", "-install_name", "-Xlinker", install_name }) |arg|
            try command.appendSlice(ctx.a, &.{ "-C", try std.fmt.allocPrint(ctx.a, "link-arg={s}", .{arg}) });
    }
    const started = std.Io.Clock.real.now(ctx.io).nanoseconds;
    ctx.trace(if (plan.producer_dylib) "miss: compiling proc-macro producer" else "miss: compiling executable producer");
    var result = try std.process.run(ctx.a, ctx.io, .{ .argv = command.items, .environ_map = ctx.env });
    result.stdout = try replacePath(ctx, result.stdout, job.out, plan.out_dir.?);
    result.stderr = try replacePath(ctx, result.stderr, job.out, plan.out_dir.?);
    result.stderr = try replacePath(ctx, result.stderr, linker, "cc");
    for (plan.outputs) |path| {
        const private = try std.fs.path.join(ctx.a, &.{ job.out, std.fs.path.basename(path) });
        const st = Dir.cwd().statFile(ctx.io, private, .{}) catch |err| switch (err) {
            error.FileNotFound => continue,
            else => return err,
        };
        if (plan.dep_info != null and eq(path, plan.dep_info.?))
            try ctx.atomic(private, try replacePath(ctx, try ctx.read(private), job.out, plan.out_dir.?));
        try cache.materialize(ctx, private, path, @intCast(st.permissions.toMode()));
    }
    try ctx.out(result.stdout);
    try std.Io.File.stderr().writeStreamingAll(ctx.io, result.stderr);
    const code = exitCode(result.term);
    if (code != 0) {
        ctx.event("failed");
        return code;
    }
    ctx.event("miss");
    const linked = @import("producer_dependencies.zig").collect(ctx, config, ctx.read(config.invocation) catch return 0, started) catch |err| {
        ctx.trace(try std.fmt.allocPrint(ctx.a, "uncached producer inputs: {s}", .{@errorName(err)}));
        return 0;
    };
    const after = native_identity.apple(ctx, driver) catch return 0;
    if (!eq(selected.hash, after.hash)) {
        ctx.trace("uncached: producer tool selection changed");
        return 0;
    }
    if (!eq(base_key, keyFor(ctx, .rust, argv) catch return 0) or !eq(binary_hash, try ctx.digest(binary))) return 0;
    if (!eq(compiler_epoch, ctx.compiler_epoch orelse return 0)) return 0;
    for (selected.files) |path| {
        const st = try Dir.cwd().statFile(ctx.io, path, .{});
        if (st.mtime.nanoseconds >= started or st.ctime.nanoseconds >= started) return 0;
    }
    const observer_stat = try Dir.cwd().statFile(ctx.io, binary, .{});
    if (observer_stat.mtime.nanoseconds >= started or observer_stat.ctime.nanoseconds >= started) return 0;
    save(ctx, key, plan, argv, before.items, directories, started, result, linked) catch |err|
        ctx.trace(try std.fmt.allocPrint(ctx.a, "uncached producer: {s}", .{@errorName(err)}));
    return 0;
}

pub fn execute(ctx: *cache.Context, kind: Kind, argv: []const []const u8) !u8 {
    if (ctx.env.get("NANOCOMPILE_DISABLE")) |v| if (eq(v, "1")) return bypass(ctx, argv, "bypass: disabled");
    const plan = (if (kind == .rust) rustPlan(ctx, argv) else zigPlan(ctx, argv)) catch |err|
        return bypass(ctx, argv, try std.fmt.allocPrint(ctx.a, "bypass: {s}", .{@errorName(err)}));
    if (plan.producer) return executeProducer(ctx, plan, argv);
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
    if (plan.configuration) |config| {
        const current = ctx.digest(config.path) catch return bypass(ctx, argv, "bypass: cannot read extra input declaration");
        if (!eq(config.hash, current)) return bypass(ctx, argv, "bypass: extra input declaration changed");
    }
    if (cache.restore(ctx, key, plan.outputs) catch false) {
        ctx.trace("hit");
        ctx.event("hit");
        return 0;
    }
    var before: std.ArrayList(cache.Dependency) = .empty;
    try before.appendSlice(ctx.a, dependencyRecords(ctx, plan.dependencies) catch return bypass(ctx, argv, "bypass: cannot fingerprint inputs"));
    const native = rust_dependencies.nativeSnapshot(ctx, plan.native_dirs) catch |err|
        return bypass(ctx, argv, try std.fmt.allocPrint(ctx.a, "bypass: native inputs unavailable ({s})", .{@errorName(err)}));
    try before.appendSlice(ctx.a, native);
    const directories = rust_dependencies.snapshot(ctx, plan.library_dirs, plan.outputs) catch return bypass(ctx, argv, "bypass: cannot enumerate dependency directories");
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
    save(ctx, key, plan, argv, before.items, directories, started, result, &.{}) catch |err| ctx.trace(try std.fmt.allocPrint(ctx.a, "uncached: {s}", .{@errorName(err)}));
    return 0;
}

fn save(ctx: *cache.Context, key: []const u8, plan: Plan, argv: []const []const u8, before: []const cache.Dependency, directories: []const rust_dependencies.Directory, started: i96, result: std.process.RunResult, linker: []const cache.Dependency) !void {
    for (before) |dep| if (!dep.directory) {
        for (plan.outputs) |out| if (eq(dep.path, out)) return error.OverlappingOutput;
    };
    // Fresh post-compilation hashes remain separate from the pre-compilation
    // snapshot. Reuse them only while constructing this successful entry.
    var validated: std.StringHashMapUnmanaged(cache.CheckedDigest) = .empty;
    defer validated.deinit(ctx.a);
    for (before) |dep| {
        if (dep.all_members) {
            if (!eq(try ctx.nativeDirectoryDigest(dep.path), dep.hash)) return error.InputChangedDuringCompilation;
        } else {
            const digest = try ctx.checkedDigest(dep.path);
            if (!eq(digest.hash, dep.hash)) return error.InputChangedDuringCompilation;
            if (!dep.directory) try validated.put(ctx.a, dep.path, digest);
        }
    }
    var paths: std.ArrayList([]const u8) = .empty;
    for (plan.dependencies) |path| try addUnique(ctx, &paths, path);
    if (plan.dep_info) |path| {
        const bytes = try ctx.read(path);
        for (try parseDepInfo(ctx.a, bytes)) |dep| try addUnique(ctx, &paths, dep);
    }
    // Outputs cannot be inputs, otherwise the next run could self-invalidate.
    for (paths.items) |dep| for (plan.outputs) |out| if (eq(dep, out)) return error.OverlappingOutput;
    var records: std.ArrayList(cache.Dependency) = .empty;
    // Retain all native files and full top-level directory membership; source
    // and Rust graph records below continue using their more specific guards.
    for (before) |dep| {
        var native_input = dep.all_members;
        if (!native_input) for (plan.native_dirs) |dir| {
            if (eq(std.fs.path.dirname(dep.path) orelse "", dir)) {
                native_input = true;
                break;
            }
        };
        if (!native_input) continue;
        const st = try Dir.cwd().statFile(ctx.io, dep.path, .{});
        if (st.mtime.nanoseconds >= started or st.ctime.nanoseconds >= started) return error.InputChangedDuringCompilation;
        try records.append(ctx.a, dep);
    }
    var hidden_native = false;
    var dirs: std.ArrayList([]const u8) = .empty;
    for (paths.items) |dep| {
        const st = try Dir.cwd().statFile(ctx.io, dep, .{});
        // Dependencies discovered after rustc finishes must predate its start.
        // ctime also catches writes followed by restoring the old mtime.
        if (st.mtime.nanoseconds >= started or st.ctime.nanoseconds >= started) return error.InputChangedDuringCompilation;
        if (!plan.producer and plan.dep_info != null and std.mem.endsWith(u8, dep, ".rs") and hiddenNativeLink(try ctx.read(dep))) hidden_native = true;
        const digest = if (validated.get(dep)) |checked| checked else try ctx.checkedDigest(dep);
        if (!cache.sameFileState(st, digest.state)) return error.InputChangedDuringCompilation;
        try validated.put(ctx.a, dep, digest);
        try records.append(ctx.a, .{ .path = dep, .hash = digest.hash });
        if (plan.dep_info != null and std.mem.endsWith(u8, dep, ".rs"))
            try addUnique(ctx, &dirs, std.fs.path.dirname(dep).?);
    }
    for (dirs.items) |dir| {
        const st = try Dir.cwd().statFile(ctx.io, dir, .{});
        if (st.mtime.nanoseconds >= started or st.ctime.nanoseconds >= started) return error.DirectoryChangedDuringCompilation;
        try records.append(ctx.a, .{ .path = dir, .hash = try ctx.directoryDigest(dir, false, plan.outputs), .directory = true });
    }
    if (!plan.producer and plan.dep_info != null and (directories.len != 0 or hidden_native))
        try rust_dependencies.collect(ctx, argv, plan.outputs, directories, started, &records, true, &validated, hidden_native);
    if (plan.producer) {
        for (plan.dependencies) |path| if (std.mem.endsWith(u8, path, ".rlib") or std.mem.endsWith(u8, path, ".rmeta")) {
            try rust_dependencies.collect(ctx, argv, &.{path}, directories, started, &records, false, &validated, false);
        };
        try records.appendSlice(ctx.a, linker);
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
    try std.testing.expect(!hiddenNativeLink("/// symbolic link (parent)\nfn /* nested /* comment */ */ link(x: u32) {} self.link(1); queue::link(2);"));
    try std.testing.expect(hiddenNativeLink("macro_use!(link(name=\"native\"));"));
    try std.testing.expect(hiddenNativeLink("/* outer /* inner */ */ #[cfg_attr(unix, link /*nested*/ (name=\"native\"))] extern {}"));
    try std.testing.expect(hiddenNativeLink("const S: &str = r##\"\"/*\"##; #[link(name=\"native\")] extern {}"));
    try std.testing.expect(hiddenNativeLink("const C: char = '\"'; const S: &str=\"/*\"; #[link(name=\"native\")] extern {}"));
    try std.testing.expect(!hiddenNativeLink("const S: &str = \"link(name=foo)\"; pub fn link<'a>(x: &'a str) {}"));
}
