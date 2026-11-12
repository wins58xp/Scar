#define SCAR_HAY_RAND 1
// __scar_rand_state, __scar_rand_base y __scar_rand_hijos: en ScarHilo (tls.c)

static inline uint64_t scar_splitmix64(uint64_t z) {
    z += 0x9E3779B97F4A7C15ULL;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static void scar_rand_init(uint64_t semilla) {
    __scar_rand_base = semilla;
    __scar_rand_hijos = 0;
    uint64_t s = scar_splitmix64(semilla);
    __scar_rand_state = s ? s : 0x9E3779B97F4A7C15ULL;
}

static void scar_rand_arranque(void) {
    const char *env = getenv("SCAR_SEED");
    if (env && *env) {
        scar_rand_init((uint64_t)strtoull(env, NULL, 10));
        return;
    }
    int probe;
    scar_rand_init((uint64_t)time(NULL) ^ (uint64_t)(uintptr_t)&probe);
}

// semilla de la próxima task que crea este hilo (se llama al crearla)
static uint64_t scar_rand_semilla_hija(void) {
    if (__scar_rand_state == 0) scar_rand_arranque();
    __scar_rand_hijos++;
    return scar_splitmix64(__scar_rand_base ^ (__scar_rand_hijos * 0xD1B54A32D192ED03ULL));
}

static inline double scar_rand(void) {
    if (__scar_rand_state == 0) scar_rand_arranque();
    uint64_t x = __scar_rand_state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    __scar_rand_state = x;
    return (double)(x >> 11) * (1.0 / (double)(1ULL << 53));
}
#define SCAR_RAND_SEMILLA_HIJA() scar_rand_semilla_hija()
#define SCAR_RAND_HILO(s) scar_rand_init(s)

