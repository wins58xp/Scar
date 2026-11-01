typedef struct { FILE* fp; int fd; uint32_t gen; int abierto; } ScarHSlot;
static ScarHSlot* scar_h_tab = NULL;
static int32_t scar_h_n = 0, scar_h_cap = 0;
@@MU@@static int64_t scar_h_nuevo(FILE* fp, int fd) {
@@LOCK@@    int32_t i = 0;
    while (i < scar_h_n && scar_h_tab[i].abierto) i++;
    if (i == scar_h_n) {
        if (scar_h_n == scar_h_cap) {
            scar_h_cap = scar_h_cap ? scar_h_cap * 2 : 16;
            scar_h_tab = realloc(scar_h_tab, sizeof(ScarHSlot) * (size_t)scar_h_cap);
        }
        scar_h_tab[i].gen = 1;
        scar_h_n++;
    }
    scar_h_tab[i].fp = fp;
    scar_h_tab[i].fd = fd;
    scar_h_tab[i].abierto = 1;
    int64_t h = ((int64_t)scar_h_tab[i].gen << 32) | (int64_t)(i + 1);
@@UNLOCK@@    return h;
}
// con el lock tomado: el slot de h si sigue abierto, si no NULL
static ScarHSlot* scar_h_slot(int64_t h) {
    int64_t i = (h & 0xffffffff) - 1;
    if (i < 0 || i >= scar_h_n) return NULL;
    ScarHSlot* s = &scar_h_tab[i];
    if (!s->abierto || s->gen != (uint32_t)((uint64_t)h >> 32)) return NULL;
    return s;
}
// 1 y lo de adentro si h está abierto; 0 si está cerrado
static int scar_h_ver(int64_t h, FILE** fp, int* fd) {
@@LOCK@@    ScarHSlot* s = scar_h_slot(h);
    if (s) { if (fp) *fp = s->fp; if (fd) *fd = s->fd; }
@@UNLOCK@@    return s != NULL;
}
// como scar_h_ver, y además lo cierra en la tabla (quien llama cierra
// el FILE*/fd que recibe); 0 si ya estaba cerrado
static int scar_h_soltar(int64_t h, FILE** fp, int* fd) {
@@LOCK@@    ScarHSlot* s = scar_h_slot(h);
    if (s) {
        if (fp) *fp = s->fp;
        if (fd) *fd = s->fd;
        s->abierto = 0;
        s->gen++;
    }
@@UNLOCK@@    return s != NULL;
}
