
// ---- runtime del worker FFI aislado por proceso ----
static int scar_ffi_write_exact(int fd, const void *buf, size_t n) {
    size_t sent = 0;
    while (sent < n) {
        ssize_t w = write(fd, (const char *)buf + sent, n - sent);
        if (w <= 0) return 0;
        sent += (size_t)w;
    }
    return 1;
}
static int scar_ffi_read_exact(int fd, void *buf, size_t n) {
    size_t got = 0;
    while (got < n) {
        ssize_t r = read(fd, (char *)buf + got, n - got);
        if (r <= 0) return 0;
        got += (size_t)r;
    }
    return 1;
}
static int scar_ffi_write_i32(int fd, int32_t v)  { return scar_ffi_write_exact(fd, &v, 4); }
static int scar_ffi_write_i64(int fd, int64_t v)  { return scar_ffi_write_exact(fd, &v, 8); }
static int scar_ffi_write_f64(int fd, double v)   { return scar_ffi_write_exact(fd, &v, 8); }
static int scar_ffi_write_bool(int fd, uint8_t v) { return scar_ffi_write_exact(fd, &v, 1); }
static int scar_ffi_write_ptr(int fd, uint64_t v) { return scar_ffi_write_exact(fd, &v, 8); }
static int scar_ffi_write_str(int fd, const char *s) {
    // Sin flag is_null: a diferencia de scar_ffi_read_str() (que lee
    // un VALOR DE RETORNO de C, donde NULL es un resultado real y
    // distinto de ""), esta función solo escribe ARGUMENTOS str hacia
    // el worker -- el tipo `str` de SCAR no es nullable (eso es
    // Option<T>/Result<T>, otro mecanismo), así que nunca hay un NULL
    // que codificar acá. Tiene que coincidir byte a byte con el
    // read_str() del worker (ffi_worker.py, build_worker_source),
    // que lee length+bytes directo sin ningún flag -- y con el mismo
    // criterio que ya usa FfiWorkerPool.call() del lado Python
    // (ffi_worker.py) al mandarle argumentos str a ese mismo worker.
    // Antes de este fix, el flag extra desincronizaba el framing del
    // pipe con el primer str que mandara el binario compilado: el
    // worker interpretaba el byte de flag como el primer byte de un
    // length de 4 bytes, pedía de más y se quedaba bloqueado para
    // siempre en su read() -- deadlock real, no del mecanismo de
    // tasks/Chan<T> sino del framing del pipe FFI aislado.
    uint32_t len = (uint32_t)strlen(s);
    if (!scar_ffi_write_exact(fd, &len, 4)) return 0;
    if (len > 0 && !scar_ffi_write_exact(fd, s, len)) return 0;
    return 1;
}
static int scar_ffi_read_i32(int fd, int32_t *out)  { return scar_ffi_read_exact(fd, out, 4); }
static int scar_ffi_read_i64(int fd, int64_t *out)  { return scar_ffi_read_exact(fd, out, 8); }
static int scar_ffi_read_f64(int fd, double *out)  { return scar_ffi_read_exact(fd, out, 8); }
static int scar_ffi_read_bool(int fd, uint8_t *out) { return scar_ffi_read_exact(fd, out, 1); }
static int scar_ffi_read_ptr(int fd, uint64_t *out) { return scar_ffi_read_exact(fd, out, 8); }
static int scar_ffi_read_str(int fd, char **out, uint8_t *is_null) {
    if (!scar_ffi_read_exact(fd, is_null, 1)) return 0;
    if (*is_null) { *out = NULL; return 1; }
    uint32_t len;
    if (!scar_ffi_read_exact(fd, &len, 4)) return 0;
    char *s = scar_malloc((size_t)len + 1);
    if (len > 0 && !scar_ffi_read_exact(fd, s, len)) return 0;
    s[len] = 0;
    *out = s;
    return 1;
}

typedef struct {
    int wfd;
    int rfd;
    pid_t pid;
    volatile sig_atomic_t dead;
    char dead_reason[160];
@@MUTEX_FIELD@@} ScarFfiWorkerHandle;

