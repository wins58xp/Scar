
// Panic de main en un programa sin tasks. Suelta todo lo vivo
// (mismo registro que usa scar_panic() con tasks) y termina el proceso.
static void scar_panic_main(const char *fmt, ...)
    __attribute__((noreturn, cold, noinline, format(printf, 1, 2)));
// Con un mensaje ya armado en el heap, del que pasa a ser dueño
// (lo usa panic(...) del usuario; ver scar_panic_propio).
static void scar_panic_main_propio(char *msg)
    __attribute__((noreturn, cold, noinline));
static void scar_panic_main_propio(char *msg) {
    fflush(stdout);
    fputs("[PANIC] main murió: ", stderr);
    fputs(msg, stderr);
    fputc('\n', stderr);
    fflush(stderr);
    free(msg);
    scar_vivos_soltar();
    scar_vivos_liberar_registro();
    exit(1);
}
static void scar_panic_main(const char *fmt, ...) {
    va_list ap;
    fflush(stdout);
    fputs("[PANIC] main murió: ", stderr);
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    fflush(stderr);
    scar_vivos_soltar();
    scar_vivos_liberar_registro();
    exit(1);
}

