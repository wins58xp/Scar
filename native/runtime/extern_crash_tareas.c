
static void scar_extern_report_crash(const char *fnname, int signum) {
    scar_panic(
        "la función extern '%s' terminó con %s -- la frontera FFI de "
        "SCAR no puede evitar esto, solo convertirlo en panic en vez de un "
        "crash mudo",
        fnname, scar_extern_signame(signum));
}

