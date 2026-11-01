
// Sin tasks no hay TaskContext/scar_panic al que recurrir (mismo
// criterio que idiv_helper/imod_helper de la rama sin tasks, arriba):
// reportar con un mensaje claro y terminar el proceso directo.
static void scar_extern_report_crash(const char *fnname, int signum) {
    scar_panic_main("la función extern '%s' terminó con %s",
        fnname, scar_extern_signame(signum));
}

