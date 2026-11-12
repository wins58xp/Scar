#define SCAR_IO_TIMEOUT_SECONDS (SCAR_JOIN_TIMEOUT_SECONDS - 0.5)

static Result_str scar_socket_read(ScarSocket __scar_h) {
    int sock;
    if (!scar_h_ver(__scar_h, NULL, &sock)) return Result_str_Err(scar_aprintf("socket cerrado"));
    double __scar_deadline = scar_monotonic_now() + SCAR_IO_TIMEOUT_SECONDS;
    for (;;) {
        scar_cancel_check();
        double __scar_remaining = __scar_deadline - scar_monotonic_now();
        if (__scar_remaining <= 0) {
            scar_panic(
                "socket.read: timeout de I/O (%.1fs) sin datos", (double)SCAR_IO_TIMEOUT_SECONDS);
        }
        double __scar_step = __scar_remaining < 0.02 ? __scar_remaining : 0.02;
        struct timeval __scar_tv;
        __scar_tv.tv_sec = (time_t)__scar_step;
        __scar_tv.tv_usec = (long)((__scar_step - (double)__scar_tv.tv_sec) * 1e6);
        fd_set __scar_fdset;
        FD_ZERO(&__scar_fdset);
        FD_SET(sock, &__scar_fdset);
        int __scar_rc = SCAR_BLOQUEANDO(select(sock + 1, &__scar_fdset, NULL, NULL, &__scar_tv));
        if (__scar_rc > 0 && FD_ISSET(sock, &__scar_fdset)) {
            char __scar_buf[4096];
            ssize_t __scar_n = SCAR_BLOQUEANDO(recv(sock, __scar_buf, sizeof(__scar_buf), 0));
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

static Result_Socket scar_listener_accept(ScarListener __scar_h) {
    int sock;
    if (!scar_h_ver(__scar_h, NULL, &sock)) return Result_Socket_Err(scar_aprintf("listener cerrado"));
    double __scar_deadline = scar_monotonic_now() + SCAR_IO_TIMEOUT_SECONDS;
    for (;;) {
        scar_cancel_check();
        double __scar_remaining = __scar_deadline - scar_monotonic_now();
        if (__scar_remaining <= 0) {
            scar_panic(
                "listener.accept: timeout de I/O (%.1fs) sin conexión entrante", (double)SCAR_IO_TIMEOUT_SECONDS);
        }
        double __scar_step = __scar_remaining < 0.02 ? __scar_remaining : 0.02;
        struct timeval __scar_tv;
        __scar_tv.tv_sec = (time_t)__scar_step;
        __scar_tv.tv_usec = (long)((__scar_step - (double)__scar_tv.tv_sec) * 1e6);
        fd_set __scar_fdset;
        FD_ZERO(&__scar_fdset);
        FD_SET(sock, &__scar_fdset);
        int __scar_rc = SCAR_BLOQUEANDO(select(sock + 1, &__scar_fdset, NULL, NULL, &__scar_tv));
        if (__scar_rc > 0 && FD_ISSET(sock, &__scar_fdset)) {
            int __scar_conn = SCAR_BLOQUEANDO(accept(sock, NULL, NULL));
            if (__scar_conn < 0) {
                char* err = scar_aprintf("error de accept: %s", strerror(errno));
                return Result_Socket_Err(err);
            }
            return Result_Socket_Ok(scar_h_nuevo(NULL, __scar_conn));
        }
    }
}
