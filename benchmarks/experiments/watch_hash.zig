//! Experimental macOS/APFS digest worker. No production cache integration.
//! Private inherited pipes carry bounded length-prefixed JSON batches.
//! REJECTED: writes through an already-dirty writable mmap can change bytes
//! without a new vnode event or metadata change. Do not use for cache validation.
const std = @import("std");
const c = std.c;
extern "c" fn nanocompile_local_apfs(fd: c_int) c_int;
const max_frame = 1024 * 1024;
const max_entries = 4096;
const notes = c.NOTE.DELETE | c.NOTE.WRITE | c.NOTE.EXTEND | c.NOTE.ATTRIB |
    c.NOTE.LINK | c.NOTE.RENAME | c.NOTE.REVOKE;

const Entry = struct { path: [:0]u8, fd: c_int, token: usize, state: c.Stat, hash: [64]u8, dirty: bool = false };
const Result = struct { hash: ?[]const u8 = null, reused: bool = false, watched: bool = false, failure: ?[]const u8 = null };
const Request = struct { mode: enum { watch, full, reset, lose_queue }, paths: []const []const u8 = &.{} };

fn same(a: c.Stat, b: c.Stat) bool {
    return a.dev == b.dev and a.ino == b.ino and a.mode == b.mode and a.nlink == b.nlink and
        a.gen == b.gen and a.flags == b.flags and a.size == b.size and
        a.mtime().sec == b.mtime().sec and a.mtime().nsec == b.mtime().nsec and
        a.ctime().sec == b.ctime().sec and a.ctime().nsec == b.ctime().nsec;
}
fn fdState(fd: c_int) !c.Stat {
    var state: c.Stat = undefined;
    if (c.fstat(fd, &state) != 0) return error.StatFailed;
    if (state.mode & c.S.IFMT != c.S.IFREG) return error.NotRegularFile;
    return state;
}
fn pathState(path: [:0]const u8) !c.Stat {
    var state: c.Stat = undefined;
    if (c.stat(path, &state) != 0) return error.PathStatFailed;
    return state;
}

const Worker = struct {
    a: std.mem.Allocator,
    queue: c_int,
    entries: [max_entries]?Entry = @splat(null),
    paths: std.StringHashMapUnmanaged(usize) = .empty,
    next_slot: usize = 0,
    next_token: usize = 1,
    capacity: usize,
    invalidations: usize = 0,
    bytes_hashed: u64 = 0,

    fn remove(self: *Worker, slot: usize) void {
        if (self.entries[slot]) |entry| {
            _ = self.paths.remove(entry.path);
            _ = c.close(entry.fd); // Closing removes its kevent.
            self.a.free(entry.path);
            self.entries[slot] = null;
        }
    }
    fn clear(self: *Worker) void {
        for (0..self.capacity) |slot| self.remove(slot);
    }
    fn disable(self: *Worker) void {
        self.clear();
        if (self.queue >= 0) _ = c.close(self.queue);
        self.queue = -1;
    }
    // Tokens never repeat within the worker lifetime. Queued old fd events
    // cannot accidentally invalidate or validate a newly recycled descriptor.
    fn drain(self: *Worker, pending: ?usize) !bool {
        if (self.queue < 0) return error.WatchUnavailable;
        var changed = false;
        const no_changes: [0]c.Kevent = .{};
        const zero: c.timespec = .{ .sec = 0, .nsec = 0 };
        var events: [64]c.Kevent = undefined;
        // Bound work even under continuously mutating files; never reuse on
        // queue errors, unfamiliar flags/filters, or an undrainable queue.
        for (0..16) |_| {
            const n = c.kevent(self.queue, &no_changes, 0, &events, events.len, &zero);
            if (n < 0) return error.WatchPollFailed;
            if (n == 0) return changed;
            for (events[0..@intCast(n)]) |event| {
                if (event.filter != c.EVFILT.VNODE or event.flags & (c.EV.ERROR | c.EV.EOF) != 0)
                    return error.WatchLost;
                if (pending != null and event.udata == pending.?) changed = true;
                for (self.entries[0..self.capacity]) |*slot| {
                    if (slot.*) |*entry| if (entry.token == event.udata) {
                        if (!entry.dirty) self.invalidations += 1;
                        entry.dirty = true;
                    };
                }
            }
        }
        return error.WatchQueueBusy;
    }
    fn pollOrDisable(self: *Worker) void {
        _ = self.drain(null) catch {
            self.disable();
            return;
        };
    }
    fn hash(self: *Worker, a: std.mem.Allocator, path_: []const u8, watch: bool) !Result {
        if (!std.fs.path.isAbsolute(path_) or path_.len > 4096 or std.mem.indexOfScalar(u8, path_, 0) != null)
            return error.InvalidPath;
        const path = try a.dupeSentinel(u8, path_, 0);
        if (watch and self.queue >= 0) {
            self.pollOrDisable();
            reuse: {
                if (self.paths.get(path_)) |i| {
                    const entry = self.entries[i].?;
                    const held = fdState(entry.fd) catch {
                        self.remove(i);
                        break :reuse;
                    };
                    const named = pathState(path) catch {
                        self.remove(i);
                        break :reuse;
                    };
                    if (entry.dirty or !same(held, entry.state) or !same(named, entry.state)) {
                        self.remove(i);
                        break :reuse;
                    }
                    self.pollOrDisable();
                    if (self.entries[i]) |current| {
                        if (!current.dirty) return .{ .hash = try a.dupe(u8, &current.hash), .reused = true, .watched = true };
                    }
                    self.remove(i);
                }
            }
        }
        const fd = c.open(path, .{ .CLOEXEC = true, .NONBLOCK = true });
        if (fd < 0) return error.OpenFailed;
        var retained = false;
        defer if (!retained) {
            _ = c.close(fd);
        };
        const before = try fdState(fd);
        if (!same(before, try pathState(path))) return error.InputChanged;
        var token: ?usize = null;
        if (watch and self.queue >= 0 and nanocompile_local_apfs(fd) != 0) {
            if (self.next_token == std.math.maxInt(usize)) self.disable() else {
                const id = self.next_token;
                self.next_token += 1;
                const event: [1]c.Kevent = .{.{ .ident = @intCast(fd), .filter = c.EVFILT.VNODE, .flags = c.EV.ADD | c.EV.CLEAR, .fflags = notes, .data = 0, .udata = id }};
                var no_events: [0]c.Kevent = .{};
                const zero: c.timespec = .{ .sec = 0, .nsec = 0 };
                if (c.kevent(self.queue, &event, 1, &no_events, 0, &zero) < 0) self.disable() else token = id;
            }
        }
        // Watch registration precedes the first read on this SAME descriptor.
        var h = std.crypto.hash.Blake3.init(.{});
        var buffer: [64 * 1024]u8 = undefined;
        while (true) {
            const n = c.read(fd, &buffer, buffer.len);
            if (n < 0) return error.ReadFailed;
            if (n == 0) break;
            h.update(buffer[0..@intCast(n)]);
            self.bytes_hashed +|= @intCast(n);
        }
        const after = try fdState(fd);
        if (!same(before, after) or !same(after, try pathState(path))) return error.InputChanged;
        if (token) |id| {
            const changed = self.drain(id) catch blk: {
                self.disable();
                token = null;
                break :blk false;
            };
            if (changed) return error.InputChanged;
        }
        var raw: [32]u8 = undefined;
        h.final(&raw);
        const hex = std.fmt.bytesToHex(raw, .lower);
        if (token) |id| {
            const slot = self.next_slot;
            self.next_slot = (slot + 1) % self.capacity;
            self.remove(slot);
            self.entries[slot] = .{ .path = try self.a.dupeSentinel(u8, path_, 0), .fd = fd, .token = id, .state = after, .hash = hex };
            self.paths.putAssumeCapacity(self.entries[slot].?.path, slot);
            retained = true;
        }
        return .{ .hash = try a.dupe(u8, &hex), .watched = retained };
    }
};

