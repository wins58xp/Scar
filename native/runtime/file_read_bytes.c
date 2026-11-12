// hasta n bytes; vacío en el fin de archivo
static @@RES@@ scar_file_read_bytes(ScarFile __scar_h, int32_t n) {
    if (n < 0) @@PANIC@@("read_bytes: cantidad negativa (%d)", n);
    FILE* f;
    if (!scar_h_ver(__scar_h, &f, NULL)) return scar_bytes_err("archivo cerrado");
    @@VEC@@ v = scar_vec_new_i32(n);
    unsigned char buf[4096];
    int32_t falta = n;
    while (falta > 0) {
        size_t k = SCAR_BLOQUEANDO(fread(buf, 1, falta < 4096 ? (size_t)falta : 4096, f));
        for (size_t i = 0; i < k; i++) scar_vec_push_i32(&v, (int32_t)buf[i]);
        falta -= (int32_t)k;
        if (k == 0) break;
    }
    if (ferror(f)) {
        scar_vec_free_i32(v);
        return scar_bytes_err("error de lectura");
    }
    return @@RES@@_Ok(v);
}

