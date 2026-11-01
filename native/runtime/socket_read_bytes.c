// exactamente n bytes; Err("EOF") si la otra punta cierra antes,
// Err("timeout") si pasa el timeout de I/O sin ningún byte nuevo
static @@RES@@ scar_socket_read_bytes(ScarSocket __scar_h, int32_t n) {
    if (n < 0) @@PANIC@@("read_bytes: cantidad negativa (%d)", n);
    int sock;
    if (!scar_h_ver(__scar_h, NULL, &sock)) return scar_bytes_err("socket cerrado");
    int base = scar_nvivos;
    @@VEC@@ v = scar_vec_new_i32(n);
    scar_vivo_push(&v, scar_drop_bytes_tmp, NULL);
    double deadline = @@AHORA@@ + SCAR_IO_TIMEOUT_SECONDS;
    while (v.len < n) {
@@CANCEL@@        double rem = deadline - @@AHORA@@;
        if (rem <= 0) {
            scar_vivo_baja(&v, base);
            scar_vec_free_i32(v);
            return scar_bytes_err("timeout");
        }
        double step = rem < 0.02 ? rem : 0.02;
        struct timeval tv;
        tv.tv_sec = (time_t)step;
        tv.tv_usec = (long)((step - (double)tv.tv_sec) * 1e6);
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(sock, &fds);
        if (select(sock + 1, &fds, NULL, NULL, &tv) > 0 && FD_ISSET(sock, &fds)) {
            unsigned char buf[4096];
            int32_t falta = n - v.len;
            ssize_t k = recv(sock, buf, falta < 4096 ? (size_t)falta : 4096, 0);
            if (k <= 0) {
                scar_vivo_baja(&v, base);
                scar_vec_free_i32(v);
                return scar_bytes_err(k == 0 ? "EOF" : "error de lectura");
            }
            for (ssize_t i = 0; i < k; i++) scar_vec_push_i32(&v, (int32_t)buf[i]);
            deadline = @@AHORA@@ + SCAR_IO_TIMEOUT_SECONDS;  // cuenta desde el último byte
        }
    }
    scar_vivo_baja(&v, base);
    return @@RES@@_Ok(v);
}

