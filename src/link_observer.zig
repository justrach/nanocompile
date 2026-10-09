//! Private final-link observer used by producer discovery. It inherits the
//! original environment and delegates to the explicitly selected driver.
//! Parent-side driver/SDK identity and scratch ownership remain separate gates.
const std = @import("std");
const cache = @import("cache.zig");
const deps = @import("link_dependencies.zig");
const responses = @import("response_files.zig");

pub const Config = struct {
    driver: []const u8,
    format: deps.Format,
    report: []const u8,
    invocation: []const u8,
    capture_id: ?[]const u8 = null,
};

pub const Invocation = struct {
    schema: u32,
    capture_id: ?[]const u8 = null,
    cwd: []const u8,
    driver: []const u8,
    args: []const []const u8,
    expanded_args: []const []const u8,
    responses: []const responses.Response,
    capture_valid: bool,
    capture_error: ?[]const u8 = null,
};

/// Parent discovery must bind completed records to its fresh capture identity.
pub fn parseInvocation(ctx: *cache.Context, config: Config, bytes: []const u8) !Invocation {
    const id = config.capture_id orelse return error.UnboundLinkCapture;
    if (id.len == 0) return error.UnboundLinkCapture;
    const parsed = try std.json.parseFromSlice(Invocation, ctx.a, try cache.unseal(ctx, bytes), .{ .allocate = .alloc_always });
    const record = parsed.value;
    if (record.schema != 1 or !record.capture_valid or record.capture_error != null) return error.InvalidLinkCapture;
    if (!std.mem.eql(u8, record.capture_id orelse return error.UnboundLinkCapture, id) or
        !std.mem.eql(u8, record.cwd, ctx.cwd) or !std.mem.eql(u8, record.driver, config.driver)) return error.UnboundLinkCapture;
    for (record.responses) |response| if (!response.unchanged or !std.fs.path.isAbsolute(response.path) or
        response.stamp.kind != .file or response.stamp.size != response.bytes.len) return error.InvalidLinkCapture;
    return record;
}

pub fn execute(ctx: *cache.Context, config_path: []const u8, args: []const []const u8) !u8 {
    if (!std.fs.path.isAbsolute(config_path) or args.len == 0) return error.InvalidLinkObserver;
    const bytes = try ctx.read(config_path);
    const parsed = try std.json.parseFromSlice(Config, ctx.a, bytes, .{ .allocate = .alloc_always });
    const config = parsed.value;
    for ([_][]const u8{ config.driver, config.report, config.invocation }) |path|
        if (!std.fs.path.isAbsolute(path)) return error.InvalidLinkObserver;
    if (std.mem.eql(u8, config.report, config.invocation) or std.mem.eql(u8, config_path, config.report) or
        std.mem.eql(u8, config_path, config.invocation)) return error.InvalidLinkObserver;
    var command: std.ArrayList([]const u8) = .empty;
    try command.append(ctx.a, config.driver);
    try command.appendSlice(ctx.a, args);
    // Separate driver arguments preserve paths containing commas or spaces.
    switch (config.format) {
        .darwin => try command.appendSlice(ctx.a, &.{ "-Xlinker", "-dependency_info", "-Xlinker", config.report }),
        .make => try command.appendSlice(ctx.a, &.{ "-Xlinker", try std.fmt.allocPrint(ctx.a, "--dependency-file={s}", .{config.report}) }),
    }
    var capture: responses.Capture = .{ .ctx = ctx };
    var capture_valid = true;
    var capture_error: ?[]const u8 = null;
    capture.append(args) catch |err| {
        capture_valid = false;
        capture_error = @errorName(err);
    };
    // Discovery failure must not change the driver's compilation behavior.
    // Parent discovery must require a fresh, sealed and valid completed record.
    std.Io.Dir.cwd().deleteFile(ctx.io, config.invocation) catch {};
    var child = try std.process.spawn(ctx.io, .{ .argv = command.items, .environ_map = ctx.env });
    const term = try child.wait(ctx.io);
    const code: u8 = switch (term) {
        .exited => |status| status,
        .signal => |signal| @intCast(@min(255, 128 + @as(u32, @backingInt(signal)))),
        else => 1,
    };
    capture_valid = capture.validate() and capture_valid;
    const record = std.json.Stringify.valueAlloc(ctx.a, Invocation{ .schema = 1, .capture_id = config.capture_id, .cwd = ctx.cwd, .driver = config.driver, .args = args, .expanded_args = capture.expanded.items, .responses = capture.responses.items, .capture_valid = capture_valid, .capture_error = capture_error }, .{}) catch return code;
    const sealed = cache.seal(ctx, record) catch return code;
    ctx.atomic(config.invocation, sealed) catch {};
    return code;
}

test "parent rejects stale, corrupt and incomplete linker captures" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var env = std.process.Environ.Map.init(a);
    var ctx: cache.Context = .{ .a = a, .io = std.testing.io, .env = &env, .root = "/cache", .cwd = "/project" };
    const config: Config = .{ .driver = "/driver", .format = .darwin, .report = "/report", .invocation = "/record", .capture_id = "fresh-id" };
    var record: Invocation = .{ .schema = 1, .cwd = ctx.cwd, .driver = config.driver, .args = &.{"input.o"}, .expanded_args = &.{"input.o"}, .responses = &.{}, .capture_valid = true, .capture_id = config.capture_id };
    const payload = try std.json.Stringify.valueAlloc(a, record, .{});
    const sealed = try cache.seal(&ctx, payload);
    _ = try parseInvocation(&ctx, config, sealed);
    var stale = config;
    stale.capture_id = "old-id";
    try std.testing.expectError(error.UnboundLinkCapture, parseInvocation(&ctx, stale, sealed));
    const corrupt = try a.dupe(u8, sealed);
    corrupt[0] = if (corrupt[0] == '0') '1' else '0';
    try std.testing.expectError(error.InvalidEntry, parseInvocation(&ctx, config, corrupt));
    record.capture_valid = false;
    const incomplete = try cache.seal(&ctx, try std.json.Stringify.valueAlloc(a, record, .{}));
    try std.testing.expectError(error.InvalidLinkCapture, parseInvocation(&ctx, config, incomplete));
    record.capture_valid = true;
    record.responses = &.{.{ .path = "/input.rsp", .bytes = "input.o", .unchanged = false }};
    const changed = try cache.seal(&ctx, try std.json.Stringify.valueAlloc(a, record, .{}));
    try std.testing.expectError(error.InvalidLinkCapture, parseInvocation(&ctx, config, changed));
}
