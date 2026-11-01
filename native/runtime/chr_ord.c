static char* scar_chr(int32_t n) {
    if (n < 1 || n > 0x10FFFF || (n >= 0xD800 && n <= 0xDFFF))
        @@PANIC@@("chr: código inválido (%d)", n);
    char* out = scar_malloc(5);
    unsigned char* p = (unsigned char*)out;
    if (n < 0x80) { p[0] = (unsigned char)n; p[1] = 0; }
    else if (n < 0x800) { p[0] = 0xC0 | (n >> 6); p[1] = 0x80 | (n & 63); p[2] = 0; }
    else if (n < 0x10000) { p[0] = 0xE0 | (n >> 12); p[1] = 0x80 | ((n >> 6) & 63); p[2] = 0x80 | (n & 63); p[3] = 0; }
    else { p[0] = 0xF0 | (n >> 18); p[1] = 0x80 | ((n >> 12) & 63); p[2] = 0x80 | ((n >> 6) & 63); p[3] = 0x80 | (n & 63); p[4] = 0; }
    return out;
}
static int32_t scar_ord(const char* s) {
    const unsigned char* p = (const unsigned char*)s;
    if (p[0] == 0) @@PANIC@@("ord: str vacío");
    if (p[0] < 0x80) return p[0];
    if ((p[0] & 0xE0) == 0xC0) return ((p[0] & 31) << 6) | (p[1] & 63);
    if ((p[0] & 0xF0) == 0xE0) return ((p[0] & 15) << 12) | ((p[1] & 63) << 6) | (p[2] & 63);
    return ((p[0] & 7) << 18) | ((p[1] & 63) << 12) | ((p[2] & 63) << 6) | (p[3] & 63);
}

