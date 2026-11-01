// Mide s una vez (largo en caracteres UTF-8 = los bytes que
// no son de continuación 10xxxxxx, igual que len() del intérprete; y
// si es todo ASCII). Cada hilo recuerda los dos últimos str medidos
// (dos, para recorrer dos a la vez: a[i] == b[i]); si s es uno de
// ellos no recorre nada. Si no, ocupa el que se usó hace más tiempo.
static inline ScarStrc* scar_strc_medir(const char* s) {
    if (s == scar_strc[0].p) { scar_strc_ult = 0; return &scar_strc[0]; }
    if (s == scar_strc[1].p) { scar_strc_ult = 1; return &scar_strc[1]; }
    int u = 1 - scar_strc_ult;
    ScarStrc* e = &scar_strc[u];
    e->p = NULL;
    const unsigned char* q = (const unsigned char*)s;
    size_t b0 = 0;
    while ((q[b0] & 0xC0) == 0x80) b0++;  // UTF-8 inválido al principio
    int32_t n = 0;
    int ascii = 1;
    for (; *q; q++) {
        if (*q < 0x80) n++;
        else { ascii = 0; if ((*q & 0xC0) != 0x80) n++; }
    }
    e->len = n;
    e->ascii = ascii;
    e->ci = 0;
    e->b0 = b0;
    e->bi = b0;
    e->p = s;
    scar_strc_ult = u;
    return e;
}
static inline int32_t scar_utf8_len(const char* s) {
    return scar_strc_medir(s)->len;
}
