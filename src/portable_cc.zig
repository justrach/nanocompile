//! Opt-in compile-only cache. Live preprocessing and complete dependency bytes
//! enter the key on every lookup; unknown compiler inputs transparently bypass.
const std = @import("std");
const builtin = @import("builtin");
const cache = @import("cache.zig");
const identity = @import("identity.zig");
const compiler = @import("compiler.zig");
const Dir = std.Io.Dir;
extern "c" fn getpid() c_int;

fn code(term: std.process.Child.Term) u8 {
    return switch (term) {
        .exited => |v| v,
        .signal => |v| @intCast(@min(255, 128 + @as(u32, @backingInt(v)))),
        else => 1,
    };
}
fn run(ctx: *cache.Context, argv: []const []const u8) !u8 {
    var child = try std.process.spawn(ctx.io, .{ .argv = argv, .environ_map = ctx.env });
    return code(try child.wait(ctx.io));
}
fn enabled(ctx: *cache.Context, name: []const u8) bool {
    return std.mem.eql(u8, ctx.env.get(name) orelse "", "1");
}
fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}
fn query(ctx: *cache.Context, argv: []const []const u8) ![]const u8 {
    const result = try std.process.run(ctx.a, ctx.io, .{ .argv = argv, .environ_map = ctx.env });
    if (code(result.term) != 0) return error.UnsupportedCompiler;
    return std.mem.trim(u8, result.stdout, "\r\n ");
}
const Job = struct { source: []const u8, output: []const u8, dep: ?[]const u8, cpp: bool, pp: []const []const u8 };
fn job(ctx: *cache.Context, args: []const []const u8, cpp: bool) !Job {
    var source: ?[]const u8 = null;
    var output: ?[]const u8 = null;
    var dep: ?[]const u8 = null;
    var compile = false;
    var dependencies = false;
    var language_cpp = cpp;
    var pp: std.ArrayList([]const u8) = .empty;
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (eq(arg, "-c")) {
            compile = true;
            continue;
        }
        if (eq(arg, "-MD") or eq(arg, "-MMD")) {
            dependencies = true;
            continue;
        }
        if (eq(arg, "-o") or eq(arg, "-MF") or eq(arg, "-MT") or eq(arg, "-MQ")) {
            i += 1;
            if (i >= args.len) return error.UnsupportedFlags;
            if (eq(arg, "-o")) {
                if (output != null) return error.UnsupportedFlags;
                output = args[i];
            }
            if (eq(arg, "-MF")) {
                if (dep != null) return error.UnsupportedFlags;
                dep = args[i];
            }
            continue;
        }
        if (eq(arg, "-I") or eq(arg, "-D") or eq(arg, "-U") or eq(arg, "-isystem") or eq(arg, "-iquote") or eq(arg, "-idirafter") or eq(arg, "-include") or eq(arg, "-isysroot") or eq(arg, "-arch") or eq(arg, "-x")) {
            i += 1;
            if (i >= args.len) return error.UnsupportedFlags;
            if (eq(arg, "-x")) {
                if (!eq(args[i], "c") and !eq(args[i], "c++")) return error.UnsupportedFlags;
                language_cpp = eq(args[i], "c++");
            }
            try pp.appendSlice(ctx.a, &.{ arg, args[i] });
            continue;
        }
        if (!std.mem.startsWith(u8, arg, "-")) {
            if (source != null or std.mem.startsWith(u8, arg, "@")) return error.UnsupportedFlags;
            const ext = std.fs.path.extension(arg);
            if (!eq(ext, ".c") and !eq(ext, ".cc") and !eq(ext, ".cpp") and !eq(ext, ".cxx")) return error.UnsupportedFlags;
            source = arg;
            if (!eq(ext, ".c")) language_cpp = true;
            try pp.append(ctx.a, arg);
            continue;
        }
        // No plugins, modules/PCH, profile files, response files, auxiliary
        // outputs or arbitrary frontend/assembler forwarding in this adapter.
        var accepted = false;
        for ([_][]const u8{ "-O0", "-O1", "-O2", "-O3", "-Os", "-Oz", "-Og", "-Ofast", "-g0", "-w", "-pipe", "-pthread", "-pedantic", "-pedantic-errors", "-nostdinc", "-nostdinc++", "-fPIC", "-fpic", "-fPIE", "-fpie", "-fno-exceptions", "-fno-rtti", "-ffunction-sections", "-fdata-sections", "-fno-common", "-fcommon", "-fomit-frame-pointer", "-fno-omit-frame-pointer", "-fvisibility=hidden", "-fvisibility=default", "-fvisibility-inlines-hidden", "-fstrict-aliasing", "-fno-strict-aliasing", "-fwrapv", "-fno-builtin", "-fsigned-char", "-funsigned-char", "-ffast-math", "-fno-fast-math" }) |known| if (eq(arg, known)) {
            accepted = true;
            break;
        };
        for ([_][]const u8{ "-I", "-D", "-U", "-std=", "-march=", "-mcpu=", "-mtune=", "-mmacosx-version-min=" }) |prefix| if (std.mem.startsWith(u8, arg, prefix) and arg.len > prefix.len) {
            accepted = true;
            break;
        };
        if (std.mem.startsWith(u8, arg, "-W") and !std.mem.startsWith(u8, arg, "-Wa,") and !std.mem.startsWith(u8, arg, "-Wp,") and !std.mem.startsWith(u8, arg, "-Wl,")) accepted = true;
        if (!accepted) return error.UnsupportedFlags;
        try pp.append(ctx.a, arg);
    }
    if (!compile or source == null or output == null or (dependencies and dep == null) or (!dependencies and dep != null)) return error.UnsupportedFlags;
    const src = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, source.? });
    const out = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, output.? });
    const dep_out = if (dep) |path| try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, path }) else null;
    if (eq(src, out) or (dep_out != null and (eq(src, dep_out.?) or eq(out, dep_out.?)))) return error.UnsupportedFlags;
    return .{ .source = src, .output = out, .dep = dep_out, .cpp = language_cpp, .pp = pp.items };
}
fn native(ctx: *cache.Context, path: []const u8) !void {
    const f = try Dir.cwd().openFile(ctx.io, path, .{});
    defer f.close(ctx.io);
    var magic: [4]u8 = undefined;
    if (try f.readPositional(ctx.io, &.{&magic}, 0) != 4) return error.UnsupportedCompiler;
    if (eq(&magic, "\x7fELF") or eq(&magic, "\xcf\xfa\xed\xfe") or eq(&magic, "\xca\xfe\xba\xbe")) return;
    return error.UnsupportedCompiler;
}
fn toolIdentity(ctx: *cache.Context, tool: []const u8, cpp: bool, gcc: bool) ![]const u8 {
    _ = cpp;
    try native(ctx, tool);
    var paths: std.ArrayList([]const u8) = .empty;
    try paths.append(ctx.a, tool);
    if (gcc) {
        for ([_][]const u8{ "-print-prog-name=cc1", "-print-prog-name=cc1plus" }) |option| {
            const cc1 = try identity.selectedExecutable(ctx, try query(ctx, &.{ tool, option }));
            try native(ctx, cc1);
            try paths.append(ctx.a, cc1);
        }
        const assembler = try identity.selectedExecutable(ctx, try query(ctx, &.{ tool, "-print-prog-name=as" }));
        try native(ctx, assembler);
        try paths.append(ctx.a, assembler);
        const specs = try query(ctx, &.{ tool, "-print-file-name=specs" });
        if (!eq(specs, "specs")) return error.UnsupportedCompilerSpecs;
    }
    if (builtin.os.tag == .linux) {
        const count = paths.items.len;
        for (0..count) |i| {
            const loaded = try query(ctx, &.{ "ldd", paths.items[i] });
            var words = std.mem.tokenizeAny(u8, loaded, " \t\r\n");
            while (words.next()) |word| if (std.fs.path.isAbsolute(word)) {
                try paths.append(ctx.a, try Dir.cwd().realPathFileAlloc(ctx.io, word, ctx.a));
            };
        }
    } else {
        // Only Apple's selected Clang here. The sealed system libraries are
        // partitioned by the actual OS version; custom macOS GCC/Clang refuse.
        const version = try query(ctx, &.{ tool, "--version" });
        if (std.mem.indexOf(u8, version, "Apple clang version") == null or (!std.mem.startsWith(u8, tool, "/Library/Developer/") and !(std.mem.startsWith(u8, tool, "/Applications/") and std.mem.indexOf(u8, tool, ".app/Contents/Developer/") != null))) return error.UnsupportedCompiler;
    }
    return identity.nativeFiles(ctx, paths.items);
}
fn less(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.order(u8, a, b) == .lt;
}
fn hiddenAssembly(bytes: []const u8) bool {
    for ([_][]const u8{ ".incbin", ".include", "pch_preprocess" }) |hidden| if (std.mem.indexOf(u8, bytes, hidden) != null) return true;
    // Permit simple assembler symbol aliases used in system declarations.
    // Actual inline asm (including split/escaped file-reading directives)
    // refuses, since its filesystem reads are invisible to preprocessing.
    for ([_][]const u8{ "__asm__", "__asm", "asm" }) |word| {
        var start: usize = 0;
        while (std.mem.indexOfPos(u8, bytes, start, word)) |index| {
            start = index + word.len;
            if (index > 0 and (std.ascii.isAlphanumeric(bytes[index - 1]) or bytes[index - 1] == '_')) continue;
            if (start < bytes.len and (std.ascii.isAlphanumeric(bytes[start]) or bytes[start] == '_')) continue;
            var tail = std.mem.trimStart(u8, bytes[start..], " \t\r\n");
            if (tail.len == 0 or tail[0] != '(') return true;
            tail = std.mem.trimStart(u8, tail[1..], " \t\r\n");
            if (tail.len == 0 or tail[0] != '"') return true;
            const end = std.mem.indexOfScalarPos(u8, tail, 1, '"') orelse return true;
            if (end == 1) return true;
            for (tail[1..end]) |ch| if (!std.ascii.isAlphanumeric(ch) and ch != '_' and ch != '$' and ch != '.') return true;
            tail = std.mem.trimStart(u8, tail[end + 1 ..], " \t\r\n");
            if (tail.len == 0 or tail[0] != ')') return true;
        }
    }
    return false;
}
fn key(ctx: *cache.Context, tool: []const u8, args: []const []const u8, work: Job, depfile: []const u8, gcc: bool) ![]const u8 {
    for (ctx.env.keys()) |name| if (std.mem.startsWith(u8, name, "DYLD_") or std.mem.startsWith(u8, name, "LD_") or eq(name, "CCC_OVERRIDE_OPTIONS") or eq(name, "DEPENDENCIES_OUTPUT") or eq(name, "SUNPRO_DEPENDENCIES") or eq(name, "GCC_COMPARE_DEBUG")) return error.UnsupportedCompilerEnvironment;
    var plan_args: std.ArrayList([]const u8) = .empty;
    try plan_args.append(ctx.a, tool);
    try plan_args.appendSlice(ctx.a, args);
    try plan_args.append(ctx.a, "-###");
    const plan = try std.process.run(ctx.a, ctx.io, .{ .argv = plan_args.items, .environ_map = ctx.env });
    if (code(plan.term) != 0 or std.mem.indexOf(u8, plan.stderr, "Configuration file:") != null) return error.UnsupportedCompilerConfig;
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.append(ctx.a, tool);
    try argv.appendSlice(ctx.a, work.pp);
    try argv.appendSlice(ctx.a, &.{ "-E", "-MD", "-MF", depfile, "-MT", "nano" });
    if (gcc) try argv.append(ctx.a, "-fpch-preprocess");
    const pp = try std.process.run(ctx.a, ctx.io, .{ .argv = argv.items, .environ_map = ctx.env, .stdout_limit = .limited(64 * 1024 * 1024) });
    if (code(pp.term) != 0) return error.PreprocessingFailed;
    if (hiddenAssembly(pp.stdout)) return error.UnsupportedInput;
    var h = cache.Hash.init(.{});
    cache.field(&h, "nanocompile-portable-cc-v1");
    cache.field(&h, ctx.cwd);
    const host = try std.zig.system.resolveTargetQuery(ctx.io, .{});
    cache.field(&h, @tagName(host.cpu.arch));
    cache.field(&h, host.cpu.model.name);
    cache.field(&h, std.mem.asBytes(&host.cpu.features.ints));
    cache.field(&h, try query(ctx, &.{ "uname", "-a" }));
    if (builtin.os.tag == .macos) cache.field(&h, try query(ctx, &.{ "sw_vers", "-buildVersion" }));
    cache.field(&h, tool);
    cache.field(&h, try toolIdentity(ctx, tool, work.cpp, gcc));
    for (args) |arg| cache.field(&h, arg);
    const keys = try ctx.a.dupe([]const u8, ctx.env.keys());
    std.mem.sort([]const u8, keys, {}, less);
    for (keys) |name| {
        cache.field(&h, name);
        cache.field(&h, ctx.env.get(name).?);
    }
    // GCC renders random temporary assembler filenames in -###; all its
    // selected binaries are fingerprinted and custom specs already refuse.
    if (!gcc) cache.field(&h, plan.stderr);
    cache.field(&h, pp.stdout);
    cache.field(&h, pp.stderr);
    const dependencies = try compiler.parseDepInfo(ctx.a, try ctx.read(depfile));
    if (dependencies.len == 0) return error.MissingDependencies;
    var seen: std.StringHashMapUnmanaged(void) = .empty;
    for (dependencies) |path| {
        const abs = try std.fs.path.resolve(ctx.a, &.{ ctx.cwd, path });
        const slot = try seen.getOrPut(ctx.a, abs);
        if (slot.found_existing) continue;
        cache.field(&h, abs);
        cache.field(&h, (try ctx.checkedDigest(abs)).hash);
    }
    return cache.finish(ctx.a, &h);
}
pub fn execute(ctx: *cache.Context, args: []const []const u8, cpp: bool) !u8 {
    const selected = ctx.env.get(if (cpp) "NANOCOMPILE_CXX" else "NANOCOMPILE_CC") orelse if (builtin.os.tag == .macos) try query(ctx, &.{ "xcrun", "--find", if (cpp) "clang++" else "clang" }) else if (cpp) "c++" else "cc";
    if (builtin.os.tag == .macos and ctx.env.get(if (cpp) "NANOCOMPILE_CXX" else "NANOCOMPILE_CC") == null and ctx.env.get("SDKROOT") == null) {
        const selected_sdk = try query(ctx, &.{ "xcrun", "--sdk", "macosx", "--show-sdk-path" });
        if (!std.fs.path.isAbsolute(selected_sdk)) return error.UnsupportedCompiler;
        const cloned = try ctx.a.create(std.process.Environ.Map);
        cloned.* = try ctx.env.clone(ctx.a);
        ctx.env = cloned;
        try ctx.env.put("SDKROOT", selected_sdk);
    }
    const tool = try identity.selectedExecutable(ctx, selected);
    var original: std.ArrayList([]const u8) = .empty;
    try original.append(ctx.a, tool);
    try original.appendSlice(ctx.a, args);
    const work = job(ctx, args, cpp) catch {
        ctx.event("cc_bypass");
        return run(ctx, original.items);
    };
    if (enabled(ctx, "NANOCOMPILE_DISABLE")) return run(ctx, original.items);
    ctx.prepare() catch return run(ctx, original.items);
    const maintenance = cache.Lock.acquire(ctx, "maintenance", false) catch return run(ctx, original.items);
    defer maintenance.release();
    var destinations: std.ArrayList([]const u8) = .empty;
    try destinations.append(ctx.a, work.output);
    if (work.dep) |dep| try destinations.append(ctx.a, dep);
    std.mem.sort([]const u8, destinations.items, {}, less);
    var output_locks: std.ArrayList(cache.Lock) = .empty;
    defer for (output_locks.items) |held| held.release();
    for (destinations.items) |destination| {
        var output_hash = cache.Hash.init(.{});
        cache.field(&output_hash, destination);
        try output_locks.append(ctx.a, cache.Lock.acquire(ctx, try std.fmt.allocPrint(ctx.a, "cc-output-{s}", .{try cache.finish(ctx.a, &output_hash)}), true) catch return run(ctx, original.items));
    }
    const version = query(ctx, &.{ tool, "--version" }) catch return run(ctx, original.items);
    const gcc = std.mem.indexOf(u8, version, "clang") == null;
    const temp = try ctx.path(&.{ "metadata", try std.fmt.allocPrint(ctx.a, "cc-preprocess-{d}.d", .{getpid()}) });
    try Dir.cwd().createDirPath(ctx.io, std.fs.path.dirname(temp).?);
    defer Dir.cwd().deleteFile(ctx.io, temp) catch {};
    const cache_key = key(ctx, tool, args, work, temp, gcc) catch |err| {
        ctx.trace(@errorName(err));
        ctx.event("cc_bypass");
        return run(ctx, original.items);
    };
    const outputs: []const []const u8 = if (work.dep) |dep| try ctx.a.dupe([]const u8, &.{ work.output, dep }) else try ctx.a.dupe([]const u8, &.{work.output});
    const lock = try cache.Lock.acquire(ctx, cache_key, true);
    defer lock.release();
    if (cache.restore(ctx, cache_key, outputs) catch false) {
        ctx.event("cc_hit");
        return 0;
    }
    ctx.event("cc_miss");
    const result = try std.process.run(ctx.a, ctx.io, .{ .argv = original.items, .environ_map = ctx.env });
    try ctx.out(result.stdout);
    try std.Io.File.stderr().writeStreamingAll(ctx.io, result.stderr);
    const status = code(result.term);
    if (status != 0) {
        ctx.event("cc_failed");
        return status;
    }
    // A second complete preprocess/input/toolchain observation rejects changes
    // across the real compilation. No header timestamp memo is introduced.
    const after = key(ctx, tool, args, work, temp, gcc) catch return status;
    if (!eq(after, cache_key)) return status;
    cache.store(ctx, cache_key, &.{}, outputs, result.stdout, result.stderr) catch |err| ctx.trace(@errorName(err));
    return status;
}
