// ---------------------------------------------------------------------------
// Tareas livianas (SCAR_TAREAS=livianas): muchas tareas en pocos hilos.
//
// Es el modo por defecto desde la 0.2.0. Con SCAR_TAREAS=hilos nada de esto
// corre: cada spawn es un hilo del sistema, como antes. Con livianas, cada tarea (y main) es una
// fibra con su propia pila, y un hilo por núcleo ("trabajador") las va
// corriendo. Una tarea que espera (un canal, un join, un sleep) se duerme en
// una ScarCond (cond.c): su trabajador toma otra en vez de dormirse él.
//
// El diseño salió del prototipo (bench/tareas/prototipos/planificador.c,
// medido): cambio de contexto propio en ensamblador (ucontext es 15 veces más
// lento), colas por trabajador con robo de la mitad, la tarea despertada en
// "siguiente" (se corre en el mismo hilo apenas la actual se duerme, como el
// runnext de Go), pilas con página de guarda (un desborde es un panic, ver
// pila.c) reusadas en una lista de libres.
//
// Dormirse sin carrera: antes de anotarse en la fila de una ScarCond la fibra
// marca `guardando`; suelta sus candados ella misma, vuelve al planificador, y
// recién ahí (con su contexto ya guardado) el planificador borra la marca.
// Quien la despierta (scar_listo) espera a que la marca se borre antes de
// ponerla en una cola: así nadie puede correrla en otro trabajador mientras
// todavía se guarda. (Soltar los candados desde el planificador, como hacía
// el prototipo, confundía a TSan: el unlock lo hacía "otro hilo".)
//
// Lo que el runtime guarda "por hilo" (__scar_ctx, el registro de dueñas
// vivas, el estado de rand(), los límites de la pila) es por tarea: el
// planificador lo guarda en la fibra al salir y lo repone al entrar
// (scar_tls_guardar / scar_tls_restaurar, al final del archivo, después de
// que todo eso está declarado).
// ---------------------------------------------------------------------------
// En Windows (MinGW) no hay mmap, sigaltstack ni el TLS por %fs que esto usa:
// ahí no se compila y cada tarea es un hilo, como antes de la 0.2.0.
// (SCAR_SIN_PLANIFICADOR hace lo mismo en cualquier sistema, para probarlo.)
#if defined(_WIN32) || defined(SCAR_SIN_PLANIFICADOR)
static int scar_correr_main(int (*fn)(int, char **), int argc, char **argv) {
    return fn(argc, argv);
}
#else
#include <limits.h>
#include <sched.h>
#include <sys/mman.h>
#include <sys/resource.h>
#define SCAR_PLANIFICADOR 1
static int scar_livianas = 0;

#define SCAR_SIM2(x) #x
#define SCAR_SIM(x) SCAR_SIM2(x)
#define SCAR_ETIQ(n) SCAR_SIM(__USER_LABEL_PREFIX__) #n

#if !defined(__x86_64__) && !defined(__aarch64__)
#define SCAR_CAMBIO_UCONTEXT 1
#include <ucontext.h>
#endif

#ifndef SCAR_CAMBIO_UCONTEXT
void scar_cambio(void **guardar_sp, void *nuevo_sp);
void scar_trampolin(void);
#if defined(__x86_64__)
// guarda los registros que la convención pide conservar (y el estado de punto
// flotante: mxcsr y la palabra de control x87), cambia de pila y vuelve por el
// ret de la otra
__asm__(
    ".text\n"
    ".globl " SCAR_ETIQ(scar_cambio) "\n"
    SCAR_ETIQ(scar_cambio) ":\n"
    "    pushq %rbp\n    pushq %rbx\n    pushq %r12\n"
    "    pushq %r13\n    pushq %r14\n    pushq %r15\n"
    "    subq $8, %rsp\n"
    "    stmxcsr (%rsp)\n    fnstcw 4(%rsp)\n"
    "    movq %rsp, (%rdi)\n"
    "    movq %rsi, %rsp\n"
    "    ldmxcsr (%rsp)\n    fldcw 4(%rsp)\n"
    "    addq $8, %rsp\n"
    "    popq %r15\n    popq %r14\n    popq %r13\n"
    "    popq %r12\n    popq %rbx\n    popq %rbp\n"
    "    ret\n"
    ".globl " SCAR_ETIQ(scar_trampolin) "\n"
    SCAR_ETIQ(scar_trampolin) ":\n"
    "    movq %r12, %rdi\n"
    "    call *%r13\n"
    "    ud2\n");
// la pila nueva, de arriba hacia abajo: trampolín (lo toma el ret), rbp, rbx,
// r12 = arg, r13 = fn, r14, r15, mxcsr + palabra de control x87. Después del
// ret la pila queda alineada a 16, como pide la convención antes de un call.
static void *scar_pila_inicial(char *tope, void (*fn)(void *), void *arg) {
    uint64_t *p = (uint64_t *)((uintptr_t)tope & ~(uintptr_t)15);
    *--p = (uint64_t)(uintptr_t)scar_trampolin;
    *--p = 0;                         /* rbp */
    *--p = 0;                         /* rbx */
    *--p = (uint64_t)(uintptr_t)arg;  /* r12 */
    *--p = (uint64_t)(uintptr_t)fn;   /* r13 */
    *--p = 0;                         /* r14 */
    *--p = 0;                         /* r15 */
    *--p = 0x037F00001F80ull;         /* mxcsr 0x1F80, fcw 0x037F */
    return p;
}
#else
__asm__(
    ".text\n"
    ".globl " SCAR_ETIQ(scar_cambio) "\n"
    SCAR_ETIQ(scar_cambio) ":\n"
    "    sub sp, sp, #160\n"
    "    stp x19, x20, [sp, #0]\n    stp x21, x22, [sp, #16]\n"
    "    stp x23, x24, [sp, #32]\n    stp x25, x26, [sp, #48]\n"
    "    stp x27, x28, [sp, #64]\n    stp x29, x30, [sp, #80]\n"
    "    stp d8, d9, [sp, #96]\n    stp d10, d11, [sp, #112]\n"
    "    stp d12, d13, [sp, #128]\n    stp d14, d15, [sp, #144]\n"
    "    mov x2, sp\n    str x2, [x0]\n"
    "    mov sp, x1\n"
    "    ldp x19, x20, [sp, #0]\n    ldp x21, x22, [sp, #16]\n"
    "    ldp x23, x24, [sp, #32]\n    ldp x25, x26, [sp, #48]\n"
    "    ldp x27, x28, [sp, #64]\n    ldp x29, x30, [sp, #80]\n"
    "    ldp d8, d9, [sp, #96]\n    ldp d10, d11, [sp, #112]\n"
    "    ldp d12, d13, [sp, #128]\n    ldp d14, d15, [sp, #144]\n"
    "    add sp, sp, #160\n"
    "    ret\n"
    ".globl " SCAR_ETIQ(scar_trampolin) "\n"
    SCAR_ETIQ(scar_trampolin) ":\n"
    "    mov x0, x19\n"
    "    blr x20\n"
    "    brk #0\n");
