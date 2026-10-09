const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const mod = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
    });
    const exe = b.addExecutable(.{ .name = "nanocompile", .root_module = mod });
    b.installArtifact(exe);
    const run = b.addRunArtifact(exe);
    b.step("run", "Run nanocompile").dependOn(&run.step);
    const tests = b.addTest(.{ .root_module = mod });
    b.step("test", "Run unit tests").dependOn(&b.addRunArtifact(tests).step);
    const integration = b.addSystemCommand(&.{ "python3", "tests/integration.py" });
    integration.addArtifactArg(exe);
    b.step("integration", "Exercise real Rust and Zig compilers").dependOn(&integration.step);
}
