/* Private macOS prototype transport. Cache logic remains in Zig. */
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <sys/time.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

static FILE *out_file, *err_file;
static int saved_out = -1, saved_err = -1;
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
int nc_worker_listen(const char *path) {
    struct sockaddr_un addr = {0};
    if (strlen(path) >= sizeof(addr.sun_path) || path[0] != '/') return -1;
    char *parent = strdup(path);
    if (!parent) return -1;
    char *slash = strrchr(parent, '/');
    *slash = 0;
    struct stat state;
    int valid = lstat(parent, &state) == 0 && S_ISDIR(state.st_mode) &&
                state.st_uid == getuid() && (state.st_mode & 0777) == 0700;
    free(parent);
    if (!valid) return -1;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    fcntl(fd, F_SETFD, FD_CLOEXEC);
    addr.sun_family = AF_UNIX;
    strlcpy(addr.sun_path, path, sizeof(addr.sun_path));
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) || chmod(path, 0600) || listen(fd, 16)) {
        close(fd); return -1;
    }
    return fd;
}
int nc_worker_accept(int listener) {
    int fd;
    do { fd = accept(listener, NULL, NULL); } while (fd < 0 && errno == EINTR);
    if (fd < 0) return -1;
    fcntl(fd, F_SETFD, FD_CLOEXEC);
    uid_t uid; gid_t gid;
    if (getpeereid(fd, &uid, &gid) || uid != getuid()) { close(fd); return -2; }
    int yes = 1;
    setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &yes, sizeof(yes));
    struct timeval timeout = {.tv_sec = 60};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    return fd;
}
int nc_worker_read(int fd, void *bytes, size_t size) { return exact(fd, bytes, size, 0); }
int nc_worker_capture(void) {
    out_file = tmpfile(); err_file = tmpfile();
    saved_out = dup(1); saved_err = dup(2);
    if (!out_file || !err_file || saved_out < 0 || saved_err < 0) return -1;
    fcntl(saved_out, F_SETFD, FD_CLOEXEC); fcntl(saved_err, F_SETFD, FD_CLOEXEC);
    return dup2(fileno(out_file), 1) < 0 || dup2(fileno(err_file), 2) < 0 ? -1 : 0;
}
int nc_worker_reply(int fd, uint8_t code) {
    if (saved_out >= 0) { dup2(saved_out, 1); close(saved_out); saved_out = -1; }
    if (saved_err >= 0) { dup2(saved_err, 2); close(saved_err); saved_err = -1; }
    long out_len = out_file ? ftell(out_file) : 0;
    long err_len = err_file ? ftell(err_file) : 0;
    // Zig writes directly to the descriptor, bypassing FILE's position cache.
    if (out_file) out_len = lseek(fileno(out_file), 0, SEEK_END);
    if (err_file) err_len = lseek(fileno(err_file), 0, SEEK_END);
    if (out_len < 0 || err_len < 0 || out_len > 64 * 1024 * 1024 || err_len > 64 * 1024 * 1024) code = 200;
    if (code == 200) out_len = err_len = 0; // Caller re-executes normal wrapper.
    uint8_t header[9] = {code};
    for (int i = 0; i < 4; ++i) {
        header[1 + i] = (uint32_t)out_len >> (8 * i);
        header[5 + i] = (uint32_t)err_len >> (8 * i);
    }
    int result = exact(fd, header, sizeof(header), 1);
    FILE *files[] = {out_file, err_file};
    long lengths[] = {out_len, err_len};
    char buffer[65536];
    for (int i = 0; i < 2; ++i) {
        if (!files[i]) continue;
        rewind(files[i]);
        while (result == 0 && lengths[i] > 0) {
            size_t want = lengths[i] < (long)sizeof(buffer) ? (size_t)lengths[i] : sizeof(buffer);
            size_t n = fread(buffer, 1, want, files[i]);
            if (n == 0 || exact(fd, buffer, n, 1)) { result = -1; break; }
            lengths[i] -= (long)n;
        }
        fclose(files[i]);
    }
    out_file = err_file = NULL;
    return result;
}
