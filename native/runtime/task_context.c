// Condvars de espera con reloj monotonico (un cambio de la
// hora del sistema no adelanta ni atrasa un sleep o un join).
static void scar_cond_init_mono(pthread_cond_t *c) {
    pthread_condattr_t a;
    pthread_condattr_init(&a);
    pthread_condattr_setclock(&a, CLOCK_MONOTONIC);
    pthread_cond_init(c, &a);
    pthread_condattr_destroy(&a);
}

// instante absoluto (CLOCK_MONOTONIC) dentro de 'secs' segundos
static struct timespec scar_abs_mono(double secs) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    if (secs < 0) secs = 0;
    time_t whole = (time_t)secs;
    long nsec = ts.tv_nsec + (long)((secs - (double)whole) * 1e9);
    ts.tv_sec += whole + nsec / 1000000000L;
    ts.tv_nsec = nsec % 1000000000L;
    return ts;
}

static TaskContext* scar_ctx_new(const char *name, TaskContext *parent) {
    TaskContext *ctx = malloc(sizeof(TaskContext));
    ctx->name = name;
    ctx->rand_semilla = SCAR_RAND_SEMILLA_HIJA();  // en el hilo de la madre
    atomic_init(&ctx->cancelled, 0);
    atomic_init(&ctx->panicked, 0);
    atomic_init(&ctx->joined, 0);
    atomic_init(&ctx->completed, 0);
    atomic_init(&ctx->finished, 0);
    pthread_mutex_init(&ctx->injected_lock, NULL);
    ctx->injected_slots = NULL;  // ver TaskContext
    ctx->panic_msg = NULL;
    ctx->free_retval = NULL;
    ctx->parent = parent;
    ctx->children = NULL;
    ctx->n_children = 0;
    ctx->cap_children = 0;
    pthread_mutex_init(&ctx->children_mu, NULL);
    pthread_mutex_init(&ctx->wait_lock, NULL);
    ctx->wait_mu = NULL;
    ctx->wait_cond = NULL;
    pthread_mutex_init(&ctx->done_mu, NULL);
    scar_cond_init_mono(&ctx->done_cond);
    ctx->done = 0;
    pthread_mutex_init(&ctx->sleep_mu, NULL);
    scar_cond_init_mono(&ctx->sleep_cond);
    scar_arena_init(&ctx->arena);
    return ctx;
}

// Ultimo paso del wrapper de una task (normal, panic o
// cancelacion). Despierta a quien este en join() sobre ella.
static void scar_ctx_mark_done(TaskContext *ctx) {
    pthread_mutex_lock(&ctx->done_mu);
    ctx->done = 1;
    pthread_cond_broadcast(&ctx->done_cond);
    pthread_mutex_unlock(&ctx->done_mu);
}

static void scar_ctx_add_child(TaskContext *parent, TaskContext *child) {
    pthread_mutex_lock(&parent->children_mu);
    if (parent->n_children == parent->cap_children) {
        parent->cap_children = parent->cap_children ? parent->cap_children * 2 : 4;
        parent->children = realloc(parent->children,
            parent->cap_children * sizeof(TaskContext*));
    }
    parent->children[parent->n_children++] = child;
    pthread_mutex_unlock(&parent->children_mu);
}

// libera un TaskContext YA reapado/joineado (ver scar_cancel_children
// mas abajo, unico lugar que la llama): para ese punto el hilo del
// hijo ya termino (pthread_join lo garantiza) y sus propios hijos ya
// fueron liberados por el propio scar_cancel_children() del hijo antes
// de retornar -- nadie mas puede tocar este ctx despues de esto.
static void scar_ctx_free(TaskContext *ctx) {
    pthread_mutex_destroy(&ctx->children_mu);
    pthread_mutex_destroy(&ctx->wait_lock);
    pthread_mutex_destroy(&ctx->injected_lock);
    pthread_mutex_destroy(&ctx->done_mu);
    pthread_cond_destroy(&ctx->done_cond);
    pthread_mutex_destroy(&ctx->sleep_mu);
    pthread_cond_destroy(&ctx->sleep_cond);
    free(ctx->injected_slots);  // NULL si la task no tiene 'accepts'
    free(ctx->children);
    free(ctx->panic_msg);
    free(ctx);
}