fn readExact(bytes: []u8) !bool {
    var offset: usize = 0;
    while (offset < bytes.len) {
        const n = c.read(0, bytes[offset..].ptr, bytes.len - offset);
        if (n < 0) return error.PipeReadFailed;
        if (n == 0) {
            if (offset == 0) return false;
            return error.TruncatedFrame;
        }
        offset += @intCast(n);
    }
    return true;
}
fn writeAll(bytes: []const u8) !void {
    var offset: usize = 0;
    while (offset < bytes.len) {
        const n = c.write(1, bytes[offset..].ptr, bytes.len - offset);
        if (n <= 0) return error.PipeWriteFailed;
        offset += @intCast(n);
    }
}

pub fn main(init: std.process.Init) !void {
    if (@import("builtin").os.tag != .macos) @compileError("This experiment requires macOS");
    const args = try init.minimal.args.toSlice(init.arena.allocator());
    const capacity = if (args.len == 2) try std.fmt.parseInt(usize, args[1], 10) else 256;
    if (capacity == 0 or capacity > max_entries) return error.InvalidCapacity;
    var worker: Worker = .{ .a = std.heap.page_allocator, .queue = c.kqueue(), .capacity = capacity };
    try worker.paths.ensureTotalCapacity(worker.a, @intCast(capacity));
    defer worker.paths.deinit(worker.a);
    defer worker.disable();
    while (true) {
        var header: [4]u8 = undefined;
        if (!try readExact(&header)) break;
        const len = std.mem.readInt(u32, &header, .little);
        if (len == 0 or len > max_frame) return error.FrameTooLarge;
        var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
        defer arena.deinit();
        const a = arena.allocator();
        const payload = try a.alloc(u8, len);
        if (!try readExact(payload)) return error.TruncatedFrame;
        const request = try std.json.parseFromSlice(Request, a, payload, .{});
        if (request.value.paths.len > 4096) return error.TooManyPaths;
        const start = std.Io.Clock.awake.now(init.io).nanoseconds;
        if (request.value.mode == .reset) worker.clear();
        if (request.value.mode == .lose_queue) worker.disable();
        const results = try a.alloc(Result, request.value.paths.len);
        for (request.value.paths, results) |path, *result| {
            result.* = worker.hash(a, path, request.value.mode == .watch) catch |err| .{ .failure = @errorName(err) };
        }
        var resident: usize = 0;
        for (worker.entries) |entry| {
            if (entry != null) resident += 1;
        }
        const response = try std.json.Stringify.valueAlloc(a, .{ .results = results, .nanoseconds = std.Io.Clock.awake.now(init.io).nanoseconds - start, .resident = resident, .invalidations = worker.invalidations, .bytes_hashed = worker.bytes_hashed, .watch_available = worker.queue >= 0 }, .{});
        if (response.len > max_frame) return error.ResponseTooLarge;
        std.mem.writeInt(u32, &header, @intCast(response.len), .little);
        try writeAll(&header);
        try writeAll(response);
    }
}
