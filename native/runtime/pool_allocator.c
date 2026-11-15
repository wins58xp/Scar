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
// Los bloques de struct (blk.c) salen de las mismas listas, con su propio
// encabezado.
// Bajo ASan/TSan el pool se apaga: cada scar_free() es un free() real,
// para que el sanitizer vea un use-after-free o un double free sobre
// un str o un struct (con el pool, el bloque vuelve a la freelist y para
// ASan sigue siendo memoria válida). Mismo header (tag SIZE_MAX).
#if defined(__SANITIZE_ADDRESS__) || defined(__SANITIZE_THREAD__)
#define SCAR_POOL_OFF 1
#endif
// El tope de cada lista de libres (diseño de la burbuja).
// Sin tope, la lista de un hilo que suelta más de lo que pide crece para
// siempre: una tarea arma los structs que manda por un canal y otra, en otro
// hilo, los suelta (bench/burbuja/llena.scar con SCAR_TAREAS=hilos: 314,8 MB
// contra 2,3 MB). Con la lista llena, el bloque que se suelta vuelve al
// sistema con free(), como antes del pool. -DSCAR_POOL_TOPE=N lo cambia al
// compilar, para medir.
#ifndef SCAR_POOL_TOPE
#define SCAR_POOL_TOPE 1024
#endif

// La clase de tamaño de un bloque de 'total' bytes (encabezado incluido), o
// -1 si no entra en ninguna (o el pool está apagado): ese va a malloc().
static inline int scar_pool_clase(size_t total) {
#ifdef SCAR_POOL_OFF
    (void)total;
    return -1;
#else
    size_t cap = (size_t)1 << SCAR_POOL_MIN_SHIFT;
    int idx = 0;
    while (cap < total && idx < SCAR_POOL_NUM_CLASSES - 1) {
        cap <<= 1;
        idx++;
    }
    return cap < total ? -1 : idx;
#endif
}

@@SCAR_POOL_DEPOSITO@@
#if defined(SCAR_POOL_DEPOSITO) && !defined(SCAR_POOL_OFF) && SCAR_POOL_TOPE >= 2
// El depósito y los cargadores.
// Con varios hilos, cada hilo guarda por clase dos listas de hasta
// SCAR_POOL_LOTE bloques (la mitad del tope): la "cargada", de donde se toma y
// adonde se deja, y la "previa", llena o vacía (los cargadores de Bonwick y
// Adams, 2001). Cuando la cargada se llena, pasa a ser la previa; si la previa
// ya estaba llena, esa se va entera a un depósito común por clase como un
// lote. Cuando la cargada se vacía, toma la previa si está llena, y si no, un
// lote del depósito; recién si tampoco hay, el bloque sale del sistema. Pasar
// un lote nunca recorre los bloques: es mover un puntero. Es el caso de una
// tarea que arma structs y otra, en otro hilo, que los suelta
// (bench/burbuja/llena.scar): los bloques dan la vuelta sin pasar por
// malloc/free. El depósito también tiene tope (SCAR_POOL_DEPOSITO_LOTES lotes
// por clase): un lote que no cabe vuelve al sistema, así que la memoria sigue
// acotada (cada hilo guarda a lo más SCAR_POOL_TOPE bloques por clase entre
// sus dos listas, como antes). El candado es de giro y se toma una vez por
// lote, no por bloque. Dentro de un lote los bloques van enlazados por next;
// el primero de cada lote guarda en su segunda palabra el lote siguiente (todo
// bloque tiene al menos 16 bytes).
#include <stdatomic.h>
#ifndef SCAR_POOL_DEPOSITO_LOTES
#define SCAR_POOL_DEPOSITO_LOTES 4
#endif
#define SCAR_POOL_LOTE (SCAR_POOL_TOPE / 2)
typedef struct { atomic_flag candado; ScarPoolNode *lotes; int n; } ScarPoolDeposito;
static ScarPoolDeposito scar_pool_deposito[SCAR_POOL_NUM_CLASSES];
static inline void scar_pool_deposito_tomar_candado(ScarPoolDeposito *d) {
    while (atomic_flag_test_and_set_explicit(&d->candado, memory_order_acquire)) {
#if defined(__x86_64__) || defined(__i386__)
        __builtin_ia32_pause();
#endif
    }
}
static inline void scar_pool_deposito_soltar_candado(ScarPoolDeposito *d) {
    atomic_flag_clear_explicit(&d->candado, memory_order_release);
}
#define SCAR_POOL_LOTE_SIG(nodo) (((ScarPoolNode **)(nodo))[1])

