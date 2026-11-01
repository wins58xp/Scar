static inline char* scar_str_concat(const char* a, const char* b) {
    size_t la = strlen(a);
    size_t lb = strlen(b);
    char* out = scar_malloc(la + lb + 1);
    memcpy(out, a, la);
    memcpy(out + la, b, lb);
    out[la + lb] = '\0';
    return out;
}
