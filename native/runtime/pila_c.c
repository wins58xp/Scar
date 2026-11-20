// ---------------------------------------------------------------------------
// Las llamadas a C de una extern fn corren en otra pila.
//
// El código de SCAR revisa su pila al entrar a cada fn (pila.c), pero el de una
// librería de C no, y no se sabe cuánta pila usa: en la pila de una tarea, una
// recursión honda de la librería podría pasarse del fondo. Por eso la llamada
// cambia a una pila de C grande (8 MB, con su página de guarda, como la de un
// hilo cualquiera) y vuelve al terminar.
//
// Cada hilo guarda una (la primera vez que llama a C) y la reusa; si ya la está
// usando (una extern que termina llamando a otra), toma otra de una lista común.
// Mientras dura la llamada la tarea no deja su hilo, así que la del hilo no
// cambia de dueño en el medio.
//
// El cambio de pila es el de pilas.c (scar_correr_en_pila). En otro procesador,
// o en Windows, la llamada queda en la misma pila.
// ---------------------------------------------------------------------------
#if defined(SCAR_HAY_CAMBIO_PILA)
#include <sys/mman.h>
#include <pthread.h>
#include <unistd.h>
#define SCAR_PILA_C_TAM ((size_t)8 << 20)
static size_t scar_pila_c_pag = 0;
static pthread_mutex_t scar_pilas_c_mu = PTHREAD_MUTEX_INITIALIZER;
static char **scar_pilas_c_libres = NULL;
static size_t scar_n_pilas_c = 0, scar_cap_pilas_c = 0;
// la del hilo (la toma una vez y la guarda), y si está en uso ahora
static _Thread_local char *scar_pila_c_hilo = NULL;
static _Thread_local int scar_pila_c_ocupada = 0;
static _Thread_local char *scar_pila_c_suelta = NULL;   // la de la lista, si se usó una

static pthread_once_t scar_pila_c_pag_una = PTHREAD_ONCE_INIT;
static void scar_pila_c_pag_iniciar(void) {
    long pg = sysconf(_SC_PAGESIZE);
    scar_pila_c_pag = pg > 0 ? (size_t)pg : 4096;
}
static char *scar_pila_c_nueva(void) {
    pthread_once(&scar_pila_c_pag_una, scar_pila_c_pag_iniciar);
    char *p = mmap(NULL, SCAR_PILA_C_TAM, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (p == MAP_FAILED) return NULL;
    if (mprotect(p, scar_pila_c_pag, PROT_NONE) != 0) {
        munmap(p, SCAR_PILA_C_TAM);
        return NULL;
    }
    return p;
}

static char *scar_pila_c_de_la_lista(void) {
    char *p = NULL;
    pthread_mutex_lock(&scar_pilas_c_mu);
    if (scar_n_pilas_c) p = scar_pilas_c_libres[--scar_n_pilas_c];
    pthread_mutex_unlock(&scar_pilas_c_mu);
    return p ? p : scar_pila_c_nueva();
}

static void scar_pila_c_a_la_lista(char *p) {
    pthread_mutex_lock(&scar_pilas_c_mu);
    if (scar_n_pilas_c == scar_cap_pilas_c) {
        size_t cap = scar_cap_pilas_c ? scar_cap_pilas_c * 2 : 16;
        char **n = realloc(scar_pilas_c_libres, cap * sizeof(char *));
        if (!n) {
            pthread_mutex_unlock(&scar_pilas_c_mu);
            munmap(p, SCAR_PILA_C_TAM);
            return;
        }
        scar_pilas_c_libres = n;
        scar_cap_pilas_c = cap;
    }
    scar_pilas_c_libres[scar_n_pilas_c++] = p;
    pthread_mutex_unlock(&scar_pilas_c_mu);
}

// La del hilo vuelve a la lista cuando el hilo termina (una tarea de modo
// hilos que llamó a C): si no, cada hilo dejaría la suya.
static pthread_key_t scar_pila_c_llave;
static pthread_once_t scar_pila_c_una = PTHREAD_ONCE_INIT;
static void scar_pila_c_fin_hilo(void *p) { if (p) scar_pila_c_a_la_lista(p); }
static void scar_pila_c_hacer_llave(void) { pthread_key_create(&scar_pila_c_llave, scar_pila_c_fin_hilo); }

// fn(arg) en una pila de C; si no hay memoria para una, en la de siempre
__attribute__((unused))
static void scar_en_pila_c(void (*fn)(void *), void *arg) {
    char *p;
    int del_hilo = !scar_pila_c_ocupada;
    if (del_hilo) {
        if (!scar_pila_c_hilo) {
            scar_pila_c_hilo = scar_pila_c_de_la_lista();
            if (scar_pila_c_hilo) {
                pthread_once(&scar_pila_c_una, scar_pila_c_hacer_llave);
                pthread_setspecific(scar_pila_c_llave, scar_pila_c_hilo);
            }
        }
        p = scar_pila_c_hilo;
    } else {
        p = scar_pila_c_de_la_lista();
    }
    if (!p) { fn(arg); return; }
    if (del_hilo) scar_pila_c_ocupada = 1;
    char *suelta_antes = scar_pila_c_suelta;
    if (!del_hilo) scar_pila_c_suelta = p;
    scar_correr_en_pila(fn, arg, p + scar_pila_c_pag, SCAR_PILA_C_TAM - scar_pila_c_pag);
    if (del_hilo) scar_pila_c_ocupada = 0;
    else { scar_pila_c_a_la_lista(p); scar_pila_c_suelta = suelta_antes; }
}

// Una extern que se cayó (el guardián saltó con siglongjmp desde la pila de C a
// la de SCAR): la pila de C que usaba queda libre otra vez.
__attribute__((unused))
static void scar_pila_c_tras_caida(void) {
    if (scar_pila_c_suelta) {
        scar_pila_c_a_la_lista(scar_pila_c_suelta);
        scar_pila_c_suelta = NULL;
    } else {
        scar_pila_c_ocupada = 0;
    }
}
#else
__attribute__((unused))
static void scar_en_pila_c(void (*fn)(void *), void *arg) { fn(arg); }
__attribute__((unused))
static void scar_pila_c_tras_caida(void) {}
#endif
