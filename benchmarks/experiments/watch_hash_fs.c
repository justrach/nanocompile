/* Experimental probe only: use the SDK's actual statfs ABI. */
#include <sys/mount.h>
#include <string.h>

int nanocompile_local_apfs(int fd) {
    struct statfs fs;
    if (fstatfs(fd, &fs) != 0) return 0;
    return (fs.f_flags & MNT_LOCAL) &&
           strncmp(fs.f_fstypename, "apfs", sizeof(fs.f_fstypename)) == 0;
}