// Unico punto de entrada para cancelar un TaskContext (lo usan
// scar_cancel_siblings, scar_cancel_children y el timeout de
// scar_join_wait): ademas de marcar 'cancelled', si ese ctx
// esta bloqueado AHORA MISMO en un pthread_cond_wait() sin timeout de
// scar_chan_send_*/recv_* (ver wait_mu/wait_cond en TaskContext), lo
// despierta al toque en vez de dejarlo dormido hasta que otro
// send()/recv()/close() en ese mismo canal lo despierte por su cuenta
// (que podria no pasar nunca -- ya no hay deadline de 200us de respaldo).
//
// El lock+broadcast+unlock de abajo se hace primero bajo wait_lock (para
// leer wait_mu/wait_cond de forma segura) y despues bajo el propio mutex
// del canal apuntado por wait_mu (requisito de POSIX para que
// pthread_cond_broadcast() tenga garantizado despertar a quien esta en
// pthread_cond_wait() sobre ese mismo par mutex/cond -- broadcastear sin
// tener el mutex tomado es una carrera clasica de "signal perdido").
// Si el ctx no esta bloqueado en ningun canal (wait_mu NULL, el caso
// comun), esto es solo el atomic_store de antes mas un lock/unlock chico
// de wait_lock que nunca tiene contencion real.
// (condicion de carrera real hallada por TSan en
// prototipo_router_verificado, 1 de cada ~40 corridas): antes se leia
// wait_mu/wait_cond bajo wait_lock, se SOLTABA wait_lock y recien
// despues se tomaba el mutex del canal. En ese hueco la tarea
// cancelada podia despertar, desregistrarse, desenrollar y liberar el
// canal (decref): use-after-free sobre su mutex/condvar. Ahora
// wait_lock se mantiene mientras se avisa: la tarea no puede
// desregistrarse (necesita wait_lock), asi que no puede llegar a
// liberar el canal en medio. El mutex del canal se toma con trylock:
// la tarea toma mu -> wait_lock al registrarse, y bloquearse aca en
// wait_lock -> mu seria un deadlock por orden de candados. Si esta
// ocupado, se suelta todo y se reintenta.
static void scar_cancel_notify(TaskContext *ctx) {
    atomic_store(&ctx->cancelled, 1);
    for (;;) {
        pthread_mutex_lock(&ctx->wait_lock);
        pthread_mutex_t *mu = ctx->wait_mu;
        pthread_cond_t *cond = ctx->wait_cond;
        if (!mu || !cond) {
            pthread_mutex_unlock(&ctx->wait_lock);
            return;
        }
        if (pthread_mutex_trylock(mu) == 0) {
            pthread_cond_broadcast(cond);
            pthread_mutex_unlock(mu);
            pthread_mutex_unlock(&ctx->wait_lock);
            return;
        }
        pthread_mutex_unlock(&ctx->wait_lock);
        struct timespec espera = { .tv_sec = 0, .tv_nsec = 1000 };
        nanosleep(&espera, NULL);
    }
}

// semantica "nursery": cuando 'ctx' panickea, cancela de
// inmediato a sus hermanas (los otros hijos de su mismo padre) -- no
// hace falta esperar a que el padre termine o haga join() para dejar
// de trabajar en vano.
static void scar_cancel_siblings(TaskContext *ctx) {
    if (!ctx->parent) return;
    TaskContext *parent = ctx->parent;
    pthread_mutex_lock(&parent->children_mu);
    for (int i = 0; i < parent->n_children; i++) {
        TaskContext *sib = parent->children[i];
        if (sib != ctx) scar_cancel_notify(sib);
    }
    pthread_mutex_unlock(&parent->children_mu);
}

