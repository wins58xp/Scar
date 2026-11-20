// ---------------------------------------------------------------------------
// Las pilas donde corre el código de SCAR.
//
// Todas miden lo mismo, una potencia de 2 (scar_pila_tam), y empiezan en una
// dirección múltiplo de su tamaño. Así el fondo de la pila sale de la dirección
// misma: `sp & scar_pila_mascara` es cuánto queda hasta el fondo, sin leer nada
// del hilo ni de la tarea. Esa es la revisión que cada fn hace al entrar.
//
// El tamaño: 8 MB, o lo que diga `ulimit -s` si es más, o SCAR_PILA_KB; se
// redondea hacia arriba a una potencia de 2, con tope de 1 GB. Es memoria
// reservada, no usada (MAP_NORESERVE): una tarea gasta solo lo que su pila toca.
//
// Se piden en bloques de SCAR_PILAS_POR_BLOQUE pilas seguidas y se reusan en una
// lista de libres. No llevan página de guarda: la revisión de pila al entrar a
// cada fn (pila.c) la reemplaza, y así un bloque entero es una sola zona de
// memoria para Linux (con guarda, cada pila partía la suya en dos, y 100.000
// tareas pedían subir vm.max_map_count).
// ---------------------------------------------------------------------------
#include <pthread.h>
#include <errno.h>
#if !defined(_WIN32)
#include <unistd.h>
#include <sys/mman.h>
#include <sys/resource.h>
static size_t scar_pila_tam = 0;
static uintptr_t scar_pila_mascara = 0;   // scar_pila_tam - 1; 0: sin iniciar
static size_t scar_pila_pag = 4096;
#define SCAR_PILAS_POR_BLOQUE 64
// más libres que esto: su memoria vuelve al sistema (madvise), su lugar queda
#define SCAR_PILAS_LIBRES_CON_MEMORIA 16384
static pthread_mutex_t scar_pilas_mu = PTHREAD_MUTEX_INITIALIZER;
static char **scar_pilas_libres = NULL;
static size_t scar_n_pilas_libres = 0, scar_cap_pilas_libres = 0;
static char *scar_pilas_bloque = NULL;    // las que quedan sin estrenar del último bloque
static int scar_pilas_quedan = 0;

static void scar_pilas_iniciar_una(void) {
    long pg = sysconf(_SC_PAGESIZE);
    if (pg > 0) scar_pila_pag = (size_t)pg;
    size_t tam = (size_t)8 << 20;
    struct rlimit rl;
    if (getrlimit(RLIMIT_STACK, &rl) == 0 && rl.rlim_cur != RLIM_INFINITY && rl.rlim_cur > tam)
        tam = (size_t)rl.rlim_cur;
    const char *kb = getenv("SCAR_PILA_KB");
    if (kb && atol(kb) >= 256) tam = (size_t)atol(kb) * 1024;
    if (tam > ((size_t)1 << 30)) tam = (size_t)1 << 30;
    size_t p2 = (size_t)1 << 16;
    while (p2 < tam) p2 <<= 1;
    scar_pila_tam = p2;
    scar_pila_mascara = (uintptr_t)p2 - 1;
}
// una sola vez (en una librería, la pueden pedir varios hilos del programa que
// la carga a la vez)
static pthread_once_t scar_pilas_una = PTHREAD_ONCE_INIT;
__attribute__((unused))
static void scar_pilas_iniciar(void) {
    pthread_once(&scar_pilas_una, scar_pilas_iniciar_una);
}

