#include <signal.h>
#ifdef _WIN32
/* Windows (MinGW) no tiene sigaction/sigaltstack/getrlimit: el guardia de
   desbordamiento de pila no se instala y una recursión sin fin termina el
   proceso como de costumbre (sin el panic lindo). No afecta al resto. */
static void scar_pila_iniciar(void) {}
__attribute__((unused)) static void scar_pila_terminar(void) {}
#else
#include <sys/resource.h>
/* Una recursión sin caso base llena la pila y el
   sistema mata al proceso con SIGSEGV (un crash mudo). Cada hilo anota dónde
   está su pila y le da al manejador una pila alternativa; si el SIGSEGV cae
   en la pila del hilo (o justo debajo) es un desbordamiento y se convierte en
   un panic. Cualquier otro SIGSEGV sigue como antes (la guardia de FFI o el
   comportamiento por defecto). No cuesta nada mientras no pase. */
#define SCAR_HAY_PILA 1
/* scar_pila_hi y scar_pila_lo: en ScarHilo (tls.c) */
static _Thread_local char scar_pila_alt[64 * 1024];
/* la pila alternativa que tenía el hilo antes (la del sistema o la de un
   sanitizer): se devuelve al terminar la tarea, para que el hilo no termine
   con una pila alternativa que se va con su memoria local */
static _Thread_local stack_t scar_pila_alt_previa;
static _Thread_local int scar_pila_alt_puesta = 0;
static struct sigaction scar_pila_previa;
static volatile sig_atomic_t scar_pila_instalada = 0;
__attribute__((noinline, cold))
static void scar_pila_desborde(void) {
    scar_pila_hi = 0;
    @@PANIC@@("desbordamiento de pila: recursión demasiado profunda (¿falta un caso base?)");
    abort();
}
static void scar_pila_senal(int sig, siginfo_t *info, void *uc) {
    uintptr_t a = (uintptr_t)info->si_addr;
    if (scar_pila_hi != 0 && a + (1u << 20) >= scar_pila_lo && a <= scar_pila_hi) {
        scar_pila_desborde();
    }
    /* no es de la pila: lo de antes */
    if (scar_pila_previa.sa_flags & SA_SIGINFO) {
        if (scar_pila_previa.sa_sigaction) { scar_pila_previa.sa_sigaction(sig, info, uc); return; }
    } else if (scar_pila_previa.sa_handler != SIG_DFL && scar_pila_previa.sa_handler != SIG_IGN) {
        scar_pila_previa.sa_handler(sig);
        return;
    }
    signal(sig, SIG_DFL);   /* vuelve a fallar y el sistema termina el proceso, como siempre */
}
static void scar_pila_alt_instalar(void) {
    if (scar_pila_alt_puesta) return;
    stack_t alt;
    alt.ss_sp = scar_pila_alt;
    alt.ss_size = sizeof scar_pila_alt;
    alt.ss_flags = 0;
    if (sigaltstack(&alt, &scar_pila_alt_previa) == 0)
        scar_pila_alt_puesta = 1;
}
__attribute__((noinline))
static void scar_pila_iniciar(void) {
#ifdef SCAR_PLANIFICADOR
    /* una tarea liviana: su pila es la de su fibra (los límites ya los puso el
       planificador, y se guardan con la fibra); la pila alternativa es del
       trabajador, una vez por hilo */
    ScarFibra *fib = scar_livianas ? scar_fibra_actual() : NULL;
    if (fib) {
        scar_pila_hi = (uintptr_t)(fib->mapa + fib->tam_mapa);
        scar_pila_lo = (uintptr_t)(fib->mapa + scar_pagina);
        scar_pila_alt_instalar();
        if (!scar_pila_instalada) {
            scar_pila_instalada = 1;
            struct sigaction sa;
            memset(&sa, 0, sizeof sa);
            sa.sa_sigaction = scar_pila_senal;
            sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
            sigemptyset(&sa.sa_mask);
            sigaction(SIGSEGV, &sa, &scar_pila_previa);
        }
        return;
    }
#endif
    uintptr_t base = (uintptr_t)__builtin_frame_address(0);
    size_t tam = 8u << 20;
    struct rlimit rl;
    if (getrlimit(RLIMIT_STACK, &rl) == 0 && rl.rlim_cur != RLIM_INFINITY && rl.rlim_cur >= (1u << 20))
        tam = (size_t)rl.rlim_cur;
    if (tam > (1024u << 20)) tam = 1024u << 20;
    scar_pila_hi = base + (64u << 10);
    scar_pila_lo = base > tam ? base - tam : 0;
    scar_pila_alt_instalar();
    if (!scar_pila_instalada) {
        scar_pila_instalada = 1;
        struct sigaction sa;
        memset(&sa, 0, sizeof sa);
        sa.sa_sigaction = scar_pila_senal;
        sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
        sigemptyset(&sa.sa_mask);
        sigaction(SIGSEGV, &sa, &scar_pila_previa);
    }
}
/* Al terminar una tarea: deja de vigilar su pila y le devuelve al hilo la pila
   alternativa que tenía. */
__attribute__((unused))
static void scar_pila_terminar(void) {
    scar_pila_hi = 0;
#ifdef SCAR_PLANIFICADOR
    if (scar_livianas) return;   /* la pila alternativa queda para el trabajador */
#endif
    if (scar_pila_alt_puesta) {
        scar_pila_alt_puesta = 0;
        sigaltstack(&scar_pila_alt_previa, NULL);
    }
}
#endif  /* _WIN32 */
