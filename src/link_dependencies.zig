//! Strict final-link dependency reports. Allocations use the caller's arena;
//! Darwin path slices borrow the report bytes. This does not infer scratch-file
//! ownership, SDK identity or lookup-directory guards: callers must supply those.
const std = @import("std");

pub const Format = enum { darwin, make };
pub const Report = struct {
    version: ?[]const u8 = null,
    inputs: []const []const u8,
    missing: []const []const u8 = &.{},
    outputs: []const []const u8,
};

pub fn parse(a: std.mem.Allocator, bytes: []const u8, format: Format) !Report {
    if (bytes.len == 0 or bytes.len > 64 * 1024 * 1024) return error.InvalidLinkReport;
    return switch (format) {
        .darwin => parseDarwin(a, bytes),
        .make => parseMake(a, bytes),
    };
}

/// LLD escapes prerequisite paths but emits its output path verbatim. Bind
/// that raw header to the caller's known destination instead of guessing how
/// several whitespace-separated target tokens should be combined.
pub fn parseForOutput(a: std.mem.Allocator, bytes: []const u8, format: Format, output: []const u8) !Report {
    if (bytes.len == 0 or bytes.len > 64 * 1024 * 1024) return error.InvalidLinkReport;
    if (output.len == 0 or std.mem.indexOfAny(u8, output, "\x00\r\n") != null) return error.InvalidLinkReport;
    // GNU ld emits raw prerequisite filenames, one per physical line with
    // two spaces of indentation, followed by matching raw phony rules. Bind
    // this exact writer layout; never guess by joining whitespace tokens.
    const gnu_start = try std.fmt.allocPrint(a, "{s}: \\\n  ", .{output});
    if (format == .make and std.mem.startsWith(u8, bytes, gnu_start))
        return parseGnuBounded(a, bytes, output);
    var normalized = bytes;
    if (format == .make and bytes.len > output.len and std.mem.startsWith(u8, bytes, output) and bytes[output.len] == ':') {
        var header: std.ArrayList(u8) = .empty;
        for (output) |ch| {
            switch (ch) {
                ' ', '\t', '#', ':', '\\' => try header.append(a, '\\'),
                '$' => try header.append(a, '$'),
                else => {},
            }
            try header.append(a, ch);
        }
        try header.appendSlice(a, bytes[output.len..]);
        normalized = header.items;
    }
    const report = try parse(a, normalized, format);
    if (report.outputs.len != 1 or !std.mem.eql(u8, report.outputs[0], output)) return error.UnexpectedLinkOutput;
    return report;
}

fn parseGnuBounded(a: std.mem.Allocator, bytes: []const u8, output: []const u8) !Report {
    const separator = " \\\n  ";
    var i = output.len + 1;
    var inputs: std.ArrayList([]const u8) = .empty;
    while (std.mem.startsWith(u8, bytes[i..], separator)) {
        i += separator.len;
        const end = std.mem.indexOfScalarPos(u8, bytes, i, '\n') orelse return error.TruncatedLinkReport;
        var path_end = end;
        // Continuation syntax belongs to the writer, not the raw filename.
        if (end >= i + 2 and std.mem.eql(u8, bytes[end - 2 .. end], " \\")) path_end -= 2;
        const path = bytes[i..path_end];
        if (path.len == 0 or std.mem.indexOfAny(u8, path, "\x00\r") != null) return error.InvalidLinkReport;
        try inputs.append(a, path);
        i = path_end;
    }
    if (inputs.items.len == 0 or i >= bytes.len or bytes[i] != '\n') return error.InvalidLinkReport;
    i += 1;
    // The mirrored phony block removes ambiguity about raw spaces, dollars,
    // colons and backslashes in each filename and detects truncated layouts.
    for (inputs.items) |path| {
        const phony = try std.fmt.allocPrint(a, "\n{s}:\n", .{path});
        if (!std.mem.startsWith(u8, bytes[i..], phony)) return error.UnsupportedLinkReport;
        i += phony.len;
    }
    if (i != bytes.len) return error.UnsupportedLinkReport;
    return .{ .inputs = try inputs.toOwnedSlice(a), .outputs = try a.dupe([]const u8, &.{output}) };
}

