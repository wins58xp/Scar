static @@GUARD_STORAGE@@volatile sig_atomic_t scar_extern_guard_active = 0;
static @@GUARD_STORAGE@@volatile sig_atomic_t scar_extern_guard_signum = 0;
static @@GUARD_STORAGE@@sigjmp_buf scar_extern_guard_env;
static @@GUARD_STORAGE@@const char *scar_extern_guard_fnname = "";

@@FFI_STR_PROPIA@@static void scar_extern_sig_handler(int signum) {
    if (scar_extern_guard_active) {
        scar_extern_guard_active = 0;
        scar_extern_guard_signum = signum;
        siglongjmp(scar_extern_guard_env, 1);
    }
    signal(signum, SIG_DFL);
    raise(signum);
}

static void scar_extern_install_guard(void) {
    signal(SIGSEGV, scar_extern_sig_handler);
    signal(SIGBUS, scar_extern_sig_handler);
    signal(SIGILL, scar_extern_sig_handler);
    signal(SIGFPE, scar_extern_sig_handler);
    signal(SIGABRT, scar_extern_sig_handler);
}

static const char *scar_extern_signame(int signum) {
    switch (signum) {
        case SIGSEGV: return "SIGSEGV (acceso invalido a memoria)";
        case SIGBUS:  return "SIGBUS (acceso a memoria invalido/mal alineado)";
        case SIGILL:  return "SIGILL (instruccion ilegal)";
        case SIGFPE:  return "SIGFPE (excepcion aritmetica)";
        case SIGABRT: return "SIGABRT (assert/abort() de la librería C)";
        default:      return "señal fatal desconocida";
    }
}

