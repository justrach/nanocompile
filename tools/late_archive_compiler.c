// Deterministic test proxy: publish an unused archive after real rustc exits,
// but before Nano sees compiler completion. Preserve compiler argv/env/streams.
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#ifndef REAL_RUSTC
#error REAL_RUSTC required
#endif
static int copy_archive(void) {
    int src = open(ARCHIVE_SEED, O_RDONLY);
    if (src < 0) return 1;
    int dst = open(ARCHIVE_DEST, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (dst < 0) { close(src); return 1; }
    char buf[16384];
    ssize_t n;
    int failed = 0;
    while ((n = read(src, buf, sizeof buf)) > 0) {
        ssize_t pos = 0;
        while (pos < n) {
            ssize_t written = write(dst, buf + pos, n - pos);
            if (written < 0 && errno == EINTR) continue;
            if (written <= 0) { failed = 1; break; }
            pos += written;
        }
        if (failed) break;
    }
    if (n < 0) failed = 1;
    close(src);
    if (close(dst) < 0) failed = 1;
    return failed;
}
int main(int argc, char **argv) {
    int publish = 0;
    for (int i = 1; i + 1 < argc; ++i)
        if (!strcmp(argv[i], "--crate-name") && !strcmp(argv[i + 1], "top")) publish = 1;
    argv[0] = REAL_RUSTC;
    if (!publish) { execv(REAL_RUSTC, argv); return 127; }
    pid_t child = fork();
    if (child < 0) return 127;
    if (!child) { execv(REAL_RUSTC, argv); _exit(127); }
    int status;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 127;
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    if (!WIFEXITED(status)) return 127;
    int result = WEXITSTATUS(status);
    if (!result && copy_archive()) return 126;
    return result;
}