// un bloque nuevo, alineado al tamaño de una pila (se pide de más y se recorta)
static int scar_pilas_bloque_nuevo(void) {
    size_t tam = scar_pila_tam, total = tam * SCAR_PILAS_POR_BLOQUE;
    char *p = mmap(NULL, total + tam, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (p == MAP_FAILED) return 0;
    uintptr_t ini = ((uintptr_t)p + tam - 1) & ~(uintptr_t)(tam - 1);
    size_t antes = ini - (uintptr_t)p, despues = tam - antes;
    if (antes) munmap(p, antes);
    if (despues) munmap((char *)ini + total, despues);
    scar_pilas_bloque = (char *)ini;
    scar_pilas_quedan = SCAR_PILAS_POR_BLOQUE;
    return 1;
}

// una pila: su dirección más baja (alineada a scar_pila_tam); NULL sin memoria
__attribute__((unused))
static char *scar_pila_tomar(void) {
    char *p = NULL;
    pthread_mutex_lock(&scar_pilas_mu);
    if (scar_n_pilas_libres) {
        p = scar_pilas_libres[--scar_n_pilas_libres];
    } else if (scar_pilas_quedan || scar_pilas_bloque_nuevo()) {
        p = scar_pilas_bloque;
        scar_pilas_bloque += scar_pila_tam;
        scar_pilas_quedan--;
    }
    pthread_mutex_unlock(&scar_pilas_mu);
    return p;
}

__attribute__((unused))
static void scar_pila_soltar(char *p) {
    pthread_mutex_lock(&scar_pilas_mu);
    if (scar_n_pilas_libres >= SCAR_PILAS_LIBRES_CON_MEMORIA)
        madvise(p, scar_pila_tam, MADV_DONTNEED);
    if (scar_n_pilas_libres == scar_cap_pilas_libres) {
        size_t cap = scar_cap_pilas_libres ? scar_cap_pilas_libres * 2 : 256;
        char **n = realloc(scar_pilas_libres, cap * sizeof(char *));
        if (!n) {   // sin lugar en la lista: la pila se pierde, pero no se pisa nada
            pthread_mutex_unlock(&scar_pilas_mu);
            return;
        }
        scar_pilas_libres = n;
        scar_cap_pilas_libres = cap;
    }
    scar_pilas_libres[scar_n_pilas_libres++] = p;
    pthread_mutex_unlock(&scar_pilas_mu);
}
#endif

// ---- correr una función en otra pila ----
// scar_llamar_en_pila (ensamblador): llama fn(arg) con la pila en `tope` y
// vuelve a la de antes. scar_correr_en_pila le suma los avisos a ASan (si no,
// confunde una pila con la otra). Lo usan las extern fn (pila_c.c) y las export
// fn de una librería (scar_lib_en_pila, abajo).
#if !defined(_WIN32) && (defined(__x86_64__) || defined(__aarch64__))
#define SCAR_HAY_CAMBIO_PILA 1
#define SCAR_PC_SIM2(x) #x
#define SCAR_PC_SIM(x) SCAR_PC_SIM2(x)
#define SCAR_PC_ETIQ(n) SCAR_PC_SIM(__USER_LABEL_PREFIX__) #n
void scar_llamar_en_pila(void (*fn)(void *), void *arg, char *tope);
#if defined(__x86_64__)
// %rbp se conserva a través de la llamada (la convención lo pide): ahí queda
// la pila de antes
__asm__(
    ".text\n"
    ".globl " SCAR_PC_ETIQ(scar_llamar_en_pila) "\n"
    SCAR_PC_ETIQ(scar_llamar_en_pila) ":\n"
    "    pushq %rbp\n"
    "    movq %rsp, %rbp\n"
    "    movq %rdx, %rsp\n"
    "    movq %rdi, %rax\n"
    "    movq %rsi, %rdi\n"
    "    call *%rax\n"
    "    movq %rbp, %rsp\n"
    "    popq %rbp\n"
    "    ret\n");
#else
__asm__(
    ".text\n"
    ".globl " SCAR_PC_ETIQ(scar_llamar_en_pila) "\n"
    SCAR_PC_ETIQ(scar_llamar_en_pila) ":\n"
    "    stp x29, x30, [sp, #-16]!\n"
    "    mov x29, sp\n"
    "    mov sp, x2\n"
    "    mov x3, x0\n"
    "    mov x0, x1\n"
    "    blr x3\n"
    "    mov sp, x29\n"
    "    ldp x29, x30, [sp], #16\n"
    "    ret\n");
#endif
#if defined(__SANITIZE_ADDRESS__)
void __sanitizer_start_switch_fiber(void **fake_stack_save, const void *bottom, size_t size);
void __sanitizer_finish_switch_fiber(void *fake_stack_save, const void **bottom_old, size_t *size_old);
#endif

typedef struct {
    void (*fn)(void *);
    void *arg;
#if defined(__SANITIZE_ADDRESS__)
    void *falsa;
    const void *abajo;
    size_t tam;
#endif
} ScarEnPila;

static void scar_en_pila_entrada(void *p) {
    ScarEnPila *e = p;
#if defined(__SANITIZE_ADDRESS__)
    __sanitizer_finish_switch_fiber(e->falsa, &e->abajo, &e->tam);
#endif
    e->fn(e->arg);
#if defined(__SANITIZE_ADDRESS__)
    __sanitizer_start_switch_fiber(&e->falsa, e->abajo, e->tam);
#endif
}

// fn(arg) en la pila [abajo, abajo + tam)
__attribute__((unused))
static void scar_correr_en_pila(void (*fn)(void *), void *arg, char *abajo, size_t tam) {
    ScarEnPila e;
    e.fn = fn;
    e.arg = arg;
#if defined(__SANITIZE_ADDRESS__)
    __sanitizer_start_switch_fiber(&e.falsa, abajo, tam);
#endif
    scar_llamar_en_pila(scar_en_pila_entrada, &e, abajo + tam);
#if defined(__SANITIZE_ADDRESS__)
    __sanitizer_finish_switch_fiber(e.falsa, NULL, NULL);
#endif
}
#endif

// ---- las export fn de una librería ----
// A una export fn la llama otro programa, desde su propia pila; el código de
// SCAR tiene que correr en una de las de acá (la revisión de pila sale de la
// dirección). Cada hilo del que llama guarda una (la primera vez) y la reusa; si
// ya la está usando (una export que, por un callback de C, termina llamando a
// otra), toma otra. Vuelven a la lista cuando el hilo termina.
#if defined(SCAR_LIBRERIA) && defined(SCAR_HAY_CAMBIO_PILA)
static _Thread_local char *scar_lib_pila = NULL;
static _Thread_local int scar_lib_pila_ocupada = 0;
static pthread_key_t scar_lib_pila_llave;
static pthread_once_t scar_lib_pila_una = PTHREAD_ONCE_INIT;
static void scar_lib_pila_fin_hilo(void *p) { if (p) scar_pila_soltar(p); }
static void scar_lib_pila_hacer_llave(void) { pthread_key_create(&scar_lib_pila_llave, scar_lib_pila_fin_hilo); }
__attribute__((unused))
static int scar_lib_en_pila(void (*fn)(void *), void *arg) {
    scar_pilas_iniciar();
    char *p;
    int del_hilo = !scar_lib_pila_ocupada;
    if (del_hilo) {
        if (!scar_lib_pila) {
            scar_lib_pila = scar_pila_tomar();
            if (!scar_lib_pila) return 0;
            pthread_once(&scar_lib_pila_una, scar_lib_pila_hacer_llave);
            pthread_setspecific(scar_lib_pila_llave, scar_lib_pila);
        }
        p = scar_lib_pila;
        scar_lib_pila_ocupada = 1;
    } else {
        p = scar_pila_tomar();
        if (!p) return 0;
    }
    scar_correr_en_pila(fn, arg, p, scar_pila_tam);
    if (del_hilo) scar_lib_pila_ocupada = 0;
    else scar_pila_soltar(p);
    return 1;
}
#endif

// Un hilo del sistema que corre código de SCAR (main, o una tarea con
// SCAR_TAREAS=hilos): con una de estas pilas, no con la de glibc. Deja en *pila
// cuál le dio, para soltarla después del pthread_join.
__attribute__((unused))
static int scar_hilo_lanzar(pthread_t *h, char **pila, void *(*fn)(void *), void *arg) {
#if !defined(_WIN32)
    scar_pilas_iniciar();
    *pila = scar_pila_tomar();
    if (!*pila) return ENOMEM;
    pthread_attr_t at;
    int rc = pthread_attr_init(&at);
    if (rc == 0) {
        rc = pthread_attr_setstack(&at, *pila, scar_pila_tam);
        if (rc == 0) rc = pthread_create(h, &at, fn, arg);
        pthread_attr_destroy(&at);
    }
    if (rc != 0) {
        scar_pila_soltar(*pila);
        *pila = NULL;
    }
    return rc;
#else
    *pila = NULL;
    return pthread_create(h, NULL, fn, arg);
#endif
}

__attribute__((unused))
static void scar_hilo_pila_soltar(char **pila) {
#if !defined(_WIN32)
    if (*pila) scar_pila_soltar(*pila);
#endif
    *pila = NULL;
}

// main de SCAR en un hilo con una de estas pilas; el hilo de siempre solo lo
// espera. Así todo el código de SCAR corre en una pila de SCAR.
typedef struct { int (*fn)(int, char **); int argc; char **argv; int rc; } ScarMainEnPila;
// Lo que el hilo de main deja en orden antes de terminar: antes el hilo de
// main no terminaba nunca (el proceso se iba primero), y ahora sí. Sin tareas
// se suelta el registro de dueñas vivas, que es del hilo (si no, LeakSanitizer
// lo ve perdido). En orden inverso al que se anotaron.
static void (*scar_main_al_terminar[4])(void);
static int scar_n_main_al_terminar = 0;
__attribute__((unused))
static void scar_main_al_terminar_poner(void (*f)(void)) {
    for (int i = 0; i < scar_n_main_al_terminar; i++)
        if (scar_main_al_terminar[i] == f) return;
    if (scar_n_main_al_terminar < 4) scar_main_al_terminar[scar_n_main_al_terminar++] = f;
}
static void *scar_main_en_pila_hilo(void *p) {
    ScarMainEnPila *m = p;
    m->rc = m->fn(m->argc, m->argv);
    for (int i = scar_n_main_al_terminar - 1; i >= 0; i--) scar_main_al_terminar[i]();
    return NULL;
}
__attribute__((unused))
static int scar_main_en_pila(int (*fn)(int, char **), int argc, char **argv) {
#if defined(_WIN32)
    return fn(argc, argv);   // sin la revisión de pila (pila.c): la del sistema alcanza
#endif
    static ScarMainEnPila m;
    m.fn = fn; m.argc = argc; m.argv = argv; m.rc = 1;
    pthread_t h;
    char *pila;
    int rc = scar_hilo_lanzar(&h, &pila, scar_main_en_pila_hilo, &m);
    if (rc != 0) {
        fprintf(stderr, "[PANIC] main murió: no se pudo darle su pila (%s)\n", strerror(rc));
        return 1;
    }
    pthread_join(h, NULL);
    scar_hilo_pila_soltar(&pila);
    return m.rc;
}
