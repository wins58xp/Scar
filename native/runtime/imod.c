static inline int32_t scar_imod(int32_t a, int32_t b) {
    if (b == 0) {
        @@PANIC@@("módulo por cero (%d %% %d)", a, b);
    }
    if (b == -1) return 0;  /* INT32_MIN % -1 es UB en C (SIGFPE en x86); el resultado es 0 */
    return a % b;
}
