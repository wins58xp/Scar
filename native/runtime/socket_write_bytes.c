static Result_i32 scar_socket_write_bytes(ScarSocket __scar_h, @@VEC@@ v) {
    int sock;
    if (!scar_h_ver(__scar_h, NULL, &sock)) return Result_i32_Err(scar_aprintf("socket cerrado"));
    unsigned char *b = scar_bytes_de_vec(v);
    size_t enviados = 0;
    while (enviados < (size_t)v.len) {
        ssize_t k = send(sock, b + enviados, (size_t)v.len - enviados, MSG_NOSIGNAL);
        if (k < 0) {
            free(b);
            char* err = scar_aprintf("error de escritura: %s", strerror(errno));
            return Result_i32_Err(err);
        }
        enviados += (size_t)k;
    }
    free(b);
    return Result_i32_Ok(v.len);
}

