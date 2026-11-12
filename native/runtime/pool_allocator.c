// SCAR_POOL_MIN_SHIFT/MAX_SHIFT/NUM_CLASSES y scar_pool_freelist: en ScarHilo (tls.c)
typedef struct ScarPoolNode { struct ScarPoolNode *next; } ScarPoolNode;

@@SCAR_POOL_CLEANUP@@
// Pool allocator para objetos chicos de vida corta: strings devueltas
// por scar_str_concat/scar_str_index, buffers de scar_fmt_*/
// scar_repr_str, y los mensajes de error (256 bytes fijos) de los
// Result_*_Err de archivo/red/pipe/int(). Bench 48 (parser) mostró que
// el patrón dígito-a-dígito de a_str() hace decenas de millones de
// malloc()/free() de 2-16 bytes -- C++ no sufre esto porque
// std::string tiene SSO; acá evitamos el mismo costo reciclando
// bloques por clase de tamaño en vez de ir al allocator del sistema
// en cada concat/index. Cada bloque lleva un header de un size_t con
// su clase (o SIZE_MAX si superó SCAR_POOL_MAX_SHIFT y se cayó a
// malloc() real) -- scar_free() lo lee para saber a qué freelist
// devolverlo, así que NUNCA hay que llamarlo con un puntero que no
// haya salido de scar_malloc(). La freelist es _Thread_local (una
// por pthread, sin locks); scar_pool_touch_thread() (ver arriba)
// registra el hilo actual la primera vez que pasa por acá para que
// ese freelist se vacíe con free() real al terminar el hilo, en vez
// de quedar huérfano.
//
// 'inline' acá (y en scar_free/scar_idiv/scar_str_index/
// scar_str_concat más abajo) es la segunda mitad del arreglo del pool:
// sin el hint, gcc -O2 no las estaba inlineando pese a ser 'static'
// (son varias líneas con un branch, quedan justo debajo del umbral por
// defecto del inliner) -- cada scar_malloc()/scar_free() seguía siendo
// una llamada real a función, no solo el push/pop de freelist. Medido
// en bench 48 (parser/tokenizer): agregar 'inline' a estas 5
// funciones bajó el tiempo de corrida ~30% adicional sobre el pool
// solo, sin cambiar ningún resultado de la suite de 46 ejemplos
// (mismo stdout, mismo exit code) -- no toca semántica, solo le pide a
// gcc que se anime a inlinear lo que ya podía.
// Bajo ASan/TSan el pool se apaga: cada scar_free() es un free() real,
// para que el sanitizer vea un use-after-free o un double free sobre
// un str (con el pool, el bloque vuelve a la freelist y para ASan
// sigue siendo memoria válida). Mismo header (tag SIZE_MAX).
#if defined(__SANITIZE_ADDRESS__) || defined(__SANITIZE_THREAD__)
#define SCAR_POOL_OFF 1
#endif
static inline void *scar_malloc(size_t n) {
@@SCAR_POOL_TOUCH@@    size_t total = n + sizeof(size_t);
#ifdef SCAR_POOL_OFF
    {
        size_t *raw = malloc(total);
        raw[0] = (size_t)-1;
        return (void *)(raw + 1);
    }
#endif
    size_t cap = (size_t)1 << SCAR_POOL_MIN_SHIFT;
    int idx = 0;
    while (cap < total && idx < SCAR_POOL_NUM_CLASSES - 1) {
        cap <<= 1;
        idx++;
    }
    if (cap < total) {
        // Más grande que la clase máxima: se cae al allocator real,
        // igual que hacía malloc() antes de este pool.
        size_t *base = malloc(total);
        base[0] = (size_t)-1;
        return (void *)(base + 1);
    }
    ScarPoolNode *node = scar_pool_freelist[idx];
    if (node != NULL) {
        scar_pool_freelist[idx] = node->next;
        size_t *base = (size_t *)node;
        base[0] = (size_t)idx;
        return (void *)(base + 1);
    }
    size_t *base = malloc(cap);
    base[0] = (size_t)idx;
    return (void *)(base + 1);
}

static inline void scar_free(void *p) {
    if (p == NULL) return;
    /*SCAR_STRC_FREE*/
@@SCAR_POOL_TOUCH@@    size_t *base = (size_t *)p - 1;
    size_t tag = base[0];
    if (tag == (size_t)-1) {
        free(base);
        return;
    }
    ScarPoolNode *node = (ScarPoolNode *)base;
    node->next = scar_pool_freelist[tag];
    scar_pool_freelist[tag] = node;
}
@@TEXTO_SIN_TOPE_C@@
