// ---------------------------------------------------------------------------
// Lo "por hilo" del runtime, todo en un struct: el contexto de la tarea, el
// registro de dueñas vivas, rand(), los límites de la pila, el recuerdo de
// s[i], el pool de bloques chicos y el guardián de las extern fn.
//
// Por qué un struct y no variables _Thread_local sueltas: con tareas livianas
// (planificador.c) una tarea puede dejar un hilo y seguir en otro. El
// compilador, dentro de una función, se guarda en un registro la dirección
// base de las variables por hilo (%fs:0) y la reusa después de una llamada;
// si esa llamada cambió de hilo, lo que sigue lee y escribe las variables del
// hilo viejo (medido: clang -O3 colgaba bench/tareas/cadena, gcc no). Acá cada
// acceso pasa por scar_tls(), que vuelve a leer la dirección cada vez (un asm
// volatile de una o dos instrucciones) y el compilador no puede guardar.
//
// Sin tareas ni canales el programa tiene un solo hilo: scar_hilo es una
// variable común y scar_tls() es su dirección, sin costo.
// ---------------------------------------------------------------------------
#include <signal.h>
struct TaskContext;
struct ScarVivo;
struct ScarPoolNode;
struct ScarTrab;
typedef struct { const char* p; size_t b0, bi; int32_t len, ci; int ascii; } ScarStrc;
#define SCAR_POOL_MIN_SHIFT 4
#define SCAR_POOL_MAX_SHIFT 11
#define SCAR_POOL_NUM_CLASSES (SCAR_POOL_MAX_SHIFT - SCAR_POOL_MIN_SHIFT + 1)
@@GUARD_TIPOS@@
typedef struct ScarHilo {
    // de la tarea (el planificador lo guarda y repone al cambiar de tarea)
    struct TaskContext *ctx;
    struct ScarVivo *vivos;
    int nvivos, capvivos;
    uint64_t rand_state, rand_base, rand_hijos;
    uintptr_t pila_hi, pila_lo;
    ScarStrc strc[2];
    int strc_ult;
    // del hilo
    unsigned int progreso_local;
    struct ScarPoolNode *pool_freelist[SCAR_POOL_NUM_CLASSES];
    int pool_registered;
    struct ScarTrab *trab;
    volatile sig_atomic_t guard_active;
    volatile sig_atomic_t guard_signum;
    const char *guard_fnname;
@@GUARD_ENV@@
} ScarHilo;
@@TLS@@
// Una llamada que puede bloquear el hilo (leer un archivo o la red, una
// extern fn): con tareas livianas, planificador.c lo redefine para que la
// tarea suelte su lugar mientras tanto y las demás sigan en otro hilo
#define SCAR_BLOQUEANDO(expr) (expr)
#define scar_bloqueo_entrar() ((void)0)
#define scar_bloqueo_salir() ((void)0)
#define __scar_ctx (scar_tls()->ctx)
#define scar_vivos (scar_tls()->vivos)
#define scar_nvivos (scar_tls()->nvivos)
#define scar_capvivos (scar_tls()->capvivos)
#define __scar_rand_state (scar_tls()->rand_state)
#define __scar_rand_base (scar_tls()->rand_base)
#define __scar_rand_hijos (scar_tls()->rand_hijos)
#define scar_pila_hi (scar_tls()->pila_hi)
#define scar_pila_lo (scar_tls()->pila_lo)
#define scar_strc (scar_tls()->strc)
#define scar_strc_ult (scar_tls()->strc_ult)
#define scar_progreso_local (scar_tls()->progreso_local)
#define scar_pool_freelist (scar_tls()->pool_freelist)
#define scar_pool_registered (scar_tls()->pool_registered)
#define scar_yo (scar_tls()->trab)
#define scar_extern_guard_active (scar_tls()->guard_active)
#define scar_extern_guard_signum (scar_tls()->guard_signum)
#define scar_extern_guard_fnname (scar_tls()->guard_fnname)
#define scar_extern_guard_env (scar_tls()->guard_env)
