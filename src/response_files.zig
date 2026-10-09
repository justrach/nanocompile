//! GNU-style compiler-driver response files, captured before final linking.
//! Uses LLVM/GCC quote/backslash conventions, not a POSIX shell. Unsupported
//! encodings, ambiguous syntax or recursion decline discovery.
const std = @import("std");
const cache = @import("cache.zig");

pub const Stamp = struct {
    inode: u64 = 0,
    size: u64 = 0,
    mtime: i96 = 0,
    ctime: i96 = 0,
    kind: std.Io.File.Kind = .unknown,
};
pub const Response = struct { path: []const u8, bytes: []const u8, stamp: Stamp = .{}, unchanged: bool = false };

fn stamp(ctx: *cache.Context, path: []const u8) !Stamp {
    const st = try std.Io.Dir.cwd().statFile(ctx.io, path, .{});
    if (st.kind != .file) return error.UnsupportedResponseFile;
    return .{ .inode = @intCast(st.inode), .size = st.size, .mtime = st.mtime.nanoseconds, .ctime = st.ctime.nanoseconds, .kind = st.kind };
}

fn equal(a: Stamp, b: Stamp) bool {
    return a.inode == b.inode and a.size == b.size and a.mtime == b.mtime and a.ctime == b.ctime and a.kind == b.kind;
}
pub const Capture = struct {
    ctx: *cache.Context,
    expanded: std.ArrayList([]const u8) = .empty,
    responses: std.ArrayList(Response) = .empty,
    active: std.ArrayList([]const u8) = .empty,
    bytes: usize = 0,

    pub fn append(self: *Capture, args: []const []const u8) !void {
        for (args) |arg| {
            if (self.expanded.items.len >= 262144) return error.ResponseLimit;
            if (!std.mem.startsWith(u8, arg, "@")) {
                try self.expanded.append(self.ctx.a, arg);
                continue;
            }
            if (self.active.items.len >= 16 or self.responses.items.len >= 256) return error.ResponseLimit;
            const path = try std.fs.path.resolve(self.ctx.a, &.{ self.ctx.cwd, arg[1..] });
            for (self.active.items) |current| if (std.mem.eql(u8, current, path)) return error.RecursiveResponse;
            const before = try stamp(self.ctx, path);
            const bytes = try self.ctx.read(path);
            if (!equal(before, try stamp(self.ctx, path))) return error.ResponseChanged;
            self.bytes += bytes.len;
            if (self.bytes > 64 * 1024 * 1024) return error.ResponseLimit;
            const tokens = try tokenize(self.ctx.a, bytes);
            try self.responses.append(self.ctx.a, .{ .path = path, .bytes = bytes, .stamp = before });
            try self.active.append(self.ctx.a, path);
            defer _ = self.active.pop();
            try self.append(tokens);
        }
    }

    pub fn validate(self: *Capture) bool {
        var valid = true;
        for (self.responses.items) |*response| {
            const before = stamp(self.ctx, response.path) catch {
                valid = false;
                continue;
            };
            const current = self.ctx.read(response.path) catch {
                valid = false;
                continue;
            };
            const after = stamp(self.ctx, response.path) catch {
                valid = false;
                continue;
            };
            response.unchanged = equal(response.stamp, before) and equal(before, after) and std.mem.eql(u8, response.bytes, current);
            valid = valid and response.unchanged;
        }
        return valid;
    }
};

pub fn tokenize(a: std.mem.Allocator, bytes: []const u8) ![]const []const u8 {
    if (std.mem.indexOfScalar(u8, bytes, 0) != null or !std.unicode.utf8ValidateSlice(bytes) or
        std.mem.startsWith(u8, bytes, "\xef\xbb\xbf")) return error.UnsupportedResponseEncoding;
    var tokens: std.ArrayList([]const u8) = .empty;
    var token: std.ArrayList(u8) = .empty;
    var active = false;
    var quote: ?u8 = null;
    var i: usize = 0;
    while (i < bytes.len) : (i += 1) {
        const ch = bytes[i];
        if (ch == '\\') {
            i += 1;
            if (i == bytes.len) return error.TruncatedResponse;
            active = true;
            try token.append(a, bytes[i]);
        } else if (quote) |delimiter| {
            if (ch == delimiter) quote = null else try token.append(a, ch);
        } else if (ch == '\'' or ch == '"') {
            quote = ch;
            active = true;
        } else if (std.mem.indexOfScalar(u8, " \t\r\n", ch) != null) {
            if (active) {
                if (tokens.items.len >= 262144) return error.ResponseLimit;
                try tokens.append(a, try a.dupe(u8, token.items));
                token.clearRetainingCapacity();
                active = false;
            }
        } else {
            active = true;
            try token.append(a, ch);
        }
    }
    if (quote != null) return error.TruncatedResponse;
    if (active) try tokens.append(a, try a.dupe(u8, token.items));
    return tokens.toOwnedSlice(a);
}

test "GNU response quotes, adjacent fragments and empty arguments" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const args = try tokenize(arena.allocator(), " 'one two.o' \"three four.o\" five\\ six.o '' a\"b c\" 'escaped\\'quote' \r\n");
    try std.testing.expectEqual(@as(usize, 6), args.len);
    try std.testing.expectEqualStrings("one two.o", args[0]);
    try std.testing.expectEqualStrings("three four.o", args[1]);
    try std.testing.expectEqualStrings("five six.o", args[2]);
    try std.testing.expectEqualStrings("", args[3]);
    try std.testing.expectEqualStrings("ab c", args[4]);
    try std.testing.expectEqualStrings("escaped'quote", args[5]);
}

test "ambiguous and non-GNU response encodings decline discovery" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    try std.testing.expectError(error.TruncatedResponse, tokenize(a, "'unterminated"));
    try std.testing.expectError(error.TruncatedResponse, tokenize(a, "trailing\\"));
    try std.testing.expectError(error.UnsupportedResponseEncoding, tokenize(a, "\xff\xfeinput"));
    try std.testing.expectError(error.UnsupportedResponseEncoding, tokenize(a, "in\x00put"));
    try std.testing.expectError(error.UnsupportedResponseEncoding, tokenize(a, "\xef\xbb\xbfinput"));
}
