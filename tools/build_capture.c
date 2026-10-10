// Native diagnostic wrapper: preserve loader environment and inherited stdin.
// Full stdout/stderr are replayed after child completion; this is not a timing
// benchmark frontend. Each invocation owns its files; no shared append races.
#define _DARWIN_C_SOURCE
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#ifndef REAL_BINARY
#error REAL_BINARY required
#endif
#ifndef CAPTURE_ROOT
#error CAPTURE_ROOT required
#endif
static long long now(clockid_t clock) {
  struct timespec t;
  clock_gettime(clock, &t);
  return (long long)t.tv_sec * 1000000000 + t.tv_nsec;
}
static void quoted(FILE *f, const char *s) {
  fputc('"', f);
  for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
    switch (*p) {
    case '"':
      fputs("\\\"", f);
      break;
    case '\\':
      fputs("\\\\", f);
      break;
    case '\n':
      fputs("\\n", f);
      break;
    case '\r':
      fputs("\\r", f);
      break;
    case '\t':
      fputs("\\t", f);
      break;
    default:
      if (*p < 32)
        fprintf(f, "\\u%04x", *p);
      else
        fputc(*p, f);
    }
  }
  fputc('"', f);
}
static void replay(int file, int target) {
  char b[65536];
  lseek(file, 0, SEEK_SET);
  ssize_t n;
  while ((n = read(file, b, sizeof b)) > 0) {
    ssize_t pos = 0;
    while (pos < n) {
      ssize_t w = write(target, b + pos, n - pos);
      if (w < 0) {
        if (errno == EINTR)
          continue;
        return;
      }
      pos += w;
    }
  }
}
int main(int argc, char **argv) {
  char current[4096], dir[4096], path[8192], cwd[4096];
  snprintf(current, sizeof current, "%s/current", CAPTURE_ROOT);
  FILE *cfg = fopen(current, "r");
  if (!cfg)
    goto fallback;
  if (!fgets(dir, sizeof dir, cfg)) {
    fclose(cfg);
    goto fallback;
  }
  fclose(cfg);
  dir[strcspn(dir, "\r\n")] = 0;
  long long start = now(CLOCK_MONOTONIC), epoch = now(CLOCK_REALTIME);
  snprintf(path, sizeof path, "%s/%ld-%lld.stdout", dir, (long)getpid(), start);
  int out = open(path, O_RDWR | O_CREAT | O_EXCL, 0600);
  if (out < 0)
    goto fallback;
  snprintf(path, sizeof path, "%s/%ld-%lld.stderr", dir, (long)getpid(), start);
  int err = open(path, O_RDWR | O_CREAT | O_EXCL, 0600);
  if (err < 0) {
    close(out);
    goto fallback;
  }
  pid_t child = fork();
  if (child < 0) {
    close(out);
    close(err);
    goto fallback;
  }
  if (child == 0) {
    dup2(out, 1);
    dup2(err, 2);
    close(out);
    close(err);
    argv[0] = REAL_BINARY;
    execv(REAL_BINARY, argv);
    perror("exec compiler wrapper");
    _exit(127);
  }
  int status;
  struct rusage usage;
  while (wait4(child, &status, 0, &usage) < 0) {
    if (errno == EINTR)
      continue;
    close(out);
    close(err);
    return 127;
  }
  long long end = now(CLOCK_MONOTONIC);
  int result = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
  snprintf(path, sizeof path, "%s/%ld-%lld.json", dir, (long)getpid(), start);
  FILE *record = fopen(path, "wx");
  if (record) {
    if (!getcwd(cwd, sizeof cwd))
      cwd[0] = 0;
    fprintf(record,
            "{\"pid\":%ld,\"child_pid\":%ld,\"start_ns\":%lld,\"end_ns\":%lld,"
            "\"epoch_start_ns\":%lld,\"exit_code\":%d,\"user_us\":%lld,"
            "\"system_us\":%lld,\"cwd\":",
            (long)getpid(), (long)child, start, end, epoch, result,
            (long long)usage.ru_utime.tv_sec * 1000000 + usage.ru_utime.tv_usec,
            (long long)usage.ru_stime.tv_sec * 1000000 +
                usage.ru_stime.tv_usec);
    quoted(record, cwd);
    fputs(",\"args\":[", record);
    for (int i = 1; i < argc; i++) {
      if (i > 1)
        fputc(',', record);
      quoted(record, argv[i]);
    }
    fputs("]}\n", record);
    fclose(record);
  }
  replay(out, STDOUT_FILENO);
  replay(err, STDERR_FILENO);
  close(out);
  close(err);
  if (WIFSIGNALED(status)) {
    signal(WTERMSIG(status), SIG_DFL);
    raise(WTERMSIG(status));
  }
  return result;
fallback:
  argv[0] = REAL_BINARY;
  execv(REAL_BINARY, argv);
  perror("exec compiler wrapper");
  return 127;
}
