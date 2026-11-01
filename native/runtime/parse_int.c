// 0 = ok, 1 = no es un entero, 2 = fuera de [lo, hi]
static int scar_parse_int(const char* s, int64_t lo, int64_t hi, int64_t *out) {
    const char *p = s;
    while (*p == ' ' || (*p >= '\t' && *p <= '\r')) p++;
    int neg = 0;
    if (*p == '+' || *p == '-') { neg = (*p == '-'); p++; }
    if (*p < '0' || *p > '9') return 1;
    uint64_t v = 0;
    int grande = 0;
    for (; *p >= '0' && *p <= '9'; p++) {
        if (grande) continue;
        if (v > (UINT64_MAX - 9) / 10) { grande = 1; continue; }
        v = v * 10 + (uint64_t)(*p - '0');
    }
    while (*p == ' ' || (*p >= '\t' && *p <= '\r')) p++;
    if (*p != '\0') return 1;
    uint64_t lim = neg ? (uint64_t)(-(lo + 1)) + 1u : (uint64_t)hi;
    if (grande || v > lim) return 2;
    *out = neg ? (v == (uint64_t)INT64_MAX + 1u ? INT64_MIN : -(int64_t)v) : (int64_t)v;
    return 0;
}
static char* scar_parse_int_err(const char* s, int rc, const char* tipo) {
    if (rc == 2) return scar_aprintf("'%s' esta fuera del rango de %s", s, tipo);
    return scar_aprintf("no se pudo convertir '%s' a entero", s);
}
