#ifdef SCAR_PLANIFICADOR
// Lo de ScarHilo (tls.c) que es de cada tarea: con tareas livianas, el
// planificador lo guarda en la fibra al dejarla y lo repone al retomarla
// (scar_cambiar_a_fibra).
static void scar_tls_guardar(ScarFibra *f) {
    f->tls_ctx = __scar_ctx;
    f->tls_vivos = scar_vivos;
    f->tls_nvivos = scar_nvivos;
    f->tls_capvivos = scar_capvivos;
    f->tls_rand[0] = __scar_rand_state;
    f->tls_rand[1] = __scar_rand_base;
    f->tls_rand[2] = __scar_rand_hijos;
    f->tls_pila_hi = scar_pila_hi;
    f->tls_pila_lo = scar_pila_lo;
}

static void scar_tls_restaurar(ScarFibra *f) {
    __scar_ctx = f->tls_ctx;
    scar_vivos = f->tls_vivos;
    scar_nvivos = f->tls_nvivos;
    scar_capvivos = f->tls_capvivos;
    __scar_rand_state = f->tls_rand[0];
    __scar_rand_base = f->tls_rand[1];
    __scar_rand_hijos = f->tls_rand[2];
    scar_pila_hi = f->tls_pila_hi;
    scar_pila_lo = f->tls_pila_lo;
    // los dos últimos str medidos eran de otra tarea
    scar_strc[0].p = scar_strc[1].p = NULL;
}
#endif
