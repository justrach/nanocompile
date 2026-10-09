//! Scope Cargo's shared library directories to the crate graph rustc actually
//! loaded. The metadata query only reads a completed artifact: bootstrap is
//! confined to that diagnostic subprocess, never the user's compilation.
const std = @import("std");
const cache = @import("cache.zig");
const Dir = std.Io.Dir;

pub const Directory = struct { path: []const u8, names: []const []const u8 };

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
pub fn parse(a: std.mem.Allocator, bytes: []const u8, reported: bool) ![]const []const u8 {
    if (!std.mem.startsWith(u8, bytes, "Crate info:\n") or std.mem.indexOf(u8, bytes, "\nproc_macro false\n") == null) return error.UnsupportedRustMetadata;
    const marker = "=External Dependencies=\n";
    const offset = std.mem.indexOf(u8, bytes, marker) orelse return error.UnsupportedRustMetadata;
    var lines = std.mem.splitScalar(u8, bytes[offset + marker.len ..], '\n');
    var names: std.ArrayList([]const u8) = .empty;
    while (lines.next()) |line| {
        if (line.len == 0) break;
        if (!reported and std.mem.indexOf(u8, line, "kind MacrosOnly") != null) return error.ProceduralMacroDependency;
        var words = std.mem.tokenizeScalar(u8, line, ' ');
        _ = try std.fmt.parseInt(usize, words.next() orelse return error.UnsupportedRustMetadata, 10);
        const name = words.next() orelse return error.UnsupportedRustMetadata;
        if (!std.mem.eql(u8, words.next() orelse "", "hash")) return error.UnsupportedRustMetadata;
        const hash = words.next() orelse return error.UnsupportedRustMetadata;
        if (hash.len != 32) return error.UnsupportedRustMetadata;
        for (hash) |ch| if (!std.ascii.isHex(ch)) return error.UnsupportedRustMetadata;
        for (name) |ch| if (!std.ascii.isAlphanumeric(ch) and ch != '_' and ch != '-') return error.UnsupportedRustMetadata;
        if (name.len == 0) return error.UnsupportedRustMetadata;
        try names.append(a, try a.dupe(u8, name));
    }
    return names.items;
}

pub fn collect(ctx: *cache.Context, argv: []const []const u8, outputs: []const []const u8, before: []const Directory, started: i96, records: *std.ArrayList(cache.Dependency)) !void {
    var artifact: ?[]const u8 = null;
    for (outputs) |out| if (std.mem.endsWith(u8, out, ".rlib")) {
        artifact = out;
        break;
    };
    if (artifact == null) for (outputs) |out| if (std.mem.endsWith(u8, out, ".rmeta")) {
        artifact = out;
        break;
    };
    const path = artifact orelse return error.UnsupportedRustMetadata;
    var query_env = try ctx.env.clone(ctx.a);
    // -Zls=root decodes existing compiler metadata without loading or running
    // proc macros. Keep the original environment on all actual compilations.
    try query_env.put("RUSTC_BOOTSTRAP", "1");
    const result = try std.process.run(ctx.a, ctx.io, .{ .argv = &.{ argv[0], "-Zls=root", path }, .environ_map = &query_env });
    if (!success(result)) return error.RustMetadataQueryFailed;
    const names = try parse(ctx.a, result.stdout, reportedMacros(ctx));
    var current: std.ArrayList(Directory) = .empty;
    for (before) |dir| try current.append(ctx.a, .{ .path = dir.path, .names = try ctx.libraryNames(dir.path, outputs) });
    // Toolchain resources are already content-fingerprinted. Resolve missing
    // directory candidates against the selected target's sysroot, not a list of
    // presumed built-in names (the standard library itself includes crates).
    var print_args: std.ArrayList([]const u8) = .empty;
    try print_args.appendSlice(ctx.a, &.{ argv[0], "--print", "target-libdir" });
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
    const sysroot = std.mem.trim(u8, sysroot_result.stdout, "\r\n");
    if (!std.fs.path.isAbsolute(sysroot)) return error.InvalidSysroot;
    for (names) |name| {
        const crate = name[0 .. std.mem.indexOfScalar(u8, name, '-') orelse name.len];
        const prefix = try std.fmt.allocPrint(ctx.a, "lib{s}", .{crate});
        var found = false;
        for (before, current.items) |old, dir| {
            const old_hash = try cache.prefixDigest(ctx.a, old.names, prefix);
            const new_hash = try cache.prefixDigest(ctx.a, dir.names, prefix);
            if (!std.mem.eql(u8, old_hash, new_hash)) return error.LibraryDirectoryChangedDuringCompilation;
            try records.append(ctx.a, .{ .path = dir.path, .hash = new_hash, .directory = true, .libraries = true, .library_prefix = prefix });
            for (dir.names) |entry| {
                if (!std.mem.startsWith(u8, entry, prefix)) continue;
                const filename = entry[0 .. std.mem.lastIndexOfScalar(u8, entry, ':') orelse return error.UnsupportedLibraryName];
                // The conservative prefix includes every rustc candidate, so
                // adding a competing version or replacing one invalidates hits.
                const input = try std.fs.path.join(ctx.a, &.{ dir.path, filename });
                const st = try Dir.cwd().statFile(ctx.io, input, .{});
                if (st.mtime.nanoseconds >= started or st.ctime.nanoseconds >= started) return error.InputChangedDuringCompilation;
                try records.append(ctx.a, .{ .path = input, .hash = try ctx.digest(input) });
                const exact = try std.fmt.allocPrint(ctx.a, "lib{s}.", .{name});
                if (std.mem.startsWith(u8, filename, exact)) found = true;
            }
        }
        if (!found) {
            const builtin_path = try std.fs.path.join(ctx.a, &.{ sysroot, try std.fmt.allocPrint(ctx.a, "lib{s}.rlib", .{name}) });
            _ = Dir.cwd().statFile(ctx.io, builtin_path, .{}) catch return error.UnresolvedRustDependency;
        }
    }
}

test "Rust metadata rejects incomplete and procedural macro graphs" {
    const prefix = "Crate info:\nproc_macro false\n=External Dependencies=\n";
    const names = try parse(std.testing.allocator, prefix ++ "1 dep-abcd hash 0123456789abcdef0123456789abcdef host_hash None kind Unconditional public\n\n", false);
    defer {
        for (names) |name| std.testing.allocator.free(name);
        std.testing.allocator.free(names);
    }
    try std.testing.expectEqualStrings("dep-abcd", names[0]);
    try std.testing.expectError(error.ProceduralMacroDependency, parse(std.testing.allocator, prefix ++ "1 macro-abcd hash 0123456789abcdef0123456789abcdef host_hash None kind MacrosOnly public\n", false));
    try std.testing.expectError(error.UnsupportedRustMetadata, parse(std.testing.allocator, "=External Dependencies=\n", false));
}

pub fn reportedMacros(ctx: *cache.Context) bool {
    return if (ctx.env.get("NANOCOMPILE_PROC_MACROS")) |mode| std.mem.eql(u8, mode, "reported") else false;
}
