static char *scar_ffi_str_propia(const char *s) {
    if (s == NULL) return NULL;
    size_t n = strlen(s);
    char *c = scar_malloc(n + 1);
    memcpy(c, s, n + 1);
    return c;
}


