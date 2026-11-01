__attribute__((noinline, cold, noreturn))
static void scar_i64_overflow(int64_t a, const char* op, int64_t b) {
    @@PANIC@@("desbordamiento de i64: %lld %s %lld", (long long)a, op, (long long)b);
    abort();
}
static inline int64_t scar_ladd(int64_t a, int64_t b) {
    int64_t r;
    if (__builtin_expect(__builtin_add_overflow(a, b, &r), 0)) scar_i64_overflow(a, "+", b);
    return r;
}
static inline int64_t scar_lsub(int64_t a, int64_t b) {
    int64_t r;
    if (__builtin_expect(__builtin_sub_overflow(a, b, &r), 0)) scar_i64_overflow(a, "-", b);
    return r;
}
static inline int64_t scar_lmul(int64_t a, int64_t b) {
    int64_t r;
    if (__builtin_expect(__builtin_mul_overflow(a, b, &r), 0)) scar_i64_overflow(a, "*", b);
    return r;
}
static inline int64_t scar_lneg(int64_t a) {
    if (__builtin_expect(a == INT64_MIN, 0)) scar_i64_overflow(0, "-", a);
    return -a;
}
static inline int64_t scar_ldiv(int64_t a, int64_t b) {
    if (b == 0) @@PANIC@@("división por cero (%lld / %lld)", (long long)a, (long long)b);
    if (a == INT64_MIN && b == -1) scar_i64_overflow(a, "/", b);
    return a / b;
}
static inline int64_t scar_lmod(int64_t a, int64_t b) {
    if (b == 0) @@PANIC@@("módulo por cero (%lld %% %lld)", (long long)a, (long long)b);
    if (b == -1) return 0;  /* INT64_MIN % -1 es UB en C; el resultado es 0 */
    return a % b;
}
static inline int64_t scar_lsar_k(int64_t a, int n) {
    return a < 0 ? ~(~a >> n) : a >> n;
}
static inline int64_t scar_lshl(int64_t a, int64_t n) {
    if (n < 0 || n > 63) @@PANIC@@("corrimiento fuera de rango (%lld << %lld)", (long long)a, (long long)n);
    return (int64_t)((uint64_t)a << n);
}
static inline int64_t scar_lshr(int64_t a, int64_t n) {
    if (n < 0 || n > 63) @@PANIC@@("corrimiento fuera de rango (%lld >> %lld)", (long long)a, (long long)n);
    return scar_lsar_k(a, (int)n);
}
static inline int32_t scar_i32_desde_i64(int64_t v) {
    if (v < INT32_MIN || v > INT32_MAX) @@PANIC@@("to_i32: %lld esta fuera del rango de i32", (long long)v);
    return (int32_t)v;
}
static inline int64_t scar_to_i64(double x) {
    if (!(x >= -9223372036854775808.0 && x < 9223372036854775808.0)) @@PANIC@@("to_i64: NaN o fuera del rango de i64");
    return (int64_t)x;
}