static void *scar_pila_inicial(char *tope, void (*fn)(void *), void *arg) {
    uint64_t *p = (uint64_t *)((uintptr_t)tope & ~(uintptr_t)15);
    p -= 20;
    memset(p, 0, 160);
    p[0] = (uint64_t)(uintptr_t)arg;               /* x19 */
    p[1] = (uint64_t)(uintptr_t)fn;                /* x20 */
    p[11] = (uint64_t)(uintptr_t)scar_trampolin;   /* x30 */
    return p;
}
#endif
#endif

// Candado de giro chico: protege secciones de pocas líneas (una cola, la fila
// de una ScarCond). Nunca se duerme con uno tomado.
typedef struct { atomic_int v; } ScarGiro;
static inline void scar_giro_tomar(ScarGiro *g) {
    for (;;) {
        if (!atomic_exchange_explicit(&g->v, 1, memory_order_acquire)) return;
        while (atomic_load_explicit(&g->v, memory_order_relaxed)) {
#if defined(__x86_64__) || defined(__i386__)
            __builtin_ia32_pause();
#elif defined(__aarch64__)
            __asm__ __volatile__("yield");
#endif
        }
    }
}
static inline void scar_giro_soltar(ScarGiro *g) {
    atomic_store_explicit(&g->v, 0, memory_order_release);
}

struct ScarCond;
typedef struct ScarFibra {
    void *sp;
#ifdef SCAR_CAMBIO_UCONTEXT
    ucontext_t uc;
#endif
    char *mapa;                 // el mmap entero: página de guarda + pila
    size_t tam_mapa;
    void *(*fn)(void *);
    void *arg;
    void *resultado;
    void *tarea;                // el TaskContext (NULL para main)
    struct ScarFibra *sig;      // en una cola de listas
    atomic_int guardando;       // está dejando su hilo: no ponerla en cola todavía
    // la espera en una ScarCond (una a la vez)
    struct ScarCond *esp_cv;
    struct ScarFibra *esp_sig, *esp_ant;
    atomic_int esp_estado;      // 0 esperando, 1 avisada, 2 vencida
    int esp_idx;                // en el montículo de plazos; -1 si no está
    atomic_int esp_plazo_vivo;  // el montículo todavía la puede tocar
    long long esp_vence;        // ns de CLOCK_MONOTONIC
    int esp_vigilancia;         // el plazo es de vigilancia (no cuenta como progreso)
    struct ScarTrab *park_trab; // en la lista de dormidas de qué trabajador (NULL: ninguna)
    struct ScarFibra *park_sig, *park_ant;
    // lo "por hilo" del runtime que en realidad es de cada tarea
    void *tls_ctx;
    void *tls_vivos;
    int tls_nvivos, tls_capvivos;
    uint64_t tls_rand[3];
    uintptr_t tls_pila_hi, tls_pila_lo;
#if defined(__SANITIZE_ADDRESS__)
    void *asan_falsa;           // pila falsa de ASan (detect_stack_use_after_return)
#endif
#if defined(__SANITIZE_THREAD__)
    void *tsan_fibra;
#endif
} ScarFibra;

typedef struct ScarTrab {
    pthread_t hilo;
    int id;
    void *sp_plan;              // el contexto del bucle del planificador
#ifdef SCAR_CAMBIO_UCONTEXT
    ucontext_t uc_plan;
#endif
    ScarFibra *actual;
    ScarGiro mu;
    ScarFibra *cab, *cola;
    atomic_int n;
    _Atomic(ScarFibra *) siguiente;
    _Atomic long long siguiente_desde;   // ns: desde cuándo espera la de "siguiente"
    int racha_siguiente;                 // despertadas seguidas por "siguiente" (justicia)
    atomic_int bloqueado;                // su tarea está en una llamada que bloquea (scar_bloqueo_entrar)
    void (*despues)(void *);
    void *despues_arg;
    void *despues_arg2;
    // dormir: cada trabajador en su propio candado (un mutex global para
    // avisar era un embudo con 12 núcleos y muchas tareas despertándose)
    pthread_mutex_t dormir_mu;
    pthread_cond_t dormir_cv;
    atomic_int durmiendo;
    // las fibras que se durmieron acá en una ScarCond sin plazo (candidatas a
    // dar el deadlock). Cada una se saca sola al despertar, con park_mu: así
    // una fibra de la lista nunca está liberada.
    ScarGiro park_mu;
    struct ScarFibra *park_cab;
#if defined(__SANITIZE_THREAD__)
    void *tsan_plan;
#endif
} ScarTrab;

// Una barrera de orden total entre "puse trabajo" y "miro si hay dormidos" (y
// al revés): un RMW seq_cst sobre un átomo y no atomic_thread_fence, que TSan
// no sabe ver.
static atomic_llong scar_proximo_plazo;   // (definido más abajo, con los plazos)
static inline long long scar_mono_ns(void);
static atomic_int scar_barrera_v = 0;
static inline void scar_barrera(void) { atomic_fetch_add_explicit(&scar_barrera_v, 0, memory_order_seq_cst); }
static int scar_n_trab = 1;           // los que corren a la vez: uno por núcleo
#define SCAR_MAX_TRAB 1024            // más los que están bloqueados en una llamada
static ScarTrab *scar_trab = NULL;
static atomic_int scar_trab_creados = 0;
static atomic_int scar_trab_bloqueados = 0;
static pthread_mutex_t scar_trab_crear_mu = PTHREAD_MUTEX_INITIALIZER;
// scar_yo (el trabajador de este hilo): en ScarHilo (tls.c)
static ScarGiro scar_global_mu;
static ScarFibra *scar_global_cab = NULL, *scar_global_cola = NULL;
static atomic_int scar_global_n = 0;
static atomic_int scar_n_dormidos = 0;
static atomic_int scar_trab_girando = 0;          // trabajadores ociosos girando
static long long scar_giro_ocioso_ns = 5000;      // cuánto gira uno sin trabajo antes de dormir
// El trabajador dormido que cuida el próximo plazo (duerme justo hasta que
// venza); los demás duermen sin mirar el reloj. -1: nadie. Antes, cada plazo
// nuevo más cercano despertaba a TODOS los dormidos a recalcular: con 12
// núcleos, 11 despertares por cada join (crear_en_serie: 2,9 -> 12,9 us).
static atomic_int scar_cuidador = -1;
static _Atomic uint64_t scar_dormidos_mapa = 0;   // bit i: el trabajador i duerme (los primeros 64)
static pthread_condattr_t scar_cond_mono_attr;
static size_t scar_pagina = 4096;
static size_t scar_tam_pila = 1u << 20;
static size_t scar_tam_pila_main = 8u << 20;

