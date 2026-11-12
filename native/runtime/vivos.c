typedef struct ScarVivo { void *slot; void (*drop)(void*); const bool *flag; } ScarVivo;
// scar_vivos, scar_nvivos y scar_capvivos: en ScarHilo (tls.c)
// alta idempotente: si el slot ya esta registrado (desde 'base', el
// inicio de la funcion actual), solo actualiza como se suelta
static void scar_vivo_alta(void *slot, void (*drop)(void*), const bool *flag, int base) {
    for (int i = scar_nvivos - 1; i >= base; i--) {
        if (scar_vivos[i].slot == slot) { scar_vivos[i].drop = drop; scar_vivos[i].flag = flag; return; }
    }
    if (scar_nvivos == scar_capvivos) {
        int cap = scar_capvivos ? scar_capvivos * 2 : 32;
        ScarVivo *nv = realloc(scar_vivos, (size_t)cap * sizeof(ScarVivo));
        if (!nv) return;  // sin memoria: a lo sumo se pierde al cancelar
        scar_vivos = nv;
        scar_capvivos = cap;
    }
    scar_vivos[scar_nvivos].slot = slot;
    scar_vivos[scar_nvivos].drop = drop;
    scar_vivos[scar_nvivos].flag = flag;
    scar_nvivos++;
}
// alta de una dueña recien nacida, que seguro no esta registrada
static inline void scar_vivo_push(void *slot, void (*drop)(void*), const bool *flag) {
    if (__builtin_expect(scar_nvivos == scar_capvivos, 0)) {
        scar_vivo_alta(slot, drop, flag, scar_nvivos);
        return;
    }
    ScarVivo *e = &scar_vivos[scar_nvivos++];
    e->slot = slot;
    e->drop = drop;
    e->flag = flag;
}
// baja idempotente; conserva el orden (los scopes cierran de adentro
// hacia afuera y el return trunca por cantidad)
static void scar_vivo_baja_lenta(void *slot, int base) {
    for (int i = scar_nvivos - 1; i >= base; i--) {
        if (scar_vivos[i].slot == slot) {
            for (int j = i + 1; j < scar_nvivos; j++) scar_vivos[j - 1] = scar_vivos[j];
            scar_nvivos--;
            return;
        }
    }
}
static inline void scar_vivo_baja(void *slot, int base) {
    if (scar_nvivos > base && scar_vivos[scar_nvivos - 1].slot == slot) {
        scar_nvivos--;
        return;
    }
    scar_vivo_baja_lenta(slot, base);
}
static void scar_vivos_soltar(void) {
    int n = scar_nvivos;
    scar_nvivos = 0;
    for (int i = n - 1; i >= 0; i--) {
        ScarVivo e = scar_vivos[i];
        if (!e.flag || *e.flag) e.drop(e.slot);
    }
}
static void scar_vivos_liberar_registro(void) {
    free(scar_vivos);
    scar_vivos = NULL;
    scar_nvivos = 0;
    scar_capvivos = 0;
}

