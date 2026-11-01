
// gcc 13 con -fsanitize=undefined avisa "null format string" en el
// vsnprintf de abajo (falso positivo de -Wformat-truncation: sin UBSan no
// aparece); se apaga solo acá.
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wformat-truncation"
#endif
__attribute__((unused, format(printf, 1, 2)))
static char *scar_aprintf(const char *fmt, ...) {
    va_list ap, ap2;
    char medir[1];
    va_start(ap, fmt);
    va_copy(ap2, ap);
    int n = vsnprintf(medir, sizeof medir, fmt, ap);
    va_end(ap);
    if (n < 0) n = 0;
    char *buf = scar_malloc((size_t)n + 1);
    vsnprintf(buf, (size_t)n + 1, fmt, ap2);
    va_end(ap2);
    return buf;
}
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC diagnostic pop
#endif

typedef struct { char *buf; size_t len, cap; } ScarSb;

__attribute__((unused))
static void scar_sb_add(ScarSb *sb, const char *s) {
    size_t n = strlen(s);
    if (sb->len + n + 1 > sb->cap) {
        size_t cap = sb->cap ? sb->cap : 64;
        while (sb->len + n + 1 > cap) cap *= 2;
        char *nb = realloc(sb->buf, cap);
        if (nb == NULL) { fputs("sin memoria\n", stderr); abort(); }
        sb->buf = nb;
        sb->cap = cap;
    }
    memcpy(sb->buf + sb->len, s, n + 1);
    sb->len += n;
}

__attribute__((unused))
static char *scar_sb_fin(ScarSb *sb) {
    char *out = scar_malloc(sb->len + 1);
    if (sb->len) memcpy(out, sb->buf, sb->len);
    out[sb->len] = '\0';
    free(sb->buf);
    return out;
}

