__attribute__((noinline, cold, noreturn))
static void scar_@@T@@_overflow(long long a, const char* op, long long b) {
    @@PANIC@@("desbordamiento de @@T@@: %lld %s %lld", a, op, b);
    abort();
}
// la cuenta exacta y si cabe en el tipo, con los builtins de gcc y clang (como
// i64.c); con un i16 la cuenta de C se haría en int igual, pero así no depende de eso
static inline @@CT@@ scar_@@T@@add(@@CT@@ a, @@CT@@ b) {
    @@CT@@ r;
    if (__builtin_expect(__builtin_add_overflow(a, b, &r), 0)) scar_@@T@@_overflow(a, "+", b);
    return r;
}
static inline @@CT@@ scar_@@T@@sub(@@CT@@ a, @@CT@@ b) {
    @@CT@@ r;
    if (__builtin_expect(__builtin_sub_overflow(a, b, &r), 0)) scar_@@T@@_overflow(a, "-", b);
    return r;
}
static inline @@CT@@ scar_@@T@@mul(@@CT@@ a, @@CT@@ b) {
    @@CT@@ r;
    if (__builtin_expect(__builtin_mul_overflow(a, b, &r), 0)) scar_@@T@@_overflow(a, "*", b);
    return r;
}
static inline @@CT@@ scar_@@T@@neg(@@CT@@ a) {
    if (__builtin_expect(a == @@MIN@@, 0)) scar_@@T@@_overflow(0, "-", a);
    return (@@CT@@)-a;
}
static inline @@CT@@ scar_@@T@@div(@@CT@@ a, @@CT@@ b) {
    if (b == 0) @@PANIC@@("división por cero (%lld / %lld)", (long long)a, (long long)b);
    if (a == @@MIN@@ && b == -1) scar_@@T@@_overflow(a, "/", b);
    return (@@CT@@)(a / b);
}
static inline @@CT@@ scar_@@T@@mod(@@CT@@ a, @@CT@@ b) {
    if (b == 0) @@PANIC@@("módulo por cero (%lld %% %lld)", (long long)a, (long long)b);
    if (b == -1) return 0;  /* el mínimo % -1: el resultado es 0 */
    return (@@CT@@)(a % b);
}
// con signo: `<<` descarta los bits que salen por arriba (puede cambiar el
// signo) y `>>` conserva el signo, sin depender del compilador
static inline @@CT@@ scar_@@T@@shl(@@CT@@ a, int64_t n) {
    if (n < 0 || n >= @@BITS@@) @@PANIC@@("corrimiento fuera de rango (%lld << %lld)", (long long)a, (long long)n);
    return (@@CT@@)(@@UCT@@)((uint32_t)(@@UCT@@)a << n);
}
static inline @@CT@@ scar_@@T@@shr(@@CT@@ a, int64_t n) {
    if (n < 0 || n >= @@BITS@@) @@PANIC@@("corrimiento fuera de rango (%lld >> %lld)", (long long)a, (long long)n);
    return (@@CT@@)(a < 0 ? ~(~a >> n) : a >> n);
}
static inline __attribute__((unused)) @@CT@@ scar_abs_@@T@@(@@CT@@ x) {
    if (x == @@MIN@@) @@PANIC@@("abs: %lld no tiene valor absoluto en @@T@@", (long long)x);
    return (@@CT@@)(x < 0 ? -x : x);
}
static inline __attribute__((unused)) @@CT@@ scar_@@T@@_desde_i64(int64_t v) {
    if (v < @@MIN@@ || v > @@MAX@@) @@PANIC@@("to_@@T@@: %lld esta fuera del rango de @@T@@", (long long)v);
    return (@@CT@@)v;
}
// de un u64 (to_@@T@@(x) con x: u64): sin pasar por int64_t, donde un u64
// grande se volvería negativo
static inline __attribute__((unused)) @@CT@@ scar_@@T@@_desde_u64(uint64_t v) {
    if (v > (uint64_t)@@MAX@@) @@PANIC@@("to_@@T@@: %llu esta fuera del rango de @@T@@", (unsigned long long)v);
    return (@@CT@@)v;
}
// los dos bordes son exactos en un double (el mínimo - 1 y el máximo + 1)
static inline @@CT@@ scar_to_@@T@@(double x) {
    if (!(x > @@MIN@@.0 - 1.0 && x < @@MAX@@.0 + 1.0)) @@PANIC@@("to_@@T@@: NaN o fuera del rango de @@T@@");
    return (@@CT@@)x;
}