// concurrencia estructurada: al terminar 'ctx' (por la razon que sea),
// sus hijos que sigan vivos sin join() se cancelan y se reapan aca --
// nunca quedan huerfanos trabajando sin supervision (ver run_main()/
// spawn_task() en el interprete).
static void scar_cancel_children(TaskContext *ctx) {
    pthread_mutex_lock(&ctx->children_mu);
    int n = ctx->n_children;
    TaskContext **kids = ctx->children;
    for (int i = 0; i < n; i++) scar_cancel_notify(kids[i]);
    pthread_mutex_unlock(&ctx->children_mu);
    for (int i = 0; i < n; i++) {
        int expected = 0;
        if (atomic_compare_exchange_strong(&kids[i]->joined, &expected, 1)) {
            // Nadie mas va a ver este retval (ganamos la carrera contra
            // un .join() de usuario -- 'joined' pasa de 0 a 1 aca mismo):
            // liberarlo ahora evita perderlo en un spawn sin join
            // (fire-and-forget). Si SI hubiera .join() de usuario,
            // este compare_exchange falla y el retval sigue siendo su
            // responsabilidad -- sin cambio para ese camino.
            void *__scar_orphan_retval = NULL;
            pthread_join(kids[i]->thread, &__scar_orphan_retval);
            if (__scar_orphan_retval && kids[i]->free_retval) {
                kids[i]->free_retval(__scar_orphan_retval);
            }
        }
    }
    // Recien aca, con los 'n' hilos hijos YA confirmados muertos (el
    // 'join' de arriba, sea el reap o el que ya habia hecho el
    // codigo de usuario via '.join()', garantiza que terminaron), es
    // seguro liberar cada TaskContext. Tiene que ser una segunda
    // pasada, separada de la de arriba: si se liberara adentro del
    // mismo loop que reapa, un hermano TODAVIA VIVO (que el loop no
    // alcanzo todavia) podria panickear por su cuenta entre medio y
    // llamar a scar_cancel_siblings(), que lee este mismo array
    // 'children' del padre -- leyendo un hermano ya liberado unas
    // iteraciones antes (use-after-free). Este es el UNICO lugar del
    // programa que recorre ctx->children, asi que es el unico lugar
    // seguro para liberar cada hijo, exactamente una vez.
    for (int i = 0; i < n; i++) {
        scar_ctx_free(kids[i]);
    }
}

// Deliberadamente NO inline: es el camino frio (solo se toma cuando
// de verdad hay que cancelar), asi que sacarlo del cuerpo de
// scar_cancel_check() lo mantiene chico -- ver el comentario de ahi
// abajo sobre por que eso importa para el loop que lo llama.
// Registro de dueñas vivas del hilo. Cancelar o panickear
// desenrolla con siglongjmp hasta el wrapper de la task, y eso se saltea
// los free() que el codegen emite al cerrar cada scope: todo str/Vec/Map
// (y los campos de los structs de la arena) que estuviera vivo se perdia.
// Ahora cada dueña se da de alta al nacer (direccion de su variable +
// como soltarla) y de baja al morir (free, movimiento, fin de su scope;
// un return trunca el registro a lo que habia al entrar a la funcion).
// Antes del siglongjmp, scar_vivos_soltar() suelta todo lo registrado,
// todavia desde el punto mas profundo, con todos los frames vivos.
@@VIVOS_RUNTIME_C@@
static __attribute__((noinline)) void scar_cancel_unwind(void) {
    TaskContext *ctx = __scar_ctx;
    if (ctx) {
        scar_vivos_soltar();
        siglongjmp(ctx->panic_env, 2);
    }
}

