__attribute__((noinline, cold, noreturn))
static void scar_@@T@@_overflow(unsigned long long a, const char* op, unsigned long long b) {
    @@PANIC@@("desbordamiento de @@T@@: %llu %s %llu", a, op, b);
    abort();
}
// la cuenta exacta y si cabe en el tipo, con los builtins de gcc y clang: vale
// igual para u8, u32 y u64 (con u64 no hay un tipo de C más ancho donde hacerla)
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
static inline @@CT@@ scar_@@T@@div(@@CT@@ a, @@CT@@ b) {
    if (b == 0) @@PANIC@@("división por cero (%llu / %llu)", (unsigned long long)a, (unsigned long long)b);
    return (@@CT@@)(a / b);
}
static inline @@CT@@ scar_@@T@@mod(@@CT@@ a, @@CT@@ b) {
    if (b == 0) @@PANIC@@("módulo por cero (%llu %% %llu)", (unsigned long long)a, (unsigned long long)b);
    return (@@CT@@)(a % b);
}
// sin signo: `<<` descarta los bits que salen por arriba y `>>` rellena con ceros
static inline @@CT@@ scar_@@T@@shl(@@CT@@ a, int64_t n) {
    if (n < 0 || n >= @@BITS@@) @@PANIC@@("corrimiento fuera de rango (%llu << %lld)", (unsigned long long)a, (long long)n);
    return (@@CT@@)((uint64_t)a << n);
}
static inline @@CT@@ scar_@@T@@shr(@@CT@@ a, int64_t n) {
    if (n < 0 || n >= @@BITS@@) @@PANIC@@("corrimiento fuera de rango (%llu >> %lld)", (unsigned long long)a, (long long)n);
    return (@@CT@@)(a >> n);
}
static inline @@CT@@ scar_@@T@@_desde_i64(int64_t v) {
    if (v < 0 || (uint64_t)v > @@MAX@@ull) @@PANIC@@("to_@@T@@: %lld esta fuera del rango de @@T@@", (long long)v);
    return (@@CT@@)v;
}
// de otro sin signo más ancho (un u64 a u32, por ejemplo): sin pasar por
// int64_t, donde un u64 grande se volvería negativo
static inline __attribute__((unused)) @@CT@@ scar_@@T@@_desde_u64(uint64_t v) {
    if (v > @@MAX@@ull) @@PANIC@@("to_@@T@@: %llu esta fuera del rango de @@T@@", (unsigned long long)v);
    return (@@CT@@)v;
}
// a los enteros con signo: to_i32 y to_i64 de un sin signo que puede no caber
static inline __attribute__((unused)) int32_t scar_@@T@@_a_i32(@@CT@@ v) {
    if ((uint64_t)v > INT32_MAX) @@PANIC@@("to_i32: %llu esta fuera del rango de i32", (unsigned long long)v);
    return (int32_t)v;
}
static inline __attribute__((unused)) int64_t scar_@@T@@_a_i64(@@CT@@ v) {
    if ((uint64_t)v > INT64_MAX) @@PANIC@@("to_i64: %llu esta fuera del rango de i64", (unsigned long long)v);
    return (int64_t)v;
}
// los dos bordes son exactos en un double (-1 y el máximo + 1)
static inline @@CT@@ scar_to_@@T@@(double x) {
    if (!(x > -1.0 && x < @@MAX@@.0 + 1.0)) @@PANIC@@("to_@@T@@: NaN o fuera del rango de @@T@@");
    return (@@CT@@)x;
}
