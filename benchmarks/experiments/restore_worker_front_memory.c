/* Lightweight experimental client. Misses exec the accepted Zig wrapper. */
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <sys/time.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifndef NC_WORKER_DIR
#define NC_WORKER_DIR "/tmp/nanocompile-restore-worker-service-memory"
#endif
#ifndef NC_FALLBACK
#define NC_FALLBACK "/tmp/nanocompile-restore-worker-service-memory/baseline"
#endif
extern char **environ;
static char *buffer;
static size_t used, capacity;
static int append(const char *p, size_t size) {
    if (used + size > 1024 * 1024) return -1;
    if (used + size > capacity) {
        size_t next = used + size + 8192;
        char *q = realloc(buffer, next);
        if (!q) return -1;
        buffer = q; capacity = next;
    }
    memcpy(buffer + used, p, size); used += size;
    return 0;
}
static int text(const char *p) { return append(p, strlen(p)); }
static int quote(const char *p, size_t size) {
    if (text("\"")) return -1;
    for (size_t i = 0; i < size; ++i) {
        unsigned char ch = p[i];
        if (ch == '"' || ch == '\\') { if (append("\\", 1)) return -1; }
        if (ch < 32) {
            char escaped[7]; snprintf(escaped, sizeof(escaped), "\\u%04x", ch);
            if (append(escaped, 6)) return -1;
        } else if (append(p + i, 1)) return -1;
    }
    return text("\"");
}
static int frame(int argc, char **argv) {
    char *cwd = getcwd(NULL, 0);
    if (!cwd) return -1;
    int result = text("{\"argv\":[");
    for (int i = 0; result == 0 && i < argc; ++i) {
        if (i) result = text(",");
        if (!result) result = quote(argv[i], strlen(argv[i]));
    }
    if (!result) result = text("],\"cwd\":");
    if (!result) result = quote(cwd, strlen(cwd));
    free(cwd);
    if (!result) result = text(",\"env\":[");
    int count = 0;
    for (char **env = environ; !result && *env; ++env) {
        char *eq = strchr(*env, '=');
        if (!eq) continue;
        if (count++) result = text(",");
        if (!result) result = text("[");
        if (!result) result = quote(*env, (size_t)(eq - *env));
        if (!result) result = text(",");
        if (!result) result = quote(eq + 1, strlen(eq + 1));
        if (!result) result = text("]");
    }
    if (!result) result = text("]}");
    return result;
}
static int exact(int fd, void *data, size_t size, int writing) {
    char *p = data;
    while (size) {
        ssize_t n = writing ? write(fd, p, size) : read(fd, p, size);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n; size -= (size_t)n;
    }
    return 0;
}
static uint32_t number(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static int request(int fd) {
    uint8_t header[9];
    for (int i = 0; i < 4; ++i) header[i] = (uint32_t)used >> (8 * i);
    if (exact(fd, header, 4, 1) || exact(fd, buffer, used, 1) || exact(fd, header, 9, 0)) return -1;
    uint32_t out_size = number(header + 1), err_size = number(header + 5);
    if (header[0] == 200 || out_size > 64 * 1024 * 1024 || err_size > 64 * 1024 * 1024) return -1;
    char *out = malloc(out_size ? out_size : 1), *err = malloc(err_size ? err_size : 1);
    if (!out || !err) { free(out); free(err); return -1; }
    // Buffer the complete reply before forwarding any bytes; a failed service
    // can fall back without duplicating part of a diagnostic stream.
    int result = exact(fd, out, out_size, 0) || exact(fd, err, err_size, 0);
    if (result) { free(out); free(err); return -1; }
    result = exact(1, out, out_size, 1) || exact(2, err, err_size, 1);
    free(out); free(err);
    return result ? 1 : header[0]; // Output failure must not replay partial bytes.
}
static int fallback(char **argv) {
    const char *path = getenv("NANOCOMPILE_FALLBACK");
    if (!path) path = NC_FALLBACK;
    if (path[0] != '/') return 1;
    execv(path, argv);
    perror("nanocompile experimental fallback");
    return 1;
}
static int obvious_fallback(int argc, char **argv) {
    if (argc < 2) return 1;
    const char *disabled = getenv("NANOCOMPILE_DISABLE");
    if (disabled && strcmp(disabled, "1") == 0) return 1;
    const char *name = strrchr(argv[1], '/');
    name = name ? name + 1 : argv[1];
    if (strcmp(name, "zig") == 0) return 0;
    if (strcmp(name, "rustc") != 0) return 1;
    for (int i = 2; i < argc; ++i) {
        const char *type = NULL;
        if (strcmp(argv[i], "--crate-type") == 0 && i + 1 < argc) type = argv[i + 1];
        if (strncmp(argv[i], "--crate-type=", 13) == 0) type = argv[i] + 13;
        if (type && (strcmp(type, "bin") == 0 || strcmp(type, "proc-macro") == 0 || strcmp(type, "proc_macro") == 0)) return 1;
        if (strcmp(argv[i], "-vV") == 0 || strcmp(argv[i], "-V") == 0 || strcmp(argv[i], "--version") == 0 ||
            strcmp(argv[i], "--print") == 0 || strncmp(argv[i], "--print=", 8) == 0) return 1;
    }
    return 0;
}
int main(int argc, char **argv) {
    if (obvious_fallback(argc, argv)) return fallback(argv);
    const char *root = getenv("NANOCOMPILE_WORKER_DIR");
    if (!root) root = NC_WORKER_DIR;
    struct stat state;
    if (argc < 2 || lstat(root, &state) || !S_ISDIR(state.st_mode) ||
        state.st_uid != getuid() || (state.st_mode & 0777) != 0700 || frame(argc, argv)) return fallback(argv);
    struct timespec started, now;
    clock_gettime(CLOCK_MONOTONIC, &started);
    for (;;) {
        int available = 0;
        int free_slot = 0;
        for (int i = 0; i < 4; ++i) {
            char path[1024];
            if (snprintf(path, sizeof(path), "%s/%d.lock", root, i) >= (int)sizeof(path)) return fallback(argv);
            int lock = open(path, O_RDWR | O_CLOEXEC | O_NOFOLLOW);
            if (lock < 0) continue;
            if (fstat(lock, &state) || !S_ISREG(state.st_mode) || state.st_uid != getuid() || (state.st_mode & 0777) != 0600) { close(lock); continue; }
            available++;
            if (flock(lock, LOCK_EX | LOCK_NB)) { close(lock); continue; }
            free_slot = 1;
            struct sockaddr_un addr = {0}; addr.sun_family = AF_UNIX;
            if (snprintf(addr.sun_path, sizeof(addr.sun_path), "%s/%d.sock", root, i) >= (int)sizeof(addr.sun_path)) { close(lock); return fallback(argv); }
            int fd = socket(AF_UNIX, SOCK_STREAM, 0);
            if (fd < 0) { close(lock); continue; }
            fcntl(fd, F_SETFD, FD_CLOEXEC);
            int yes = 1; setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &yes, sizeof(yes));
            struct timeval timeout = {.tv_sec = 60};
            setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
            uid_t uid; gid_t gid;
            int valid = connect(fd, (struct sockaddr *)&addr, sizeof(addr)) == 0 &&
                        getpeereid(fd, &uid, &gid) == 0 && uid == getuid();
            int code = valid ? request(fd) : -1;
            close(fd); close(lock);
            if (valid) return code < 0 ? fallback(argv) : code;
        }
        if (!available || free_slot) return fallback(argv);
        clock_gettime(CLOCK_MONOTONIC, &now);
        if (now.tv_sec - started.tv_sec >= 5) return fallback(argv);
        // Contended live workers are bounded by the caller's Cargo jobs. A
        // missing service with leftover locks should not spin forever.
        int live = 0;
        for (int i = 0; i < 4; ++i) {
            char path[1024]; snprintf(path, sizeof(path), "%s/%d.sock", root, i);
            if (lstat(path, &state) == 0 && S_ISSOCK(state.st_mode)) live++;
        }
        if (!live) return fallback(argv);
        usleep(100);
    }
}
