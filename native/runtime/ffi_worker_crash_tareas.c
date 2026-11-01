
static void scar_ffi_worker_report_crash(const char *fnname, const char *libname, const char *reason) {
    scar_panic(
        "la función extern '%s' de la librería '%s' tumbó su proceso "
        "worker (%s) -- el resto del programa SCAR sigue corriendo, pero "
        "esa librería queda inutilizable por el resto de esta corrida",
        fnname, libname, reason);
}

