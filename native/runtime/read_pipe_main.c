#define SCAR_IO_TIMEOUT_SECONDS 7.5

static double __scar_io_monotonic_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static Result_str scar_read_pipe(int32_t fd) {
@@CHEQUEO_FD@@    double __scar_deadline = __scar_io_monotonic_now() + SCAR_IO_TIMEOUT_SECONDS;
    for (;;) {
        double __scar_remaining = __scar_deadline - __scar_io_monotonic_now();
        if (__scar_remaining <= 0) {
            scar_panic_main("read_pipe: timeout de I/O (%.1fs) sin datos en fd=%d",
                (double)SCAR_IO_TIMEOUT_SECONDS, fd);
        }
        double __scar_step = __scar_remaining < 0.02 ? __scar_remaining : 0.02;
        struct timeval __scar_tv;
        __scar_tv.tv_sec = (time_t)__scar_step;
        __scar_tv.tv_usec = (long)((__scar_step - (double)__scar_tv.tv_sec) * 1e6);
        fd_set __scar_fdset;
        FD_ZERO(&__scar_fdset);
        FD_SET(fd, &__scar_fdset);
        int __scar_rc = select(fd + 1, &__scar_fdset, NULL, NULL, &__scar_tv);
@@CHEQUEO_SELECT@@        if (__scar_rc > 0 && FD_ISSET(fd, &__scar_fdset)) {
            char __scar_buf[4096];
            ssize_t __scar_n = read(fd, __scar_buf, sizeof(__scar_buf));
            if (__scar_n <= 0) {
                char* __scar_eof = scar_malloc(4);
                memcpy(__scar_eof, "EOF", 4);
                return Result_str_Err(__scar_eof);
            }
            char* __scar_out = scar_malloc((size_t)__scar_n + 1);
            memcpy(__scar_out, __scar_buf, (size_t)__scar_n);
            __scar_out[__scar_n] = '\0';
            return Result_str_Ok(__scar_out);
        }
    }
}
