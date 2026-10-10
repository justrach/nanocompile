//! Scope Cargo's shared library directories to the crate graph rustc actually
//! loaded. The metadata query only reads a completed artifact: bootstrap is
//! confined to that diagnostic subprocess, never the user's compilation.
const std = @import("std");
const cache = @import("cache.zig");
const metadata = @import("rust_metadata.zig");
const Dir = std.Io.Dir;

pub const Directory = struct { path: []const u8, names: []const []const u8 };

/// Native search is not recursive. Track every immediate file and every name,
/// including symlink targets and competing archive names. Thin archives can
/// reference objects outside this directory, so leave them uncached.
pub fn nativeSnapshot(ctx: *cache.Context, dirs: []const []const u8) ![]const cache.Dependency {
    var records: std.ArrayList(cache.Dependency) = .empty;
    for (dirs) |path| {
        try records.append(ctx.a, .{ .path = path, .hash = try ctx.nativeDirectoryDigest(path), .directory = true, .all_members = true });
        var dir = try Dir.cwd().openDir(ctx.io, path, .{ .iterate = true });
        defer dir.close(ctx.io);
        var iterator = dir.iterate();
        while (try iterator.next(ctx.io)) |entry| {
            if (entry.kind == .directory) continue;
            const input = try std.fs.path.join(ctx.a, &.{ path, entry.name });
            const file = try Dir.cwd().openFile(ctx.io, input, .{});
            defer file.close(ctx.io);
            if ((try file.stat(ctx.io)).kind != .file) return error.UnsupportedNativeInput;
            var magic: [8]u8 = undefined;
            var reader = file.reader(ctx.io, &.{});
            const n = try reader.interface.readSliceShort(&magic);
            if (std.mem.eql(u8, magic[0..n], "!<thin>\n")) return error.ThinNativeArchive;
            try records.append(ctx.a, .{ .path = input, .hash = try ctx.digest(input) });
        }
    }
    return records.items;
}

pub fn snapshot(ctx: *cache.Context, dirs: []const []const u8, outputs: []const []const u8) ![]const Directory {
    var result: std.ArrayList(Directory) = .empty;
    for (dirs) |dir| try result.append(ctx.a, .{ .path = dir, .names = try ctx.libraryNames(dir, outputs) });
    return result.items;
}

fn success(result: std.process.RunResult) bool {
    return switch (result.term) {
        .exited => |code| code == 0,
        else => false,
    };
}

// Unknown diagnostic formats cannot silently produce an incomplete graph.
pub const Crate = struct { name: []const u8, hash: []const u8, proc_macro: bool };
pub fn parse(a: std.mem.Allocator, bytes: []const u8, reported: bool) ![]const Crate {
    if (!std.mem.startsWith(u8, bytes, "Crate info:\n") or std.mem.indexOf(u8, bytes, "\nproc_macro false\n") == null) return error.UnsupportedRustMetadata;
    const marker = "=External Dependencies=\n";
    const offset = std.mem.indexOf(u8, bytes, marker) orelse return error.UnsupportedRustMetadata;
    var lines = std.mem.splitScalar(u8, bytes[offset + marker.len ..], '\n');
    var names: std.ArrayList(Crate) = .empty;
    errdefer {
        for (names.items) |crate| {
            a.free(crate.name);
            a.free(crate.hash);
        }
        names.deinit(a);
    }
    while (lines.next()) |line| {
        if (line.len == 0) break;
        if (!reported and std.mem.indexOf(u8, line, "kind MacrosOnly") != null) return error.ProceduralMacroDependency;
        var words = std.mem.tokenizeScalar(u8, line, ' ');
        _ = try std.fmt.parseInt(usize, words.next() orelse return error.UnsupportedRustMetadata, 10);
        const name = words.next() orelse return error.UnsupportedRustMetadata;
        if (!std.mem.eql(u8, words.next() orelse "", "hash")) return error.UnsupportedRustMetadata;
        const hash = words.next() orelse return error.UnsupportedRustMetadata;
        if (!metadata.validCrateHash(hash)) return error.UnsupportedRustMetadata;
        for (name) |ch| if (!std.ascii.isAlphanumeric(ch) and ch != '_' and ch != '-') return error.UnsupportedRustMetadata;
        if (name.len == 0) return error.UnsupportedRustMetadata;
        try names.append(a, .{ .name = try a.dupe(u8, name), .hash = try a.dupe(u8, hash), .proc_macro = std.mem.indexOf(u8, line, "kind MacrosOnly") != null });
    }
    return names.items;
}

