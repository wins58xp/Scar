static Result_i32 scar_file_write_bytes(ScarFile __scar_h, @@VEC@@ v) {
    FILE* f;
    if (!scar_h_ver(__scar_h, &f, NULL)) return Result_i32_Err(scar_aprintf("archivo cerrado"));
    unsigned char *b = scar_bytes_de_vec(v);
    size_t k = fwrite(b, 1, (size_t)v.len, f);
    free(b);
    if (k < (size_t)v.len) {
        char* err = scar_aprintf("error de escritura: %s", strerror(errno));
        return Result_i32_Err(err);
    }
    return Result_i32_Ok(v.len);
}