// La cargada de este hilo está vacía: toma la previa si está llena, o un lote
// del depósito. Devuelve el primer bloque de la nueva cargada, o NULL.
static inline ScarPoolNode *scar_pool_recargar(int idx) {
    if (scar_pool_previo_n[idx] > 0) {
        scar_pool_freelist[idx] = scar_pool_previo[idx];
        scar_pool_n[idx] = scar_pool_previo_n[idx];
        scar_pool_previo[idx] = NULL;
        scar_pool_previo_n[idx] = 0;
        return scar_pool_freelist[idx];
    }
    ScarPoolDeposito *d = &scar_pool_deposito[idx];
    scar_pool_deposito_tomar_candado(d);
    ScarPoolNode *lote = d->lotes;
    if (lote != NULL) {
        d->lotes = SCAR_POOL_LOTE_SIG(lote);
        d->n--;
    }
    scar_pool_deposito_soltar_candado(d);
    if (lote == NULL) return NULL;
    // las listas de este hilo ahora tienen bloques: que se vacíen al terminar
    scar_pool_touch_thread();
    scar_pool_freelist[idx] = lote;
    scar_pool_n[idx] = SCAR_POOL_LOTE;
    return lote;
}

// La cargada de este hilo se llenó: pasa a ser la previa. Si la previa ya
// estaba llena, se va entera al depósito (o al sistema, si está lleno).
static inline void scar_pool_descargar(int idx) {
    ScarPoolNode *lote = scar_pool_previo_n[idx] > 0 ? scar_pool_previo[idx] : NULL;
    scar_pool_previo[idx] = scar_pool_freelist[idx];
    scar_pool_previo_n[idx] = scar_pool_n[idx];
    scar_pool_freelist[idx] = NULL;
    scar_pool_n[idx] = 0;
    if (lote == NULL) return;
    ScarPoolDeposito *d = &scar_pool_deposito[idx];
    scar_pool_deposito_tomar_candado(d);
    int cabe = d->n < SCAR_POOL_DEPOSITO_LOTES;
    if (cabe) {
        SCAR_POOL_LOTE_SIG(lote) = d->lotes;
        d->lotes = lote;
        d->n++;
    }
    scar_pool_deposito_soltar_candado(d);
    if (!cabe) {
        while (lote != NULL) {
            ScarPoolNode *sig = lote->next;
            free(lote);
            lote = sig;
        }
    }
}

// Los caminos lentos van aparte (noinline), para que scar_pool_tomar y
// scar_pool_dejar, que se copian en cada lugar que pide o suelta un texto, un
// struct o un Vec, queden con el mismo código que sin depósito: con el camino
// lento adentro, bench/canales/mensajes_grandes rendía un 6 % menos aunque no
// pasara nunca por el depósito (4.9).
static __attribute__((noinline)) void *scar_pool_tomar_lento(int idx) {
    ScarPoolNode *node = scar_pool_recargar(idx);
    if (node != NULL) {
        scar_pool_freelist[idx] = node->next;
        scar_pool_n[idx]--;
        return (void *)node;
    }
    return malloc((size_t)1 << (SCAR_POOL_MIN_SHIFT + idx));
}
static __attribute__((noinline)) void scar_pool_dejar_lento(void *base, int idx) {
    scar_pool_descargar(idx);
    ScarPoolNode *node = (ScarPoolNode *)base;
    node->next = NULL;
    scar_pool_freelist[idx] = node;
    scar_pool_n[idx] = 1;
}
#define SCAR_POOL_CON_DEPOSITO 1
#endif

// Un bloque crudo de la clase idx: el primero de la lista de libres de este
// hilo; si está vacía, de la previa o de un lote del depósito (con tareas); si
// tampoco hay, uno nuevo del sistema.
static inline void *scar_pool_tomar(int idx) {
    ScarPoolNode *node = scar_pool_freelist[idx];
    if (__builtin_expect(node != NULL, 1)) {
        scar_pool_freelist[idx] = node->next;
        scar_pool_n[idx]--;
        return (void *)node;
    }
#ifdef SCAR_POOL_CON_DEPOSITO
    return scar_pool_tomar_lento(idx);
#else
    return malloc((size_t)1 << (SCAR_POOL_MIN_SHIFT + idx));
#endif
}

