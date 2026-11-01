@@RYU_D2D@@
static char* scar_fmt_f64(double v) {
    char* buf = scar_malloc(64);
    if (isnan(v)) { strcpy(buf, "nan"); return buf; }
    if (isinf(v)) { strcpy(buf, v < 0 ? "-inf" : "inf"); return buf; }
    if (v == 0.0) { strcpy(buf, signbit(v) ? "-0.0" : "0.0"); return buf; }
    uint64_t mant;
    int32_t e;
    scar_ryu_shortest(v, &mant, &e);
    char digits[24];
    int nd = 0;
    {
        char rev[24];
        int k = 0;
        do { rev[k++] = (char)('0' + mant % 10); mant /= 10; } while (mant);
        while (k) digits[nd++] = rev[--k];
    }
    int exp10 = e + nd - 1;
    int decpt = exp10 + 1;
    char* o = buf;
    if (signbit(v)) *o++ = '-';
    if (decpt > -4 && decpt <= 16) {
        if (decpt <= 0) {
            *o++ = '0'; *o++ = '.';
            for (int i = 0; i < -decpt; i++) *o++ = '0';
            for (int i = 0; i < nd; i++) *o++ = digits[i];
        } else if (decpt >= nd) {
            for (int i = 0; i < nd; i++) *o++ = digits[i];
            for (int i = 0; i < decpt - nd; i++) *o++ = '0';
            *o++ = '.'; *o++ = '0';
        } else {
            for (int i = 0; i < decpt; i++) *o++ = digits[i];
            *o++ = '.';
            for (int i = decpt; i < nd; i++) *o++ = digits[i];
        }
        *o = 0;
    } else {
        *o++ = digits[0];
        if (nd > 1) { *o++ = '.'; for (int i = 1; i < nd; i++) *o++ = digits[i]; }
        snprintf(o, 16, "e%c%02d", exp10 < 0 ? '-' : '+', exp10 < 0 ? -exp10 : exp10);
    }
    return buf;
}
