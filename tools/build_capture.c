// Native diagnostic wrapper: preserve loader environment and inherited stdin.
// Streams are forwarded live and retained exactly; this remains a diagnostic
// frontend with logging overhead. Each invocation owns its files; no shared append races.
#define _DARWIN_C_SOURCE
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <poll.h>
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
static int write_all(int fd, const char *bytes, ssize_t size) {
  ssize_t pos = 0;
  while (pos < size) {
    ssize_t n = write(fd, bytes + pos, size - pos);
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) return 0;
    pos += n;
  }
  return 1;
}
static int tee_streams(int *fds, int *logs, FILE *chunks) {
  struct pollfd streams[2] = {{fds[0], POLLIN, 0}, {fds[1], POLLIN, 0}};
  long long offsets[2] = {0, 0};
  int remaining = 2, complete = 1;
  char bytes[16384];
  while (remaining) {
    int ready = poll(streams, 2, -1);
    if (ready < 0 && errno == EINTR) continue;
    if (ready < 0) { complete = 0; break; }
    for (int i = 0; i < 2; ++i) {
      if (streams[i].fd < 0 || !streams[i].revents) continue;
      ssize_t n = read(streams[i].fd, bytes, sizeof bytes);
      if (n < 0 && errno == EINTR) continue;
      if (n <= 0) {
        if (n < 0) complete = 0;
        close(streams[i].fd); streams[i].fd = -1; --remaining;
        continue;
      }
      long long arrival = now(CLOCK_MONOTONIC);
      if (!write_all(logs[i], bytes, n)) complete = 0;
      if (fprintf(chunks, "%d,%lld,%lld,%lld\n", i, offsets[i], (long long)n, arrival) < 0) complete = 0;
      offsets[i] += n;
      if (!write_all(i == 0 ? STDOUT_FILENO : STDERR_FILENO, bytes, n)) {
        complete = 0;
        close(streams[i].fd); streams[i].fd = -1; --remaining;
      }
    }
  }
  for (int i = 0; i < 2; ++i) if (streams[i].fd >= 0) close(streams[i].fd);
  return complete;
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
  int output_pipe[2], error_pipe[2];
  if (pipe(output_pipe) < 0) { close(out); close(err); goto fallback; }
  if (pipe(error_pipe) < 0) {
    close(output_pipe[0]); close(output_pipe[1]); close(out); close(err); goto fallback;
  }
  snprintf(path, sizeof path, "%s/%ld-%lld.chunks", dir, (long)getpid(), start);
  FILE *chunks = fopen(path, "wx");
  if (!chunks) {
    close(output_pipe[0]); close(output_pipe[1]); close(error_pipe[0]); close(error_pipe[1]); close(out); close(err); goto fallback;
  }
  pid_t child = fork();
  if (child < 0) {
    fclose(chunks);
    close(output_pipe[0]); close(output_pipe[1]); close(error_pipe[0]); close(error_pipe[1]);
    close(out);
    close(err);
    goto fallback;
  }
  if (child == 0) {
    dup2(output_pipe[1], 1);
    dup2(error_pipe[1], 2);
    close(output_pipe[0]); close(output_pipe[1]); close(error_pipe[0]); close(error_pipe[1]);
    fclose(chunks);
    close(out);
    close(err);
    argv[0] = REAL_BINARY;
    execv(REAL_BINARY, argv);
    perror("exec compiler wrapper");
    _exit(127);
  }
  close(output_pipe[1]); close(error_pipe[1]);
  int input_fds[2] = {output_pipe[0], error_pipe[0]}, log_fds[2] = {out, err};
  int complete = tee_streams(input_fds, log_fds, chunks);
  if (fclose(chunks)) complete = 0;
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
    fprintf(record, "],\"streaming_capture\":true,\"capture_complete\":%s}\n", complete ? "true" : "false");
    fclose(record);
  }
  close(out);
  close(err);
  if (WIFSIGNALED(status)) {
    signal(WTERMSIG(status), SIG_DFL);
    raise(WTERMSIG(status));
  }
  return complete ? result : 127;
fallback:
  argv[0] = REAL_BINARY;
  execv(REAL_BINARY, argv);
  perror("exec compiler wrapper");
  return 127;
}