// el safepoint: se llama en el back-edge de cada loop, en
// el prologo del hilo de cada tarea, y en el prologo de cada `fn`
// normal (cubre recursion sin loops). Nunca en ningun
// otro lado.
//
// 'static inline': medido con push/pop de Vec (16M iteraciones entre 4
// tareas), gcc -O2 no
// desenrollaba el loop del caller cuando este chequeo era una llamada
// real fuera de linea -- aun revisando cada 256 vueltas en vez de cada
// una (ver el comentario en WhileStmt/WhileLetStmt de mas arriba),
// un 'call' de verdad en el medio del loop le basta al compilador
// para tratar todo lo que sigue como opaco y no reordenar/desenrollar
// alrededor. El cuerpo de esta funcion es solo una lectura TLS +
// comparacion + un branch raramente tomado (al camino frio de arriba,
// que se queda fuera de linea a proposito) -- chico a proposito para
// que 'inline' sea una sugerencia realista, no solo cosmetica.
static inline void scar_cancel_check(void) {
    TaskContext *ctx = __scar_ctx;
    if (ctx && atomic_load(&ctx->cancelled)) scar_cancel_unwind();
}

// Progreso global del programa (gemelo de _PROGRESO en interpreter.py):
// cada safepoint de trabajo real (back-edge de loop cada 256 vueltas,
// prologo de fn/task, paso de sleep) lo incrementa. scar_join_wait solo
// declara 'probable deadlock' si NINGUNA task avanzo durante
// SCAR_JOIN_TIMEOUT_SECONDS seguidos. Las esperas bloqueadas (canal,
// join, I/O) usan scar_cancel_check a secas y no cuentan.
// Los safepoints calientes (loops, prologos) cuentan en un contador
// propio del hilo y publican al global cada 64: un contador global
// tocado en cada llamada se disputaba entre hilos (46_ tardaba 1,16x).
// Los eventos raros (pasar un mensaje, dormir) publican siempre.
static _Atomic unsigned long scar_progreso = 0;
// Cuantas tasks estan ahora en sleep(). sleep() duerme de una vez (no
// en pasos que cuenten como avance), asi que join() considera que hay progreso mientras
// alguna duerma (va a despertar sola).
static _Atomic int scar_durmiendo = 0;
static __thread unsigned int scar_progreso_local = 0;
static inline void scar_avance(void) {
    atomic_fetch_add_explicit(&scar_progreso, 1, memory_order_relaxed);
}
static inline void scar_safepoint(void) {
    if ((++scar_progreso_local & 0x3Fu) == 0) scar_avance();
    scar_cancel_check();
}

// Deadlock SEGURO en canales. Cuantas
// tareas viven (main incluida) y cuantas estan trabadas esperando un
// canal o un join(). Si todas esperan, ninguna duerme y nada avanza en
// dos vueltas seguidas de 250 ms, ninguna va a poder seguir nunca: el
// send()/recv() que lo nota hace panic en vez de colgarse para siempre.
// Una tarea que duerme, lee la red o el teclado, o corre codigo, no
// cuenta como esperando: no hay falsos positivos. Gemelo de
// _EsperaCanal en interpreter.py.
static _Atomic int scar_hilos_vivos = 1;
static _Atomic int scar_hilos_esperando = 0;
typedef struct { unsigned long visto; int quietas; } ScarEspera;
static int scar_esperar_cond(pthread_cond_t *cv, pthread_mutex_t *mu, ScarEspera *e) {
    atomic_fetch_add(&scar_hilos_esperando, 1);
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);  // las condvars de canal usan el reloj por defecto
    ts.tv_nsec += 250000000L;
    if (ts.tv_nsec >= 1000000000L) { ts.tv_sec++; ts.tv_nsec -= 1000000000L; }
    int trabado = 0;
    if (pthread_cond_timedwait(cv, mu, &ts) == ETIMEDOUT) {
        unsigned long p = atomic_load_explicit(&scar_progreso, memory_order_relaxed);
        if (p == e->visto && atomic_load(&scar_durmiendo) == 0
            && atomic_load(&scar_hilos_esperando) >= atomic_load(&scar_hilos_vivos)) {
            if (++e->quietas >= 2) trabado = 1;
        } else {
            e->quietas = 0;
            e->visto = p;
        }
    }
    atomic_fetch_sub(&scar_hilos_esperando, 1);
    return trabado;
}

