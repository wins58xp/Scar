__attribute__((noinline, cold, noreturn))
static void scar_i32_overflow(int32_t a, const char* op, int32_t b) {
@@CUERPO@@    abort();
}
static inline int32_t scar_iadd(int32_t a, int32_t b) {
    int32_t r;
    if (__builtin_expect(__builtin_add_overflow(a, b, &r), 0)) scar_i32_overflow(a, "+", b);
    return r;
}
static inline int32_t scar_isub(int32_t a, int32_t b) {
    int32_t r;
    if (__builtin_expect(__builtin_sub_overflow(a, b, &r), 0)) scar_i32_overflow(a, "-", b);
    return r;
}
static inline int32_t scar_imul(int32_t a, int32_t b) {
    int32_t r;
    if (__builtin_expect(__builtin_mul_overflow(a, b, &r), 0)) scar_i32_overflow(a, "*", b);
    return r;
}
static inline int32_t scar_ineg(int32_t a) {
    if (__builtin_expect(a == INT32_MIN, 0)) scar_i32_overflow(0, "-", a);
    return -a;
}
