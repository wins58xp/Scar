static Result_File scar_file_open(const char* path, const char* mode) {
    if (strcmp(mode, "r") != 0 && strcmp(mode, "w") != 0 && strcmp(mode, "a") != 0) {
        char* buf = scar_aprintf("mode invalido: '%s' (use 'r'/'w'/'a')", mode);
        return Result_File_Err(buf);
    }
    FILE* f = fopen(path, mode);
    if (f == NULL) {
        char* buf = scar_aprintf("no se pudo abrir '%s': %s", path, strerror(errno));
        return Result_File_Err(buf);
    }
    return Result_File_Ok(scar_h_nuevo(f, -1));
}

// El buffer lleva el mismo header que un bloque grande de
// scar_malloc (tag SIZE_MAX, ver scar_free): es un str como cualquier
// otro y se libera con scar_free(). Antes era malloc/realloc pelado y
// arrastraba un segundo origen (libc_free) por todo el backend.
static Result_str scar_file_read_all(ScarFile __scar_h) {
    FILE* f;
    if (!scar_h_ver(__scar_h, &f, NULL)) return Result_str_Err(scar_aprintf("archivo cerrado"));
    size_t __scar_cap = 4096, __scar_len = 0;
    size_t* __scar_base = malloc(sizeof(size_t) + __scar_cap);
    for (;;) {
        if (__scar_len == __scar_cap) {
            __scar_cap *= 2;
            __scar_base = realloc(__scar_base, sizeof(size_t) + __scar_cap);
        }
        char* __scar_buf = (char*)(__scar_base + 1);
        size_t __scar_n = fread(__scar_buf + __scar_len, 1, __scar_cap - __scar_len, f);
        __scar_len += __scar_n;
        if (__scar_n == 0) break;
    }
    if (ferror(f)) {
        free(__scar_base);
        char* err = scar_aprintf("error de lectura: %s", strerror(errno));
        return Result_str_Err(err);
    }
    __scar_base = realloc(__scar_base, sizeof(size_t) + __scar_len + 1);
    __scar_base[0] = (size_t)-1;
    char* __scar_buf = (char*)(__scar_base + 1);
    __scar_buf[__scar_len] = '\0';
    return Result_str_Ok(__scar_buf);
}

static Result_i32 scar_file_write(ScarFile __scar_h, const char* s) {
    FILE* f;
    if (!scar_h_ver(__scar_h, &f, NULL)) return Result_i32_Err(scar_aprintf("archivo cerrado"));
    size_t __scar_len = strlen(s);
    size_t __scar_written = fwrite(s, 1, __scar_len, f);
    if (__scar_written < __scar_len) {
        char* err = scar_aprintf("error de escritura: %s", strerror(errno));
        return Result_i32_Err(err);
    }
    return Result_i32_Ok((int32_t)__scar_written);
}

// cerrar uno ya cerrado no hace nada
static void scar_file_close(ScarFile __scar_h) {
    FILE* f;
    if (scar_h_soltar(__scar_h, &f, NULL)) fclose(f);
}
