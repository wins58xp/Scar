// ScarCond: la condvar del runtime (canales, join, sleep). Con un hilo por
// tarea (SCAR_TAREAS=hilos, y siempre sin el planificador) es una
// pthread_cond_t tal cual. Con tareas livianas, una fibra que espera se anota
// en la fila de la ScarCond y le deja su hilo a otra (planificador.c); quien
// avisa la pone lista. Lo que no corre en una fibra espera en la pthread_cond_t
// de siempre.
typedef struct ScarCond {
    pthread_cond_t c;
#ifdef SCAR_PLANIFICADOR
    int mono;                   // los plazos vienen en CLOCK_MONOTONIC (si no, REALTIME)
    ScarGiro lk;                // protege la fila
    ScarFibra *cab, *ult;
    atomic_int n_os;            // esperando en `c` (no en una fibra)
#endif
} ScarCond;

static void scar_cond_init(ScarCond *cv, int mono) {
    if (mono) {
        pthread_condattr_t a;
        pthread_condattr_init(&a);
        pthread_condattr_setclock(&a, CLOCK_MONOTONIC);
        pthread_cond_init(&cv->c, &a);
        pthread_condattr_destroy(&a);
    } else {
        pthread_cond_init(&cv->c, NULL);
    }
#ifdef SCAR_PLANIFICADOR
    cv->mono = mono;
    atomic_init(&cv->lk.v, 0);
    cv->cab = cv->ult = NULL;
    atomic_init(&cv->n_os, 0);
#endif
}

static inline void scar_cond_destroy(ScarCond *cv) { pthread_cond_destroy(&cv->c); }

#ifdef SCAR_PLANIFICADOR
static void scar_cond_fila_quitar(ScarCond *cv, ScarFibra *f) {
    if (f->esp_ant) f->esp_ant->esp_sig = f->esp_sig; else cv->cab = f->esp_sig;
    if (f->esp_sig) f->esp_sig->esp_ant = f->esp_ant; else cv->ult = f->esp_ant;
    f->esp_sig = f->esp_ant = NULL;
    f->esp_cv = NULL;
}

// un plazo vencido (scar_plazos_disparar): la fibra sale de la fila. La
// ScarCond sigue viva: la fibra todavía esperaba en ella.
static void scar_cond_quitar_vencida(ScarFibra *f) {
    ScarCond *cv = f->esp_cv;
    if (!cv) return;
    scar_giro_tomar(&cv->lk);
    if (f->esp_cv == cv) scar_cond_fila_quitar(cv, f);
    scar_giro_soltar(&cv->lk);
}

#endif

// Espera un aviso, soltando `mu` mientras tanto (y volviéndolo a tomar), como
// pthread_cond_timedwait. `hasta` NULL: sin plazo. Devuelve 0, ETIMEDOUT o,
// con tareas livianas, SCAR_TRABADA (el planificador la eligió para dar el
// deadlock). `vigilancia`: el plazo solo vuelve a mirar (un tramo de join), no
// es progreso.
static int scar_cond_timedwait_k(ScarCond *cv, pthread_mutex_t *mu, const struct timespec *hasta, int vigilancia) {
#ifdef SCAR_PLANIFICADOR
    ScarFibra *f = scar_livianas ? scar_fibra_actual() : NULL;
    if (f) {
        long long vence = 0;
        if (hasta) {
            long long h = (long long)hasta->tv_sec * 1000000000LL + hasta->tv_nsec;
            if (cv->mono) {
                vence = h;
            } else {
                struct timespec rt;
                clock_gettime(CLOCK_REALTIME, &rt);
                vence = scar_mono_ns() + (h - ((long long)rt.tv_sec * 1000000000LL + rt.tv_nsec));
            }
        }
        atomic_store(&f->esp_estado, 0);
        // `guardando` antes de anotarse: quien la avise va a esperar a que el
        // planificador la tenga guardada (ver planificador.c)
        atomic_store_explicit(&f->guardando, 1, memory_order_relaxed);
        scar_giro_tomar(&cv->lk);
        f->esp_cv = cv;
        f->esp_sig = NULL;
        f->esp_ant = cv->ult;
        if (cv->ult) cv->ult->esp_sig = f; else cv->cab = f;
        cv->ult = f;
        scar_giro_soltar(&cv->lk);
        if (hasta) scar_plazo_poner(f, vence, vigilancia);
        else scar_park_poner(f);   // candidata a dar el deadlock
        pthread_mutex_unlock(mu);
        scar_ceder_al_plan(NULL, NULL);
        if (!hasta) scar_park_quitar(f);
        // despierta: avisada (1), vencida (2) o trabada (3)
        int e = atomic_load(&f->esp_estado);
        int r = e == 2 ? ETIMEDOUT : e == 3 ? SCAR_TRABADA : 0;
        if (hasta && e != 2) scar_plazo_quitar(f);
        pthread_mutex_lock(mu);
        return r;
    }
    if (scar_livianas) atomic_fetch_add(&cv->n_os, 1);
    int r = hasta ? pthread_cond_timedwait(&cv->c, mu, hasta) : pthread_cond_wait(&cv->c, mu);
    if (scar_livianas) atomic_fetch_sub(&cv->n_os, 1);
    return r;
#else
    return hasta ? pthread_cond_timedwait(&cv->c, mu, hasta) : pthread_cond_wait(&cv->c, mu);
#endif
}

static inline int scar_cond_timedwait(ScarCond *cv, pthread_mutex_t *mu, const struct timespec *hasta) {
    return scar_cond_timedwait_k(cv, mu, hasta, 0);
}
static inline int scar_cond_wait(ScarCond *cv, pthread_mutex_t *mu) {
    return scar_cond_timedwait_k(cv, mu, NULL, 0);
}

static void scar_cond_signal(ScarCond *cv) {
#ifdef SCAR_PLANIFICADOR
    if (scar_livianas) {
        ScarFibra *f = NULL;
        scar_giro_tomar(&cv->lk);
        while ((f = cv->cab)) {
            scar_cond_fila_quitar(cv, f);
            int e = 0;
            if (atomic_compare_exchange_strong(&f->esp_estado, &e, 1)) break;
            f = NULL;   // le ganó su plazo: el aviso es para la siguiente
        }
        scar_giro_soltar(&cv->lk);
        if (f) scar_listo(f, 1);
        else if (atomic_load(&cv->n_os) > 0) pthread_cond_signal(&cv->c);
        return;
    }
#endif
    pthread_cond_signal(&cv->c);
}

static void scar_cond_broadcast(ScarCond *cv) {
#ifdef SCAR_PLANIFICADOR
    if (scar_livianas) {
        ScarFibra *lista = NULL, *f;
        scar_giro_tomar(&cv->lk);
        while ((f = cv->cab)) {
            scar_cond_fila_quitar(cv, f);
            int e = 0;
            if (atomic_compare_exchange_strong(&f->esp_estado, &e, 1)) {
                f->esp_sig = lista;
                lista = f;
            }
        }
        scar_giro_soltar(&cv->lk);
        while (lista) {
            ScarFibra *sig = lista->esp_sig;
            lista->esp_sig = NULL;
            scar_listo(lista, 0);
            lista = sig;
        }
        if (atomic_load(&cv->n_os) > 0) pthread_cond_broadcast(&cv->c);
        return;
    }
#endif
    pthread_cond_broadcast(&cv->c);
}
