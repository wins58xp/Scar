static inline int32_t scar_idiv(int32_t a, int32_t b) {
    if (b == 0) {
        @@PANIC@@("división por cero (%d / %d)", a, b);
    }
    if (a == INT32_MIN && b == -1) {
        @@PANIC@@("desbordamiento de i32: %d / %d", a, b);
    }
    return a / b;
}
