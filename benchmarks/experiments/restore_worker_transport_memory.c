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
int nc_worker_reply_memory(int fd, uint8_t code, const uint8_t *out, size_t out_len,
                           const uint8_t *err, size_t err_len) {
    if (out_len > 64 * 1024 * 1024 || err_len > 64 * 1024 * 1024) code = 200;
    if (code == 200) out_len = err_len = 0;
    uint8_t header[9] = {code};
    for (int i = 0; i < 4; ++i) {
        header[1 + i] = (uint32_t)out_len >> (8 * i);
        header[5 + i] = (uint32_t)err_len >> (8 * i);
    }
    if (exact(fd, header, sizeof(header), 1)) return -1;
    if (exact(fd, (void *)out, out_len, 1)) return -1;
    return exact(fd, (void *)err, err_len, 1);
}
