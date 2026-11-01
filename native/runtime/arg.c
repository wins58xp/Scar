static int scar_argc_prog = 0;
static char** scar_argv_prog = NULL;
static int scar_utf8_valido(const unsigned char* p) {
    while (*p) {
        unsigned c = *p;
        int n; unsigned cp;
        if (c < 0x80) { p++; continue; }
        else if (c >= 0xC2 && c <= 0xDF) { n = 1; cp = c & 0x1F; }
        else if (c >= 0xE0 && c <= 0xEF) { n = 2; cp = c & 0x0F; }
        else if (c >= 0xF0 && c <= 0xF4) { n = 3; cp = c & 0x07; }
        else return 0;
        for (int k = 1; k <= n; k++) {
            if ((p[k] & 0xC0) != 0x80) return 0;
            cp = (cp << 6) | (p[k] & 0x3F);
        }
        if ((n == 2 && cp < 0x800) || (n == 3 && cp < 0x10000)) return 0;
        if (cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) return 0;
        p += n + 1;
    }
    return 1;
}
static @@OPT@@ scar_arg(int32_t i) {
    if (i < 0 || i >= scar_argc_prog) return @@OPT@@_None();
    if (!scar_utf8_valido((const unsigned char*)scar_argv_prog[i]))
        @@PANIC@@("arg(%d): el argumento no es UTF-8 válido", i);
    return @@OPT@@_Some(scar_argv_prog[i]);
}

