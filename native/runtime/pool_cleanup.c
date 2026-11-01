
static pthread_key_t scar_pool_key;
static pthread_once_t scar_pool_once = PTHREAD_ONCE_INIT;

static void scar_pool_reclaim(void *unused) {
    (void)unused;
    for (int i = 0; i < SCAR_POOL_NUM_CLASSES; i++) {
        ScarPoolNode *node = scar_pool_freelist[i];
        while (node != NULL) {
            ScarPoolNode *next = node->next;
            free(node);
            node = next;
        }
        scar_pool_freelist[i] = NULL;
    }
}

static void scar_pool_make_key(void) {
    pthread_key_create(&scar_pool_key, scar_pool_reclaim);
}

// scar_pool_touch_thread() se llama en CADA scar_malloc()/scar_free(),
// así que el costo real (pthread_once + pthread_getspecific/
// pthread_setspecific, que son llamadas reales a libpthread, no un
// acceso nativo a TLS) tiene que pagarse UNA sola vez por hilo, no una
// vez por alloc/free. Se cachea en esta bandera _Thread_local: el path
// rápido (después de la primera vez en cada hilo) es solo una lectura
// TLS nativa + un branch, sin tocar pthread para nada. La key
// centinela (scar_pool_key/scar_pool_reclaim, ver arriba) sigue siendo
// necesaria como el único gancho que ofrece pthread para correr
// código al salir el hilo; esta bandera no la reemplaza, solo evita
// volver a tocarla en cada llamada.
static _Thread_local int scar_pool_registered = 0;

static inline void scar_pool_touch_thread(void) {
    if (scar_pool_registered) return;
    scar_pool_registered = 1;
    pthread_once(&scar_pool_once, scar_pool_make_key);
    pthread_setspecific(scar_pool_key, (void *)(uintptr_t)1);
}