static void scar_panic_propio(char *buf) __attribute__((noreturn));
static void scar_panic(const char *fmt, ...) {
    // sin tope (antes buf[256] cortaba el mensaje). Mide, reserva
    // lo justo y le pasa el bloque a scar_panic_propio.
    va_list ap, ap2;
    char medir[1];
    va_start(ap, fmt);
    va_copy(ap2, ap);
    int n = vsnprintf(medir, sizeof medir, fmt, ap);
    va_end(ap);
    if (n < 0) n = 0;
    char *buf = malloc((size_t)n + 1);
    if (!buf) { fputs("[PANIC] sin memoria para el mensaje\n", stderr); exit(1); }
    vsnprintf(buf, (size_t)n + 1, fmt, ap2);
    va_end(ap2);
    scar_panic_propio(buf);
}

// El panic con un mensaje ya armado en el heap (malloc), del que
// pasa a ser dueño: con ctx lo guarda el contexto; sin ctx se libera
// antes de salir. Lo usa también panic(...) del usuario (sin copiar el
// mensaje a la pila: un arreglo de largo variable con un texto muy largo
// podía desbordar la pila de la task).
static void scar_panic_propio(char *buf) {
    TaskContext *ctx = __scar_ctx;
    fflush(stdout);
#ifndef SCAR_LIBRERIA  // en una librería lo da scar_error()
    // main (el contexto raíz, sin madre) se nombra igual que sin tareas
    if (!ctx || !ctx->parent)
        fprintf(stderr, "[PANIC] main murió: %s\n", buf);
    else
        fprintf(stderr, "[PANIC] la tarea '%s' murió: %s\n", ctx->name, buf);
    fflush(stderr);
#endif
    if (ctx) {
        free(ctx->panic_msg);
        ctx->panic_msg = buf;  // el contexto es el dueño
        atomic_store(&ctx->panicked, 1);
        scar_cancel_siblings(ctx);
        scar_vivos_soltar();
        siglongjmp(ctx->panic_env, 1);
    } else {
        free(buf);
        exit(1);
    }
}

// join() sobre una tarea que panickeo re-lanza ese panic en quien la
// joinea -- si 'quien' es otra tarea, esto se vuelve un
// panic de esa tarea tambien, y sigue subiendo la cadena.
static void scar_propagate_panic(TaskContext *child_ctx) {
    TaskContext *ctx = __scar_ctx;
    fflush(stdout);
#ifndef SCAR_LIBRERIA  // en una librería lo da scar_error()
    if (!ctx || !ctx->parent)
        fprintf(stderr, "[PANIC] main murió porque su hija '%s' panickeó: %s\n",
            child_ctx->name, child_ctx->panic_msg ? child_ctx->panic_msg : "");
    else
        fprintf(stderr,
            "[PANIC] la tarea '%s' murió porque su hija '%s' panickeó: %s\n",
            ctx->name, child_ctx->name, child_ctx->panic_msg ? child_ctx->panic_msg : "");
    fflush(stderr);
#endif
    if (ctx) {
        atomic_store(&ctx->panicked, 1);
        free(ctx->panic_msg);
        ctx->panic_msg = strdup(child_ctx->panic_msg ? child_ctx->panic_msg : "");
        scar_cancel_siblings(ctx);
        scar_vivos_soltar();
        siglongjmp(ctx->panic_env, 1);
    } else {
        exit(1);
    }
}

// mismo valor por defecto que DEFAULT_JOIN_TIMEOUT en interpreter.py:
// deliberadamente generoso para no dar falsos positivos con los sleep()
// de los ejemplos (hasta ~3s). Se ajusta con
// '-DSCAR_JOIN_TIMEOUT_SECONDS=<valor>' -- compile_file() ya pasa esa flag
// siempre, con el mismo valor que lee
// SCAR_JOIN_TIMEOUT del intérprete; el literal de abajo es solo el
// fallback si alguien compila el .c generado a mano, sin pasar por cli.py.
#ifndef SCAR_JOIN_TIMEOUT_SECONDS
#define SCAR_JOIN_TIMEOUT_SECONDS 8.0
#endif