test "GNU ld raw paths require the known output and matching phony layout" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const output = "/out, with spaces/lib.so";
    const inputs = [_][]const u8{ "/tmp/nano observer, job/private output/generated, object", "/persist/with $:# and \\literal.o" };
    var bytes: std.ArrayList(u8) = .empty;
    try bytes.appendSlice(a, try std.fmt.allocPrint(a, "{s}:", .{output}));
    for (inputs) |path| try bytes.appendSlice(a, try std.fmt.allocPrint(a, " \\\n  {s}", .{path}));
    try bytes.append(a, '\n');
    for (inputs) |path| try bytes.appendSlice(a, try std.fmt.allocPrint(a, "\n{s}:\n", .{path}));
    const report = try parseForOutput(a, bytes.items, .make, output);
    try std.testing.expectEqual(@as(usize, 2), report.inputs.len);
    for (inputs, report.inputs) |expected, actual| try std.testing.expectEqualStrings(expected, actual);
    try std.testing.expectError(error.UnsupportedLinkReport, parse(a, bytes.items, .make));
    try std.testing.expectError(error.UnsupportedLinkReport, parseForOutput(a, bytes.items[0 .. bytes.items.len - 1], .make, output));
    const corrupt = try a.dupe(u8, bytes.items);
    corrupt[corrupt.len - 3] = 'X';
    try std.testing.expectError(error.UnsupportedLinkReport, parseForOutput(a, corrupt, .make, output));
}

fn parseDarwin(a: std.mem.Allocator, bytes: []const u8) !Report {
    var inputs: std.ArrayList([]const u8) = .empty;
    var missing: std.ArrayList([]const u8) = .empty;
    var outputs: std.ArrayList([]const u8) = .empty;
    var version: ?[]const u8 = null;
    var i: usize = 0;
    while (i < bytes.len) {
        const opcode = bytes[i];
        const end = std.mem.indexOfScalarPos(u8, bytes, i + 1, 0) orelse return error.TruncatedLinkReport;
        const value = bytes[i + 1 .. end];
        if (value.len == 0) return error.InvalidLinkReport;
        if (version == null and opcode != 0) return error.InvalidLinkReport;
        switch (opcode) {
            0 => {
                if (version != null) return error.InvalidLinkReport;
                version = value;
            },
            0x10 => try inputs.append(a, value),
            0x11 => try missing.append(a, value),
            0x40 => try outputs.append(a, value),
            else => return error.UnsupportedLinkReport,
        }
        i = end + 1;
    }
    if (version == null or outputs.items.len != 1 or inputs.items.len == 0) return error.InvalidLinkReport;
    return .{ .version = version, .inputs = try inputs.toOwnedSlice(a), .missing = try missing.toOwnedSlice(a), .outputs = try outputs.toOwnedSlice(a) };
}

const Rule = struct {
    targets: std.ArrayList([]const u8) = .empty,
    inputs: std.ArrayList([]const u8) = .empty,
    colon: bool = false,

    fn token(self: *Rule, a: std.mem.Allocator, bytes: *std.ArrayList(u8)) !void {
        if (bytes.items.len == 0) return;
        const path = try a.dupe(u8, bytes.items);
        try (if (self.colon) &self.inputs else &self.targets).append(a, path);
        bytes.clearRetainingCapacity();
    }
    fn complete(self: *Rule, report: *?Report, a: std.mem.Allocator) !void {
        if (self.targets.items.len == 0 and self.inputs.items.len == 0 and !self.colon) return;
        if (!self.colon or self.targets.items.len == 0) return error.InvalidLinkReport;
        if (self.inputs.items.len != 0) {
            if (report.* != null or self.targets.items.len != 1) return error.UnsupportedLinkReport;
            report.* = .{ .inputs = try a.dupe([]const u8, self.inputs.items), .outputs = try a.dupe([]const u8, self.targets.items) };
        }
        self.targets.clearRetainingCapacity();
        self.inputs.clearRetainingCapacity();
        self.colon = false;
    }
};

fn parseMake(a: std.mem.Allocator, bytes: []const u8) !Report {
    var rule: Rule = .{};
    var token: std.ArrayList(u8) = .empty;
    var report: ?Report = null;
    var i: usize = 0;
    while (i < bytes.len) : (i += 1) {
        const ch = bytes[i];
        switch (ch) {
            0 => return error.InvalidLinkReport,
            '\\' => {
                i += 1;
                if (i == bytes.len) return error.TruncatedLinkReport;
                if (bytes[i] == '\n') {
                    try rule.token(a, &token);
                } else if (bytes[i] == '\r' and i + 1 < bytes.len and bytes[i + 1] == '\n') {
                    i += 1;
                    try rule.token(a, &token);
                } else try token.append(a, bytes[i]);
            },
            '$' => {
                if (i + 1 == bytes.len or bytes[i + 1] != '$') return error.UnsupportedLinkReport;
                i += 1;
                try token.append(a, '$');
            },
            '#' => {
                try rule.token(a, &token);
                while (i + 1 < bytes.len and bytes[i + 1] != '\n') : (i += 1) {}
            },
            ':' => {
                if (rule.colon) return error.UnsupportedLinkReport;
                try rule.token(a, &token);
                if (rule.targets.items.len == 0) return error.InvalidLinkReport;
                rule.colon = true;
            },
            ' ', '\t' => try rule.token(a, &token),
            '\n', '\r' => {
                try rule.token(a, &token);
                try rule.complete(&report, a);
            },
            else => try token.append(a, ch),
        }
    }
    try rule.token(a, &token);
    try rule.complete(&report, a);
    return report orelse error.InvalidLinkReport;
}