// rustc's metadata-only loader skips the rlib flavor after loading a matching
// rmeta in the same filename group. Only use an exact same-stem companion;
// broad fallback and nonmatching metadata retain full candidate validation.
fn unusedCompanion(resolver: *metadata.Resolver, dir: Directory, filename: []const u8, crate: Crate, triple: []const u8) !bool {
    if (crate.proc_macro or !std.mem.endsWith(u8, filename, ".rlib")) return false;
    const expected = try std.fmt.allocPrint(resolver.ctx.a, "lib{s}.rlib", .{crate.name});
    if (!std.mem.eql(u8, filename, expected)) return false;
    const companion = try std.fmt.allocPrint(resolver.ctx.a, "lib{s}.rmeta", .{crate.name});
    for (dir.names) |entry| {
        const name = entry[0 .. std.mem.lastIndexOfScalar(u8, entry, ':') orelse return error.UnsupportedLibraryName];
        if (!std.mem.eql(u8, name, companion)) continue;
        const path = try std.fs.path.join(resolver.ctx.a, &.{ dir.path, companion });
        const root = (resolver.inspect(path, false) catch null) orelse return false;
        return root.matches(crate.name, crate.hash, triple, false);
    }
    return false;
}

const DirectGraph = struct { root: metadata.Root, names: []const Crate };
fn directGraph(ctx: *cache.Context, path: []const u8) !?DirectGraph {
    if (!std.mem.endsWith(u8, path, ".rmeta")) return null;
    const before = Dir.cwd().statFile(ctx.io, path, .{}) catch return null;
    const bytes = ctx.read(path) catch return null;
    const graph = @import("rmeta_direct.zig").decode(ctx.a, bytes) catch return null;
    const after = try Dir.cwd().statFile(ctx.io, path, .{});
    if (!cache.sameFileState(before, after)) return error.InputChangedDuringMetadataQuery;
    var names: std.ArrayList(Crate) = .empty;
    for (graph.dependencies) |crate| {
        if (!reportedMacros(ctx) and crate.proc_macro) return error.ProceduralMacroDependency;
        try names.append(ctx.a, .{ .name = crate.name, .hash = crate.hash, .proc_macro = crate.proc_macro });
    }
    return .{ .root = .{ .name = graph.root.name, .hash = graph.root.hash, .triple = graph.root.triple, .proc_macro = graph.root.proc_macro }, .names = names.items };
}

