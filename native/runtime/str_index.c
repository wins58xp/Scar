static inline char* scar_str_index(const char* s, int32_t i) {
    ScarStrc* e = scar_strc_medir(s);
    int32_t len = e->len;
    if (i < 0 || i >= len) {
        @@PANIC@@("índice fuera de rango: %d (longitud %d)", i, len);
    }
    const unsigned char* p;
    size_t n = 1;
    if (e->ascii) {
        p = (const unsigned char*)s + i;
    } else {
        // desde el último carácter visitado si i va hacia adelante
        int32_t k = e->ci;
        size_t b = e->bi;
        if (i < k) { k = 0; b = e->b0; }
        p = (const unsigned char*)s + b;
        while (k < i) {
            p++;
            while ((*p & 0xC0) == 0x80) p++;
            k++;
        }
        e->ci = i;
        e->bi = (size_t)(p - (const unsigned char*)s);
        while (p[n] != 0 && (p[n] & 0xC0) == 0x80) n++;
    }
    char* out = scar_malloc(n + 1);
    memcpy(out, p, n);
    out[n] = '\0';
    return out;
}
