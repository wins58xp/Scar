// Un f32 como texto: el decimal más corto (de 1 a 9 cifras, bien redondeado)
// que vuelve al mismo f32, con la forma de un f64 (`0.1`, `2.0`, `1e+20`).
// Igual que types_.fmt_f32 del intérprete, paso por paso: las cifras salen de
// printf("%.*e") sobre el valor como double, y la vuelta se comprueba leyendo
// el texto como double y redondeándolo a float (no con strtof: así las dos
// implementaciones redondean en el mismo orden).
static char* scar_fmt_f32(float f) {
    char* buf = scar_malloc(64);
    if (isnan(f)) { strcpy(buf, "nan"); return buf; }
    if (isinf(f)) { strcpy(buf, f < 0 ? "-inf" : "inf"); return buf; }
    if (f == 0.0f) { strcpy(buf, signbit(f) ? "-0.0" : "0.0"); return buf; }
    float a = fabsf(f);
    char s[48];
    for (int p = 1; p <= 9; p++) {
        snprintf(s, sizeof s, "%.*e", p - 1, (double)a);
        if ((float)strtod(s, NULL) == a) break;
    }
    char digits[16];
    int nd = 0;
    char* q = s;
    for (; *q && *q != 'e'; q++) if (*q >= '0' && *q <= '9') digits[nd++] = *q;
    while (nd > 1 && digits[nd - 1] == '0') nd--;
    int exp10 = atoi(q + 1);
    int decpt = exp10 + 1;
    char* o = buf;
    if (signbit(f)) *o++ = '-';
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