static void scar_tls_guardar(ScarFibra *f);
static void scar_tls_restaurar(ScarFibra *f);
static void scar_cond_quitar_vencida(ScarFibra *f);
static void scar_tarea_fibra_termino(void *tarea, void *resultado);

// ¿esta llamada corre adentro de una fibra? (con hilos: nunca)
static inline ScarFibra *scar_fibra_actual(void) {
    ScarTrab *t = scar_yo;
    return t ? t->actual : NULL;
}

static inline long long scar_mono_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (long long)t.tv_sec * 1000000000LL + t.tv_nsec;
}

// ---- pilas: mmap con una página de guarda abajo, reusadas ----
static pthread_mutex_t scar_pilas_mu = PTHREAD_MUTEX_INITIALIZER;
static char *scar_pilas_libres = NULL;    // enlazadas por la primera palabra útil
static int scar_n_pilas_libres = 0;
#define SCAR_MAX_PILAS_LIBRES 16384

static char *scar_pila_tomar(size_t tam) {
    if (tam == scar_tam_pila) {
        pthread_mutex_lock(&scar_pilas_mu);
        char *p = scar_pilas_libres;
        if (p) {
            scar_pilas_libres = *(char **)(p + scar_pagina);
            scar_n_pilas_libres--;
        }
        pthread_mutex_unlock(&scar_pilas_mu);
        if (p) return p;
    }
    char *p = mmap(NULL, tam + scar_pagina, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (p == MAP_FAILED) return NULL;
    if (mprotect(p, scar_pagina, PROT_NONE) != 0) {
        munmap(p, tam + scar_pagina);
        return NULL;
    }
    return p;
}

static void scar_pila_soltar(char *p, size_t tam) {
    if (tam == scar_tam_pila) {
        pthread_mutex_lock(&scar_pilas_mu);
        if (scar_n_pilas_libres < SCAR_MAX_PILAS_LIBRES) {
            *(char **)(p + scar_pagina) = scar_pilas_libres;
            scar_pilas_libres = p;
            scar_n_pilas_libres++;
            pthread_mutex_unlock(&scar_pilas_mu);
            return;
        }
        pthread_mutex_unlock(&scar_pilas_mu);
    }
    munmap(p, tam + scar_pagina);
}

// ---- avisos a los sanitizers en cada cambio de pila ----
#if defined(__SANITIZE_ADDRESS__)
void __sanitizer_start_switch_fiber(void **fake_stack_save, const void *bottom, size_t size);
void __sanitizer_finish_switch_fiber(void *fake_stack_save, const void **bottom_old, size_t *size_old);
#endif
#if defined(__SANITIZE_THREAD__)
void *__tsan_get_current_fiber(void);
void *__tsan_create_fiber(unsigned flags);
void __tsan_destroy_fiber(void *fiber);
void __tsan_switch_to_fiber(void *fiber, unsigned flags);
#endif

// ---- colas ----
static void scar_trab_crear_si_hace_falta(void);

// Hay trabajo nuevo en una cola: si un trabajador duerme, se lo despierta; si
// no y quien lo puso está ocupado corriendo una fibra (o no es un trabajador),
// se crea uno más, hasta uno por núcleo.
// despierta a un trabajador dormido (si hay): el de menor número en la
// máscara, con su propio candado
static void scar_despertar_dormido(void) {
    uint64_t m = atomic_load_explicit(&scar_dormidos_mapa, memory_order_relaxed);
    ScarTrab *v = NULL;
    if (m) {
        v = &scar_trab[__builtin_ctzll(m)];
    } else {
        // más de 64 trabajadores (bloqueos): buscar uno dormido a mano
        int creados = atomic_load(&scar_trab_creados);
        for (int i = 64; i < creados; i++)
            if (atomic_load_explicit(&scar_trab[i].durmiendo, memory_order_relaxed)) { v = &scar_trab[i]; break; }
    }
    if (!v) return;
    pthread_mutex_lock(&v->dormir_mu);
    pthread_cond_signal(&v->dormir_cv);
    pthread_mutex_unlock(&v->dormir_mu);
}
static void scar_despertar_un_trabajador(void) {
    if (atomic_load(&scar_n_dormidos) > 0) {
        scar_despertar_dormido();
    } else if (atomic_load_explicit(&scar_trab_creados, memory_order_relaxed)
                   - atomic_load_explicit(&scar_trab_bloqueados, memory_order_relaxed) < scar_n_trab
               && (!scar_yo || scar_yo->actual)) {
        scar_trab_crear_si_hace_falta();
    }
}

// Una tarea va a hacer una llamada que puede bloquear su hilo (leer un
// archivo o la red, una extern fn que tarda lo que quiera): deja de contar
// como trabajador mientras dura, lo que tenía en cola pasa a la cola global, y
// si hace falta se crea otro hilo para que las demás tareas sigan. Al volver,
// el hilo sigue con su tarea (si por un rato corren más hilos que núcleos, el
// que sobra se duerme en cuanto se queda sin trabajo).
static void scar_bloqueo_entrar_real(void) {
    ScarTrab *t = scar_yo;
    if (!t || !t->actual) return;
    atomic_fetch_add(&scar_trab_bloqueados, 1);
    atomic_store_explicit(&t->bloqueado, 1, memory_order_release);
    // lo que este trabajador tenía en cola se lo pueden llevar los demás
    // (scar_robar, que a un bloqueado también le roba la "siguiente"); acá
    // solo se avisa si hace falta, sin mover nada: un fwrite chico no puede
    // costar una mudanza de cola cada vez
    // (también si hay un plazo pendiente: mientras esta tarea está en C nadie
    // de este hilo va a mirar el reloj)
    if (atomic_load_explicit(&t->n, memory_order_relaxed) > 0
        || atomic_load_explicit(&t->siguiente, memory_order_relaxed)
        || atomic_load_explicit(&scar_proximo_plazo, memory_order_relaxed) != LLONG_MAX) {
        scar_barrera();
        if (atomic_load(&scar_n_dormidos) > 0) {
            scar_despertar_dormido();
        } else if (atomic_load(&scar_trab_creados) - atomic_load(&scar_trab_bloqueados) < scar_n_trab) {
            scar_trab_crear_si_hace_falta();
        }
    }
}
static void scar_bloqueo_salir_real(void) {
    ScarTrab *t = scar_yo;
    if (!t || !t->actual) return;
    atomic_store_explicit(&t->bloqueado, 0, memory_order_relaxed);
    atomic_fetch_sub(&scar_trab_bloqueados, 1);
}
#undef SCAR_BLOQUEANDO
#undef scar_bloqueo_entrar
#undef scar_bloqueo_salir
#define scar_bloqueo_entrar() do { if (scar_livianas) scar_bloqueo_entrar_real(); } while (0)
#define scar_bloqueo_salir() do { if (scar_livianas) scar_bloqueo_salir_real(); } while (0)
#define SCAR_BLOQUEANDO(expr) __extension__ ({ scar_bloqueo_entrar(); __typeof__(expr) __scar_r = (expr); scar_bloqueo_salir(); __scar_r; })

// Pone una fibra lista para correr. Desde una fibra, con como_siguiente: en
// "siguiente" de su trabajador (la que estaba ahí pasa a la cola, donde otros
// la pueden robar). Desde el planificador: en la cola del trabajador. Desde
// afuera de los trabajadores: en la cola global.
static void scar_listo(ScarFibra *f, int como_siguiente) {
    // la fibra puede estar todavía guardando su contexto en otro hilo (unos
    // cientos de ns): esperar a que termine
    while (atomic_load_explicit(&f->guardando, memory_order_acquire)) {
#if defined(__x86_64__) || defined(__i386__)
        __builtin_ia32_pause();
#elif defined(__aarch64__)
        __asm__ __volatile__("yield");
#endif
    }
    ScarTrab *t = scar_yo;
    if (t) {
        // Justicia: dos tareas que se pasan mensajes sin parar irían siempre por
        // "siguiente" y las demás de la cola de este trabajador no correrían
        // nunca (no hay quien las interrumpa). Cada 64 seguidas, la despertada
        // va al final de la cola y las otras tienen su turno.
        if (como_siguiente && t->actual
            && !(++t->racha_siguiente >= 64 && atomic_load_explicit(&t->n, memory_order_relaxed) > 0)) {
            atomic_store_explicit(&t->siguiente_desde, scar_mono_ns(), memory_order_relaxed);
            ScarFibra *vieja = atomic_exchange(&t->siguiente, f);
            if (!vieja) return;
            f = vieja;
        } else if (como_siguiente) {
            t->racha_siguiente = 0;
        }
        f->sig = NULL;
        scar_giro_tomar(&t->mu);
        if (t->cola) t->cola->sig = f; else t->cab = f;
        t->cola = f;
        atomic_fetch_add_explicit(&t->n, 1, memory_order_relaxed);
        scar_giro_soltar(&t->mu);
    } else {
        f->sig = NULL;
        scar_giro_tomar(&scar_global_mu);
        if (scar_global_cola) scar_global_cola->sig = f; else scar_global_cab = f;
        scar_global_cola = f;
        atomic_fetch_add_explicit(&scar_global_n, 1, memory_order_relaxed);
        scar_giro_soltar(&scar_global_mu);
    }
    scar_barrera();
    scar_despertar_un_trabajador();
}

static ScarFibra *scar_cola_sacar(ScarTrab *t) {
    if (atomic_load_explicit(&t->n, memory_order_relaxed) == 0) return NULL;
    scar_giro_tomar(&t->mu);
    ScarFibra *f = t->cab;
    if (f) {
        t->cab = f->sig;
        if (!t->cab) t->cola = NULL;
        atomic_fetch_sub_explicit(&t->n, 1, memory_order_relaxed);
    }
    scar_giro_soltar(&t->mu);
    return f;
}

static ScarFibra *scar_global_sacar(void) {
    if (atomic_load_explicit(&scar_global_n, memory_order_relaxed) == 0) return NULL;
    scar_giro_tomar(&scar_global_mu);
    ScarFibra *f = scar_global_cab;
    if (f) {
        scar_global_cab = f->sig;
        if (!scar_global_cab) scar_global_cola = NULL;
        atomic_fetch_sub_explicit(&scar_global_n, 1, memory_order_relaxed);
    }
    scar_giro_soltar(&scar_global_mu);
    return f;
}

// robar a otro trabajador la mitad de su cola (una para correr ya, el resto a
// la mía); "siguiente" solo después de un rato sin trabajo: la tarea que la
// despertó suele dormirse enseguida y la corre su propio hilo
static ScarFibra *scar_robar(ScarTrab *t, int tambien_siguiente) {
    int creados = atomic_load(&scar_trab_creados);
    for (int k = 1; k < creados; k++) {
        ScarTrab *v = &scar_trab[(t->id + k) % creados];
        if (atomic_load_explicit(&v->n, memory_order_relaxed) > 0) {
            ScarFibra *resto[64];
            int nr = 0;
            scar_giro_tomar(&v->mu);
            int llevar = (atomic_load_explicit(&v->n, memory_order_relaxed) + 1) / 2;
            ScarFibra *primera = v->cab;
            if (primera) {
                v->cab = primera->sig;
                atomic_fetch_sub_explicit(&v->n, 1, memory_order_relaxed);
                for (int i = 1; i < llevar && nr < 64 && v->cab; i++) {
                    ScarFibra *x = v->cab;
                    v->cab = x->sig;
                    atomic_fetch_sub_explicit(&v->n, 1, memory_order_relaxed);
                    resto[nr++] = x;
                }
                if (!v->cab) v->cola = NULL;
            }
            scar_giro_soltar(&v->mu);
            if (nr) {
                scar_giro_tomar(&t->mu);
                for (int i = 0; i < nr; i++) {
                    resto[i]->sig = NULL;
                    if (t->cola) t->cola->sig = resto[i]; else t->cab = resto[i];
                    t->cola = resto[i];
                }
                atomic_fetch_add_explicit(&t->n, nr, memory_order_relaxed);
                scar_giro_soltar(&t->mu);
            }
            if (primera) return primera;
        }
        if (tambien_siguiente && atomic_load_explicit(&v->siguiente, memory_order_relaxed)
            // solo si lleva un rato ahí (el dueño no la tomó porque sigue ocupado):
            // recién despertada, la corre su propio trabajador en cuanto la
            // actual se duerma, sin cruzar de núcleo. A un trabajador bloqueado
            // en una llamada se le roba enseguida.
            && (atomic_load_explicit(&v->bloqueado, memory_order_relaxed)
                || scar_mono_ns() - atomic_load_explicit(&v->siguiente_desde, memory_order_relaxed) > 50000)) {
            ScarFibra *s = atomic_exchange(&v->siguiente, NULL);
            if (s) return s;
        }
    }
    return NULL;
}

// ---- plazos (esperas con tiempo: sleep, el join con su plazo, los 250 ms
// del detector de deadlock): un montículo de fibras ordenado por vencimiento ----
static pthread_mutex_t scar_plazos_mu = PTHREAD_MUTEX_INITIALIZER;
static ScarFibra **scar_plazos = NULL;
static int scar_n_plazos = 0, scar_cap_plazos = 0;
static atomic_llong scar_proximo_plazo = LLONG_MAX;
// plazos "de progreso" (un sleep: cuando venza, algo avanza) contra "de
// vigilancia" (los tramos de un join, que solo vuelven a mirar): el detector
// de deadlock (scar_detectar_deadlock) ignora los de vigilancia
static atomic_int scar_plazos_progreso = 0;
#define SCAR_TRABADA 0x7A6B  // lo que devuelve scar_cond_timedwait a la fibra elegida en un deadlock

static void scar_plazos_subir(int i) {
    while (i > 0) {
        int p = (i - 1) / 2;
        if (scar_plazos[p]->esp_vence <= scar_plazos[i]->esp_vence) break;
        ScarFibra *x = scar_plazos[p];
        scar_plazos[p] = scar_plazos[i]; scar_plazos[p]->esp_idx = p;
        scar_plazos[i] = x; x->esp_idx = i;
        i = p;
    }
}
static void scar_plazos_bajar(int i) {
    for (;;) {
        int a = 2 * i + 1, b = a + 1, m = i;
        if (a < scar_n_plazos && scar_plazos[a]->esp_vence < scar_plazos[m]->esp_vence) m = a;
        if (b < scar_n_plazos && scar_plazos[b]->esp_vence < scar_plazos[m]->esp_vence) m = b;
        if (m == i) break;
        ScarFibra *x = scar_plazos[m];
        scar_plazos[m] = scar_plazos[i]; scar_plazos[m]->esp_idx = m;
        scar_plazos[i] = x; x->esp_idx = i;
        i = m;
    }
}
static void scar_plazos_quitar_idx(int i) {
    ScarFibra *f = scar_plazos[i];
    f->esp_idx = -1;
    if (!f->esp_vigilancia) atomic_fetch_sub(&scar_plazos_progreso, 1);
    scar_n_plazos--;
    if (i != scar_n_plazos) {
        scar_plazos[i] = scar_plazos[scar_n_plazos];
        scar_plazos[i]->esp_idx = i;
        scar_plazos_bajar(i);
        scar_plazos_subir(i);
    }
    atomic_store(&scar_proximo_plazo, scar_n_plazos ? scar_plazos[0]->esp_vence : LLONG_MAX);
}
static void scar_plazo_poner(ScarFibra *f, long long vence, int vigilancia) {
    f->esp_vigilancia = vigilancia;
    if (!vigilancia) atomic_fetch_add(&scar_plazos_progreso, 1);
    pthread_mutex_lock(&scar_plazos_mu);
    if (scar_n_plazos == scar_cap_plazos) {
        scar_cap_plazos = scar_cap_plazos ? scar_cap_plazos * 2 : 64;
        scar_plazos = realloc(scar_plazos, sizeof(ScarFibra *) * (size_t)scar_cap_plazos);
    }
    f->esp_vence = vence;
    atomic_store(&f->esp_plazo_vivo, 1);
    f->esp_idx = scar_n_plazos;
    scar_plazos[scar_n_plazos++] = f;
    scar_plazos_subir(f->esp_idx);
    long long antes = atomic_load(&scar_proximo_plazo);
    atomic_store(&scar_proximo_plazo, scar_plazos[0]->esp_vence);
    pthread_mutex_unlock(&scar_plazos_mu);
    // un plazo más cercano que el que esperan los trabajadores dormidos: que
    // alguno se despierte a recalcular cuánto dormir
    // Un plazo de vigilancia (un tramo de join) no necesita precisión: los
    // dormidos se despiertan solos cada 50 ms. Uno de progreso (un sleep): que
    // lo sepa el cuidador, o que alguno pase a serlo.
    if (!vigilancia && vence < antes && atomic_load(&scar_n_dormidos) > 0) {
        int k = atomic_load(&scar_cuidador);
        if (k >= 0) {
            pthread_mutex_lock(&scar_trab[k].dormir_mu);
            pthread_cond_signal(&scar_trab[k].dormir_cv);
            pthread_mutex_unlock(&scar_trab[k].dormir_mu);
        } else {
            scar_despertar_dormido();
        }
    }
}
// La fibra ya despertó (avisada): saca su plazo, o espera a que quien lo está
// disparando termine de tocarla.
static void scar_plazo_quitar(ScarFibra *f) {
    pthread_mutex_lock(&scar_plazos_mu);
    if (f->esp_idx >= 0) {
        scar_plazos_quitar_idx(f->esp_idx);
        atomic_store(&f->esp_plazo_vivo, 0);
    }
    pthread_mutex_unlock(&scar_plazos_mu);
    while (atomic_load(&f->esp_plazo_vivo)) sched_yield();
}
// los plazos vencidos: la fibra que todavía esperaba se despierta "vencida"
static void scar_plazos_disparar(void) {
    if (atomic_load_explicit(&scar_proximo_plazo, memory_order_relaxed) == LLONG_MAX) return;
    long long ahora = scar_mono_ns();
    if (ahora < atomic_load_explicit(&scar_proximo_plazo, memory_order_relaxed)) return;
    for (;;) {
        pthread_mutex_lock(&scar_plazos_mu);
        if (scar_n_plazos == 0 || scar_plazos[0]->esp_vence > ahora) {
            pthread_mutex_unlock(&scar_plazos_mu);
            return;
        }
        ScarFibra *f = scar_plazos[0];
        scar_plazos_quitar_idx(0);
        pthread_mutex_unlock(&scar_plazos_mu);
        int e = 0;
        if (atomic_compare_exchange_strong(&f->esp_estado, &e, 2)) {
            scar_cond_quitar_vencida(f);
            atomic_store(&f->esp_plazo_vivo, 0);
            scar_listo(f, 0);
        } else {
            atomic_store(&f->esp_plazo_vivo, 0);
        }
    }
}

// ---- cambios de contexto ----
static void scar_cambiar_a_fibra(ScarTrab *t, ScarFibra *f) {
    t->actual = f;
    scar_tls_restaurar(f);
#if defined(__SANITIZE_ADDRESS__)
    void *falsa = NULL;
    __sanitizer_start_switch_fiber(&falsa, f->mapa + scar_pagina, f->tam_mapa - scar_pagina);
#endif
#if defined(__SANITIZE_THREAD__)
    __tsan_switch_to_fiber(f->tsan_fibra, 0);
#endif
#ifdef SCAR_CAMBIO_UCONTEXT
    swapcontext(&t->uc_plan, &f->uc);
#else
    scar_cambio(&t->sp_plan, f->sp);
#endif
#if defined(__SANITIZE_ADDRESS__)
    __sanitizer_finish_switch_fiber(falsa, NULL, NULL);
#endif
    scar_tls_guardar(f);
    t->actual = NULL;
    // la fibra ya está guardada: desde acá otro hilo puede correrla
    atomic_store_explicit(&f->guardando, 0, memory_order_release);
    if (t->despues) {
        void (*d)(void *) = t->despues;
        t->despues = NULL;
        d(t->despues_arg);
    }
}

// La fibra actual vuelve al planificador. `despues` corre ya en el
// planificador, con el contexto de la fibra guardado.
static void scar_ceder_al_plan(void (*despues)(void *), void *arg) {
    ScarTrab *t = scar_yo;
    ScarFibra *f = t->actual;
    atomic_store_explicit(&f->guardando, 1, memory_order_relaxed);
    t->despues = despues;
    t->despues_arg = arg;
#if defined(__SANITIZE_ADDRESS__)
    __sanitizer_start_switch_fiber(&f->asan_falsa, NULL, 0);
#endif
#if defined(__SANITIZE_THREAD__)
    __tsan_switch_to_fiber(t->tsan_plan, 0);
#endif
#ifdef SCAR_CAMBIO_UCONTEXT
    swapcontext(&f->uc, &t->uc_plan);
#else
    scar_cambio(&f->sp, t->sp_plan);
#endif
#if defined(__SANITIZE_ADDRESS__)
    __sanitizer_finish_switch_fiber(f->asan_falsa, NULL, NULL);
#endif
    // volvió: puede ser en otro trabajador
}

static void scar_reponer(void *f) { scar_listo((ScarFibra *)f, 0); }

// ceder el turno: la fibra vuelve a la cola recién cuando ya está guardada
static void scar_ceder(void) {
    ScarFibra *f = scar_fibra_actual();
    if (f) scar_ceder_al_plan(scar_reponer, f);
    else sched_yield();
}

// ¿hay un plazo vencido sin disparar? (lo mira una tarea que no espera nunca)
static inline int scar_plazo_vencido(void) {
    long long p = atomic_load_explicit(&scar_proximo_plazo, memory_order_relaxed);
    return p != LLONG_MAX && p <= scar_mono_ns();
}

// ¿hay otra fibra lista en este trabajador o en la global? (para ceder el
// turno en los bucles largos sin esperas, ver scar_safepoint)
static inline int scar_hay_otras(void) {
    ScarTrab *t = scar_yo;
    return t && (atomic_load_explicit(&t->siguiente, memory_order_relaxed)
                 || atomic_load_explicit(&t->n, memory_order_relaxed) > 0
                 || atomic_load_explicit(&scar_global_n, memory_order_relaxed) > 0);
}

static void scar_fibra_fin(void *p) {
    ScarFibra *f = p;
    void *tarea = f->tarea, *res = f->resultado;
#if defined(__SANITIZE_THREAD__)
    __tsan_destroy_fiber(f->tsan_fibra);
#endif
    scar_pila_soltar(f->mapa, f->tam_mapa - scar_pagina);
    free(f);
    if (tarea) scar_tarea_fibra_termino(tarea, res);
}

static void scar_fibra_entrada(void *p) {
    ScarFibra *f = p;
#if defined(__SANITIZE_ADDRESS__)
    __sanitizer_finish_switch_fiber(NULL, NULL, NULL);
#endif
    f->resultado = f->fn(f->arg);
    scar_ceder_al_plan(scar_fibra_fin, f);
}

#ifdef SCAR_CAMBIO_UCONTEXT
static void scar_fibra_entrada_uc(unsigned lo, unsigned hi) {
    scar_fibra_entrada((void *)(((uintptr_t)hi << 32) | lo));
}
#endif

// una fibra nueva (sin poner en cola); NULL si no hay memoria para su pila
static ScarFibra *scar_fibra_nueva(void *(*fn)(void *), void *arg, void *tarea, size_t tam) {
    ScarFibra *f = calloc(1, sizeof(ScarFibra));
    if (!f) return NULL;
    f->mapa = scar_pila_tomar(tam);
    if (!f->mapa) { free(f); return NULL; }
    f->tam_mapa = tam + scar_pagina;
    f->fn = fn;
    f->arg = arg;
    f->tarea = tarea;
    f->esp_idx = -1;
    f->tls_pila_lo = (uintptr_t)(f->mapa + scar_pagina);
    f->tls_pila_hi = (uintptr_t)(f->mapa + f->tam_mapa);
#ifdef SCAR_CAMBIO_UCONTEXT
    getcontext(&f->uc);
    f->uc.uc_stack.ss_sp = f->mapa + scar_pagina;
    f->uc.uc_stack.ss_size = tam;
    f->uc.uc_link = NULL;
    uintptr_t u = (uintptr_t)f;
    makecontext(&f->uc, (void (*)(void))scar_fibra_entrada_uc, 2, (unsigned)u, (unsigned)(u >> 32));
#else
    f->sp = scar_pila_inicial(f->mapa + f->tam_mapa, scar_fibra_entrada, f);
#endif
#if defined(__SANITIZE_THREAD__)
    f->tsan_fibra = __tsan_create_fiber(0);
#endif
    return f;
}

// la lista de dormidas sin plazo de un trabajador
static inline void scar_park_poner(ScarFibra *f) {
    ScarTrab *t = scar_yo;
    f->park_trab = t;
    scar_giro_tomar(&t->park_mu);
    f->park_ant = NULL;
    f->park_sig = t->park_cab;
    if (t->park_cab) t->park_cab->park_ant = f;
    t->park_cab = f;
    scar_giro_soltar(&t->park_mu);
}
static inline void scar_park_quitar(ScarFibra *f) {
    ScarTrab *t = f->park_trab;
    if (!t) return;
    scar_giro_tomar(&t->park_mu);
    if (f->park_ant) f->park_ant->park_sig = f->park_sig; else t->park_cab = f->park_sig;
    if (f->park_sig) f->park_sig->park_ant = f->park_ant;
    scar_giro_soltar(&t->park_mu);
    f->park_trab = NULL;
    f->park_sig = f->park_ant = NULL;
}

// ---- deadlock ----
// Con tareas livianas el planificador lo ve solo: todos los trabajadores
// dormidos, nada en las colas, ninguna tarea bloqueada en C y ningún plazo de
// progreso pendiente: nadie puede volver a correr. (Con hilos, cada espera en
// un canal vence a los 250 ms y mira si hubo progreso; acá las esperas en un
// canal no tienen plazo, que con 12 núcleos el montículo era un embudo.)
// Despierta a una fibra parqueada como "trabada": vuelve de su espera con
// SCAR_TRABADA y panickea con el mensaje de deadlock de siempre, por el camino
// de siempre (cancela hermanas, suelta lo vivo, el join lo propaga).
static int scar_detectar_deadlock(ScarTrab *t) {
    (void)t;
    if (atomic_load(&scar_trab_bloqueados) != 0) return 0;
    if (atomic_load_explicit(&scar_global_n, memory_order_relaxed) > 0) return 0;
    if (atomic_load(&scar_plazos_progreso) != 0) return 0;
    int creados = atomic_load(&scar_trab_creados);
    if (atomic_load(&scar_n_dormidos) != creados) return 0;
    scar_barrera();
    // segunda mirada, por si algo cambió mientras contábamos
    if (atomic_load(&scar_trab_bloqueados) != 0 || atomic_load(&scar_plazos_progreso) != 0
        || atomic_load(&scar_n_dormidos) != atomic_load(&scar_trab_creados)) return 0;
    for (int i = 0; i < creados; i++) {
        if (atomic_load_explicit(&scar_trab[i].n, memory_order_relaxed) > 0
            || atomic_load_explicit(&scar_trab[i].siguiente, memory_order_relaxed)) return 0;
    }
    for (int i = 0; i < creados; i++) {
        ScarTrab *v = &scar_trab[i];
        ScarFibra *elegida = NULL;
        scar_giro_tomar(&v->park_mu);
        for (ScarFibra *f = v->park_cab; f; f = f->park_sig) {
            int e = 0;
            if (atomic_compare_exchange_strong(&f->esp_estado, &e, 3)) {
                // seguía esperando: su ScarCond está viva y nadie más la despierta
                scar_cond_quitar_vencida(f);
                elegida = f;
                break;
            }
        }
        scar_giro_soltar(&v->park_mu);
        if (elegida) { scar_listo(elegida, 0); return 1; }
    }
    // nadie a quien despertar: no es un deadlock de canales (si lo es de join,
    // lo da el plazo de join). Desde el planificador no se puede panickear.
    return 0;
}

// ---- trabajadores ----
static ScarFibra *scar_buscar_trabajo(ScarTrab *t, int vuelta) {
    scar_plazos_disparar();
    ScarFibra *f = atomic_load_explicit(&t->siguiente, memory_order_relaxed)
        ? atomic_exchange(&t->siguiente, NULL) : NULL;
    if (f) return f;
    t->racha_siguiente = 0;
    if ((f = scar_cola_sacar(t))) return f;
    if ((f = scar_global_sacar())) return f;
    return scar_robar(t, vuelta > 200 || atomic_load_explicit(&scar_trab_bloqueados, memory_order_relaxed) > 0);
}

static void *scar_bucle_trabajador(void *p) {
    ScarTrab *t = p;
    scar_yo = t;
#if defined(__SANITIZE_THREAD__)
    t->tsan_plan = __tsan_get_current_fiber();
#endif
    uint64_t mi_bit = t->id < 64 ? (1ull << t->id) : 0;
    for (;;) {
        ScarFibra *f = NULL;
        // sin trabajo: girar un rato (SCAR_GIRO_OCIOSO_US, 5 us) antes de dormir, que dormir
        // y despertar un hilo cuesta mucho más que eso. Pero no todos a la vez:
        // a lo más un cuarto de los trabajadores (en una máquina chica, ninguno),
        // que girando le quitan el núcleo a las tareas que sí trabajan
        long long t_giro = 0;
        int girando = 0;
        for (int vuelta = 0; !f; vuelta++) {
            f = scar_buscar_trabajo(t, vuelta);
            if (f) break;
            if (vuelta == 64) {
                if (atomic_fetch_add(&scar_trab_girando, 1) < scar_n_trab / 4) { girando = 1; t_giro = scar_mono_ns(); }
                else { atomic_fetch_sub(&scar_trab_girando, 1); break; }
            }
            if (vuelta > 64) {
                if ((vuelta & 7) == 0 && scar_mono_ns() - t_giro > scar_giro_ocioso_ns) break;
                sched_yield();
            }
        }
        if (girando) atomic_fetch_sub(&scar_trab_girando, 1);
        if (f) { scar_cambiar_a_fibra(t, f); continue; }
        // nada que hacer: a dormir hasta el próximo plazo (o un rato). Anotarse
        // primero y mirar de nuevo después: quien pone trabajo mira
        // scar_n_dormidos después de ponerlo, así que uno de los dos ve al otro.
        // (la última mirada va antes de tomar el candado: disparar un plazo
        // pone una fibra lista y eso quiere despertar a un dormido)
        atomic_fetch_add(&scar_n_dormidos, 1);
        if (mi_bit) atomic_fetch_or(&scar_dormidos_mapa, mi_bit);
        atomic_store(&t->durmiendo, 1);
        scar_barrera();
        f = scar_buscar_trabajo(t, 1000);
        if (!f && scar_detectar_deadlock(t)) {
            // despertó a una fibra como trabada (o panickeó): volver a mirar
            atomic_store(&t->durmiendo, 0);
            if (mi_bit) atomic_fetch_and(&scar_dormidos_mapa, ~mi_bit);
            atomic_fetch_sub(&scar_n_dormidos, 1);
            continue;
        }
        pthread_mutex_lock(&t->dormir_mu);
        // un aviso que llegó entre esa mirada y el candado se habría perdido:
        // mirar otra vez (sin disparar plazos ni tomar nada) ya con el candado
        long long prox = atomic_load(&scar_proximo_plazo);
        long long ahora = scar_mono_ns();
        if (!f && (atomic_load_explicit(&t->siguiente, memory_order_relaxed)
                   || atomic_load_explicit(&t->n, memory_order_relaxed) > 0
                   || atomic_load_explicit(&scar_global_n, memory_order_relaxed) > 0
                   || prox <= ahora)) {
            atomic_store(&t->durmiendo, 0);
            if (mi_bit) atomic_fetch_and(&scar_dormidos_mapa, ~mi_bit);
            atomic_fetch_sub(&scar_n_dormidos, 1);
            pthread_mutex_unlock(&t->dormir_mu);
            continue;
        }
        int soy_cuidador = 0;
        if (!f) {
            long long espera = 50000000LL;   // 50 ms a lo más
            if (prox != LLONG_MAX) {
                int nadie = -1;
                if (atomic_compare_exchange_strong(&scar_cuidador, &nadie, t->id)) {
                    soy_cuidador = 1;
                    long long falta = prox - ahora;
                    if (falta < espera) espera = falta > 0 ? falta : 0;
                }
            }
            if (espera > 0) {
                struct timespec ts;
                clock_gettime(CLOCK_MONOTONIC, &ts);
                long long ns = ts.tv_nsec + espera;
                ts.tv_sec += ns / 1000000000LL;
                ts.tv_nsec = ns % 1000000000LL;
                pthread_cond_timedwait(&t->dormir_cv, &t->dormir_mu, &ts);
            }
        }
        atomic_store(&t->durmiendo, 0);
        if (mi_bit) atomic_fetch_and(&scar_dormidos_mapa, ~mi_bit);
        atomic_fetch_sub(&scar_n_dormidos, 1);
        pthread_mutex_unlock(&t->dormir_mu);
        if (soy_cuidador) {
            atomic_store(&scar_cuidador, -1);
            // me despertaron por trabajo y queda un plazo sin vencer: que otro
            // dormido pase a cuidarlo
            long long p2 = atomic_load(&scar_proximo_plazo);
            if (p2 != LLONG_MAX && p2 > scar_mono_ns() && atomic_load(&scar_n_dormidos) > 0)
                scar_despertar_dormido();
        }
        if (f) scar_cambiar_a_fibra(t, f);
    }
    return NULL;
}

static void scar_trab_crear_si_hace_falta(void) {
    pthread_mutex_lock(&scar_trab_crear_mu);
    int i = atomic_load(&scar_trab_creados);
    if (i < SCAR_MAX_TRAB && i - atomic_load(&scar_trab_bloqueados) < scar_n_trab) {
        scar_trab[i].id = i;
        pthread_mutex_init(&scar_trab[i].dormir_mu, NULL);
        pthread_cond_init(&scar_trab[i].dormir_cv, &scar_cond_mono_attr);
        pthread_attr_t a;
        pthread_attr_init(&a);
        pthread_attr_setstacksize(&a, 256 * 1024);  // el planificador usa poca pila
        // se cuenta ANTES de crearlo: el hilo nuevo puede tomar una tarea
        // enseguida, y el detector de deadlock compara dormidos contra creados
        // (contado después, veía "todos dormidos" con este corriendo: un falso
        // deadlock, 2 de 3.200 corridas de 151_ bajo carga)
        atomic_store(&scar_trab_creados, i + 1);
        if (pthread_create(&scar_trab[i].hilo, &a, scar_bucle_trabajador, &scar_trab[i]) != 0)
            atomic_store(&scar_trab_creados, i);
        pthread_attr_destroy(&a);
    }
    pthread_mutex_unlock(&scar_trab_crear_mu);
}

typedef struct { int (*fn)(int, char **); int argc; char **argv; } ScarMainArgs;
static void *scar_main_fibra(void *p) {
    ScarMainArgs *m = p;
    exit(m->fn(m->argc, m->argv));
    return NULL;
}

// Corre main: con SCAR_TAREAS=hilos, tal cual; con livianas (por defecto), como
// la primera fibra, en este hilo (el trabajador 0). Los otros trabajadores se
// crean recién cuando hay trabajo para ellos: un programa sigue con un solo
// hilo hasta su primer spawn (importa para el fork() del worker de FFI).
static int scar_correr_main(int (*fn)(int, char **), int argc, char **argv) {
#ifndef SCAR_LIBRERIA
    // tareas livianas por defecto (0.2.0); SCAR_TAREAS=hilos vuelve a un hilo
    // del sistema por tarea
    const char *modo = getenv("SCAR_TAREAS");
    scar_livianas = !(modo && strcmp(modo, "hilos") == 0);
#endif
    if (!scar_livianas) return fn(argc, argv);
    long pg = sysconf(_SC_PAGESIZE);
    if (pg > 0) scar_pagina = (size_t)pg;
    long nc = sysconf(_SC_NPROCESSORS_ONLN);
    scar_n_trab = nc > 0 ? (int)nc : 1;
    const char *h = getenv("SCAR_TAREAS_HILOS");
    if (h && atoi(h) > 0) scar_n_trab = atoi(h);
    const char *go = getenv("SCAR_GIRO_OCIOSO_US");
    if (go && atol(go) >= 0) scar_giro_ocioso_ns = atol(go) * 1000LL;
    const char *kb = getenv("SCAR_PILA_TAREA_KB");
    if (kb && atol(kb) >= 64) scar_tam_pila = ((size_t)atol(kb) * 1024 + scar_pagina - 1) & ~(scar_pagina - 1);
    struct rlimit rl;
    if (getrlimit(RLIMIT_STACK, &rl) == 0 && rl.rlim_cur != RLIM_INFINITY && rl.rlim_cur >= (1u << 20))
        scar_tam_pila_main = (size_t)rl.rlim_cur;
    if (scar_tam_pila_main > (1024u << 20)) scar_tam_pila_main = 1024u << 20;
    scar_tam_pila_main = (scar_tam_pila_main + scar_pagina - 1) & ~(scar_pagina - 1);
    pthread_condattr_init(&scar_cond_mono_attr);
    pthread_condattr_setclock(&scar_cond_mono_attr, CLOCK_MONOTONIC);
    scar_trab = calloc(SCAR_MAX_TRAB, sizeof(ScarTrab));
    scar_trab[0].id = 0;
    pthread_mutex_init(&scar_trab[0].dormir_mu, NULL);
    pthread_cond_init(&scar_trab[0].dormir_cv, &scar_cond_mono_attr);
    atomic_store(&scar_trab_creados, 1);
    static ScarMainArgs m;
    m.fn = fn; m.argc = argc; m.argv = argv;
    ScarFibra *f = scar_fibra_nueva(scar_main_fibra, &m, NULL, scar_tam_pila_main);
    if (!f) {
        fprintf(stderr, "[PANIC] main murió: no hay memoria para su pila (SCAR_TAREAS=livianas)\n");
        return 1;
    }
    scar_yo = &scar_trab[0];
    scar_listo(f, 0);
    scar_bucle_trabajador(&scar_trab[0]);
    return 0;
}
#endif  /* sin planificador */
