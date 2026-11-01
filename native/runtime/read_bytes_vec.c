// los valores de un Vec<i32> como bytes; uno fuera de 0..255 es un panic
static unsigned char *scar_bytes_de_vec(@@VEC@@ v) {
    unsigned char *b = malloc(v.len > 0 ? (size_t)v.len : 1);
    if (!b) @@PANIC@@("write_bytes: sin memoria");
    for (int32_t i = 0; i < v.len; i++) {
        if (v.data[i] < 0 || v.data[i] > 255) {
            int32_t x = v.data[i];
            free(b);
            @@PANIC@@("write_bytes: %d no es un byte (0..255)", x);
        }
        b[i] = (unsigned char)v.data[i];
    }
    return b;
}

