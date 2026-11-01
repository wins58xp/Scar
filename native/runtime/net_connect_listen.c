static Result_Socket scar_tcp_connect(const char* host, int32_t port) {
    char __scar_port_buf[16];
    snprintf(__scar_port_buf, sizeof(__scar_port_buf), "%d", port);
    struct addrinfo __scar_hints, *__scar_res;
    memset(&__scar_hints, 0, sizeof(__scar_hints));
    __scar_hints.ai_family = AF_INET;
    __scar_hints.ai_socktype = SOCK_STREAM;
    int __scar_gai_rc = getaddrinfo(host, __scar_port_buf, &__scar_hints, &__scar_res);
    if (__scar_gai_rc != 0) {
        char* buf = scar_aprintf("no se pudo conectar a %s:%d: %s", host, port, gai_strerror(__scar_gai_rc));
        return Result_Socket_Err(buf);
    }
    int fd = socket(__scar_res->ai_family, __scar_res->ai_socktype, __scar_res->ai_protocol);
    if (fd < 0) {
        freeaddrinfo(__scar_res);
        char* buf = scar_aprintf("no se pudo conectar a %s:%d: %s", host, port, strerror(errno));
        return Result_Socket_Err(buf);
    }
    int __scar_conn_rc = connect(fd, __scar_res->ai_addr, __scar_res->ai_addrlen);
    freeaddrinfo(__scar_res);
    if (__scar_conn_rc != 0) {
        close(fd);
        char* buf = scar_aprintf("no se pudo conectar a %s:%d: %s", host, port, strerror(errno));
        return Result_Socket_Err(buf);
    }
    return Result_Socket_Ok(scar_h_nuevo(NULL, fd));
}

static Result_Listener scar_tcp_listen(int32_t port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        char* buf = scar_aprintf("no se pudo escuchar en el puerto %d: %s", port, strerror(errno));
        return Result_Listener_Err(buf);
    }
    int __scar_reuse = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &__scar_reuse, sizeof(__scar_reuse));
    struct sockaddr_in __scar_addr;
    memset(&__scar_addr, 0, sizeof(__scar_addr));
    __scar_addr.sin_family = AF_INET;
    __scar_addr.sin_addr.s_addr = INADDR_ANY;
    __scar_addr.sin_port = htons((uint16_t)port);
    if (bind(fd, (struct sockaddr*)&__scar_addr, sizeof(__scar_addr)) != 0 ||
        listen(fd, 5) != 0) {
        char* buf = scar_aprintf("no se pudo escuchar en el puerto %d: %s", port, strerror(errno));
        close(fd);
        return Result_Listener_Err(buf);
    }
    return Result_Listener_Ok(scar_h_nuevo(NULL, fd));
}

static Result_i32 scar_socket_write(ScarSocket __scar_h, const char* s) {
    int sock;
    if (!scar_h_ver(__scar_h, NULL, &sock)) return Result_i32_Err(scar_aprintf("socket cerrado"));
    size_t __scar_len = strlen(s);
    size_t __scar_sent = 0;
    while (__scar_sent < __scar_len) {
        // MSG_NOSIGNAL: si la otra punta cerró, Err como en el intérprete
        // (sin él, SIGPIPE terminaba el proceso)
        ssize_t __scar_n = send(sock, s + __scar_sent, __scar_len - __scar_sent, MSG_NOSIGNAL);
        if (__scar_n < 0) {
            char* err = scar_aprintf("error de escritura: %s", strerror(errno));
            return Result_i32_Err(err);
        }
        __scar_sent += (size_t)__scar_n;
    }
    return Result_i32_Ok((int32_t)__scar_sent);
}

// cerrar uno ya cerrado no hace nada
static void scar_socket_close(ScarSocket __scar_h) {
    int sock;
    if (scar_h_soltar(__scar_h, NULL, &sock)) close(sock);
}

static void scar_listener_close(ScarListener __scar_h) {
    int sock;
    if (scar_h_soltar(__scar_h, NULL, &sock)) close(sock);
}
