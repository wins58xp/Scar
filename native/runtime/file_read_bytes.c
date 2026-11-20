// hasta n bytes; vacío en el fin de archivo
static @@RES@@ scar_file_@@METODO@@(ScarFile __scar_h, int32_t n) {
    if (n < 0) @@PANIC@@("@@METODO@@: cantidad negativa (%d)", n);
    FILE* f;
    if (!scar_h_ver(__scar_h, &f, NULL)) return scar_bytes_err@@SUF@@("archivo cerrado");
    @@VEC@@ v = scar_vec_new_@@T@@(n);
    unsigned char buf[4096];
    int32_t falta = n;
    while (falta > 0) {
        size_t k = SCAR_BLOQUEANDO(fread(buf, 1, falta < 4096 ? (size_t)falta : 4096, f));
        for (size_t i = 0; i < k; i++) scar_vec_push_@@T@@(&v, (@@CT@@)buf[i]);
        falta -= (int32_t)k;
        if (k == 0) break;
    }
    if (ferror(f)) {
        scar_vec_free_@@T@@(v);
        return scar_bytes_err@@SUF@@("error de lectura");
    }
    return @@RES@@_Ok(v);
}