pub fn collect(ctx: *cache.Context, argv: []const []const u8, outputs: []const []const u8, before: []const Directory, started: i96, records: *std.ArrayList(cache.Dependency), metadata_only: bool, validated: *const std.StringHashMapUnmanaged(cache.CheckedDigest), hidden_native: bool) !void {
    var artifact: ?[]const u8 = null;
    for (outputs) |out| if (std.mem.endsWith(u8, out, ".rmeta")) {
        artifact = out;
        break;
    };
    if (artifact == null) for (outputs) |out| if (std.mem.endsWith(u8, out, ".rlib")) {
        artifact = out;
        break;
    };
    const path = artifact orelse return error.UnsupportedRustMetadata;
    // Resolve the toolchain from the original cwd before moving diagnostic
    // readers into private storage. rustup accepts an absolute toolchain root.
    var print_args: std.ArrayList([]const u8) = .empty;
    try print_args.appendSlice(ctx.a, &.{ argv[0], "--print", "sysroot", "--print", "target-libdir" });
    var i: usize = 1;
    while (i < argv.len) : (i += 1) {
        if (std.mem.eql(u8, argv[i], "--target")) {
            if (i + 1 == argv.len) return error.MissingTarget;
            try print_args.appendSlice(ctx.a, &.{ "--target", argv[i + 1] });
            i += 1;
        } else if (std.mem.startsWith(u8, argv[i], "--target=")) try print_args.append(ctx.a, argv[i]);
    }
    const sysroot_result = try std.process.run(ctx.a, ctx.io, .{ .argv = print_args.items, .environ_map = ctx.env });
    if (!success(sysroot_result)) return error.RustSysrootQueryFailed;
    var locations = std.mem.tokenizeAny(u8, sysroot_result.stdout, "\r\n");
    const selected_sysroot = locations.next() orelse return error.InvalidSysroot;
    const sysroot = locations.next() orelse return error.InvalidSysroot;
    if (locations.next() != null or !std.fs.path.isAbsolute(selected_sysroot) or !std.fs.path.isAbsolute(sysroot)) return error.InvalidSysroot;
    var query_env = try ctx.env.clone(ctx.a);
    try query_env.put("RUSTC_BOOTSTRAP", "1");
    try query_env.put("RUSTUP_TOOLCHAIN", selected_sysroot);
    const reader_compiler = try metadata.readerCompiler(ctx, argv[0]);
    const query_cwd = try ctx.path(&.{"metadata-queries"});
    try Dir.cwd().createDirPath(ctx.io, query_cwd);
    const native_checked = if (hidden_native) try ctx.checkedDigest(path) else null;
    const graph = (try directGraph(ctx, path)) orelse blk: {
        const result = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ reader_compiler, "-Zls=root", path }, .environ_map = &query_env, .cwd = .{ .path = query_cwd } });
        if (!success(result)) return error.RustMetadataQueryFailed;
        break :blk DirectGraph{ .names = try parse(ctx.a, result.stdout, reportedMacros(ctx)), .root = try metadata.parse(result.stdout) };
    };
    const names = graph.names;
    const own_root = graph.root;
    if (native_checked) |checked| {
        if (!std.mem.endsWith(u8, path, ".rmeta")) return error.HiddenNativeLinkInput;
        const bytes = try ctx.read(path);
        try @import("native_metadata.zig").dynamicOnly(bytes, own_root);
        const after = try ctx.checkedDigest(path);
        if (!std.mem.eql(u8, checked.hash, after.hash) or !cache.sameFileState(checked.state, after.state)) return error.InputChangedDuringMetadataQuery;
    }
    var resolver: metadata.Resolver = .{ .ctx = ctx, .compiler = reader_compiler, .query_env = &query_env, .query_cwd = query_cwd };
    defer resolver.roots.deinit(ctx.a);
    defer resolver.hashes.deinit(ctx.a);
    defer resolver.states.deinit(ctx.a);
    // These records were freshly content-validated after compilation. Share
    // them within this entry construction, never across compilation or hits.
    var checked = validated.iterator();
    while (checked.next()) |record| {
        try resolver.hashes.put(ctx.a, record.key_ptr.*, record.value_ptr.hash);
        try resolver.states.put(ctx.a, record.key_ptr.*, record.value_ptr.state);
    }
    // Classification memos save subprocesses, but consumers still hash every
    // non-toolchain input before using them.
    for (outputs) |out| if (std.mem.endsWith(u8, out, ".rlib") or std.mem.endsWith(u8, out, ".rmeta"))
        try resolver.remember(out, own_root);
    var current: std.ArrayList(Directory) = .empty;
    for (before) |dir| try current.append(ctx.a, .{ .path = dir.path, .names = try ctx.libraryNames(dir.path, outputs) });
    for (names) |crate| {
        const name = crate.name;
        const full_prefix = try std.fmt.allocPrint(ctx.a, "lib{s}", .{name});
        const builtin_path = try std.fs.path.join(ctx.a, &.{ sysroot, try std.fmt.allocPrint(ctx.a, "lib{s}.rmeta", .{name}) });
        var primary_found = false;
        for (current.items) |dir| {
            for (dir.names) |entry| {
                if (!std.mem.startsWith(u8, entry, full_prefix)) continue;
                const filename = entry[0 .. std.mem.lastIndexOfScalar(u8, entry, ':') orelse return error.UnsupportedLibraryName];
                if (metadata_only and try unusedCompanion(&resolver, dir, filename, crate, own_root.triple)) {
                    primary_found = true;
                    continue;
                }
                const input = try std.fs.path.join(ctx.a, &.{ dir.path, filename });
                const root = (resolver.inspect(input, false) catch null) orelse continue;
                if (root.matches(name, crate.hash, own_root.triple, crate.proc_macro)) primary_found = true;
            }
        }
        if (!primary_found) {
            if (resolver.inspect(builtin_path, true) catch null) |root|
                primary_found = root.matches(name, crate.hash, own_root.triple, crate.proc_macro);
        }
        // rustc first tries the dependency's full extra-filename prefix, then
        // searches broadly only when that finds no matching metadata. When
        // falling back, guard all candidates: the diagnostic display combines
        // crate name and arbitrary extra-filename, so splitting on '-' would
        // guess the semantic name for nonstandard or renamed artifacts.
        const prefix = if (primary_found) full_prefix else "";
        var found = false;
        for (before, current.items) |old, dir| {
            const old_hash = try cache.prefixDigest(ctx.a, old.names, prefix);
            const new_hash = try cache.prefixDigest(ctx.a, dir.names, prefix);
            if (!std.mem.eql(u8, old_hash, new_hash)) return error.LibraryDirectoryChangedDuringCompilation;
            try records.append(ctx.a, .{ .path = dir.path, .hash = new_hash, .directory = true, .libraries = true, .library_prefix = prefix });
            for (dir.names) |entry| {
                if (!std.mem.startsWith(u8, entry, prefix)) continue;
                const filename = entry[0 .. std.mem.lastIndexOfScalar(u8, entry, ':') orelse return error.UnsupportedLibraryName];
                if (metadata_only and primary_found and try unusedCompanion(&resolver, dir, filename, crate, own_root.triple)) continue;
                // Include every candidate in the selected search phase. A
                // competing matching library still invalidates the restore.
                const input = try std.fs.path.join(ctx.a, &.{ dir.path, filename });
                const st = try Dir.cwd().statFile(ctx.io, input, .{});
                if (st.mtime.nanoseconds >= started or st.ctime.nanoseconds >= started) return error.InputChangedDuringCompilation;
                try records.append(ctx.a, .{ .path = input, .hash = try resolver.digest(input) });
                const exact = try std.fmt.allocPrint(ctx.a, "lib{s}.", .{name});
                if (std.mem.startsWith(u8, filename, exact)) found = true;
                if (!primary_found and !found) {
                    if (resolver.inspect(input, false) catch null) |root|
                        if (root.matches(name, crate.hash, own_root.triple, crate.proc_macro)) {
                            found = true;
                        };
                }
            }
        }
        if (!found) {
            _ = Dir.cwd().statFile(ctx.io, builtin_path, .{}) catch return error.UnresolvedRustDependency;
        }
    }
}

test "Rust metadata rejects incomplete and procedural macro graphs" {
    const prefix = "Crate info:\nproc_macro false\n=External Dependencies=\n";
    const names = try parse(std.testing.allocator, prefix ++ "1 dep-abcd hash 0123456789abcdef0123456789abcdef host_hash None kind Unconditional public\n\n", false);
    defer {
        for (names) |crate| {
            std.testing.allocator.free(crate.name);
            std.testing.allocator.free(crate.hash);
        }
        std.testing.allocator.free(names);
    }
    try std.testing.expectEqualStrings("dep-abcd", names[0].name);
    try std.testing.expectError(error.ProceduralMacroDependency, parse(std.testing.allocator, prefix ++ "1 macro-abcd hash 0123456789abcdef0123456789abcdef host_hash None kind MacrosOnly public\n", false));
    try std.testing.expectError(error.UnsupportedRustMetadata, parse(std.testing.allocator, "=External Dependencies=\n", false));
}

pub fn reportedMacros(ctx: *cache.Context) bool {
    return if (ctx.env.get("NANOCOMPILE_PROC_MACROS")) |mode| std.mem.eql(u8, mode, "reported") else false;
}