test "Darwin linker inputs include negative lookup records" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const report = try parse(arena.allocator(), "\x00ld v1\x00\x10/SDK/libSystem.tbd\x00\x11/absent.a\x00\x10/archive with spaces.a\x00\x40/out.dylib\x00", .darwin);
    try std.testing.expectEqualStrings("ld v1", report.version.?);
    try std.testing.expectEqual(@as(usize, 2), report.inputs.len);
    try std.testing.expectEqualStrings("/archive with spaces.a", report.inputs[1]);
    try std.testing.expectEqualStrings("/absent.a", report.missing[0]);
    try std.testing.expectEqualStrings("/out.dylib", report.outputs[0]);
}

test "Darwin reports reject unsupported and incomplete records" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    try std.testing.expectError(error.InvalidLinkReport, parse(a, "", .darwin));
    try std.testing.expectError(error.InvalidLinkReport, parse(a, "\x10input\x00", .darwin));
    try std.testing.expectError(error.TruncatedLinkReport, parse(a, "\x00ld\x00\x10input", .darwin));
    try std.testing.expectError(error.UnsupportedLinkReport, parse(a, "\x00ld\x00\x12input\x00", .darwin));
    try std.testing.expectError(error.InvalidLinkReport, parse(a, "\x00ld\x00\x00ld\x00", .darwin));
    try std.testing.expectError(error.InvalidLinkReport, parse(a, "\x00ld\x00\x10input\x00", .darwin));
    try std.testing.expectError(error.InvalidLinkReport, parse(a, "\x00ld\x00\x10input\x00\x40one\x00\x40two\x00", .darwin));
}

test "ELF Make reports decode escapes and ignore phony targets" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const report = try parse(arena.allocator(), "/out\\ file.so: /lib\\ one.a \\\n /cash$$file.a /hash\\#file.a /colon\\:file.a /slash\\\\file.a\n\n/lib\\ one.a:\n/cash$$file.a:\n", .make);
    try std.testing.expectEqualStrings("/out file.so", report.outputs[0]);
    try std.testing.expectEqual(@as(usize, 5), report.inputs.len);
    try std.testing.expectEqualStrings("/lib one.a", report.inputs[0]);
    try std.testing.expectEqualStrings("/cash$file.a", report.inputs[1]);
    try std.testing.expectEqualStrings("/hash#file.a", report.inputs[2]);
    try std.testing.expectEqualStrings("/colon:file.a", report.inputs[3]);
    try std.testing.expectEqualStrings("/slash\\file.a", report.inputs[4]);
    try std.testing.expectEqual(@as(usize, 0), report.missing.len);
    const crlf = try parse(arena.allocator(), "out: a \\\r\n b\r\n", .make);
    try std.testing.expectEqual(@as(usize, 2), crlf.inputs.len);
    const comment = try parse(arena.allocator(), "# comment\nout: a # comment\n", .make);
    try std.testing.expectEqual(@as(usize, 1), comment.inputs.len);
}

test "ELF reports reject expansion, malformed rules and multiple link rules" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    try std.testing.expectError(error.UnsupportedLinkReport, parse(a, "out: $(FILES)\n", .make));
    try std.testing.expectError(error.TruncatedLinkReport, parse(a, "out: path\\", .make));
    try std.testing.expectError(error.InvalidLinkReport, parse(a, "not a rule\n", .make));
    try std.testing.expectError(error.InvalidLinkReport, parse(a, "out:\n", .make));
    try std.testing.expectError(error.UnsupportedLinkReport, parse(a, "out: one\nother: two\n", .make));
    try std.testing.expectError(error.InvalidLinkReport, parse(a, "out: in\x00put\n", .make));
}

test "LLD raw output paths are accepted only with a known matching destination" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const bytes = "/out, with spaces/libmacro.so: \\\n /lib\\ with\\ spaces/dep.rlib \\\n /native.a\n\n/native.a:\n";
    try std.testing.expectError(error.UnsupportedLinkReport, parse(a, bytes, .make));
    const report = try parseForOutput(a, bytes, .make, "/out, with spaces/libmacro.so");
    try std.testing.expectEqualStrings("/out, with spaces/libmacro.so", report.outputs[0]);
    try std.testing.expectEqualStrings("/lib with spaces/dep.rlib", report.inputs[0]);
    try std.testing.expectError(error.UnsupportedLinkReport, parseForOutput(a, bytes, .make, "/other.so"));
    try std.testing.expectError(error.UnexpectedLinkOutput, parseForOutput(a, "out: a\n", .make, "different"));
    try std.testing.expectError(error.UnsupportedLinkReport, parseForOutput(a, "out with spaces: a\nother: b\n", .make, "out with spaces"));
}
