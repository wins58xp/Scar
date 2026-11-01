
static void scar_ffi_worker_report_crash(const char *fnname, const char *libname, const char *reason) {
    scar_panic_main(
        "la función extern '%s' de la librería '%s' "
        "tumbó su proceso worker (%s)",
        fnname, libname, reason);
}