static double scar_monotonic_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

// join() consciente de la cancelacion de quien espera (cascada
// de mas de un nivel): en vez de un pthread_join() ciego, espera en
// pasos cortos revisando en cada paso si a quien esta haciendo join()
// lo cancelaron mientras tanto -- si es asi, scar_cancel_check() hace
// unwind y esta funcion nunca vuelve. Si la tarea joineada panickeo,
// re-lanza ese panic aca.
//
// Timeout de deadlock (calcado de join_task()/ScarDeadlock en
// interpreter.py): si la hija no termino dentro de SCAR_JOIN_TIMEOUT_SECONDS,
// esto NO es una prueba de que hay un deadlock (indecidible en general) --
// es un timeout que dice "esto tardo demasiado, algo esta mal". Se cancela
// a la hija (best-effort, se le da hasta 1s para reaccionar en su propio
// safepoint) y se reporta via scar_panic(), que hace que ESTE join() se
// vuelva un panic propio de quien esta esperando -- mismo mecanismo que
// cualquier otro panic, nunca nos colgamos en silencio.
static void* scar_join_wait(TaskContext *child_ctx) {
    // Un segundo .join() sobre el mismo TaskHandle no esta prohibido por
    // el checker (a diferencia de un struct no-Copy, TaskHandle no se
    // marca como movido). El interprete lo tolera gratis porque
    // Thread.join() de Python es idempotente; pthread_tryjoin_np() NO
    // lo es -- llamarlo dos veces sobre el mismo pthread_t es UB una
    // vez que el primero ya reaped el thread (confirmado: ASan aborta
    // con 'CheckUnwind' en sanitizer_thread_arg_retval; sin ASan, la
    // segunda llamada nunca ve rc==0 y termina en 'probable deadlock'
    // a los 8s -- un diagnostico enganoso para lo que es un bug
    // distinto). Se corta ahi mismo, alto y claro, en vez de arriesgar
    // el UB o el falso 'deadlock': la primera exitosa ya dejo
    // 'joined' en 1 (ver mas abajo).
    if (atomic_load(&child_ctx->joined)) {
        scar_panic(
            "join() llamado más de una vez sobre '%s' -- una tarea "
            "solo puede joinearse una vez",
            child_ctx->name);
    }
    // Espera en la condvar 'done' de la hija (ver
    // scar_ctx_mark_done) en vez de sondear pthread_tryjoin_np cada
    // 200us -- antes main se despertaba ~4000 veces por segundo mientras
    // esperaba. Se registra en wait_mu/wait_cond como un recv() de canal,
    // asi que scar_cancel_notify() la despierta si la cancelan. La espera
    // tiene tope (un cuarto del plazo, maximo 1 s) solo para revisar el
    // progreso del programa: el plazo de 'probable deadlock' se cuenta
    // desde la ultima vez que alguna task avanzo o mientras haya alguna
    // durmiendo (scar_durmiendo), igual que antes.
    void *retval = NULL;
    double deadline = scar_monotonic_now() + SCAR_JOIN_TIMEOUT_SECONDS;
    unsigned long visto = atomic_load_explicit(&scar_progreso, memory_order_relaxed);
    double tramo = SCAR_JOIN_TIMEOUT_SECONDS / 4.0;
    if (tramo > 1.0) tramo = 1.0;
    TaskContext *yo = __scar_ctx;
    scar_cancel_check();
    pthread_mutex_lock(&child_ctx->done_mu);
    while (!child_ctx->done) {
        double ahora_t = scar_monotonic_now();
        unsigned long ahora = atomic_load_explicit(&scar_progreso, memory_order_relaxed);
        if (ahora != visto || atomic_load(&scar_durmiendo) > 0) {
            // alguna task avanzo (o duerme, y va a terminar sola):
            // el plazo se cuenta desde aca
            visto = ahora;
            deadline = ahora_t + SCAR_JOIN_TIMEOUT_SECONDS;
        }
        if (ahora_t >= deadline) {
            pthread_mutex_unlock(&child_ctx->done_mu);
            scar_cancel_notify(child_ctx);
            struct timespec giveup = scar_abs_mono(1.0);
            pthread_mutex_lock(&child_ctx->done_mu);
            while (!child_ctx->done) {
                if (pthread_cond_timedwait(&child_ctx->done_cond, &child_ctx->done_mu, &giveup) == ETIMEDOUT) break;
            }
            int termino = child_ctx->done;
            pthread_mutex_unlock(&child_ctx->done_mu);
            if (termino) {
                pthread_join(child_ctx->thread, &retval);
                atomic_store(&child_ctx->joined, 1);
            }
            scar_panic(
                "join() sobre '%s' no termino tras %.1fs - probable deadlock "
                "(tarea cancelada, no se pudo confirmar la causa)",
                child_ctx->name, SCAR_JOIN_TIMEOUT_SECONDS);
        }
        double resta = deadline - ahora_t;
        struct timespec hasta = scar_abs_mono(resta < tramo ? resta : tramo);
        if (yo) {
            pthread_mutex_lock(&yo->wait_lock);
            yo->wait_mu = &child_ctx->done_mu;
            yo->wait_cond = &child_ctx->done_cond;
            pthread_mutex_unlock(&yo->wait_lock);
            // despues de registrarse: una cancelacion anterior al
            // registro no encontro a quien despertar, se ve aca
            if (atomic_load(&yo->cancelled)) {
                pthread_mutex_lock(&yo->wait_lock);
                yo->wait_mu = NULL;
                yo->wait_cond = NULL;
                pthread_mutex_unlock(&yo->wait_lock);
                pthread_mutex_unlock(&child_ctx->done_mu);
                scar_cancel_unwind();
            }
        }
        atomic_fetch_add(&scar_hilos_esperando, 1);  // Join() tambien espera
        pthread_cond_timedwait(&child_ctx->done_cond, &child_ctx->done_mu, &hasta);
        atomic_fetch_sub(&scar_hilos_esperando, 1);
        if (yo) {
            pthread_mutex_lock(&yo->wait_lock);
            yo->wait_mu = NULL;
            yo->wait_cond = NULL;
            pthread_mutex_unlock(&yo->wait_lock);
        }
    }
    pthread_mutex_unlock(&child_ctx->done_mu);
    // la hija ya hizo su ultimo paso: este join es inmediato
    pthread_join(child_ctx->thread, &retval);
    atomic_store(&child_ctx->joined, 1);
    if (atomic_load(&child_ctx->panicked)) {
        scar_propagate_panic(child_ctx);
    } else if (!atomic_load(&child_ctx->completed)) {
        // La hija nunca corrio su cuerpo hasta el final: no panickeo
        // (eso ya se cubrio arriba) pero tampoco termino -- fue
        // cancelada mientras estaba en vuelo (tipicamente por la
        // cascada 'nursery' de una hermana que panickeo). 'retval'
        // es NULL/basura en ese caso: no hay ningun i32/struct/Result
        // real que devolver, asi que esto NO puede tratarse como un
        // join() exitoso. En vez de que quien llama a .join() reciba
        // ese NULL y lo desreferencie a ciegas, este join() se vuelve
        // un panic propio de quien esta esperando -- mismo mecanismo
        // (scar_panic -> cascada a hermanas -> siglongjmp) que
        // cualquier otro panic.
        scar_panic(
            "join() sobre '%s' nunca completo -- fue cancelada antes "
            "de terminar (probablemente por la cascada de una tarea "
            "hermana que panickeó)",
            child_ctx->name);
    }
    return retval;
}