// Devuelve un bloque crudo de la clase idx a la lista de libres de este hilo.
// Con tareas, una lista llena (SCAR_POOL_LOTE) pasa a ser la previa y la
// previa llena va al depósito; sin tareas (un solo hilo), con la lista en el
// tope el bloque vuelve al sistema.
// (scar_pool_touch_thread() va acá y no en scar_pool_tomar(): un hilo que
// nunca dejó un bloque no tiene lista que vaciar al terminar.)
static inline void scar_pool_dejar(void *base, int idx) {
@@SCAR_POOL_TOUCH@@#ifdef SCAR_POOL_CON_DEPOSITO
    if (__builtin_expect(scar_pool_n[idx] >= SCAR_POOL_LOTE, 0)) {
        scar_pool_dejar_lento(base, idx);
        return;
    }
#else
    if (scar_pool_n[idx] >= SCAR_POOL_TOPE) {
        free(base);
        return;
    }
#endif
    ScarPoolNode *node = (ScarPoolNode *)base;
    node->next = scar_pool_freelist[idx];
    scar_pool_freelist[idx] = node;
    scar_pool_n[idx]++;
}

static inline void *scar_malloc(size_t n) {
    size_t total = n + sizeof(size_t);
    int idx = scar_pool_clase(total);
    size_t *base = idx < 0 ? malloc(total) : scar_pool_tomar(idx);
    base[0] = (size_t)idx;
    return (void *)(base + 1);
}

static inline void scar_free(void *p) {
    if (p == NULL) return;
    /*SCAR_STRC_FREE*/
    size_t *base = (size_t *)p - 1;
    if (base[0] == (size_t)-1) {
        free(base);
        return;
    }
    scar_pool_dejar(base, (int)base[0]);
}

// Los buffers de los Vec salen de las mismas listas: antes iban a
// malloc/realloc/free de glibc, y en un programa con dos regiones eran
// unos 23 millones de llamadas por corrida, muchas soltadas en otro hilo que
// el que las pidió; esa pelea dentro de glibc dormía a los hilos (los dos
// modos de tareas). El encabezado es de 16 bytes, no de 8: así los datos
// quedan alineados a 16 como los de malloc. Guarda la clase, o SIZE_MAX si
// el buffer es de malloc directo (más grande que la clase máxima, o el pool
// apagado bajo ASan/TSan). Un buffer de la clase idx deja lugar para
// 2^(MIN+idx) - 16 bytes, y el Vec usa todo ese lugar como capacidad.
#define SCAR_VBUF_HDR 16

// Un buffer para al menos n bytes; en *util, cuántos entran de verdad.
static inline void *scar_vbuf_pedir(size_t n, size_t *util) {
    size_t total = n + SCAR_VBUF_HDR;
    int idx = scar_pool_clase(total);
    size_t *base;
    if (idx < 0) {
        base = malloc(total);
        *util = n;
    } else {
        base = scar_pool_tomar(idx);
        *util = ((size_t)1 << (SCAR_POOL_MIN_SHIFT + idx)) - SCAR_VBUF_HDR;
    }
    if (base == NULL) {
        fputs("sin memoria\n", stderr);
        abort();
    }
    base[0] = (size_t)idx;
    return (unsigned char *)base + SCAR_VBUF_HDR;
}

static inline void scar_vbuf_soltar(void *p) {
    if (p == NULL) return;
    size_t *base = (size_t *)((unsigned char *)p - SCAR_VBUF_HDR);
    if (base[0] == (size_t)-1) {
        free(base);
        return;
    }
    scar_pool_dejar(base, (int)base[0]);
}

// Lleva el buffer p (con 'usados' bytes ocupados) a uno de al menos n bytes.
// Uno de malloc directo que sigue siendo grande se agranda con realloc; lo
// demás se copia a un buffer nuevo y el viejo vuelve a su lista.
static inline void *scar_vbuf_agrandar(void *p, size_t usados, size_t n, size_t *util) {
    if (p != NULL) {
        size_t *base = (size_t *)((unsigned char *)p - SCAR_VBUF_HDR);
        if (base[0] == (size_t)-1 && scar_pool_clase(n + SCAR_VBUF_HDR) < 0) {
            base = realloc(base, n + SCAR_VBUF_HDR);
            if (base == NULL) {
                fputs("sin memoria\n", stderr);
                abort();
            }
            *util = n;
            return (unsigned char *)base + SCAR_VBUF_HDR;
        }
    }
    void *q = scar_vbuf_pedir(n, util);
    if (p != NULL) {
        if (usados) memcpy(q, p, usados);
        scar_vbuf_soltar(p);
    }
    return q;
}
@@TEXTO_SIN_TOPE_C@@