static int scar_ffi_strict_mode(void) {
    const char *v = getenv("SCAR_FFI_STRICT");
    return v != NULL && v[0] != '\0' && strcmp(v, "0") != 0;
}

// Causa de muerte del worker -- reapea con waitpid() (nunca se
// reinicia un worker muerto, mismo criterio de política que
// FfiWorkerPool en ffi_worker.py: un handle vivo del lado del
// programa SCAR que en realidad ya no existe en ningún lado sería
// el mismo tipo de estado inconsistente silencioso que todo esto
// reemplaza, solo que un nivel más arriba).
static const char *scar_ffi_worker_crash_reason(pid_t pid) {
    static char buf[128];
    int status;
    if (pid <= 0 || waitpid(pid, &status, 0) < 0) {
        snprintf(buf, sizeof(buf), "no se pudo determinar la causa exacta");
        return buf;
    }
    if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        const char *nm = strsignal(sig);
        snprintf(buf, sizeof(buf), "termino por %s", nm ? nm : "una señal desconocida");
    } else if (WIFEXITED(status)) {
        snprintf(buf, sizeof(buf), "terminó con código de salida %d", WEXITSTATUS(status));
    } else {
        snprintf(buf, sizeof(buf), "termino de forma inesperada");
    }
    return buf;
}

static void scar_ffi_worker_mark_dead(ScarFfiWorkerHandle *h, const char *reason) {
    h->dead = 1;
    strncpy(h->dead_reason, reason, sizeof(h->dead_reason) - 1);
    h->dead_reason[sizeof(h->dead_reason) - 1] = 0;
    if (h->pid > 0) kill(h->pid, SIGKILL);  // no-op si ya murio
}

static void scar_ffi_worker_start_one(ScarFfiWorkerHandle *h, const char *libname, const char *path, int strict) {
    const char *fail_reason = NULL;
    int inpipe[2];
    int outpipe[2];
    if (pipe(inpipe) != 0 || pipe(outpipe) != 0) {
        fail_reason = "no se pudo crear el pipe para el worker";
    } else {
        pid_t pid = fork();
        if (pid < 0) {
            close(inpipe[0]); close(inpipe[1]); close(outpipe[0]); close(outpipe[1]);
            fail_reason = "fork() fallo al lanzar el worker";
        } else if (pid == 0) {
            // hijo: todavia single-thread (esto corre ANTES de cualquier
            // spawn de SCAR, ver el arranque de main() mas abajo) -- exec()
            // seguro, sin el riesgo de fork() con threads vivos.
            dup2(inpipe[0], 0);
            dup2(outpipe[1], 1);
            close(inpipe[0]); close(inpipe[1]);
            close(outpipe[0]); close(outpipe[1]);
            execl(path, path, (char *)NULL);
            _exit(127);  // execl() fallo -- el padre lo ve como pipe roto
        } else {
            close(inpipe[0]);
            close(outpipe[1]);
            h->wfd = inpipe[1];
            h->rfd = outpipe[0];
            h->pid = pid;
            h->dead = 0;
        }
    }
    if (fail_reason == NULL) return;
    strncpy(h->dead_reason, fail_reason, sizeof(h->dead_reason) - 1);
    h->dead_reason[sizeof(h->dead_reason) - 1] = 0;
    h->dead = 1;
    if (strict) {
        fflush(stdout);
        fprintf(stderr,
            "[scar] modo seguro (SCAR_FFI_STRICT): no se pudo iniciar el worker "
            "FFI aislado para '%s' (%s) -- se rechaza la carga en vez de "
            "ejecutar sus llamadas extern sin aislamiento de proceso\n",
            libname, fail_reason);
        fflush(stderr);
        exit(1);
    }
    fprintf(stderr,
        "[scar] aviso: no se pudo iniciar el worker FFI aislado para '%s' "
        "(%s) -- a diferencia del interprete, este binario ya compilado no "
        "tiene un modo sin aislamiento al que caer: sus llamadas extern van "
        "a panickear apenas se las use en esta corrida. Corre con "
        "SCAR_FFI_STRICT=1 para rechazar esto de entrada en vez de fallar "
        "recien en el primer uso.\n",
        libname, fail_reason);
}

